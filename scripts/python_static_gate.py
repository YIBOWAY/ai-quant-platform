#!/usr/bin/env python3
"""Fail-closed repository-authoritative Python static verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT = "quant-system-python-static/v1"
GATE2_CONTRACT = "quant-system-backend-non-postgres/v1"
EXPECTED_BRANCH = "codex/agent-v0-2-release"
PUBLICATION_REMOTE = "github"
PUBLICATION_REMOTE_URL = "https://github.com/YIBOWAY/ai-quant-platform.git"
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"
RUFF_AUTHORITY_LINE = (
    'run_step "Ruff" "$PYTHON_BIN" -m ruff check src/quant_system tests'
)
RUFF_ARGV_TAIL = ("-m", "ruff", "check", "src/quant_system", "tests")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_NETWORK_DENIAL_SOURCE = r"""
import errno
import socket

try:
    probe = socket.socket()
    probe.settimeout(0.2)
    probe.connect(("127.0.0.1", 9))
except OSError as exc:
    raise SystemExit(0 if exc.errno in {errno.EACCES, errno.EPERM} else 2)
raise SystemExit(3)
"""
_TOOL_PROBE_SOURCE = r"""
import hashlib
import importlib.metadata
import json
import pathlib
import sys

package = __import__("quant_system")
quant_distribution = importlib.metadata.distribution("quant-system")
ruff_distribution = importlib.metadata.distribution("ruff")
direct_url_text = quant_distribution.read_text("direct_url.json")
direct_url = json.loads(direct_url_text) if direct_url_text else None
ruff_executable = pathlib.Path(sys.executable).parent / "ruff"

def file_identity(path):
    resolved = path.resolve()
    content = resolved.read_bytes()
    return {
        "path": str(path.absolute()),
        "realpath": str(resolved),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }

