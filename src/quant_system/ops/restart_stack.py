"""Compliant launchd stack restart with provider-free authority observations."""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.ops.common import (
    GitIdentity,
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_immutable,
)
from quant_system.storage.database import get_database, schema_fingerprint

BACKEND_LABEL = "com.aiquant.backend"
FRONTEND_LABEL = "com.aiquant.frontend"
CONNECTOR_LABEL = "com.aiquant.agent-v02-connector"
SETTINGS_URL = "http://127.0.0.1:8765/api/settings"
GATEWAY_URL = "http://127.0.0.1:8765/api/hermes/gateway"
FRONTEND_ORIGIN = "http://127.0.0.1:3001"
CONNECTOR_LOG = Path("data/_runtime/logs/agent-v02-connector.launchd.out.log")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def parse_launchctl_pid(document: str) -> int:
    match = re.search(r"(?m)^\s*pid = ([1-9][0-9]*)\s*$", document)
    if match is None:
        raise ReleaseOperationError("launchd job has no running pid")
    return int(match.group(1))


def parse_launchctl_last_exit_code(document: str) -> int:
    match = re.search(r"(?m)^\s*last exit code = (-?[0-9]+)\s*$", document)
    if match is None:
        raise ReleaseOperationError("launchd job has no last exit code")
    return int(match.group(1))


def parse_launchctl_runs(document: str) -> int:
    match = re.search(r"(?m)^\s*runs = ([1-9][0-9]*)\s*$", document)
    if match is None:
        raise ReleaseOperationError("launchd job has no positive generation count")
    return int(match.group(1))


def observed_launchctl_last_exit_code(
    document: str,
    *,
    label: str,
) -> int | None:
    """Require a zero historical exit only for the always-on connector."""

    try:
        value = parse_launchctl_last_exit_code(document)
    except ReleaseOperationError:
        if label == CONNECTOR_LABEL:
            raise
        return None
    if label == CONNECTOR_LABEL and value != 0:
        raise ReleaseOperationError("connector launchd last exit code is nonzero")
    return value


def _validate_settings_observation(
    document: object,
    *,
    require_nested_bind_address: bool,
) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("/api/settings response is not an object")
    public = document.get("safety")
    settings = document.get("settings")
    nested = settings.get("safety") if isinstance(settings, dict) else None
    if not isinstance(public, dict) or not isinstance(nested, dict):
        raise ReleaseOperationError("/api/settings safety projection is absent")
    common_required = {
        "kill_switch": True,
        "live_trading_enabled": False,
        "dry_run": True,
        "paper_trading": True,
    }
    for layer_name, observed in (("public", public), ("nested", nested)):
        for name, expected in common_required.items():
            value = observed.get(name)
            if value is not expected:
                raise ReleaseOperationError(f"/api/settings {layer_name} safety mismatch: {name}")
    bind_address = "127.0.0.1"
    if public.get("bind_address") != bind_address:
        raise ReleaseOperationError("/api/settings public safety mismatch: bind_address")
    if (require_nested_bind_address or "bind_address" in nested) and nested.get(
        "bind_address"
    ) != bind_address:
        raise ReleaseOperationError("/api/settings nested safety mismatch: bind_address")
    return {
        **common_required,
        "bind_address": bind_address,
    }


def validate_settings_observation(document: object) -> dict[str, object]:
    """Validate the legacy symmetric settings fixture contract."""

    return _validate_settings_observation(
        document,
        require_nested_bind_address=True,
    )


def validate_live_settings_observation(document: object) -> dict[str, object]:
    """Validate the real API projection without inventing a model bind field."""

    return _validate_settings_observation(
        document,
        require_nested_bind_address=False,
    )