print(
    json.dumps(
        {
            "direct_url": direct_url,
            "prefix": str(pathlib.Path(sys.prefix).resolve()),
            "python": file_identity(pathlib.Path(sys.executable)),
            "quant_system_file": str(pathlib.Path(package.__file__).resolve()),
            "quant_system_version": quant_distribution.version,
            "ruff": {
                "distribution_path": str(
                    pathlib.Path(ruff_distribution.locate_file("")).resolve()
                ),
                "executable": file_identity(ruff_executable),
                "version": ruff_distribution.version,
            },
            "version": sys.version,
            "version_info": list(sys.version_info[:3]),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
)
"""


class GateError(RuntimeError):
    """The Gate 4 repository command contract was not satisfied."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        before = path.stat()
    except OSError as exc:
        raise GateError(f"file_identity_failed:{path.name}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise GateError(f"not_regular_file:{path.name}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(128 * 1024), b""):
                digest.update(block)
        after = path.stat()
    except OSError as exc:
        raise GateError(f"file_identity_failed:{path.name}") from exc
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise GateError(f"file_changed_while_hashing:{path.name}")
    return digest.hexdigest()


def file_identity(path: Path, *, relative_to: Path | None = None) -> dict[str, object]:
    try:
        info = path.stat()
    except OSError as exc:
        raise GateError(f"file_identity_failed:{path.name}") from exc
    label = str(path.relative_to(relative_to)) if relative_to is not None else str(path)
    return {
        "path": label,
        "sha256": sha256_file(path),
        "size_bytes": info.st_size,
    }


def canonical_json(document: object) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _strict_json(content: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GateError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise GateError("nonfinite_json_value")

    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except GateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GateError("invalid_json") from exc


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _require_canonical_absolute(path: Path, error: str) -> Path:
    if (
        not path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or _has_symlink_component(path)
    ):
        raise GateError(error)
    resolved = path.resolve()
    if resolved != path:
        raise GateError(error)
    return resolved


def load_canonical_json(path: Path) -> dict[str, Any]:
    resolved = _require_canonical_absolute(path, "gate2_receipt_path_invalid")
    try:
        info = resolved.lstat()
        parent_info = resolved.parent.lstat()
        content = resolved.read_bytes()
    except OSError as exc:
        raise GateError("gate2_receipt_unreadable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or stat.S_IMODE(parent_info.st_mode) != 0o700
    ):
        raise GateError("gate2_receipt_permissions_invalid")
    document = _strict_json(content)
    if not isinstance(document, dict):
        raise GateError("gate2_receipt_invalid")
    if canonical_json(document) != content:
        raise GateError("gate2_receipt_not_canonical")
    return document


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GateError(f"artifact_write_failed:{path.name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _artifact(path: Path) -> dict[str, object]:
    identity = file_identity(path)
    identity["path"] = path.name
    return identity


def _prepare_output(path: Path, *, root: Path) -> Path:
    resolved = _require_canonical_absolute(path, "output_dir_not_canonical")
    if resolved == root or root in resolved.parents:
        raise GateError("output_dir_inside_checkout")
    try:
        parent_info = resolved.parent.lstat()
    except FileNotFoundError as exc:
        raise GateError("output_dir_parent_missing") from exc
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or stat.S_IMODE(parent_info.st_mode) & 0o022
    ):
        raise GateError("output_dir_parent_unsafe")
    try:
        if resolved.exists():
            info = resolved.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or any(resolved.iterdir())
            ):
                raise GateError("output_dir_not_empty_private")
        else:
            resolved.mkdir(mode=0o700)
            resolved.chmod(0o700)
    except OSError as exc:
        raise GateError("output_dir_create_failed") from exc
    return resolved


def _git_environment() -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _git_argv(root: Path, *arguments: str) -> list[str]:
    return [
        "/usr/bin/git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-C",
        str(root),
        *arguments,
    ]


def _git_bytes(root: Path, *arguments: str, allow_empty: bool = False) -> bytes:
    completed = subprocess.run(
        _git_argv(root, *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if completed.returncode != 0 or (not allow_empty and not completed.stdout.strip()):
        raise GateError("git_identity_failed")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("utf-8", "strict").strip()


def _git_quiet_clean(root: Path, *arguments: str) -> bool:
    completed = subprocess.run(
        _git_argv(root, *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if completed.returncode not in {0, 1} or completed.stdout or completed.stderr:
        raise GateError("git_diff_audit_failed")
    return completed.returncode == 0


def _tagged_ls_files(content: bytes) -> tuple[bytes, ...]:
    records = tuple(record for record in content.split(b"\0") if record)
    if not records or any(len(record) < 3 or record[1:2] != b" " for record in records):
        raise GateError("tracked_index_flags_invalid")
    return records


def _tracked_tree_audit(root: Path) -> dict[str, object]:
    verbose = _tagged_ls_files(_git_bytes(root, "ls-files", "-v", "-z"))
    tagged = _tagged_ls_files(_git_bytes(root, "ls-files", "-t", "-z"))
    if len(verbose) != len(tagged):
        raise GateError("tracked_index_flags_invalid")
    assume_unchanged = tuple(
        record for record in verbose if record[:1].decode("ascii").islower()
    )
    skip_worktree = tuple(record for record in (*verbose, *tagged) if record[:1] == b"S")
    if assume_unchanged or skip_worktree:
        raise GateError("tracked_index_flags_hidden")
    if _git_bytes(root, "ls-files", "-u", "-z", allow_empty=True):
        raise GateError("tracked_index_conflicts")
    index_matches_head = _git_quiet_clean(
        root,
        "diff-index",
        "--quiet",
        "--cached",
        "--ignore-submodules=none",
        "HEAD",
        "--",
    )
    worktree_matches_index = _git_quiet_clean(
        root,
        "diff-files",
        "--quiet",
        "--ignore-submodules=none",
        "--",
    )
    return {
        "assume_unchanged_count": 0,
        "conflict_entry_count": 0,
        "index_matches_head": index_matches_head,
        "ls_files_flags_sha256": sha256(
            b"verbose\0" + b"\0".join(verbose) + b"\0tagged\0" + b"\0".join(tagged)
        ),
        "skip_worktree_count": 0,
        "tracked_path_count": len(verbose),
        "worktree_matches_index": worktree_matches_index,
    }


def git_identity(root: Path) -> dict[str, object]:
    toplevel = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve()
    if toplevel != root:
        raise GateError("git_toplevel_mismatch")
    tracked_tree = _tracked_tree_audit(root)
    status = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        allow_empty=True,
    )
    tracked_clean = bool(
        tracked_tree["index_matches_head"] and tracked_tree["worktree_matches_index"]
    )
    return {
        "branch": _git_text(root, "symbolic-ref", "--short", "HEAD"),
        "clean": status == b"" and tracked_clean,
        "clean_status_sha256": sha256(status),
        "commit": _git_text(root, "rev-parse", "--verify", "HEAD"),
        "git_toplevel": str(toplevel),
        "publication_remote": PUBLICATION_REMOTE,
        "publication_remote_url": _git_text(
            root,
            "remote",
            "get-url",
            PUBLICATION_REMOTE,
        ),
        "root": str(root),
        "tracked_tree": tracked_tree,
        "tree": _git_text(root, "rev-parse", "--verify", "HEAD^{tree}"),
    }


def require_expected_commit(root: Path, expected_commit: str | None) -> dict[str, object]:
    if expected_commit is None or _COMMIT.fullmatch(expected_commit) is None:
        raise GateError("expected_commit_invalid")
    identity = git_identity(root)
    if identity["commit"] != expected_commit:
        raise GateError("expected_commit_mismatch")
    if identity["branch"] != EXPECTED_BRANCH:
        raise GateError("expected_branch_mismatch")
    if identity["publication_remote_url"] != PUBLICATION_REMOTE_URL:
        raise GateError("publication_remote_mismatch")
    if not identity["clean"]:
        raise GateError("checkout_not_clean")
    return identity


def gate2_runtime_path(*, root: Path, evidence: Path, commit: str) -> Path:
    run_digest = sha256(f"{commit}\0{evidence}".encode())[:16]
    return root / ".tmp" / f"backend-non-postgres-{commit[:12]}-{run_digest}"


def _safe_runtime_directory(path: Path, *, root: Path, error: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise GateError(error) from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or (path != root and root not in path.parents)
    ):
        raise GateError(error)


def _input_identity(root: Path) -> dict[str, dict[str, object]]:
    relatives = (
        "pyproject.toml",
        "uv.lock",
        "scripts/verify.sh",
        "scripts/backend_non_postgres_gate.py",
        "scripts/verify_backend_non_postgres.sh",
        "scripts/python_static_gate.py",
        "scripts/verify_python_static.sh",
    )
    return {
        relative: file_identity(root / relative, relative_to=root)
        for relative in relatives
    }


def validate_gate2_receipt(
    *,
    path: Path,
    root: Path,
    expected_commit: str,
    repository_identity: dict[str, object],
) -> dict[str, Any]:
    if path.name != "backend-non-postgres-receipt.json":
        raise GateError("gate2_receipt_name_invalid")
    document = load_canonical_json(path)
    if document.get("contract") != GATE2_CONTRACT:
        raise GateError("gate2_receipt_contract_invalid")
    if document.get("status") != "passed":
        raise GateError("gate2_receipt_not_passed")
    before = document.get("repository_before")
    after = document.get("repository_after")
    if before != after or before != repository_identity:
        raise GateError("gate2_repository_identity_mismatch")
    if not isinstance(before, dict) or before.get("commit") != expected_commit:
        raise GateError("gate2_commit_mismatch")
    evidence = path.parent
    evidence_record = document.get("evidence_directory")
    if (
        not isinstance(evidence_record, dict)
        or evidence_record.get("path") != str(evidence)
    ):
        raise GateError("gate2_evidence_path_mismatch")
    runtime = gate2_runtime_path(root=root, evidence=evidence, commit=expected_commit)
    fresh = document.get("fresh_environment")
    transient = document.get("transient_runtime")
    expected_venv = runtime / "venv"
    if (
        not isinstance(fresh, dict)
        or fresh.get("inside_checkout") is not True
        or fresh.get("preexisting") is not False
        or fresh.get("path") != str(expected_venv)
        or not isinstance(transient, dict)
        or transient.get("root") != str(runtime)
        or transient.get("cleanup_owner") != "outer_collector"
        or transient.get("evidence_artifact") is not False
        or transient.get("runner_recursive_cleanup") is not False
        or not isinstance(transient.get("paths"), dict)
        or transient["paths"].get("venv") != str(expected_venv)
    ):
        raise GateError("gate2_runtime_path_mismatch")
    _safe_runtime_directory(
        root / ".tmp",
        root=root,
        error="gate2_runtime_parent_unsafe",
    )
    _safe_runtime_directory(runtime, root=root / ".tmp", error="gate2_runtime_unsafe")
    _safe_runtime_directory(expected_venv, root=runtime, error="gate2_venv_unsafe")
    for name in ("home", "tmp", "pycache"):
        _safe_runtime_directory(
            runtime / name,
            root=runtime,
            error=f"gate2_runtime_directory_unsafe:{name}",
        )
    inputs_before = document.get("inputs_before")
    inputs_after = document.get("inputs_after")
    if not isinstance(inputs_before, dict) or inputs_before != inputs_after:
        raise GateError("gate2_input_identity_mismatch")
    current_inputs = _input_identity(root)
    for relative in (
        "pyproject.toml",
        "uv.lock",
        "scripts/backend_non_postgres_gate.py",
        "scripts/verify_backend_non_postgres.sh",
    ):
        if inputs_before.get(relative) != current_inputs[relative]:
            raise GateError(f"gate2_input_identity_mismatch:{relative}")
    python_record = document.get("python")
    if (
        not isinstance(python_record, dict)
        or not isinstance(python_record.get("identity"), dict)
        or python_record.get("lock_sha256") != current_inputs["uv.lock"]["sha256"]
    ):
        raise GateError("gate2_python_identity_missing")
    python_identity = python_record["identity"]
    python = expected_venv / "bin/python"
    if (
        python_identity.get("prefix") != str(expected_venv)
        or python_identity.get("sys_executable") != str(expected_venv / "bin/python")
        or python_identity.get("version_info", [])[:2] != [3, 11]
        or python_identity.get("quant_system_file", "").startswith(str(root / "src"))
        or not str(python_identity.get("quant_system_file", "")).startswith(
            str(expected_venv)
        )
        or not isinstance(python_identity.get("direct_url"), dict)
        or python_identity["direct_url"].get("url") != root.as_uri()
        or not isinstance(python_identity["direct_url"].get("dir_info"), dict)
        or python_identity["direct_url"]["dir_info"].get("editable") is not False
    ):
        raise GateError("gate2_python_identity_invalid")
    try:
        python_info = python.stat()
        python_realpath = python.resolve(strict=True)
    except OSError as exc:
        raise GateError("gate2_python_executable_invalid") from exc
    if (
        not stat.S_ISREG(python_info.st_mode)
        or python_info.st_uid != os.getuid()
        or not os.access(python, os.X_OK)
        or str(python_realpath) != python_identity.get("sys_executable_realpath")
    ):
        raise GateError("gate2_python_executable_invalid")
    return {
        "inputs": {
            "pyproject.toml": inputs_before["pyproject.toml"],
            "uv.lock": inputs_before["uv.lock"],
        },
        "python_identity": python_identity,
        "python_executable": {
            "path": str(python),
            "realpath": str(python_realpath),
            "sha256": sha256_file(python_realpath),
            "size_bytes": python_realpath.stat().st_size,
        },
        "receipt": {
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        },
        "runtime": {
            "root": str(runtime),
            "venv": str(expected_venv),
        },
    }


def load_repository_authority(root: Path) -> dict[str, Any]:
    source = root / "scripts" / "verify.sh"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        ruff_configuration = pyproject["tool"]["ruff"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError) as exc:
        raise GateError("repository_static_authority_invalid") from exc
    matches = [
        index
        for index, line in enumerate(lines, start=1)
        if line == RUFF_AUTHORITY_LINE
    ]
    if matches != [28] or not isinstance(ruff_configuration, dict):
        raise GateError("repository_static_authority_invalid")
    lint = ruff_configuration.get("lint")
    if (
        ruff_configuration.get("target-version") != "py311"
        or not isinstance(lint, dict)
        or lint.get("select") != ["E", "F", "I", "UP", "B", "SIM"]
    ):
        raise GateError("repository_static_authority_invalid")
    return {
        "argv_tail": list(RUFF_ARGV_TAIL),
        "ruff_configuration": ruff_configuration,
        "source": {
            **file_identity(source, relative_to=root),
            "line": RUFF_AUTHORITY_LINE,
            "line_number": matches[0],
        },
    }


def static_environment(*, runtime: Path, python: Path) -> dict[str, str]:
    return {
        "HOME": str(runtime / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(runtime / "pycache"),
        "RUFF_CACHE_DIR": str(runtime / "ruff-cache"),
        "TMPDIR": str(runtime / "tmp"),
    }


def _require_sandbox_exec() -> Path:
    if (
        not SANDBOX_EXEC.is_file()
        or SANDBOX_EXEC.is_symlink()
        or not os.access(SANDBOX_EXEC, os.X_OK)
    ):
        raise GateError("network_sandbox_not_executable")
    return SANDBOX_EXEC


def _run_logged(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    output: Path,
    name: str,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
    started_at = utc_now()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    completed_at = utc_now()
    stdout_path = output / f"{name}.stdout.log"
    stderr_path = output / f"{name}.stderr.log"
    _write_exclusive(stdout_path, completed.stdout)
    _write_exclusive(stderr_path, completed.stderr)
    return completed, {
        "argv": list(argv),
        "completed_at": completed_at,
        "exit_code": completed.returncode,
        "started_at": started_at,
        "stderr": _artifact(stderr_path),
        "stdout": _artifact(stdout_path),
        "stdout_stderr_sha256": sha256(completed.stdout + b"\0" + completed.stderr),
    }


def _run_json_probe(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    output: Path,
    name: str,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object], object]:
    started_at = utc_now()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    completed_at = utc_now()
    stderr_path = output / f"{name}.stderr.log"
    _write_exclusive(stderr_path, completed.stderr)
    document = _strict_json(completed.stdout) if completed.returncode == 0 else None
    return completed, {
        "argv": list(argv),
        "completed_at": completed_at,
        "exit_code": completed.returncode,
        "started_at": started_at,
        "stderr": _artifact(stderr_path),
        "stdout": {
            "embedded_in_receipt": True,
            "sha256": sha256(completed.stdout),
            "size_bytes": len(completed.stdout),
        },
        "stdout_stderr_sha256": sha256(completed.stdout + b"\0" + completed.stderr),
    }, document


def _validate_tool_probe(
    document: object,
    *,
    root: Path,
    venv: Path,
    gate2_python_identity: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise GateError("tool_identity_probe_invalid")
    required = {
        "direct_url",
        "prefix",
        "python",
        "quant_system_file",
        "quant_system_version",
        "ruff",
        "version",
        "version_info",
    }
    if set(document) != required or document["version_info"][:2] != [3, 11]:
        raise GateError("tool_identity_probe_invalid")
    python = document["python"]
    ruff = document["ruff"]
    direct_url = document["direct_url"]
    if (
        not isinstance(python, dict)
        or python.get("path") != str(venv / "bin/python")
        or not isinstance(ruff, dict)
        or not isinstance(ruff.get("executable"), dict)
        or ruff["executable"].get("path") != str(venv / "bin/ruff")
        or document["prefix"] != str(venv)
        or not str(document["quant_system_file"]).startswith(str(venv))
        or str(document["quant_system_file"]).startswith(str(root / "src"))
        or not isinstance(direct_url, dict)
        or direct_url.get("url") != root.as_uri()
        or not isinstance(direct_url.get("dir_info"), dict)
        or direct_url["dir_info"].get("editable") is not False
    ):
        raise GateError("tool_identity_probe_invalid")
    for field in (
        "direct_url",
        "prefix",
        "quant_system_file",
        "version_info",
    ):
        if document[field] != gate2_python_identity[field]:
            raise GateError(f"gate2_python_identity_drift:{field}")
    if python.get("realpath") != gate2_python_identity.get("sys_executable_realpath"):
        raise GateError("gate2_python_identity_drift:sys_executable_realpath")
    return document


def _require_helper_path(root: Path) -> dict[str, str]:
    actual = Path(__file__).resolve()
    expected = root / "scripts" / "python_static_gate.py"
    if actual != expected:
        raise GateError("helper_path_mismatch")
    return {"actual_path": str(actual), "expected_path": str(expected)}


def _require_public_entrypoint(root: Path, argument: str) -> dict[str, str]:
    expected = root / "scripts" / "verify_python_static.sh"
    resolved = Path(argument).resolve()
    if resolved != expected or not expected.is_file() or expected.is_symlink():
        raise GateError("public_entrypoint_mismatch")
    return {
        "argument": argument,
        "expected_path": str(expected),
        "resolved_path": str(resolved),
    }


def describe_contract(root: Path) -> dict[str, object]:
    return {
        "branch": EXPECTED_BRANCH,
        "contract": CONTRACT,
        "entrypoint": "scripts/verify_python_static.sh",
        "gate2_contract": GATE2_CONTRACT,
        "gate2_fresh_environment_required": True,
        "publication_remote": {
            "name": PUBLICATION_REMOTE,
            "url": PUBLICATION_REMOTE_URL,
        },
        "repository_authority": load_repository_authority(root),
        "sandbox": {
            "database": "not-configured",
            "network": "deny",
            "provider": "not-configured",
        },
    }


def run_gate(
    *,
    root: Path,
    gate2_receipt_argument: Path,
    output_argument: Path,
    expected_commit: str | None,
    public_entrypoint: str,
    public_argv: tuple[str, ...],
) -> dict[str, object]:
    entrypoint_binding = _require_public_entrypoint(root, public_entrypoint)
    repository_before = require_expected_commit(root, expected_commit)
    assert expected_commit is not None
    output = _prepare_output(output_argument, root=root)
    inputs_before = _input_identity(root)
    authority = load_repository_authority(root)
    gate2 = validate_gate2_receipt(
        path=gate2_receipt_argument,
        root=root,
        expected_commit=expected_commit,
        repository_identity=repository_before,
    )
    runtime = Path(gate2["runtime"]["root"])
    venv = Path(gate2["runtime"]["venv"])
    python = venv / "bin/python"
    ruff_cache = runtime / "ruff-cache"
    try:
        ruff_cache.mkdir(mode=0o700)
    except OSError as exc:
        raise GateError("ruff_cache_not_fresh") from exc
    _safe_runtime_directory(ruff_cache, root=runtime, error="ruff_cache_unsafe")
    environment = static_environment(runtime=runtime, python=python)
    sandbox_exec = _require_sandbox_exec()
    started_at = utc_now()
    output_info = output.lstat()
    output_parent_info = output.parent.lstat()
    receipt: dict[str, Any] = {
        "command": {
            "argv": [public_entrypoint, *public_argv],
            "cwd": str(root),
            "entrypoint_binding": entrypoint_binding,
            "environment_strategy": "allowlist",
            "may_touch_database": False,
            "may_touch_network": False,
            "may_touch_provider": False,
            "may_touch_runtime": False,
            "may_touch_trading": False,
        },
        "contract": CONTRACT,
        "environment": environment,
        "evidence_directory": {
            "mode": f"{stat.S_IMODE(output_info.st_mode):03o}",
            "owner_uid": output_info.st_uid,
            "parent_mode": f"{stat.S_IMODE(output_parent_info.st_mode):03o}",
            "parent_owner_uid": output_parent_info.st_uid,
            "path": str(output),
        },
        "expected_commit": expected_commit,
        "gate2_binding": gate2,
        "inputs_before": inputs_before,
        "repository_authority": authority,
        "repository_before": repository_before,
        "started_at": started_at,
        "status": "running",
    }
    error: GateError | None = None
    try:
        network, network_record = _run_logged(
            argv=(
                str(sandbox_exec),
                "-p",
                SANDBOX_PROFILE,
                str(python),
                "-I",
                "-B",
                "-c",
                _NETWORK_DENIAL_SOURCE,
            ),
            cwd=root,
            env=environment,
            output=output,
            name="network-denial-probe",
        )
        receipt["network_sandbox"] = network_record
        if network.returncode != 0:
            raise GateError("network_sandbox_probe_failed")

        probe, probe_record, probe_document = _run_json_probe(
            argv=(
                str(sandbox_exec),
                "-p",
                SANDBOX_PROFILE,
                str(python),
                "-I",
                "-B",
                "-c",
                _TOOL_PROBE_SOURCE,
            ),
            cwd=root,
            env=environment,
            output=output,
            name="python-ruff-identity",
        )
        receipt["tool_identity"] = probe_record
        if probe.returncode != 0:
            raise GateError("tool_identity_probe_failed")
        probe_identity = _validate_tool_probe(
            probe_document,
            root=root,
            venv=venv,
            gate2_python_identity=gate2["python_identity"],
        )
        receipt["tool_identity"]["identity"] = probe_identity

        ruff_version, ruff_version_record = _run_logged(
            argv=(
                str(sandbox_exec),
                "-p",
                SANDBOX_PROFILE,
                str(python),
                "-I",
                "-B",
                "-m",
                "ruff",
                "--version",
            ),
            cwd=root,
            env=environment,
            output=output,
            name="ruff-version",
        )
        receipt["ruff_version"] = ruff_version_record
        expected_version = f"ruff {probe_identity['ruff']['version']}\n".encode()
        if ruff_version.returncode != 0 or ruff_version.stdout != expected_version:
            raise GateError("ruff_version_identity_mismatch")

        ruff, ruff_record = _run_logged(
            argv=(
                str(sandbox_exec),
                "-p",
                SANDBOX_PROFILE,
                str(python),
                "-I",
                "-B",
                *RUFF_ARGV_TAIL,
            ),
            cwd=root,
            env=environment,
            output=output,
            name="ruff-check",
        )
        receipt["ruff"] = ruff_record
        if ruff.returncode != 0:
            raise GateError(f"ruff_exit_nonzero:{ruff.returncode}")

        repository_after = git_identity(root)
        inputs_after = _input_identity(root)
        receipt["repository_after"] = repository_after
        receipt["inputs_after"] = inputs_after
        if repository_after != repository_before:
            raise GateError("repository_identity_changed")
        if inputs_after != inputs_before:
            raise GateError("repository_inputs_changed")
        if sha256_file(gate2_receipt_argument) != gate2["receipt"]["sha256"]:
            raise GateError("gate2_receipt_changed")
        receipt["status"] = "passed"
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, GateError)
            else GateError(f"unexpected_runner_error:{type(exc).__name__}")
        )
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        try:
            receipt["repository_after"] = git_identity(root)
            receipt["inputs_after"] = _input_identity(root)
        except GateError as identity_error:
            receipt["post_failure_identity_error"] = str(identity_error)
    finally:
        receipt["completed_at"] = utc_now()
        receipt_path = output / "python-static-receipt.json"
        _write_exclusive(receipt_path, canonical_json(receipt))
    if error is not None:
        raise error
    return {
        "contract": CONTRACT,
        "receipt": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "status": "passed",
    }


def _parse_public_args(argv: tuple[str, ...]) -> argparse.Namespace:
    seen: set[str] = set()
    describe = False
    values: dict[str, str] = {}
    index = 0
    forbidden = (
        "--bootstrap-python",
        "--public-argv",
        "--public-entrypoint",
        "--repository-root",
    )
    while index < len(argv):
        token = argv[index]
        if token in forbidden or token.startswith(tuple(f"{name}=" for name in forbidden)):
            raise GateError("public_argument_forbidden")
        if token == "--describe":
            name = token
            value: str | None = None
        elif token in {"--gate2-receipt", "--output-dir", "--expected-commit"}:
            name = token
            index += 1
            if index >= len(argv) or argv[index].startswith("--"):
                raise GateError("public_arguments_invalid")
            value = argv[index]
        elif token.startswith(
            ("--gate2-receipt=", "--output-dir=", "--expected-commit=")
        ):
            name, _, value = token.partition("=")
        else:
            raise GateError("public_arguments_invalid")
        if name in seen:
            raise GateError("public_argument_duplicate")
        seen.add(name)
        if name == "--describe":
            describe = True
        elif not value:
            raise GateError("public_arguments_invalid")
        else:
            values[name] = value
        index += 1
    required = {"--gate2-receipt", "--output-dir", "--expected-commit"}
    if describe:
        if seen != {"--describe"}:
            raise GateError("public_arguments_invalid")
    elif seen != required:
        raise GateError("public_arguments_invalid")
    return argparse.Namespace(
        describe=describe,
        expected_commit=values.get("--expected-commit"),
        gate2_receipt=(
            Path(values["--gate2-receipt"]) if "--gate2-receipt" in values else None
        ),
        output_dir=Path(values["--output-dir"]) if "--output-dir" in values else None,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--bootstrap-python", type=Path, required=True)
    parser.add_argument("--public-entrypoint", required=True)
    parser.add_argument("--public-argv", nargs=argparse.REMAINDER, required=True)
    internal = parser.parse_args()
    public = _parse_public_args(tuple(internal.public_argv))
    internal.describe = public.describe
    internal.expected_commit = public.expected_commit
    internal.gate2_receipt = public.gate2_receipt
    internal.output_dir = public.output_dir
    internal.public_argv = tuple(internal.public_argv)
    return internal


def main() -> int:
    args = _parse_args()
    root = args.repository_root.resolve()
    _require_helper_path(root)
    _require_public_entrypoint(root, args.public_entrypoint)
    if sys.version_info[:2] != (3, 11):
        raise GateError("bootstrap_python_not_3_11")
    if Path(sys.executable).resolve() != args.bootstrap_python.resolve():
        raise GateError("bootstrap_python_mismatch")
    if args.describe:
        result = describe_contract(root)
    else:
        result = run_gate(
            root=root,
            gate2_receipt_argument=args.gate2_receipt,
            output_argument=args.output_dir,
            expected_commit=args.expected_commit,
            public_entrypoint=args.public_entrypoint,
            public_argv=args.public_argv,
        )
    print(
        json.dumps(
            result,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"python_static_error={exc}", file=sys.stderr, flush=True)
        raise SystemExit(78) from exc