def validate_release_observation(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("release status response is not an object")
    if document.get("contract") != "agent-v0.2-release-cli/v1":
        raise ReleaseOperationError("release status contract is invalid")
    decision = document.get("decision")
    if not isinstance(decision, dict):
        raise ReleaseOperationError("release status decision is absent")
    closed_fields = (
        "release_authorized",
        "public_write_authorized",
        "chat_write_ready",
    )
    for field in closed_fields:
        if decision.get(field) is not False:
            raise ReleaseOperationError(f"release authority is not closed: {field}")
    if decision.get("ready") is not False:
        raise ReleaseOperationError("release authority ready flag is not closed")
    return {
        "release_authorized": False,
        "public_write_authorized": False,
        "chat_write_ready": False,
        "ready": decision.get("ready"),
        "blockers": decision.get("blockers"),
        "release_stamp_id": decision.get("release_stamp_id"),
        "public_cutover_id": decision.get("public_cutover_id"),
        "event_cursor": decision.get("event_cursor"),
    }


def validate_gateway_observation(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("/api/hermes/gateway response is not an object")
    if document.get("chat_write_ready") is not False:
        raise ReleaseOperationError("/api/hermes/gateway chat write is not closed")
    return {
        "chat_write_ready": False,
        "read_status": document.get("read_status"),
        "connected": document.get("connected"),
        "session_api_available": document.get("session_api_available"),
        "blockers": document.get("blockers"),
    }


def validate_launcher_source(source: str) -> None:
    if ("|" + "|" + " true") in source:
        raise ReleaseOperationError("launcher contains a forbidden masking construct")
    if ("/api/" + "health") in source:
        raise ReleaseOperationError("launcher contains a forbidden readiness route")


def frontend_build_tree_facts(next_root: Path) -> dict[str, object]:
    """Content-address every regular file and directory in one Next build."""

    if next_root.is_symlink() or not next_root.is_dir():
        raise ReleaseOperationError("frontend .next build root is unavailable")
    entries: list[dict[str, object]] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(next_root.rglob("*"), key=lambda item: item.as_posix()):
        info = path.lstat()
        relative = path.relative_to(next_root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            raise ReleaseOperationError(f"frontend .next contains symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries.append(
                {
                    "kind": "directory",
                    "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                    "path": relative,
                }
            )
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ReleaseOperationError(f"frontend .next contains non-regular entry: {relative}")
        file_count += 1
        total_bytes += info.st_size
        entries.append(
            {
                "bytes": info.st_size,
                "kind": "file",
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                "path": relative,
                "sha256": sha256_file(path),
            }
        )
    build_id = next_root / "BUILD_ID"
    if build_id.is_symlink() or not build_id.is_file():
        raise ReleaseOperationError("frontend build identity is absent")
    return {
        "root": str(next_root.resolve()),
        "tree_sha256": sha256_bytes(canonical_json_bytes(entries)),
        "entry_count": len(entries),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "build_id_sha256": sha256_file(build_id),
    }


def validate_frontend_build_authority(
    authority: object,
    identity: GitIdentity,
) -> dict[str, object]:
    if not isinstance(authority, dict):
        raise ReleaseOperationError("frontend build authority is not an object")
    repository = authority.get("repository")
    next_facts = authority.get("next")
    expected_repository = {
        "commit": identity.commit,
        "tree": identity.tree,
    }
    if repository != expected_repository:
        raise ReleaseOperationError("frontend build authority does not bind the current repository")
    if not isinstance(next_facts, dict):
        raise ReleaseOperationError("frontend build authority lacks .next facts")
    tree_digest = next_facts.get("tree_sha256")
    if not isinstance(tree_digest, str) or len(tree_digest) != 64:
        raise ReleaseOperationError("frontend build authority tree digest is invalid")
    if not isinstance(next_facts.get("file_count"), int):
        raise ReleaseOperationError("frontend build authority file count is invalid")
    if not isinstance(next_facts.get("total_bytes"), int):
        raise ReleaseOperationError("frontend build authority byte count is invalid")
    build_inputs = authority.get("build_inputs")
    if not isinstance(build_inputs, dict) or build_inputs.get("unchanged") is not True:
        raise ReleaseOperationError("frontend build input authority is invalid")
    if not (
        build_inputs.get("pre_build")
        == build_inputs.get("post_build")
        == build_inputs.get("post_activation")
    ):
        raise ReleaseOperationError("frontend build inputs are not exact across build")
    activation = authority.get("atomic_activation")
    if not isinstance(activation, dict) or activation.get("active_after") != next_facts:
        raise ReleaseOperationError("frontend atomic activation authority is invalid")
    rollback = activation.get("rollback")
    if (
        not isinstance(rollback, dict)
        or not isinstance(rollback.get("path"), str)
        or not isinstance(rollback.get("facts"), dict)
        or rollback.get("available_until_restart_outcome") is not True
    ):
        raise ReleaseOperationError("frontend rollback authority is invalid")
    return authority


def _extract_committed_frontend(repository_root: Path, workspace: Path) -> Path:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", "src/frontend"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if archive.returncode != 0:
        raise ReleaseOperationError("current-HEAD frontend archive failed")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            parts = Path(member.name).parts
            allowed_parent = member.isdir() and parts in {
                ("src",),
                ("src", "frontend"),
            }
            if (
                not parts
                or (parts[:2] != ("src", "frontend") and not allowed_parent)
                or Path(member.name).is_absolute()
                or ".." in parts
                or member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ReleaseOperationError("frontend archive has an unsafe entry")
        bundle.extractall(workspace, members=members, filter="data")
    frontend = workspace / "src" / "frontend"
    if not frontend.is_dir():
        raise ReleaseOperationError("frontend archive did not produce a project")
    return frontend


def _rebind_staged_build_paths(
    next_root: Path,
    *,
    staged_frontend: Path,
    active_frontend: Path,
) -> dict[str, object]:
    staged = os.fsencode(staged_frontend.resolve())
    active = os.fsencode(active_frontend.resolve())
    rewritten: list[dict[str, object]] = []
    for path in sorted(next_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        payload = path.read_bytes()
        if staged not in payload:
            continue
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseOperationError(
                "staged frontend path appears in a non-text build artifact: "
                f"{path.relative_to(next_root).as_posix()}"
            ) from exc
        updated = payload.replace(staged, active)
        before_sha256 = sha256_bytes(payload)
        path.write_bytes(updated)
        rewritten.append(
            {
                "path": path.relative_to(next_root).as_posix(),
                "before_sha256": before_sha256,
                "after_sha256": sha256_bytes(updated),
            }
        )
    for path in next_root.rglob("*"):
        if path.is_file() and not path.is_symlink() and staged in path.read_bytes():
            raise ReleaseOperationError("staged frontend path remains in build output")
    return {
        "from_path_sha256": sha256_bytes(staged),
        "to_path": str(active_frontend.resolve()),
        "rewritten_file_count": len(rewritten),
        "rewritten_files": rewritten,
    }


def _prune_staged_frontend_cache(next_root: Path) -> dict[str, object]:
    """Remove Next build-only caches before the runtime tree is activated."""

    cache_root = next_root / "cache"
    if cache_root.is_symlink():
        raise ReleaseOperationError("staged frontend cache is a symlink")
    if not cache_root.exists():
        return {
            "relative_path": "cache",
            "present_after_build": False,
            "absent_before_activation": True,
            "tree_sha256": sha256_bytes(canonical_json_bytes([])),
            "entry_count": 0,
            "file_count": 0,
            "total_bytes": 0,
        }
    if not cache_root.is_dir():
        raise ReleaseOperationError("staged frontend cache is not a directory")
    entries: list[dict[str, object]] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(cache_root.rglob("*"), key=lambda item: item.as_posix()):
        info = path.lstat()
        relative = path.relative_to(cache_root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            raise ReleaseOperationError(f"staged frontend cache contains symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries.append({"kind": "directory", "path": relative})
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ReleaseOperationError(
                f"staged frontend cache contains non-regular entry: {relative}"
            )
        file_count += 1
        total_bytes += info.st_size
        entries.append(
            {
                "bytes": info.st_size,
                "kind": "file",
                "path": relative,
                "sha256": sha256_file(path),
            }
        )
    facts = {
        "relative_path": "cache",
        "present_after_build": True,
        "absent_before_activation": True,
        "tree_sha256": sha256_bytes(canonical_json_bytes(entries)),
        "entry_count": len(entries),
        "file_count": file_count,
        "total_bytes": total_bytes,
    }
    shutil.rmtree(cache_root)
    if cache_root.exists() or cache_root.is_symlink():
        raise ReleaseOperationError("staged frontend cache removal failed")
    return facts


def _atomic_exchange_directories(active: Path, staged: Path) -> str:
    if any(path.is_symlink() or not path.is_dir() for path in (active, staged)):
        raise ReleaseOperationError("frontend atomic switch requires two directories")
    if active.parent.stat().st_dev != staged.parent.stat().st_dev:
        raise ReleaseOperationError("frontend build staging is on another filesystem")
    libc = ctypes.CDLL(None, use_errno=True)
    active_bytes = os.fsencode(active)
    staged_bytes = os.fsencode(staged)
    if sys.platform == "darwin":
        rename = getattr(libc, "renamex_np", None)
        if rename is None:
            raise ReleaseOperationError("atomic directory exchange is unavailable")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(active_bytes, staged_bytes, 0x00000002)
        primitive = "renamex_np(RENAME_SWAP)"
    elif sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise ReleaseOperationError("atomic directory exchange is unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, active_bytes, -100, staged_bytes, 0x00000002)
        primitive = "renameat2(RENAME_EXCHANGE)"
    else:
        raise ReleaseOperationError("atomic directory exchange is unsupported")
    if result != 0:
        error_number = ctypes.get_errno()
        raise ReleaseOperationError(f"atomic frontend build exchange failed: errno={error_number}")
    return primitive


def _same_build_content(
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    fields = (
        "tree_sha256",
        "entry_count",
        "file_count",
        "total_bytes",
        "build_id_sha256",
    )
    return all(left.get(field) == right.get(field) for field in fields)


def _activate_staged_frontend_build(
    *,
    active_next: Path,
    staged_next: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    active_before = frontend_build_tree_facts(active_next)
    staged_facts = frontend_build_tree_facts(staged_next)
    primitive = _atomic_exchange_directories(active_next, staged_next)
    try:
        active_after = frontend_build_tree_facts(active_next)
        if not _same_build_content(staged_facts, active_after):
            raise ReleaseOperationError("activated frontend differs from verified staged build")
    except BaseException as activation_error:
        _atomic_exchange_directories(active_next, staged_next)
        restored = frontend_build_tree_facts(active_next)
        if restored != active_before:
            raise ReleaseOperationError(
                "frontend build rollback did not restore bytes"
            ) from activation_error
        raise
    return active_after, {
        "primitive": primitive,
        "active_before": active_before,
        "staged_verified": staged_facts,
        "active_after": active_after,
        "old_build_retained_for_restart_transaction": True,
    }


def _retain_frontend_rollback(
    *,
    repository_root: Path,
    active_next: Path,
    staged_next: Path,
    activation: dict[str, object],
) -> dict[str, object]:
    """Move the old active build into a private restart-transaction authority."""

    rollback_parent = ensure_private_directory(
        repository_root / "data" / "_runtime" / "agent-v02-frontend-rollbacks"
    )
    placeholder = Path(
        tempfile.mkdtemp(
            prefix="previous-",
            dir=rollback_parent,
        )
    )
    os.chmod(placeholder, 0o700)
    placeholder.rmdir()
    try:
        os.replace(staged_next, placeholder)
        rollback_facts = frontend_build_tree_facts(placeholder)
        active_facts = frontend_build_tree_facts(active_next)
        active_before = activation.get("active_before")
        active_after = activation.get("active_after")
        if not isinstance(active_before, dict) or not isinstance(active_after, dict):
            raise ReleaseOperationError("frontend activation authority is malformed")
        if not _same_build_content(rollback_facts, active_before):
            raise ReleaseOperationError("retained frontend rollback bytes changed")
        if active_facts != active_after:
            raise ReleaseOperationError("active frontend changed while retaining rollback")
    except BaseException as retention_error:
        if placeholder.is_dir() and active_next.is_dir():
            _atomic_exchange_directories(active_next, placeholder)
            restored = frontend_build_tree_facts(active_next)
            active_before = activation.get("active_before")
            if not isinstance(active_before, dict) or restored != active_before:
                raise ReleaseOperationError(
                    "frontend rollback retention failure did not restore bytes"
                ) from retention_error
        raise
    return {
        "path": str(placeholder),
        "facts": rollback_facts,
        "available_until_restart_outcome": True,
    }


def _restore_frontend_rollback(
    *,
    active_next: Path,
    rollback: dict[str, object],
    activation: dict[str, object],
) -> dict[str, object]:
    """Atomically restore the pre-build bytes after a later restart failure."""

    rollback_path_value = rollback.get("path")
    rollback_facts = rollback.get("facts")
    if not isinstance(rollback_path_value, str) or not isinstance(
        rollback_facts,
        dict,
    ):
        raise ReleaseOperationError("frontend rollback authority is malformed")
    rollback_path = Path(rollback_path_value)
    active_before = activation.get("active_before")
    active_after = activation.get("active_after")
    if not isinstance(active_before, dict) or not isinstance(active_after, dict):
        raise ReleaseOperationError("frontend activation authority is malformed")
    current_active = frontend_build_tree_facts(active_next)
    current_rollback = frontend_build_tree_facts(rollback_path)
    if current_active != active_after:
        raise ReleaseOperationError("active frontend changed before rollback")
    if current_rollback != rollback_facts or not _same_build_content(
        current_rollback,
        active_before,
    ):
        raise ReleaseOperationError("retained frontend rollback authority changed")
    primitive = _atomic_exchange_directories(active_next, rollback_path)
    restored = frontend_build_tree_facts(active_next)
    parked_candidate = frontend_build_tree_facts(rollback_path)
    if restored != active_before:
        raise ReleaseOperationError("frontend restart rollback did not restore bytes")
    if not _same_build_content(parked_candidate, active_after):
        raise ReleaseOperationError("frontend candidate changed during rollback")
    return {
        "status": "restored",
        "primitive": primitive,
        "active_restored": restored,
        "candidate_parked": parked_candidate,
        "rollback_path": str(rollback_path),
    }


def _frontend_build_environment(
    *,
    npm: Path,
    workspace: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    """Create a private, offline build environment without backend secrets."""

    node_text = shutil.which("node")
    if node_text is None:
        raise ReleaseOperationError("node is unavailable for current-HEAD frontend build")
    node = Path(node_text)
    environment_root = ensure_private_directory(workspace / "build-environment")
    writable_roots: dict[str, Path] = {}
    for name in ("home", "tmp", "xdg-cache", "npm-cache"):
        writable_roots[name] = ensure_private_directory(environment_root / name)

    path_entries = tuple(
        dict.fromkeys(
            (
                str(node.resolve().parent),
                str(npm.resolve().parent),
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            )
        )
    )
    environment = {
        "HOME": str(writable_roots["home"]),
        "TMPDIR": str(writable_roots["tmp"]),
        "TMP": str(writable_roots["tmp"]),
        "TEMP": str(writable_roots["tmp"]),
        "XDG_CACHE_HOME": str(writable_roots["xdg-cache"]),
        "NPM_CONFIG_CACHE": str(writable_roots["npm-cache"]),
        "NPM_CONFIG_OFFLINE": "true",
        "NPM_CONFIG_PREFER_OFFLINE": "true",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_PROGRESS": "false",
        "NEXT_TELEMETRY_DISABLED": "1",
        "TURBO_TELEMETRY_DISABLED": "1",
        "NODE_ENV": "production",
        "CI": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.pathsep.join(path_entries),
    }
    inherited_names: list[str] = []
    for name in (
        "NEXT_PUBLIC_QUANT_API_BASE_URL",
        "QUANT_API_REWRITE_ORIGIN",
    ):
        value = os.environ.get(name)
        if value is None:
            continue
        if (
            not value
            or len(value.encode("utf-8")) > 4096
            or any(character in value for character in ("\x00", "\r", "\n"))
        ):
            raise ReleaseOperationError(f"frontend build environment field is invalid: {name}")
        parsed = urllib.parse.urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ReleaseOperationError(
                f"frontend build environment field has an invalid port: {name}"
            ) from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or port is None
        ):
            raise ReleaseOperationError(
                f"frontend build environment field is not a loopback origin: {name}"
            )
        environment[name] = value
        inherited_names.append(name)

    value_digests = {
        name: {
            "bytes": len(value.encode("utf-8")),
            "sha256": sha256_bytes(value.encode("utf-8")),
        }
        for name, value in sorted(environment.items())
    }
    writable_root_facts = {
        name: {
            "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
            "owner_uid": path.stat().st_uid,
            "path": str(path),
        }
        for name, path in sorted(writable_roots.items())
    }
    authority: dict[str, object] = {
        "environment_names": sorted(environment),
        "environment_value_digests": value_digests,
        "build_tools": {
            "node": _regular_artifact_stamp(node, executable=True),
            "npm": _regular_artifact_stamp(npm, executable=True),
        },
        "inherited_frontend_build_fields": sorted(inherited_names),
        "network_policy": {
            "npm_offline": True,
            "npm_update_notifier": False,
            "next_telemetry_disabled": True,
            "turbo_telemetry_disabled": True,
            "proxy_environment_inherited": False,
        },
        "private_writable_roots": writable_root_facts,
    }
    authority["authority_sha256"] = sha256_bytes(canonical_json_bytes(authority))
    return environment, authority


def _frontend_build_input_authority(
    repository_root: Path,
    *,
    npm: Path,
) -> dict[str, object]:
    """Bind the actual frontend environment, manifests, and installed tools."""

    node_text = shutil.which("node")
    if node_text is None:
        raise ReleaseOperationError("node is unavailable for frontend input authority")
    frontend_root = repository_root / "src" / "frontend"
    runtime_root = repository_root / "data" / "_runtime"
    environment_path = Path(
        os.environ.get(
            "QS_AGENT_V02_FRONTEND_ENV_FILE",
            runtime_root / "agent-v0.2-frontend.env",
        )
    )
    body: dict[str, object] = {
        "environment": _private_environment_stamp(environment_path),
        "locks": {
            "package_lock": _regular_artifact_stamp(frontend_root / "package-lock.json"),
            "installed_package_lock": _regular_artifact_stamp(
                frontend_root / "node_modules" / ".package-lock.json"
            ),
        },
        "dependencies": {
            "package_manifest": _regular_artifact_stamp(frontend_root / "package.json"),
            "installed_next_manifest": _regular_artifact_stamp(
                frontend_root / "node_modules" / "next" / "package.json"
            ),
        },
        "tools": {
            "node": _regular_artifact_stamp(Path(node_text), executable=True),
            "npm": _regular_artifact_stamp(npm, executable=True),
            "next": _regular_artifact_stamp(
                frontend_root / "node_modules" / ".bin" / "next",
                executable=True,
            ),
        },
    }
    body["authority_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _build_current_frontend(
    repository_root: Path,
    identity: GitIdentity,
) -> tuple[dict[str, object], dict[str, object]]:
    npm = shutil.which("npm")
    if npm is None:
        raise ReleaseOperationError("npm is unavailable for current-HEAD frontend build")
    npm_path = Path(npm)
    frontend_root = repository_root / "src" / "frontend"
    active_node_modules = frontend_root / "node_modules"
    active_next = frontend_root / ".next"
    if active_node_modules.is_symlink() or not active_node_modules.is_dir():
        raise ReleaseOperationError("release frontend node_modules is unavailable")
    if active_next.is_symlink() or not active_next.is_dir():
        raise ReleaseOperationError("active frontend build is unavailable")
    build_inputs_pre = _frontend_build_input_authority(
        repository_root,
        npm=npm_path,
    )
    staging_parent = ensure_private_directory(
        repository_root / "data" / "_runtime" / "agent-v02-frontend-builds"
    )
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=staging_parent) as raw:
        workspace = Path(raw)
        os.chmod(workspace, 0o700)
        staged_frontend = _extract_committed_frontend(repository_root, workspace)
        staged_node_modules = staged_frontend / "node_modules"
        staged_node_modules.symlink_to(active_node_modules, target_is_directory=True)
        build_environment, build_environment_authority = _frontend_build_environment(
            npm=npm_path,
            workspace=workspace,
        )
        completed = subprocess.run(
            [npm, "run", "build"],
            cwd=staged_frontend,
            env=build_environment,
            check=False,
            capture_output=True,
        )
        command = {
            "argv": [npm, "run", "build"],
            "working_directory_kind": "isolated_committed_frontend_archive",
            "exit_code": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stdout_bytes": len(completed.stdout),
            "stderr_sha256": sha256_bytes(completed.stderr),
            "stderr_bytes": len(completed.stderr),
            "environment": build_environment_authority,
        }
        if completed.returncode != 0:
            raise ReleaseOperationError("current-HEAD frontend build failed")
        build_inputs_post_build = _frontend_build_input_authority(
            repository_root,
            npm=npm_path,
        )
        if build_inputs_post_build != build_inputs_pre:
            raise ReleaseOperationError(
                "frontend environment, dependency, or install changed during build"
            )
        staged_next = staged_frontend / ".next"
        excluded_build_cache = _prune_staged_frontend_cache(staged_next)
        command["excluded_build_cache"] = excluded_build_cache
        path_rebinding = _rebind_staged_build_paths(
            staged_next,
            staged_frontend=staged_frontend,
            active_frontend=frontend_root,
        )
        staged_verified = frontend_build_tree_facts(staged_next)
        post_build_identity = git_identity(repository_root, require_clean=True)
        if post_build_identity != identity:
            raise ReleaseOperationError("repository identity changed during frontend build")
        active_facts, activation = _activate_staged_frontend_build(
            active_next=active_next,
            staged_next=staged_next,
        )
        try:
            if not _same_build_content(staged_verified, active_facts):
                raise ReleaseOperationError("frontend activation digest changed")
            build_inputs_post_activation = _frontend_build_input_authority(
                repository_root,
                npm=npm_path,
            )
            if build_inputs_post_activation != build_inputs_pre:
                raise ReleaseOperationError("frontend inputs changed across build activation")
            post_build_identity = git_identity(repository_root, require_clean=True)
            if post_build_identity != identity:
                raise ReleaseOperationError("repository identity changed after frontend activation")
            authority = {
                "repository": {
                    "commit": identity.commit,
                    "tree": identity.tree,
                },
                "next": active_facts,
                "excluded_build_cache": excluded_build_cache,
                "path_rebinding": path_rebinding,
                "atomic_activation": activation,
                "build_inputs": {
                    "pre_build": build_inputs_pre,
                    "post_build": build_inputs_post_build,
                    "post_activation": build_inputs_post_activation,
                    "unchanged": True,
                },
            }
            rollback = _retain_frontend_rollback(
                repository_root=repository_root,
                active_next=active_next,
                staged_next=staged_next,
                activation=activation,
            )
            activation["rollback"] = rollback
            validate_frontend_build_authority(authority, identity)
        except BaseException as validation_error:
            rollback_value = activation.get("rollback")
            if isinstance(rollback_value, dict):
                _restore_frontend_rollback(
                    active_next=active_next,
                    rollback=rollback_value,
                    activation=activation,
                )
            elif staged_next.is_dir():
                _atomic_exchange_directories(active_next, staged_next)
                restored = frontend_build_tree_facts(active_next)
                if restored != activation["active_before"]:
                    raise ReleaseOperationError(
                        "frontend post-activation rollback did not restore bytes"
                    ) from validation_error
            elif frontend_build_tree_facts(active_next) != activation["active_before"]:
                raise ReleaseOperationError(
                    "frontend activation failure lost rollback authority"
                ) from validation_error
            raise
    return authority, command


def _json_get(
    url: str,
    *,
    timeout: float = 3,
) -> dict[str, object]:
    headers = {
        "Accept": "application/json",
        "Origin": FRONTEND_ORIGIN,
        "Sec-Fetch-Site": "same-origin",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_RejectRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ReleaseOperationError(f"provider-free observation failed: {url}")
            if response.geturl() != url:
                raise ReleaseOperationError("provider-free observation redirected")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise ReleaseOperationError("provider-free observation is not JSON content")
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ReleaseOperationError(f"provider-free observation unavailable: {url}") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise ReleaseOperationError("provider-free observation is oversized")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("provider-free observation is not JSON") from exc
    if not isinstance(document, dict):
        raise ReleaseOperationError("provider-free observation is not an object")
    return document


def _launchctl_document(launchctl: str, domain: str, label: str) -> str:
    completed = subprocess.run(
        [launchctl, "print", f"{domain}/{label}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReleaseOperationError(f"launchd job is unavailable: {label}")
    return completed.stdout


def _connector_mode_from_process_command(command: str) -> str:
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        raise ReleaseOperationError("connector process command is malformed") from exc
    if not any(
        arguments[index : index + 2] == ["hermes", "connector-worker"]
        for index in range(max(0, len(arguments) - 1))
    ):
        raise ReleaseOperationError("connector process is not the connector worker")
    modes: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == "--mode":
            if index + 1 >= len(arguments):
                raise ReleaseOperationError("connector process mode is malformed")
            modes.append(arguments[index + 1])
        elif argument.startswith("--mode="):
            modes.append(argument.partition("=")[2])
    if modes != ["reconcile_only"]:
        raise ReleaseOperationError("connector process mode is not exactly reconcile_only")
    return modes[0]


def _process_facts(
    *,
    launchctl: str,
    domain: str,
    label: str,
    repository_root: Path,
    preflight: dict[str, object],
    require_runtime_match: bool = True,
) -> dict[str, object]:
    launchd = _launchctl_document(launchctl, domain, label)
    pid = parse_launchctl_pid(launchd)
    scripts = {
        BACKEND_LABEL: "run_quant_backend.sh",
        FRONTEND_LABEL: "run_quant_frontend.sh",
        CONNECTOR_LABEL: "run_agent_v02_connector.sh",
    }
    script = scripts.get(label)
    if script is None:
        raise ReleaseOperationError("unknown launchd label")
    expected_script = repository_root / "scripts" / script
    if str(expected_script) not in launchd:
        raise ReleaseOperationError(f"launchd source path mismatch: {label}")
    launcher_sha256 = sha256_file(expected_script)
    if launcher_sha256 != preflight.get("source_sha256"):
        raise ReleaseOperationError(f"launchd source changed after preflight: {label}")
    command = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    executable = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm="],
        check=False,
        capture_output=True,
        text=True,
    )
    process_start = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=False,
        capture_output=True,
        text=True,
    )
    executable_images = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-d", "txt", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    cwd_result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    if any(
        result.returncode != 0
        for result in (
            command,
            executable,
            process_start,
            executable_images,
            cwd_result,
        )
    ):
        raise ReleaseOperationError(f"process identity observation failed: {label}")
    process_started_at = process_start.stdout.strip()
    if not process_started_at:
        raise ReleaseOperationError(f"process start identity is absent: {label}")
    image_paths = [
        line[1:]
        for line in executable_images.stdout.splitlines()
        if line.startswith("n") and len(line) > 1
    ]
    if not image_paths:
        raise ReleaseOperationError(f"process executable image is absent: {label}")
    last_exit_code = observed_launchctl_last_exit_code(launchd, label=label)
    runtime = preflight.get("runtime")
    if not isinstance(runtime, dict):
        raise ReleaseOperationError(f"preflight runtime identity is absent: {label}")
    runtime_executable_name = "node" if label == FRONTEND_LABEL else "python"
    runtime_executable = runtime.get(runtime_executable_name)
    if not isinstance(runtime_executable, str):
        raise ReleaseOperationError(f"preflight executable identity is absent: {label}")
    runtime_matches = Path(image_paths[0]).resolve() == Path(runtime_executable).resolve()
    if require_runtime_match and not runtime_matches:
        raise ReleaseOperationError(f"running executable differs from preflight: {label}")
    cwd_paths = [
        line[1:]
        for line in cwd_result.stdout.splitlines()
        if line.startswith("n") and len(line) > 1
    ]
    expected_cwd = (
        repository_root / "src" / "frontend" if label == FRONTEND_LABEL else repository_root
    )
    if len(cwd_paths) != 1 or Path(cwd_paths[0]).resolve() != expected_cwd.resolve():
        raise ReleaseOperationError(f"process working directory mismatch: {label}")

    facts: dict[str, object] = {
        "label": label,
        "pid": pid,
        "process_executable": executable.stdout.strip(),
        "process_started_at": process_started_at,
        "process_command": command.stdout.strip(),
        "actual_executable_image": image_paths[0],
        "actual_executable_image_sha256": sha256_file(Path(image_paths[0])),
        "mapped_text_image_count": len(image_paths),
        "working_directory": cwd_paths[0],
        "launchd_document_sha256": sha256_bytes(launchd.encode("utf-8")),
        "launcher_path": str(expected_script),
        "launcher_sha256": launcher_sha256,
        "last_exit_code": last_exit_code,
        "preflight_source_sha256": preflight["source_sha256"],
        "runtime_matches_preflight": runtime_matches,
    }
    if label == CONNECTOR_LABEL:
        facts["launchd_runs"] = parse_launchctl_runs(launchd)
        facts["connector_mode"] = _connector_mode_from_process_command(command.stdout.strip())
    if label in {BACKEND_LABEL, FRONTEND_LABEL}:
        listeners = subprocess.run(
            [
                "lsof",
                "-nP",
                "-a",
                "-p",
                str(pid),
                "-iTCP",
                "-sTCP:LISTEN",
                "-Fn",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if listeners.returncode != 0:
            raise ReleaseOperationError(f"listener observation failed: {label}")
        listener_names = [
            line[1:]
            for line in listeners.stdout.splitlines()
            if line.startswith("n") and len(line) > 1
        ]
        expected_port = 8765 if label == BACKEND_LABEL else 3001
        expected_listener = f"127.0.0.1:{expected_port}"
        if not listener_names or set(listener_names) != {expected_listener}:
            raise ReleaseOperationError(f"process listener is not exact loopback: {label}")
        facts.update(
            {
                "listener_sha256": sha256_bytes(listeners.stdout.encode("utf-8")),
                "listeners": sorted(set(listener_names)),
                "loopback_port": expected_port,
            }
        )
    if label == FRONTEND_LABEL:
        installed_root = (repository_root / "src" / "frontend" / "node_modules").resolve()
        mapped_installed = [
            path for path in image_paths if Path(path).resolve().is_relative_to(installed_root)
        ]
        if not mapped_installed:
            raise ReleaseOperationError("frontend has no mapped release node_modules image")
        facts["mapped_release_node_modules_images"] = mapped_installed
        facts["next_build"] = frontend_build_tree_facts(
            repository_root / "src" / "frontend" / ".next"
        )
    return facts


def _wait_tcp(port: int, *, deadline: float) -> None:
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise ReleaseOperationError(f"loopback port {port} did not become ready") from last_error


def _wait_settings(*, deadline: float) -> dict[str, object]:
    last_error: ReleaseOperationError | None = None
    while time.monotonic() < deadline:
        try:
            return _json_get(SETTINGS_URL)
        except ReleaseOperationError as exc:
            last_error = exc
            time.sleep(0.2)
    raise ReleaseOperationError("provider-free /api/settings did not become ready") from last_error


def _release_status(repository_root: Path) -> dict[str, object]:
    cli = repository_root / ".venv" / "bin" / "quant-system"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ReleaseOperationError("installed quant-system CLI is unavailable")
    argv = [str(cli), "hermes", "release", "status"]
    completed = subprocess.run(
        argv,
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ReleaseOperationError("provider-free release status command failed")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("release status output is not JSON") from exc
    return {
        "facts": validate_release_observation(document),
        "command": {
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stdout_bytes": len(completed.stdout),
            "stderr_sha256": sha256_bytes(completed.stderr),
            "stderr_bytes": len(completed.stderr),
        },
    }


def _validate_connector_cycle(
    document: object,
    *,
    require_liveness: bool = False,
) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("connector cycle is not a JSON object")
    if document.get("mode") != "reconcile_only":
        raise ReleaseOperationError("connector is not in reconcile-only mode")
    zero_fields = (
        "claimed_count",
        "delivered_count",
        "dispatch_unknown_count",
        "hermes_mutation_count",
        "outcome_unknown_count",
        "provider_call_count",
        "recovered_count",
        "rejected_count",
        "requeued_count",
        "terminal_count",
    )
    observed: dict[str, int] = {}
    for field in zero_fields:
        value = document.get(field)
        if type(value) is not int or value != 0:
            raise ReleaseOperationError(f"connector cycle has a nonzero effect: {field}")
        observed[field] = value
    if document.get("last_command_id") is not None:
        raise ReleaseOperationError("connector cycle observed a command")
    if document.get("last_dispatch_outcome") is not None:
        raise ReleaseOperationError("connector cycle observed a dispatch outcome")
    connector_liveness = document.get("connector_liveness")
    if require_liveness:
        if not isinstance(connector_liveness, dict):
            raise ReleaseOperationError("connector cycle liveness fact is absent")
        status = connector_liveness.get("status")
        if not isinstance(status, str) or not status:
            raise ReleaseOperationError("connector cycle liveness status is absent")
        if status == "active":
            if (
                connector_liveness.get("mode") != "reconcile_only"
                or not isinstance(connector_liveness.get("generation_token"), str)
                or not connector_liveness["generation_token"]
            ):
                raise ReleaseOperationError("active connector liveness generation is malformed")
        elif connector_liveness != {"status": "not_acquired"}:
            raise ReleaseOperationError("reconcile-only connector liveness state is not exact")
    return {
        "mode": "reconcile_only",
        "effect_counters": observed,
        "last_command_id": None,
        "last_dispatch_outcome": None,
        "capability_read_status": document.get("capability_read_status"),
        "connector_liveness": connector_liveness,
        "session_provisioning": document.get("session_provisioning"),
    }


def _connector_generation_authority(
    process_facts: object,
) -> dict[str, object]:
    if not isinstance(process_facts, dict):
        raise ReleaseOperationError("connector generation process facts are absent")
    required = {
        "label": str,
        "pid": int,
        "process_started_at": str,
        "process_command": str,
        "actual_executable_image": str,
        "actual_executable_image_sha256": str,
        "launcher_sha256": str,
        "launchd_runs": int,
        "last_exit_code": int,
        "connector_mode": str,
    }
    for field, expected_type in required.items():
        value = process_facts.get(field)
        if type(value) is not expected_type or (expected_type is str and not value):
            raise ReleaseOperationError(f"connector generation fact is absent: {field}")
    if process_facts["label"] != CONNECTOR_LABEL:
        raise ReleaseOperationError("connector generation label is invalid")
    if process_facts["pid"] <= 0 or process_facts["launchd_runs"] <= 0:
        raise ReleaseOperationError("connector generation values are invalid")
    if process_facts["last_exit_code"] != 0:
        raise ReleaseOperationError("connector generation has a nonzero exit")
    if process_facts["connector_mode"] != "reconcile_only":
        raise ReleaseOperationError("connector generation mode is not reconcile_only")
    body: dict[str, object] = {
        "pid": process_facts["pid"],
        "launchd_runs": process_facts["launchd_runs"],
        "process_started_at": process_facts["process_started_at"],
        "process_command_sha256": sha256_bytes(
            str(process_facts["process_command"]).encode("utf-8")
        ),
        "actual_executable_image": process_facts["actual_executable_image"],
        "actual_executable_image_sha256": process_facts["actual_executable_image_sha256"],
        "launcher_sha256": process_facts["launcher_sha256"],
        "mode": "reconcile_only",
        "last_exit_code": 0,
    }
    body["authority_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _validate_connector_heartbeat_observation(
    boundary: object,
    observation: object,
) -> dict[str, object]:
    if not isinstance(boundary, dict) or not isinstance(observation, dict):
        raise ReleaseOperationError("connector heartbeat authority is absent")
    boundary_offset = boundary.get("offset")
    boundary_time = boundary.get("captured_monotonic_ns")
    observed_start = observation.get("start_offset")
    observed_end = observation.get("end_offset")
    observed_time = observation.get("observed_monotonic_ns")
    if any(
        type(value) is not int
        for value in (
            boundary_offset,
            boundary_time,
            observed_start,
            observed_end,
            observed_time,
        )
    ):
        raise ReleaseOperationError("connector heartbeat offsets are malformed")
    assert isinstance(boundary_offset, int)
    assert isinstance(boundary_time, int)
    assert isinstance(observed_start, int)
    assert isinstance(observed_end, int)
    assert isinstance(observed_time, int)
    if observed_start < boundary_offset or observed_end <= observed_start:
        raise ReleaseOperationError("connector heartbeat predates follow boundary")
    if observed_time <= boundary_time:
        raise ReleaseOperationError("connector heartbeat observation is stale")
    boundary_generation = boundary.get("connector_generation")
    observed_generation = observation.get("connector_generation")
    if not isinstance(boundary_generation, dict) or observed_generation != boundary_generation:
        raise ReleaseOperationError("connector heartbeat generation changed during cycle")
    cycle = observation.get("cycle")
    if not isinstance(cycle, dict):
        raise ReleaseOperationError("connector heartbeat cycle is absent")
    if cycle.get("mode") != "reconcile_only":
        raise ReleaseOperationError("connector heartbeat mode is not reconcile_only")
    if not isinstance(cycle.get("connector_liveness"), dict):
        raise ReleaseOperationError("connector heartbeat liveness fact is absent")
    return {
        **observation,
        "fresh_after_boundary": True,
        "same_connector_generation": True,
        "mode": "reconcile_only",
    }


def _connector_log_snapshot(
    path: Path,
    *,
    require_liveness: bool = False,
) -> dict[str, object]:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseOperationError("connector log is absent") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ReleaseOperationError("connector log is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
            raise ReleaseOperationError("connector log identity changed during observation")
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_uid != os.getuid()
            or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise ReleaseOperationError("connector log is not owner-only")
        if current.st_size == 0:
            raise ReleaseOperationError("connector log is empty")
        observed_device = current.st_dev
        observed_inode = current.st_ino
        observed_offset = current.st_size
        os.lseek(descriptor, -1, os.SEEK_END)
        if os.read(descriptor, 1) != b"\n":
            raise ReleaseOperationError("connector log has an incomplete current record")
        read_size = min(observed_offset, 1024 * 1024)
        os.lseek(descriptor, observed_offset - read_size, os.SEEK_SET)
        tail = os.read(descriptor, read_size)
    finally:
        os.close(descriptor)
    complete_lines = [line for line in tail.splitlines() if line.strip()]
    if not complete_lines:
        raise ReleaseOperationError("connector log has no complete record")
    try:
        latest = json.loads(complete_lines[-1])
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("latest connector cycle is not JSON") from exc
    return {
        "path": str(path),
        "device": observed_device,
        "inode": observed_inode,
        "offset": observed_offset,
        "latest_cycle": _validate_connector_cycle(
            latest,
            require_liveness=require_liveness,
        ),
        "latest_cycle_sha256": sha256_bytes(complete_lines[-1] + b"\n"),
    }


def _capture_connector_follow_boundary(
    path: Path,
    *,
    pre_restart_snapshot: dict[str, object],
    process_facts: dict[str, dict[str, dict[str, object]]],
    require_connector_authority: bool = False,
) -> dict[str, object]:
    """Set the follow offset only after replacement PID facts are available."""

    pre = process_facts.get("pre")
    post = process_facts.get("post")
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise ReleaseOperationError("restart process facts are malformed")
    for service in ("backend", "frontend", "connector"):
        before = pre.get(service)
        after = post.get(service)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ReleaseOperationError("restart process facts are incomplete")
        if type(before.get("pid")) is not int or type(after.get("pid")) is not int:
            raise ReleaseOperationError("restart process pid facts are malformed")
    for service in ("backend", "frontend"):
        if pre[service]["pid"] == post[service]["pid"]:
            raise ReleaseOperationError(f"{service} pid did not change")
    if pre["connector"]["pid"] != post["connector"]["pid"]:
        raise ReleaseOperationError("connector was unexpectedly restarted")

    boundary = _connector_log_snapshot(
        path,
        require_liveness=require_connector_authority,
    )
    for field in ("device", "inode"):
        if boundary.get(field) != pre_restart_snapshot.get(field):
            raise ReleaseOperationError("connector log identity changed before follow boundary")
    pre_offset = pre_restart_snapshot.get("offset")
    boundary_offset = boundary.get("offset")
    if type(pre_offset) is not int or type(boundary_offset) is not int:
        raise ReleaseOperationError("connector log boundary is malformed")
    if boundary_offset < pre_offset:
        raise ReleaseOperationError("connector log truncated before follow boundary")
    if require_connector_authority:
        pre_generation = _connector_generation_authority(pre["connector"])
        post_generation = _connector_generation_authority(post["connector"])
        if post_generation != pre_generation:
            raise ReleaseOperationError("connector generation changed before follow boundary")
        boundary["connector_generation"] = post_generation
        boundary["captured_monotonic_ns"] = time.monotonic_ns()
    return boundary


def _wait_fresh_connector_cycle(
    path: Path,
    *,
    snapshot: dict[str, object],
    deadline: float,
    connector_generation: dict[str, object] | None = None,
    require_liveness: bool = False,
) -> dict[str, object]:
    offset = snapshot.get("offset")
    device = snapshot.get("device")
    inode = snapshot.get("inode")
    if type(offset) is not int or type(device) is not int or type(inode) is not int:
        raise ReleaseOperationError("connector log snapshot is malformed")
    while time.monotonic() < deadline:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            current = os.fstat(descriptor)
            if current.st_dev != device or current.st_ino != inode:
                raise ReleaseOperationError("connector log rotated during restart")
            if current.st_size < offset:
                raise ReleaseOperationError("connector log was truncated during restart")
            available = current.st_size - offset
            if available > 1024 * 1024:
                raise ReleaseOperationError("fresh connector evidence is oversized")
            os.lseek(descriptor, offset, os.SEEK_SET)
            appended = os.read(descriptor, available)
        finally:
            os.close(descriptor)
        for line in appended.splitlines(keepends=True):
            if not line.endswith(b"\n") or not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseOperationError("fresh connector cycle is not JSON") from exc
            observation: dict[str, object] = {
                "start_offset": offset,
                "end_offset": offset + len(line),
                "record_sha256": sha256_bytes(line),
                "cycle": _validate_connector_cycle(
                    document,
                    require_liveness=require_liveness,
                ),
            }
            if require_liveness:
                if connector_generation is None:
                    raise ReleaseOperationError(
                        "connector generation is absent from heartbeat wait"
                    )
                observation["observed_monotonic_ns"] = time.monotonic_ns()
                observation["connector_generation"] = connector_generation
                return _validate_connector_heartbeat_observation(
                    snapshot,
                    observation,
                )
            return observation
        time.sleep(0.2)
    raise ReleaseOperationError("no fresh connector cycle arrived after restart")


def _command_queue_facts(settings: Settings) -> dict[str, object]:
    database = get_database(settings)
    if database is None:
        raise ReleaseOperationError("command queue database is unavailable")
    try:
        with database.connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            rows = conn.execute(
                """
                SELECT state, count(*)
                FROM quant_system.hermes_commands
                GROUP BY state
                ORDER BY state
                """
            ).fetchall()
            pending_outbox = conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_outbox
                WHERE topic = 'hermes.command.queued'
                  AND consumed_at IS NULL
                """
            ).fetchone()
    except Exception as exc:
        raise ReleaseOperationError("command queue read-only observation failed") from exc
    state_counts = {str(row[0]): int(row[1]) for row in rows}
    active_count = sum(state_counts.get(state, 0) for state in ("queued", "leased"))
    outbox_count = int(pending_outbox[0]) if pending_outbox is not None else -1
    if active_count != 0 or outbox_count != 0:
        raise ReleaseOperationError("connector command queue is not empty")
    return {
        "state_counts": state_counts,
        "queued_or_leased_count": active_count,
        "pending_queued_outbox_count": outbox_count,
        "transaction_read_only": True,
    }


def _preflight_check(repository_root: Path, script: str) -> dict[str, object]:
    path = repository_root / "scripts" / script
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ReleaseOperationError(f"restart launcher is unsafe: {script}")
    source = path.read_text(encoding="utf-8")
    validate_launcher_source(source)
    completed = subprocess.run(
        [str(path), "--check"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise ReleaseOperationError(f"restart preflight failed: {script}")
    try:
        stdout = completed.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseOperationError(f"restart preflight is not UTF-8: {script}") from exc
    patterns = {
        "run_quant_backend.sh": (
            re.compile(r"^backend_ready=true release_root=(\S+) python=(\S+)$"),
            ("release_root", "python"),
            'exec "$PYTHON" -m quant_system.cli serve --host 127.0.0.1 --port 8765',
        ),
        "run_quant_frontend.sh": (
            re.compile(r"^frontend_ready=true release_root=(\S+) node=(\S+) next=(\S+)$"),
            ("release_root", "node", "next"),
            'exec "$NODE_BIN" "$NEXT_BIN" start -H 127.0.0.1 -p 3001',
        ),
        "run_agent_v02_connector.sh": (
            re.compile(r"^connector_ready=true release_root=(\S+) python=(\S+)$"),
            ("release_root", "python"),
            'exec "$PYTHON" -m quant_system.cli hermes connector-worker',
        ),
    }
    definition = patterns.get(script)
    if definition is None:
        raise ReleaseOperationError(f"unknown restart preflight: {script}")
    pattern, fields, required_exec = definition
    match = pattern.fullmatch(stdout)
    if match is None:
        raise ReleaseOperationError(f"restart preflight identity is malformed: {script}")
    runtime = dict(zip(fields, match.groups(), strict=True))
    if Path(runtime["release_root"]).resolve() != repository_root.resolve():
        raise ReleaseOperationError(f"restart preflight release root mismatch: {script}")
    if required_exec not in source:
        raise ReleaseOperationError(f"restart launcher exec contract mismatch: {script}")
    executable_name = "node" if script == "run_quant_frontend.sh" else "python"
    executable = Path(runtime[executable_name])
    resolved_executable = executable.resolve() if executable.is_symlink() else executable.absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ReleaseOperationError(f"restart preflight executable is absent: {script}")
    runtime[f"{executable_name}_resolved"] = str(resolved_executable)
    if script == "run_quant_backend.sh":
        expected_module = repository_root / "src" / "quant_system" / "__init__.py"
        if 'export PYTHONPATH="$ROOT/src' not in source:
            raise ReleaseOperationError("backend launcher does not bind release source")
        if expected_module.is_symlink() or not expected_module.is_file():
            raise ReleaseOperationError("backend release module is absent")
        runtime["module"] = str(expected_module)
        runtime["module_sha256"] = sha256_file(expected_module)
    if script == "run_quant_frontend.sh":
        expected_next = repository_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
        if Path(runtime["next"]).absolute() != expected_next.absolute():
            raise ReleaseOperationError("frontend is not bound to release node_modules")
    return {
        "argv": [str(path), "--check"],
        "exit_code": completed.returncode,
        "source_sha256": sha256_bytes(source.encode("utf-8")),
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "runtime": runtime,
    }


def _private_environment_stamp(path: Path) -> dict[str, object]:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseOperationError(f"runtime environment file is absent: {path}") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ReleaseOperationError(f"runtime environment file is not owner-only: {path}")
    return {
        "path": str(path.resolve()),
        "owner_uid": info.st_uid,
        "mode": "0600",
        "bytes": info.st_size,
        "sha256": sha256_file(path),
    }


def _regular_artifact_stamp(
    path: Path,
    *,
    executable: bool = False,
) -> dict[str, object]:
    try:
        link_info = path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseOperationError(f"runtime authority artifact is absent: {path}") from exc
    resolved = path.resolve()
    if not resolved.is_file():
        raise ReleaseOperationError(f"runtime authority artifact is invalid: {path}")
    info = resolved.stat()
    if executable and not os.access(path, os.X_OK):
        raise ReleaseOperationError(f"runtime authority executable is not executable: {path}")
    return {
        "path": str(path.absolute()),
        "resolved_path": str(resolved),
        "path_kind": "symlink" if stat.S_ISLNK(link_info.st_mode) else "regular",
        "owner_uid": info.st_uid,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "bytes": info.st_size,
        "sha256": sha256_file(resolved),
    }


def _python_dependency_stamp(executable: Path, *, cwd: Path) -> dict[str, object]:
    script = (
        "import importlib.metadata as metadata,json,sys;"
        "items=sorted((d.metadata.get('Name') or '',d.version) "
        "for d in metadata.distributions());"
        "print(json.dumps({'executable':sys.executable,'version':sys.version,"
        "'items':items},sort_keys=True,separators=(',',':')))"
    )
    completed = subprocess.run(
        [str(executable), "-c", script],
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0 or completed.stderr:
        raise ReleaseOperationError("Python dependency inventory failed")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("Python dependency inventory is invalid") from exc
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise ReleaseOperationError("Python dependency inventory is malformed")
    return {
        "executable": str(executable.absolute()),
        "resolved_executable": str(executable.resolve()),
        "python_version": document.get("version"),
        "distribution_count": len(document["items"]),
        "inventory_sha256": sha256_bytes(canonical_json_bytes(document["items"])),
        "command_stdout_sha256": sha256_bytes(completed.stdout),
    }


def _runtime_authority_snapshot(
    repository_root: Path,
    checks: dict[str, dict[str, object]],
) -> dict[str, object]:
    runtime_root = repository_root / "data" / "_runtime"
    environment_paths = {
        "backend": Path(
            os.environ.get(
                "QS_AGENT_V02_BACKEND_ENV_FILE",
                runtime_root / "agent-v0.2-backend.env",
            )
        ),
        "frontend": Path(
            os.environ.get(
                "QS_AGENT_V02_FRONTEND_ENV_FILE",
                runtime_root / "agent-v0.2-frontend.env",
            )
        ),
        "connector": Path(
            os.environ.get(
                "QS_AGENT_V02_CONNECTOR_ENV_FILE",
                runtime_root / "agent-v0.2-connector.env",
            )
        ),
    }
    environments = {
        name: _private_environment_stamp(path) for name, path in environment_paths.items()
    }
    locks = {
        "python": _regular_artifact_stamp(repository_root / "uv.lock"),
        "frontend": _regular_artifact_stamp(
            repository_root / "src" / "frontend" / "package-lock.json"
        ),
    }
    dependencies = {
        "python_manifest": _regular_artifact_stamp(repository_root / "pyproject.toml"),
        "frontend_manifest": _regular_artifact_stamp(
            repository_root / "src" / "frontend" / "package.json"
        ),
    }
    runtimes: dict[str, dict[str, object]] = {}
    for service in ("backend", "frontend", "connector"):
        check = checks.get(service)
        runtime = check.get("runtime") if isinstance(check, dict) else None
        if not isinstance(runtime, dict):
            raise ReleaseOperationError(f"{service} runtime preflight is absent")
        runtimes[service] = runtime
    backend_python = Path(str(runtimes["backend"].get("python")))
    connector_python = Path(str(runtimes["connector"].get("python")))
    frontend_node = Path(str(runtimes["frontend"].get("node")))
    frontend_next = Path(str(runtimes["frontend"].get("next")))
    python_inventories: dict[str, object] = {}
    for executable in (backend_python, connector_python):
        resolved_key = str(executable.resolve())
        if resolved_key not in python_inventories:
            python_inventories[resolved_key] = _python_dependency_stamp(
                executable,
                cwd=repository_root,
            )
    installs = {
        "backend_python": _regular_artifact_stamp(
            backend_python,
            executable=True,
        ),
        "connector_python": _regular_artifact_stamp(
            connector_python,
            executable=True,
        ),
        "frontend_node": _regular_artifact_stamp(
            frontend_node,
            executable=True,
        ),
        "frontend_next": _regular_artifact_stamp(
            frontend_next,
            executable=True,
        ),
        "release_cli": _regular_artifact_stamp(
            repository_root / ".venv" / "bin" / "quant-system",
            executable=True,
        ),
        "frontend_node_modules_lock": _regular_artifact_stamp(
            repository_root / "src" / "frontend" / "node_modules" / ".package-lock.json"
        ),
        "frontend_next_package": _regular_artifact_stamp(
            repository_root / "src" / "frontend" / "node_modules" / "next" / "package.json"
        ),
        "python_dependency_inventories": python_inventories,
    }
    body = {
        "environments": environments,
        "locks": locks,
        "dependencies": dependencies,
        "installs": installs,
    }
    body["authority_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _stable_process_authority(process_facts: object) -> dict[str, object]:
    if not isinstance(process_facts, dict):
        raise ReleaseOperationError("stable process facts are absent")
    required_fields = (
        "label",
        "process_executable",
        "process_command",
        "actual_executable_image",
        "actual_executable_image_sha256",
        "working_directory",
        "launcher_path",
        "launcher_sha256",
        "preflight_source_sha256",
        "runtime_matches_preflight",
    )
    missing = [field for field in required_fields if field not in process_facts]
    if missing:
        raise ReleaseOperationError("stable process authority is incomplete: " + ",".join(missing))
    body = {field: process_facts[field] for field in required_fields}
    label = process_facts.get("label")
    if label in {BACKEND_LABEL, FRONTEND_LABEL}:
        for field in ("listeners", "loopback_port"):
            if field not in process_facts:
                raise ReleaseOperationError(f"stable process listener authority is absent: {label}")
            body[field] = process_facts[field]
    if label == FRONTEND_LABEL:
        for field in ("mapped_release_node_modules_images", "next_build"):
            if field not in process_facts:
                raise ReleaseOperationError(f"stable frontend process authority is absent: {field}")
            body[field] = process_facts[field]
    if label == CONNECTOR_LABEL:
        body["connector_generation"] = _connector_generation_authority(process_facts)
    body["authority_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _validate_pre_activation_restart_authority(
    authority: object,
    *,
    identity: GitIdentity,
    activation: object,
) -> dict[str, object]:
    if not isinstance(authority, dict):
        raise ReleaseOperationError("pre-activation restart authority is absent")
    authority_sha256 = authority.get("authority_sha256")
    unsigned = {field: value for field, value in authority.items() if field != "authority_sha256"}
    if (
        not isinstance(authority_sha256, str)
        or len(authority_sha256) != 64
        or sha256_bytes(canonical_json_bytes(unsigned)) != authority_sha256
    ):
        raise ReleaseOperationError("pre-activation restart authority digest is invalid")
    repository = authority.get("repository")
    if isinstance(repository, GitIdentity):
        repository_matches = repository == identity
    else:
        repository_matches = repository == asdict(identity)
    if not repository_matches:
        raise ReleaseOperationError("pre-activation repository identity is not current")
    if (
        type(authority.get("captured_monotonic_ns")) is not int
        or authority["captured_monotonic_ns"] <= 0
    ):
        raise ReleaseOperationError("pre-activation capture time is absent")
    if not isinstance(activation, dict):
        raise ReleaseOperationError("frontend activation authority is malformed")
    active_before = activation.get("active_before")
    processes = authority.get("processes")
    frontend = processes.get("frontend") if isinstance(processes, dict) else None
    pre_build = frontend.get("next_build") if isinstance(frontend, dict) else None
    if (
        not isinstance(active_before, dict)
        or not isinstance(pre_build, dict)
        or pre_build != active_before
    ):
        raise ReleaseOperationError("pre-activation frontend build is not bound to the old process")
    return authority


def _capture_pre_activation_restart_authority(
    repository_root: Path,
    *,
    identity: GitIdentity,
) -> dict[str, object] | None:
    """Capture the running generation while the old frontend bytes are active."""

    launchctl = shutil.which("launchctl")
    if launchctl is None:
        return None
    domain = f"gui/{os.getuid()}"
    checks = {
        "backend": _preflight_check(repository_root, "run_quant_backend.sh"),
        "frontend": _preflight_check(repository_root, "run_quant_frontend.sh"),
        "connector": _preflight_check(
            repository_root,
            "run_agent_v02_connector.sh",
        ),
    }
    runtime_authority = _runtime_authority_snapshot(repository_root, checks)
    connector_log_path = repository_root / CONNECTOR_LOG
    connector_log = _connector_log_snapshot(
        connector_log_path,
        require_liveness=True,
    )
    settings = Settings()
    processes = {
        "backend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=BACKEND_LABEL,
            repository_root=repository_root,
            preflight=checks["backend"],
            require_runtime_match=False,
        ),
        "frontend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=FRONTEND_LABEL,
            repository_root=repository_root,
            preflight=checks["frontend"],
            require_runtime_match=False,
        ),
        "connector": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=CONNECTOR_LABEL,
            repository_root=repository_root,
            preflight=checks["connector"],
        ),
    }
    connector_generation = _connector_generation_authority(processes["connector"])
    schema = schema_fingerprint(get_database(settings))
    if schema in {"<db-disabled>", "<unavailable>"}:
        raise ReleaseOperationError("pre-activation schema fingerprint is unavailable")
    authority: dict[str, object] = {
        "repository": asdict(identity),
        "captured_at": utc_now(),
        "captured_monotonic_ns": time.monotonic_ns(),
        "launchctl": launchctl,
        "domain": domain,
        "checks": checks,
        "runtime_authority": runtime_authority,
        "processes": processes,
        "stable_processes": {
            service: _stable_process_authority(facts) for service, facts in processes.items()
        },
        "connector_generation": connector_generation,
        "connector_log": connector_log,
        "settings": validate_live_settings_observation(_json_get(SETTINGS_URL)),
        "gateway": validate_gateway_observation(_json_get(GATEWAY_URL)),
        "release": _release_status(repository_root),
        "schema_fingerprint": schema,
        "command_queue": _command_queue_facts(settings),
    }
    authority["authority_sha256"] = sha256_bytes(canonical_json_bytes(authority))
    return authority


def _capture_live_restart_publication_seal(
    *,
    repository_root: Path,
    launchctl: str,
    domain: str,
    checks: dict[str, dict[str, object]],
    expected: dict[str, object],
    deadline: float,
) -> dict[str, object]:
    """Re-observe the complete live authority after provisional publication."""

    expected_processes = expected.get("processes")
    expected_generation = expected.get("connector_generation")
    expected_connector_log = expected.get("connector_log")
    expected_repository = expected.get("repository")
    expected_runtime = expected.get("runtime_authority")
    if (
        not isinstance(expected_processes, dict)
        or not isinstance(expected_generation, dict)
        or not isinstance(expected_connector_log, dict)
        or not isinstance(expected_repository, dict)
        or not isinstance(expected_runtime, dict)
    ):
        raise ReleaseOperationError("restart publication seal expectation is incomplete")

    connector_before_boundary = _process_facts(
        launchctl=launchctl,
        domain=domain,
        label=CONNECTOR_LABEL,
        repository_root=repository_root,
        preflight=checks["connector"],
    )
    if _connector_generation_authority(connector_before_boundary) != expected_generation:
        raise ReleaseOperationError("connector generation changed before publication seal boundary")
    connector_boundary = _connector_log_snapshot(
        repository_root / CONNECTOR_LOG,
        require_liveness=True,
    )
    for field in ("device", "inode"):
        if connector_boundary.get(field) != expected_connector_log.get(field):
            raise ReleaseOperationError("connector log identity changed before publication seal")
    prior_offset = expected_connector_log.get("offset")
    boundary_offset = connector_boundary.get("offset")
    if (
        type(prior_offset) is not int
        or type(boundary_offset) is not int
        or boundary_offset < prior_offset
    ):
        raise ReleaseOperationError("connector log offset changed before publication seal")
    connector_boundary["connector_generation"] = expected_generation
    connector_boundary["captured_monotonic_ns"] = time.monotonic_ns()
    fresh_connector_cycle = _wait_fresh_connector_cycle(
        repository_root / CONNECTOR_LOG,
        snapshot=connector_boundary,
        deadline=deadline,
        connector_generation=expected_generation,
        require_liveness=True,
    )

    _wait_tcp(8765, deadline=deadline)
    _wait_tcp(3001, deadline=deadline)
    settings_observation = validate_live_settings_observation(_wait_settings(deadline=deadline))
    gateway_observation = validate_gateway_observation(_json_get(GATEWAY_URL))
    processes = {
        "backend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=BACKEND_LABEL,
            repository_root=repository_root,
            preflight=checks["backend"],
        ),
        "frontend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=FRONTEND_LABEL,
            repository_root=repository_root,
            preflight=checks["frontend"],
        ),
        "connector": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=CONNECTOR_LABEL,
            repository_root=repository_root,
            preflight=checks["connector"],
        ),
    }
    for service in ("backend", "frontend", "connector"):
        before = expected_processes.get(service)
        after = processes[service]
        if (
            not isinstance(before, dict)
            or before.get("pid") != after.get("pid")
            or _stable_process_authority(before) != _stable_process_authority(after)
        ):
            raise ReleaseOperationError(f"{service} live authority changed during publication seal")
    if _connector_generation_authority(processes["connector"]) != expected_generation:
        raise ReleaseOperationError("connector generation changed during publication seal")

    release_observation = _release_status(repository_root)
    settings = Settings()
    schema = schema_fingerprint(get_database(settings))
    queue = _command_queue_facts(settings)
    repository = git_identity(repository_root, require_clean=True)
    runtime = _runtime_authority_snapshot(repository_root, checks)
    observed = {
        "processes": processes,
        "settings": settings_observation,
        "gateway": gateway_observation,
        "release": release_observation,
        "schema_fingerprint": schema,
        "command_queue": queue,
        "repository": asdict(repository),
        "runtime_authority": runtime,
    }
    for field in (
        "settings",
        "gateway",
        "release",
        "schema_fingerprint",
        "command_queue",
        "repository",
        "runtime_authority",
    ):
        if observed[field] != expected.get(field):
            raise ReleaseOperationError(
                f"restart live authority changed during publication seal: {field}"
            )

    seal: dict[str, object] = {
        "status": "sealed",
        "captured_at": utc_now(),
        "captured_monotonic_ns": time.monotonic_ns(),
        **observed,
        "connector_generation": expected_generation,
        "connector_boundary": connector_boundary,
        "fresh_connector_cycle": fresh_connector_cycle,
    }
    seal["authority_sha256"] = sha256_bytes(canonical_json_bytes(seal))
    return seal


def _capture_build_restoration_publication_seal(
    *,
    repository_root: Path,
    expected_build: dict[str, object],
    identity: GitIdentity,
) -> dict[str, object]:
    """Seal pre-kickstart rollback without inventing service observations."""

    active_build = frontend_build_tree_facts(repository_root / "src" / "frontend" / ".next")
    if active_build != expected_build:
        raise ReleaseOperationError("restored frontend build changed after provisional publication")
    current_identity = git_identity(repository_root, require_clean=True)
    if current_identity != identity:
        raise ReleaseOperationError(
            "repository identity changed after rollback provisional publication"
        )
    seal: dict[str, object] = {
        "status": "sealed",
        "scope": "pre_kickstart_build_and_repository",
        "captured_at": utc_now(),
        "captured_monotonic_ns": time.monotonic_ns(),
        "active_build": active_build,
        "repository": asdict(current_identity),
    }
    seal["authority_sha256"] = sha256_bytes(canonical_json_bytes(seal))
    return seal


def _complete_activated_restart(
    *,
    repository_root: Path,
    output_dir: Path,
    identity: GitIdentity,
    frontend_build_authority: dict[str, object],
    frontend_build_command: dict[str, object],
    restart_state: dict[str, object],
    pre_activation_authority: dict[str, object] | None,
    timeout_seconds: float = 30,
) -> dict[str, object]:
    receipt_path = output_dir / "restart-receipt.json"
    provisional_path = output_dir / "restart-receipt.provisional.json"
    launchctl = shutil.which("launchctl")
    if launchctl is None:
        raise ReleaseOperationError("launchctl is unavailable")
    activation = frontend_build_authority.get("atomic_activation")
    validated_pre_activation = _validate_pre_activation_restart_authority(
        pre_activation_authority,
        identity=identity,
        activation=activation,
    )
    if validated_pre_activation.get("launchctl") != launchctl:
        raise ReleaseOperationError("launchctl identity changed after activation")
    domain = validated_pre_activation.get("domain")
    if domain != f"gui/{os.getuid()}":
        raise ReleaseOperationError("launchctl domain changed after activation")
    assert isinstance(domain, str)
    restart_state["launchctl"] = launchctl
    restart_state["domain"] = domain
    restart_state["pre_activation_authority"] = validated_pre_activation
    checks = {
        "backend": _preflight_check(repository_root, "run_quant_backend.sh"),
        "frontend": _preflight_check(repository_root, "run_quant_frontend.sh"),
        "connector": _preflight_check(
            repository_root,
            "run_agent_v02_connector.sh",
        ),
    }
    if checks != validated_pre_activation.get("checks"):
        raise ReleaseOperationError("restart preflight changed after activation")
    restart_state["checks"] = checks
    runtime_authority_pre = validated_pre_activation.get("runtime_authority")
    if not isinstance(runtime_authority_pre, dict):
        raise ReleaseOperationError("pre-activation runtime authority is absent")
    if _runtime_authority_snapshot(repository_root, checks) != runtime_authority_pre:
        raise ReleaseOperationError("runtime authority changed after activation")
    connector_log_path = repository_root / CONNECTOR_LOG
    connector_log_pre_restart = validated_pre_activation.get("connector_log")
    processes = validated_pre_activation.get("processes")
    if not isinstance(connector_log_pre_restart, dict) or not isinstance(
        processes,
        dict,
    ):
        raise ReleaseOperationError("pre-activation process authority is absent")
    pre = {
        "backend": processes.get("backend"),
        "frontend": processes.get("frontend"),
        "connector": processes.get("connector"),
        "settings": validated_pre_activation.get("settings"),
        "gateway": validated_pre_activation.get("gateway"),
        "release": validated_pre_activation.get("release"),
        "schema_fingerprint": validated_pre_activation.get("schema_fingerprint"),
        "command_queue": validated_pre_activation.get("command_queue"),
        "connector_log_pre_restart": connector_log_pre_restart,
        "captured_before_frontend_activation": True,
    }
    if pre["schema_fingerprint"] in {"<db-disabled>", "<unavailable>"}:
        raise ReleaseOperationError("pre-restart schema fingerprint is unavailable")
    if any(
        not isinstance(pre.get(service), dict) for service in ("backend", "frontend", "connector")
    ):
        raise ReleaseOperationError("pre-restart process facts are incomplete")
    current_candidate = frontend_build_tree_facts(repository_root / "src" / "frontend" / ".next")
    if current_candidate != frontend_build_authority.get("next"):
        raise ReleaseOperationError("active candidate changed before restart transaction")
    restart_state["service_reconciliation_required"] = True
    restart_state["service_kickstarts_attempted"] = []
    for label in (BACKEND_LABEL, FRONTEND_LABEL):
        attempted = restart_state["service_kickstarts_attempted"]
        assert isinstance(attempted, list)
        attempted.append(label)
        completed = subprocess.run(
            [launchctl, "kickstart", "-k", f"{domain}/{label}"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise ReleaseOperationError(f"launchd kickstart failed: {label}")

    deadline = time.monotonic() + timeout_seconds
    _wait_tcp(8765, deadline=deadline)
    _wait_tcp(3001, deadline=deadline)
    post_settings_raw = _wait_settings(deadline=deadline)
    post_gateway_raw = _json_get(GATEWAY_URL)
    post_processes = {
        "backend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=BACKEND_LABEL,
            repository_root=repository_root,
            preflight=checks["backend"],
        ),
        "frontend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=FRONTEND_LABEL,
            repository_root=repository_root,
            preflight=checks["frontend"],
        ),
        "connector": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=CONNECTOR_LABEL,
            repository_root=repository_root,
            preflight=checks["connector"],
        ),
    }
    connector_follow_boundary = _capture_connector_follow_boundary(
        connector_log_path,
        pre_restart_snapshot=connector_log_pre_restart,
        process_facts={
            "pre": {
                "backend": pre["backend"],
                "frontend": pre["frontend"],
                "connector": pre["connector"],
            },
            "post": post_processes,
        },
        require_connector_authority=True,
    )
    connector_generation = connector_follow_boundary.get("connector_generation")
    if not isinstance(connector_generation, dict):
        raise ReleaseOperationError("connector generation is absent from follow boundary")
    fresh_connector_cycle = _wait_fresh_connector_cycle(
        connector_log_path,
        snapshot=connector_follow_boundary,
        deadline=deadline,
        connector_generation=connector_generation,
        require_liveness=True,
    )
    connector_after_cycle = _process_facts(
        launchctl=launchctl,
        domain=domain,
        label=CONNECTOR_LABEL,
        repository_root=repository_root,
        preflight=checks["connector"],
    )
    if _connector_generation_authority(connector_after_cycle) != connector_generation:
        raise ReleaseOperationError("connector generation changed after fresh cycle")
    post = {
        **post_processes,
        "settings": validate_live_settings_observation(post_settings_raw),
        "gateway": validate_gateway_observation(post_gateway_raw),
        "release": _release_status(repository_root),
        "schema_fingerprint": schema_fingerprint(get_database(Settings())),
        "command_queue": _command_queue_facts(Settings()),
        "connector_follow_boundary": connector_follow_boundary,
        "fresh_connector_cycle": fresh_connector_cycle,
        "connector_after_cycle": connector_after_cycle,
    }
    if post["schema_fingerprint"] != pre["schema_fingerprint"]:
        raise ReleaseOperationError("schema fingerprint changed across restart")
    for service in ("backend", "frontend"):
        if pre[service]["pid"] == post[service]["pid"]:  # type: ignore[index]
            raise ReleaseOperationError(f"{service} pid did not change")
    if pre["connector"]["pid"] != post["connector"]["pid"]:  # type: ignore[index]
        raise ReleaseOperationError("connector was unexpectedly restarted")
    if not isinstance(activation, dict):
        raise ReleaseOperationError("frontend activation authority is malformed")
    if pre["frontend"]["next_build"] != activation.get("active_before"):  # type: ignore[index]
        raise ReleaseOperationError("old frontend process is not bound to the pre-activation build")
    post_identity = git_identity(repository_root, require_clean=True)
    if post_identity != identity:
        raise ReleaseOperationError("repository identity changed across restart")
    validate_frontend_build_authority(frontend_build_authority, post_identity)
    if post["frontend"]["next_build"] != frontend_build_authority["next"]:  # type: ignore[index]
        raise ReleaseOperationError(
            "running frontend build differs from current-HEAD build authority"
        )
    if pre["settings"] != post["settings"]:
        raise ReleaseOperationError("safety settings changed across restart")
    runtime_authority_post = _runtime_authority_snapshot(repository_root, checks)
    if runtime_authority_post != runtime_authority_pre:
        raise ReleaseOperationError("environment, lock, dependency, or install authority changed")
    receipt: dict[str, object] = {
        "schema_version": "agent-v0.2.2-launchd-restart.v1",
        "status": "passed",
        "repository": asdict(identity),
        "post_restart_repository": asdict(post_identity),
        "frontend_build_authority": frontend_build_authority,
        "frontend_build_command": frontend_build_command,
        "runtime_authority": {
            "pre_restart": runtime_authority_pre,
            "post_restart": runtime_authority_post,
            "unchanged": True,
        },
        "provider_free_readiness_paths": [
            "/api/settings",
            "/api/hermes/gateway",
            "quant-system hermes release status",
        ],
        "forbidden_readiness_path_used": False,
        "preflight_checks": checks,
        "pre_restart": pre,
        "post_restart": post,
        "pre_activation_authority": validated_pre_activation,
        "processes_replaced": True,
        "connector_was_not_restarted": True,
        "connector_fresh_reconcile_only_cycle_observed": True,
        "connector_generation_unchanged": True,
        "command_queue_empty_before_and_after": True,
        "source_identity_unchanged": True,
        "safety_identity_unchanged": True,
        "release_authorized": False,
    }
    expected_live_authority: dict[str, object] = {
        "processes": post_processes,
        "settings": post["settings"],
        "gateway": post["gateway"],
        "release": post["release"],
        "schema_fingerprint": post["schema_fingerprint"],
        "command_queue": post["command_queue"],
        "repository": asdict(post_identity),
        "runtime_authority": runtime_authority_post,
        "connector_generation": connector_generation,
        "connector_log": connector_follow_boundary,
    }
    provisional: dict[str, object] = {
        "schema_version": "agent-v0.2.2-launchd-restart-provisional.v1",
        "status": "provisional",
        "intended_status": "passed",
        "published_at": utc_now(),
        "repository": asdict(identity),
        "expected_live_authority_sha256": sha256_bytes(
            canonical_json_bytes(expected_live_authority)
        ),
        "acceptance_rule": "restart-receipt.json requires a sealed post-publication re-observation",
    }
    write_immutable(provisional_path, canonical_json_bytes(provisional))
    provisional_bytes = canonical_json_bytes(provisional)
    publication_seal = _capture_live_restart_publication_seal(
        repository_root=repository_root,
        launchctl=launchctl,
        domain=domain,
        checks=checks,
        expected=expected_live_authority,
        deadline=time.monotonic() + timeout_seconds,
    )
    receipt["completed_at"] = utc_now()
    receipt["provisional_publication"] = {
        "path": str(provisional_path),
        "sha256": sha256_bytes(provisional_bytes),
        "status": "provisional",
    }
    receipt["publication_seal"] = publication_seal
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt


def _reconcile_services_after_rollback(
    *,
    repository_root: Path,
    restart_state: dict[str, object],
    restored_build: dict[str, object],
    timeout_seconds: float,
    identity: GitIdentity,
) -> dict[str, object]:
    if restart_state.get("service_reconciliation_required") is not True:
        return {
            "status": "not_required",
            "both_services_kickstart_attempted": False,
        }
    launchctl = restart_state.get("launchctl")
    domain = restart_state.get("domain")
    checks = restart_state.get("checks")
    pre_activation = restart_state.get("pre_activation_authority")
    if (
        not isinstance(launchctl, str)
        or not isinstance(domain, str)
        or not isinstance(checks, dict)
        or any(
            not isinstance(checks.get(service), dict)
            for service in ("backend", "frontend", "connector")
        )
        or not isinstance(pre_activation, dict)
    ):
        return {
            "status": "recovery_incomplete",
            "both_services_kickstart_attempted": False,
            "errors": ["recovery_authority_absent"],
        }
    pre_processes = pre_activation.get("processes")
    if not isinstance(pre_processes, dict):
        return {
            "status": "recovery_incomplete",
            "both_services_kickstart_attempted": False,
            "errors": ["pre_activation_processes_absent"],
        }

    commands: dict[str, object] = {}
    errors: list[str] = []
    labels = {
        "backend": BACKEND_LABEL,
        "frontend": FRONTEND_LABEL,
    }
    for service, label in labels.items():
        argv = [launchctl, "kickstart", "-k", f"{domain}/{label}"]
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
            )
        except Exception:
            commands[service] = {
                "argv": argv,
                "outcome": "execution_error",
            }
            errors.append(f"{service}_kickstart_execution_error")
            continue
        commands[service] = {
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout_bytes": len(completed.stdout),
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stderr_bytes": len(completed.stderr),
            "stderr_sha256": sha256_bytes(completed.stderr),
        }
        if completed.returncode != 0:
            errors.append(f"{service}_kickstart_failed")

    document: dict[str, object] = {
        "status": "recovery_incomplete",
        "both_services_kickstart_attempted": True,
        "commands": commands,
        "errors": errors,
        "provider_or_trading_route_used": False,
    }
    if errors:
        return document

    deadline = time.monotonic() + max(timeout_seconds, 30)
    for service, port in (("backend", 8765), ("frontend", 3001)):
        try:
            _wait_tcp(port, deadline=deadline)
        except ReleaseOperationError:
            errors.append(f"{service}_tcp_readiness_failed")

    settings_observation: dict[str, object] | None = None
    gateway_observation: dict[str, object] | None = None
    release_observation: dict[str, object] | None = None
    try:
        settings_observation = validate_live_settings_observation(_wait_settings(deadline=deadline))
    except ReleaseOperationError:
        errors.append("settings_readiness_failed")
    try:
        gateway_observation = validate_gateway_observation(_json_get(GATEWAY_URL))
    except ReleaseOperationError:
        errors.append("gateway_readiness_failed")
    try:
        release_observation = _release_status(repository_root)
    except ReleaseOperationError:
        errors.append("release_readiness_failed")

    recovered_processes: dict[str, object] = {}
    for service, label in (
        ("backend", BACKEND_LABEL),
        ("frontend", FRONTEND_LABEL),
        ("connector", CONNECTOR_LABEL),
    ):
        try:
            recovered_processes[service] = _process_facts(
                launchctl=launchctl,
                domain=domain,
                label=label,
                repository_root=repository_root,
                preflight=checks[service],  # type: ignore[arg-type]
            )
        except ReleaseOperationError:
            errors.append(f"{service}_process_authority_failed")

    document["processes"] = recovered_processes
    document["readiness"] = {
        "settings": settings_observation,
        "gateway": gateway_observation,
        "release": release_observation,
    }
    if errors:
        return document

    for service in ("backend", "frontend"):
        before = pre_processes.get(service)
        after = recovered_processes.get(service)
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or before.get("pid") == after.get("pid")
        ):
            errors.append(f"{service}_pid_not_reconciled")
            continue
        try:
            if _stable_process_authority(after) != _stable_process_authority(before):
                errors.append(f"{service}_process_authority_changed")
        except ReleaseOperationError:
            errors.append(f"{service}_stable_process_authority_failed")
    frontend_after = recovered_processes.get("frontend")
    frontend_before = pre_processes.get("frontend")
    if (
        not isinstance(frontend_after, dict)
        or not isinstance(frontend_before, dict)
        or frontend_after.get("next_build") != restored_build
        or frontend_before.get("next_build") != restored_build
    ):
        errors.append("frontend_build_not_restored")

    connector_before = pre_processes.get("connector")
    connector_after = recovered_processes.get("connector")
    try:
        before_generation = _connector_generation_authority(connector_before)
        after_generation = _connector_generation_authority(connector_after)
        if after_generation != before_generation:
            errors.append("connector_generation_changed")
    except ReleaseOperationError:
        errors.append("connector_generation_authority_failed")
        before_generation = None

    for field, observed in (
        ("settings", settings_observation),
        ("gateway", gateway_observation),
        ("release", release_observation),
    ):
        if observed != pre_activation.get(field):
            errors.append(f"{field}_readiness_changed")

    try:
        settings = Settings()
        schema = schema_fingerprint(get_database(settings))
        queue = _command_queue_facts(settings)
        document["schema_fingerprint"] = schema
        document["command_queue"] = queue
        if schema != pre_activation.get("schema_fingerprint"):
            errors.append("schema_fingerprint_changed")
        if queue != pre_activation.get("command_queue"):
            errors.append("command_queue_changed")
    except ReleaseOperationError:
        errors.append("database_readiness_failed")

    try:
        current_identity = git_identity(repository_root, require_clean=True)
        if current_identity != identity:
            errors.append("repository_identity_changed")
        runtime = _runtime_authority_snapshot(
            repository_root,
            checks,  # type: ignore[arg-type]
        )
        document["runtime_authority"] = runtime
        if runtime != pre_activation.get("runtime_authority"):
            errors.append("runtime_authority_changed")
    except ReleaseOperationError:
        errors.append("repository_or_runtime_authority_failed")

    if not errors and isinstance(before_generation, dict):
        try:
            connector_log = pre_activation.get("connector_log")
            if not isinstance(connector_log, dict):
                raise ReleaseOperationError("pre-activation connector log authority is absent")
            boundary = _capture_connector_follow_boundary(
                repository_root / CONNECTOR_LOG,
                pre_restart_snapshot=connector_log,
                process_facts={
                    "pre": {
                        "backend": pre_processes["backend"],
                        "frontend": pre_processes["frontend"],
                        "connector": pre_processes["connector"],
                    },
                    "post": {
                        "backend": recovered_processes["backend"],
                        "frontend": recovered_processes["frontend"],
                        "connector": recovered_processes["connector"],
                    },
                },
                require_connector_authority=True,
            )
            heartbeat = _wait_fresh_connector_cycle(
                repository_root / CONNECTOR_LOG,
                snapshot=boundary,
                deadline=deadline,
                connector_generation=before_generation,
                require_liveness=True,
            )
            connector_final = _process_facts(
                launchctl=launchctl,
                domain=domain,
                label=CONNECTOR_LABEL,
                repository_root=repository_root,
                preflight=checks["connector"],  # type: ignore[arg-type]
            )
            if _connector_generation_authority(connector_final) != before_generation:
                raise ReleaseOperationError("connector generation changed after recovery cycle")
            document["connector_follow_boundary"] = boundary
            document["connector_heartbeat"] = heartbeat
            document["connector_after_heartbeat"] = connector_final
        except ReleaseOperationError:
            errors.append("connector_heartbeat_or_generation_failed")

    document["errors"] = errors
    if errors:
        return document
    document["status"] = "restored"
    document["exact_prior_process_authority_restored"] = True
    document["exact_prior_readiness_authority_restored"] = True
    document["connector_generation_unchanged"] = True
    document["connector_fresh_reconcile_only_cycle_observed"] = True
    return document


def restart_stack(
    *,
    repository_root: Path,
    output_dir: Path,
    timeout_seconds: float = 30,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    output_dir = ensure_private_directory(output_dir)
    receipt_path = output_dir / "restart-receipt.json"
    provisional_receipt_path = output_dir / "restart-receipt.provisional.json"
    failure_path = output_dir / "restart-failure-recovery.json"
    provisional_failure_path = output_dir / "restart-failure-recovery.provisional.json"
    if any(
        path.exists()
        for path in (
            receipt_path,
            provisional_receipt_path,
            failure_path,
            provisional_failure_path,
        )
    ):
        raise ReleaseOperationError("restart output already exists")
    identity = git_identity(repository_root, require_clean=True)
    pre_activation_authority = _capture_pre_activation_restart_authority(
        repository_root,
        identity=identity,
    )
    frontend_build_authority, frontend_build_command = _build_current_frontend(
        repository_root,
        identity,
    )
    activation = frontend_build_authority.get("atomic_activation")
    if not isinstance(activation, dict):
        raise ReleaseOperationError("frontend activation authority is absent")
    rollback = activation.get("rollback")
    if not isinstance(rollback, dict):
        raise ReleaseOperationError("frontend rollback authority is absent")
    restart_state: dict[str, object] = {
        "service_reconciliation_required": False,
    }
    try:
        return _complete_activated_restart(
            repository_root=repository_root,
            output_dir=output_dir,
            identity=identity,
            frontend_build_authority=frontend_build_authority,
            frontend_build_command=frontend_build_command,
            restart_state=restart_state,
            pre_activation_authority=pre_activation_authority,
            timeout_seconds=timeout_seconds,
        )
    except BaseException as operation_error:
        recovery_error: BaseException | None = None
        rollback_error: BaseException | None = None
        reconciliation_error: BaseException | None = None
        rollback_recovery: dict[str, object] | None = None
        process_recovery: dict[str, object] | None = None
        restored_build: dict[str, object] | None = None
        try:
            rollback_recovery = _restore_frontend_rollback(
                active_next=repository_root / "src" / "frontend" / ".next",
                rollback=rollback,
                activation=activation,
            )
            restored_build_value = rollback_recovery["active_restored"]
            assert isinstance(restored_build_value, dict)
            restored_build = restored_build_value
        except BaseException as exc:
            rollback_error = exc

        reconciliation_target = restored_build
        if reconciliation_target is None:
            active_before = activation.get("active_before")
            if isinstance(active_before, dict):
                reconciliation_target = active_before
        try:
            if not isinstance(reconciliation_target, dict):
                raise ReleaseOperationError("pre-activation frontend recovery target is absent")
            process_recovery = _reconcile_services_after_rollback(
                repository_root=repository_root,
                restart_state=restart_state,
                restored_build=reconciliation_target,
                timeout_seconds=timeout_seconds,
                identity=identity,
            )
            if process_recovery.get("status") == "recovery_incomplete":
                raise ReleaseOperationError(
                    "backend/frontend restart reconciliation was incomplete"
                )
        except BaseException as exc:
            reconciliation_error = exc
        recovery_error = rollback_error or reconciliation_error
        operation_message = (
            str(operation_error)
            if isinstance(operation_error, ReleaseOperationError)
            else "unexpected_internal_error"
        )
        recovery_document: dict[str, object] = {
            "schema_version": "agent-v0.2.2-launchd-restart-failure-recovery.v1",
            "status": "recovery_incomplete",
            "repository": asdict(identity),
            "operation_error": {
                "class": operation_error.__class__.__name__,
                "error": operation_message,
            },
            "frontend_build_authority": frontend_build_authority,
            "rollback_recovery": rollback_recovery,
            "frontend_process_recovery": process_recovery,
            "service_reconciliation": process_recovery,
            "manual_recovery_artifacts": {
                "retained_rollback": rollback,
                "expected_active_before": activation.get("active_before"),
                "expected_active_after": activation.get("active_after"),
                "rollback_recovery": rollback_recovery,
            },
            "provider_or_trading_route_used_for_recovery": False,
            "success_receipt_exists": receipt_path.exists(),
        }
        if recovery_error is None:
            recovery_expectation = {
                "repository": asdict(identity),
                "frontend_build_authority": frontend_build_authority,
                "rollback_recovery": rollback_recovery,
                "service_reconciliation": process_recovery,
            }
            provisional_recovery: dict[str, object] = {
                "schema_version": ("agent-v0.2.2-launchd-restart-failure-recovery-provisional.v1"),
                "status": "provisional",
                "intended_status": "restored",
                "published_at": utc_now(),
                "repository": asdict(identity),
                "expected_recovery_sha256": sha256_bytes(
                    canonical_json_bytes(recovery_expectation)
                ),
                "acceptance_rule": (
                    "restart-failure-recovery.json restored requires a sealed "
                    "post-publication re-observation"
                ),
            }
            try:
                provisional_bytes = canonical_json_bytes(provisional_recovery)
                write_immutable(provisional_failure_path, provisional_bytes)
                if process_recovery is not None and process_recovery.get("status") == "restored":
                    checks = restart_state.get("checks")
                    launchctl = restart_state.get("launchctl")
                    domain = restart_state.get("domain")
                    pre_activation = restart_state.get("pre_activation_authority")
                    readiness = process_recovery.get("readiness")
                    recovered_processes = process_recovery.get("processes")
                    connector_log = process_recovery.get("connector_follow_boundary")
                    if (
                        not isinstance(checks, dict)
                        or not isinstance(launchctl, str)
                        or not isinstance(domain, str)
                        or not isinstance(pre_activation, dict)
                        or not isinstance(readiness, dict)
                        or not isinstance(recovered_processes, dict)
                        or not isinstance(connector_log, dict)
                    ):
                        raise ReleaseOperationError(
                            "restored publication seal authority is incomplete"
                        )
                    pre_processes = pre_activation.get("processes")
                    connector_before = (
                        pre_processes.get("connector") if isinstance(pre_processes, dict) else None
                    )
                    expected_generation = _connector_generation_authority(connector_before)
                    live_expected: dict[str, object] = {
                        "processes": recovered_processes,
                        "settings": readiness.get("settings"),
                        "gateway": readiness.get("gateway"),
                        "release": readiness.get("release"),
                        "schema_fingerprint": process_recovery.get("schema_fingerprint"),
                        "command_queue": process_recovery.get("command_queue"),
                        "repository": asdict(identity),
                        "runtime_authority": process_recovery.get("runtime_authority"),
                        "connector_generation": expected_generation,
                        "connector_log": connector_log,
                    }
                    publication_seal = _capture_live_restart_publication_seal(
                        repository_root=repository_root,
                        launchctl=launchctl,
                        domain=domain,
                        checks=checks,  # type: ignore[arg-type]
                        expected=live_expected,
                        deadline=time.monotonic() + max(timeout_seconds, 30),
                    )
                elif (
                    process_recovery is not None
                    and process_recovery.get("status") == "not_required"
                    and isinstance(restored_build, dict)
                ):
                    publication_seal = _capture_build_restoration_publication_seal(
                        repository_root=repository_root,
                        expected_build=restored_build,
                        identity=identity,
                    )
                else:
                    raise ReleaseOperationError("restored publication seal authority is absent")
                recovery_document["provisional_publication"] = {
                    "path": str(provisional_failure_path),
                    "sha256": sha256_bytes(provisional_bytes),
                    "status": "provisional",
                }
                recovery_document["publication_seal"] = publication_seal
            except BaseException as exc:
                recovery_error = exc
        recovery_document["status"] = (
            "restored" if recovery_error is None else "recovery_incomplete"
        )
        recovery_document["completed_at"] = utc_now()
        if recovery_error is not None:
            recovery_document["recovery_error"] = {
                "class": recovery_error.__class__.__name__,
                "error": (
                    str(recovery_error)
                    if isinstance(recovery_error, ReleaseOperationError)
                    else "unexpected_internal_error"
                ),
            }
        try:
            write_immutable(
                failure_path,
                canonical_json_bytes(recovery_document),
            )
        except BaseException as evidence_error:
            raise ReleaseOperationError(
                "restart failed and recovery evidence could not be persisted"
            ) from evidence_error
        if recovery_error is not None:
            raise ReleaseOperationError(
                "restart failed and frontend rollback recovery was incomplete"
            ) from operation_error
        raise ReleaseOperationError(
            f"{operation_message}; frontend build restored"
        ) from operation_error
