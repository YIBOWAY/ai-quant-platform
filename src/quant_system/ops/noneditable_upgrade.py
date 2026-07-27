"""Published-baseline to final non-editable wheel upgrade rehearsal."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from quant_system.ops.common import (
    GitIdentity,
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    read_private_regular,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_immutable,
)

PUBLISHED_BASELINE = "e19087e1580a21ccc9160bc664167972e322021c"
RELEASE_BRANCH = "codex/agent-v0-2-release"
NETWORK_SANDBOX = Path("/usr/bin/sandbox-exec")
NETWORK_SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"
GIT_BINARY = Path("/usr/bin/git")
CANONICAL_GITHUB_REMOTE = "https://github.com/YIBOWAY/ai-quant-platform.git"
EXPECTED_CONSOLE_ENTRY_POINT = "quant_system.cli:app"
EXPECTED_CONSOLE_SCRIPT_BODY = """# -*- coding: utf-8 -*-
import sys
from quant_system.cli import app
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(app())
"""
GIT_SAFE_CONFIG = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "credential.helper=",
)
BOOTSTRAP_AUTHORITY_SCHEMA = "agent-v0.2.2-commit-bound-bootstrap.v2"
BOOTSTRAP_AUTHORITY_FIELDS = frozenset(
    {
        "archive_sha256",
        "commit",
        "file_count",
        "noneditable_upgrade_sha256",
        "release_ops_sha256",
        "repository_root",
        "schema_version",
        "source_manifest_sha256",
        "source_root",
        "tree",
    }
)


def _guarded_argv(argv: list[str]) -> list[str]:
    """Run a subprocess beneath a fail-closed macOS network deny profile."""

    return [
        str(NETWORK_SANDBOX),
        "-p",
        NETWORK_SANDBOX_PROFILE,
        *argv,
    ]


def _uv_sync_argv(uv_path: Path, *, inexact: bool) -> list[str]:
    """Sync the explicitly active copy-based venv without asking uv to replace it.

    Supplying ``--python <venv>/bin/python`` to ``uv sync`` treats that
    interpreter as the Python used to create the project environment.  uv may
    then replace the pre-created ``--copies`` environment with its default
    symlink-based environment.  ``VIRTUAL_ENV`` and ``--active`` already bind
    the exact target, so the interpreter selector must stay absent here.
    """

    command = [
        str(uv_path),
        "sync",
        "--frozen",
        "--offline",
    ]
    if inexact:
        command.append("--inexact")
    command.extend(
        [
            "--extra",
            "api",
            "--no-dev",
            "--no-editable",
            "--no-install-project",
            "--active",
            "--no-python-downloads",
        ]
    )
    return command


def _git_argv(repository_root: Path, *arguments: str) -> list[str]:
    """Return the only admissible, pinned and network-denied Git command."""

    if not GIT_BINARY.is_file() or GIT_BINARY.is_symlink() or not os.access(GIT_BINARY, os.X_OK):
        raise ReleaseOperationError("pinned Git executable is unavailable")
    return _guarded_argv(
        [
            str(GIT_BINARY),
            "--no-replace-objects",
            *GIT_SAFE_CONFIG,
            "-C",
            str(repository_root.resolve()),
            *arguments,
        ]
    )


def _run_git(
    repository_root: Path,
    *arguments: str,
    env: dict[str, str],
    stdout: Any = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git through the single sandboxed runner used by the rehearsal."""

    if any(name.startswith("GIT_") for name in env):
        raise ReleaseOperationError("Git environment overrides are forbidden")
    git_environment = dict(env)
    git_environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    return subprocess.run(
        _git_argv(repository_root, *arguments),
        env=git_environment,
        check=False,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


def _forbidden_source_roots(
    repository_root: Path,
    baseline_root: Path,
    final_root: Path,
) -> tuple[Path, ...]:
    """Return source trees that an installed-wheel import must never use.

    The upgrade environment intentionally lives below ``baseline_root``.  The
    whole archive roots therefore cannot be forbidden: doing so rejects the
    legitimate ``baseline_root/.venv/.../site-packages`` installation.  Only
    the checkout/archive source trees are forbidden.
    """

    return tuple((root / "src").resolve() for root in (repository_root, baseline_root, final_root))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _bootstrap_authority(
    *,
    repository_root: Path,
    output_dir: Path,
    authority_path: Path,
    authority_sha256: str,
) -> dict[str, object]:
    """Verify the stdlib bootstrap identity before trusting its archived source."""

    if re.fullmatch(r"[0-9a-f]{64}", authority_sha256) is None:
        raise ReleaseOperationError("bootstrap authority digest is malformed")
    expected_path = output_dir / "bootstrap-source-authority.json"
    candidate_path = Path(os.path.abspath(os.fspath(authority_path)))
    if candidate_path != expected_path:
        raise ReleaseOperationError("bootstrap authority path is not output-bound")
    payload = read_private_regular(candidate_path)
    if sha256_bytes(payload) != authority_sha256:
        raise ReleaseOperationError("bootstrap authority digest changed")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseOperationError("bootstrap authority is not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != BOOTSTRAP_AUTHORITY_FIELDS:
        raise ReleaseOperationError("bootstrap authority fields are not closed")
    if canonical_json_bytes(document) != payload:
        raise ReleaseOperationError("bootstrap authority is not canonical")
    if document["schema_version"] != BOOTSTRAP_AUTHORITY_SCHEMA:
        raise ReleaseOperationError("bootstrap authority schema is unsupported")
    for field in (
        "archive_sha256",
        "noneditable_upgrade_sha256",
        "release_ops_sha256",
        "source_manifest_sha256",
    ):
        value = document[field]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ReleaseOperationError(f"bootstrap authority {field} is malformed")
    for field in ("commit", "tree"):
        value = document[field]
        if (
            not isinstance(value, str)
            or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None
        ):
            raise ReleaseOperationError(f"bootstrap authority {field} is malformed")
    if not isinstance(document["file_count"], int) or document["file_count"] <= 0:
        raise ReleaseOperationError("bootstrap authority file count is malformed")
    if document["repository_root"] != str(repository_root):
        raise ReleaseOperationError("bootstrap authority repository is not exact-bound")

    source_root = (output_dir / "bootstrap-source" / "src").resolve(strict=True)
    if document["source_root"] != str(source_root):
        raise ReleaseOperationError("bootstrap authority source root is not exact-bound")
    loaded_upgrade = Path(__file__).resolve(strict=True)
    expected_upgrade = (source_root / "quant_system" / "ops" / "noneditable_upgrade.py").resolve(
        strict=True
    )
    expected_release = (source_root / "quant_system" / "ops" / "release_ops.py").resolve(
        strict=True
    )
    if loaded_upgrade != expected_upgrade:
        raise ReleaseOperationError("noneditable verifier is not bootstrap-bound")
    if sha256_file(expected_upgrade) != document["noneditable_upgrade_sha256"]:
        raise ReleaseOperationError("bootstrap noneditable verifier bytes changed")
    if sha256_file(expected_release) != document["release_ops_sha256"]:
        raise ReleaseOperationError("bootstrap release dispatcher bytes changed")

    archive_payload = read_private_regular(output_dir / "bootstrap-source.tar")
    if sha256_bytes(archive_payload) != document["archive_sha256"]:
        raise ReleaseOperationError("bootstrap source archive bytes changed")
    return document


def _safe_command_log_payload(
    *,
    argv: list[str],
    exit_code: int,
    stdout: bytes,
    stderr: bytes,
) -> bytes:
    """Render command evidence without persisting untrusted output bytes."""

    return canonical_json_bytes(
        {
            "argv": argv,
            "exit_code": exit_code,
            "stdout_sha256": sha256_bytes(stdout),
            "stdout_bytes": len(stdout),
            "stderr_sha256": sha256_bytes(stderr),
            "stderr_bytes": len(stderr),
            "raw_output_persisted": False,
        }
    )


def _run(
    argv: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    write_immutable(
        log_path,
        _safe_command_log_payload(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        ),
    )
    if completed.returncode != 0:
        raise ReleaseOperationError(f"upgrade command failed: {log_path.name}")
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout),
        "stdout_bytes": len(completed.stdout),
        "stderr_sha256": sha256_bytes(completed.stderr),
        "stderr_bytes": len(completed.stderr),
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "log_path": str(log_path),
    }


def _isolated_process_environment(
    output_dir: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    """Build the only environment inherited by package and smoke commands."""

    output_dir = ensure_private_directory(output_dir)
    runtime = ensure_private_directory(output_dir / "execution-environment")
    paths = {
        "HOME": ensure_private_directory(runtime / "home"),
        "TMPDIR": ensure_private_directory(runtime / "tmp"),
        "TMP": ensure_private_directory(runtime / "tmp"),
        "TEMP": ensure_private_directory(runtime / "tmp"),
        "XDG_CACHE_HOME": ensure_private_directory(runtime / "xdg-cache"),
        "PYTHONPYCACHEPREFIX": ensure_private_directory(runtime / "pycache"),
        "UV_CACHE_DIR": ensure_private_directory(runtime / "uv-cache"),
    }
    if not NETWORK_SANDBOX.is_file() or not os.access(NETWORK_SANDBOX, os.X_OK):
        raise ReleaseOperationError("network-deny sandbox is unavailable")
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "COLUMNS": "120",
        **{name: str(path) for name, path in paths.items()},
        "UV_OFFLINE": "1",
        "UV_NO_CONFIG": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
        "QS_DATABASE_AUTO_MIGRATE": "false",
    }
    return environment, {
        "network": "denied",
        "sandbox": str(NETWORK_SANDBOX),
        "sandbox_profile_sha256": sha256_bytes(NETWORK_SANDBOX_PROFILE.encode("utf-8")),
        "environment_variable_names": sorted(environment),
        "private_paths": {name: str(path) for name, path in paths.items()},
    }


def _archive_commit(
    *,
    repository_root: Path,
    commit: str,
    destination: Path,
    archive_path: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    with archive_path.open("xb") as output:
        archive = _run_git(
            repository_root,
            "archive",
            "--format=tar",
            commit,
            stdout=output,
            env=env or {},
        )
    archive_path.chmod(0o600)
    if archive.returncode != 0:
        raise ReleaseOperationError(f"git archive failed for {commit}")
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, mode="r:") as bundle:
        root = destination.resolve()
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ReleaseOperationError("git archive contains an unsafe path")
            if member.issym() or member.islnk():
                raise ReleaseOperationError("git archive contains a link")
        bundle.extractall(destination, filter="data")
    return {
        "commit": commit,
        "archive_path": str(archive_path),
        "archive_sha256": sha256_file(archive_path),
        "archive_bytes": archive_path.stat().st_size,
    }


def _probe_script() -> str:
    """Return an isolated interpreter probe that emits only credential-safe facts."""

    return "\n".join(
        (
            "import hashlib",
            "import importlib.metadata as metadata",
            "import json",
            "import pathlib",
            "import socket",
            "import sys",
            "import sysconfig",
            "import urllib.parse",
            "network_attempts = []",
            "def deny_network(*args, **kwargs):",
            "    network_attempts.append('blocked')",
            "    raise RuntimeError('network access denied by upgrade probe')",
            "socket.socket.connect = deny_network",
            "socket.socket.connect_ex = deny_network",
            "socket.create_connection = deny_network",
            "def symlink_components(path):",
            "    path = pathlib.Path(path).absolute()",
            "    current = pathlib.Path(path.anchor)",
            "    found = []",
            "    for part in path.parts[1:]:",
            "        current = current / part",
            "        if current.is_symlink():",
            "            found.append(str(current))",
            "    return found",
            "def valid_sha256(value):",
            "    return (",
            "        isinstance(value, str)",
            "        and len(value) == 64",
            "        and all(character in '0123456789abcdef' for character in value)",
            "    )",
            "site_roots = sorted({",
            "    str(pathlib.Path(value).resolve())",
            "    for value in (sysconfig.get_path('purelib'), sysconfig.get_path('platlib'))",
            "    if value",
            "})",
            "distribution = metadata.distribution('quant-system')",
            "console_entry_points = sorted(",
            "    (",
            "        {",
            "            'group': entry.group,",
            "            'name': entry.name,",
            "            'value': entry.value,",
            "        }",
            "        for entry in distribution.entry_points",
            "        if entry.group == 'console_scripts'",
            "    ),",
            "    key=lambda row: (row['group'], row['name'], row['value']),",
            ")",
            "import quant_system",
            "module_raw = pathlib.Path(quant_system.__file__).absolute()",
            "root = module_raw.resolve()",
            "module_site_roots = [",
            "    value",
            "    for value in site_roots",
            "    if pathlib.Path(value) == root or pathlib.Path(value) in root.parents",
            "]",
            "direct = distribution.read_text('direct_url.json')",
            "direct_document = json.loads(direct) if direct else {}",
            "direct_facts = None",
            "if direct_document:",
            "    url = direct_document.get('url')",
            "    parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None",
            "    archive_info = direct_document.get('archive_info')",
            "    archive_sha256 = None",
            "    if isinstance(archive_info, dict):",
            "        hashes = archive_info.get('hashes')",
            "        if isinstance(hashes, dict) and valid_sha256(hashes.get('sha256')):",
            "            archive_sha256 = hashes['sha256']",
            "        legacy_hash = archive_info.get('hash')",
            "        if (",
            "            archive_sha256 is None",
            "            and isinstance(legacy_hash, str)",
            "            and legacy_hash.startswith('sha256=')",
            "            and valid_sha256(legacy_hash[7:])",
            "        ):",
            "            archive_sha256 = legacy_hash[7:]",
            "    directory_info = direct_document.get('dir_info')",
            "    direct_facts = {",
            "        'present': True,",
            "        'scheme': parsed.scheme if parsed is not None else None,",
            "        'credential_present': bool(",
            "            parsed is not None and (parsed.username or parsed.password)",
            "        ),",
            "        'netloc_present': bool(parsed is not None and parsed.netloc),",
            "        'query_present': bool(parsed is not None and parsed.query),",
            "        'fragment_present': bool(parsed is not None and parsed.fragment),",
            "        'url_sha256': (",
            "            hashlib.sha256(url.encode('utf-8')).hexdigest()",
            "            if isinstance(url, str)",
            "            else None",
            "        ),",
            "        'archive_sha256': archive_sha256,",
            "        'directory_install': isinstance(directory_info, dict),",
            "        'editable': (",
            "            directory_info.get('editable')",
            "            if isinstance(directory_info, dict)",
            "            else False",
            "        ),",
            "    }",
            "pth = []",
            "for site_value in site_roots:",
            "    site = pathlib.Path(site_value)",
            "    for path in sorted(site.glob('*.pth')):",
            "        payload = path.read_bytes()",
            "        classes = {'blank': 0, 'comment': 0, 'executable': 0, 'path': 0}",
            "        for raw_line in payload.decode('utf-8', 'replace').splitlines():",
            "            line = raw_line.strip()",
            "            if not line:",
            "                classes['blank'] += 1",
            "            elif line.startswith('#'):",
            "                classes['comment'] += 1",
            "            elif line.startswith('import ') or line.startswith('import\\t'):",
            "                classes['executable'] += 1",
            "            else:",
            "                classes['path'] += 1",
            "        pth.append({",
            "            'path': str(path.resolve()),",
            "            'sha256': hashlib.sha256(payload).hexdigest(),",
            "            'bytes': len(payload),",
            "            'line_classes': classes,",
            "            'symlink_components': symlink_components(path),",
            "        })",
            "installed = hashlib.sha256()",
            "installed_files = []",
            "installed_symlinks = []",
            "for entry in sorted(distribution.files or (), key=str):",
            "    target = distribution.locate_file(entry)",
            "    installed_symlinks.extend(symlink_components(target))",
            "    if target.is_file():",
            "        installed_files.append(str(entry))",
            "        installed.update(str(entry).encode('utf-8'))",
            "        installed.update(b'\\0')",
            "        installed.update(target.read_bytes())",
            "        installed.update(b'\\0')",
            "package_root = module_raw.parent",
            "package = hashlib.sha256()",
            "package_files = []",
            "package_symlinks = []",
            "for target in sorted(package_root.rglob('*'), key=lambda item: str(item)):",
            "    package_symlinks.extend(symlink_components(target))",
            "    if target.is_file() and not target.is_symlink():",
            "        relative = target.relative_to(package_root).as_posix()",
            "        package_files.append(relative)",
            "        package.update(relative.encode('utf-8'))",
            "        package.update(b'\\0')",
            "        package.update(target.read_bytes())",
            "        package.update(b'\\0')",
            "inventory = hashlib.sha256()",
            "inventory_rows = sorted(",
            "    (",
            "        item.metadata['Name'].lower().replace('_', '-'),",
            "        item.version,",
            "    )",
            "    for item in metadata.distributions()",
            "    if item.metadata['Name']",
            ")",
            "for name, version in inventory_rows:",
            "    inventory.update(name.encode('utf-8'))",
            "    inventory.update(b'==')",
            "    inventory.update(version.encode('utf-8'))",
            "    inventory.update(b'\\0')",
            "print(json.dumps({",
            "    'distribution': distribution.metadata['Name'],",
            "    'version': distribution.version,",
            "    'console_entry_points': console_entry_points,",
            "    'module': str(root),",
            "    'module_raw': str(module_raw),",
            "    'module_symlink_components': symlink_components(module_raw),",
            "    'site_packages': (",
            "        module_site_roots[0] if len(module_site_roots) == 1 else None",
            "    ),",
            "    'site_roots': site_roots,",
            "    'sys_executable': str(pathlib.Path(sys.executable).resolve()),",
            "    'sys_executable_raw': str(pathlib.Path(sys.executable).absolute()),",
            "    'sys_executable_symlink_components': symlink_components(sys.executable),",
            "    'sys_prefix': str(pathlib.Path(sys.prefix).resolve()),",
            "    'sys_base_prefix': str(pathlib.Path(sys.base_prefix).resolve()),",
            "    'sys_path': [",
            "        str(pathlib.Path(value).resolve()) for value in sys.path if value",
            "    ],",
            "    'direct_url': direct_facts,",
            "    'pth': pth,",
            "    'installed_file_count': len(installed_files),",
            "    'installed_tree_sha256': installed.hexdigest(),",
            "    'installed_symlink_components': sorted(set(installed_symlinks)),",
            "    'package_file_count': len(package_files),",
            "    'package_tree_sha256': package.hexdigest(),",
            "    'package_symlink_components': sorted(set(package_symlinks)),",
            "    'environment_inventory_count': len(inventory_rows),",
            "    'environment_inventory_sha256': inventory.hexdigest(),",
            "    'network_attempt_count': len(network_attempts),",
            "}, sort_keys=True))",
        )
    )


def _require_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ReleaseOperationError(f"non-editable import probe lacks {key}")
    return value


def _require_sha256(document: dict[str, Any], key: str) -> str:
    value = _require_string(document, key)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ReleaseOperationError(f"non-editable import probe has malformed {key}")
    return value


def _require_positive_integer(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReleaseOperationError(f"non-editable import probe has invalid {key}")
    return value


def _require_empty_string_list(document: dict[str, Any], key: str) -> None:
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReleaseOperationError(f"non-editable import probe has malformed {key}")
    if value:
        raise ReleaseOperationError(f"non-editable import probe found symlink use: {key}")


def _validate_import_probe(
    document: dict[str, Any],
    *,
    forbidden_roots: tuple[Path, ...],
    expected_python: Path | None = None,
    expected_wheel: Path | None = None,
    expected_version: str | None = None,
) -> dict[str, object]:
    """Validate observed import metadata without trusting probe assertions."""

    if document.get("distribution") != "quant-system":
        raise ReleaseOperationError("installed distribution identity mismatch")
    module = Path(_require_string(document, "module")).resolve()
    site_packages = Path(_require_string(document, "site_packages")).resolve()
    executable = Path(_require_string(document, "sys_executable")).resolve()
    if not _is_within(module, site_packages):
        raise ReleaseOperationError("installed module is outside site-packages")
    for forbidden in forbidden_roots:
        if _is_within(module, forbidden):
            raise ReleaseOperationError("installed module resolves to a source root")
    environment_root = executable.parent.parent
    if (
        executable.parent.name != "bin"
        or environment_root.name != ".venv"
        or site_packages.name != "site-packages"
        or not _is_within(site_packages, environment_root)
    ):
        raise ReleaseOperationError(
            "installed module is not bound to the target environment site-packages"
        )
    strict = any(value is not None for value in (expected_python, expected_wheel, expected_version))
    if expected_python is not None and executable != expected_python.resolve():
        raise ReleaseOperationError("probe executable is not the requested environment Python")
    if expected_version is not None and document.get("version") != expected_version:
        raise ReleaseOperationError("installed distribution version mismatch")

    direct = document.get("direct_url")
    if direct is not None:
        if not isinstance(direct, dict):
            raise ReleaseOperationError("direct_url metadata is malformed")
        if "present" in direct:
            if direct.get("present") is not True:
                raise ReleaseOperationError("direct_url presence fact is malformed")
            if direct.get("credential_present") is not False:
                raise ReleaseOperationError("credential-bearing direct_url is forbidden")
            if any(
                direct.get(field) is not False
                for field in ("netloc_present", "query_present", "fragment_present")
            ):
                raise ReleaseOperationError("non-local direct_url components are forbidden")
            if direct.get("directory_install") is not False:
                raise ReleaseOperationError("directory direct_url installation is forbidden")
            if direct.get("editable") is not False:
                raise ReleaseOperationError("editable direct_url installation is forbidden")
            if direct.get("scheme") != "file":
                raise ReleaseOperationError("wheel direct_url is not a local file")
            _require_sha256(direct, "url_sha256")
            archive_sha256 = direct.get("archive_sha256")
            if archive_sha256 is not None:
                _require_sha256(direct, "archive_sha256")
            if expected_wheel is not None:
                expected_url_sha256 = sha256_bytes(
                    expected_wheel.resolve().as_uri().encode("utf-8")
                )
                if direct.get("url_sha256") != expected_url_sha256:
                    raise ReleaseOperationError(
                        "installed direct_url does not bind the requested wheel"
                    )
                if archive_sha256 is not None and archive_sha256 != sha256_file(expected_wheel):
                    raise ReleaseOperationError(
                        "installed direct_url archive digest does not match the wheel"
                    )
        else:
            directory_info = direct.get("dir_info")
            if directory_info is not None and not isinstance(directory_info, dict):
                raise ReleaseOperationError("direct_url dir_info is malformed")
            if isinstance(directory_info, dict) and directory_info.get("editable") is not False:
                raise ReleaseOperationError("editable direct_url installation is forbidden")
            if strict:
                raise ReleaseOperationError("direct_url probe exposed unsafe raw metadata")
    elif expected_wheel is not None:
        raise ReleaseOperationError("installed wheel lacks direct_url binding")

    rows = document.get("pth")
    if not isinstance(rows, list):
        raise ReleaseOperationError("PTH inventory is malformed")
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseOperationError("PTH inventory row is malformed")
        if "line_classes" in row:
            classes = row.get("line_classes")
            if not isinstance(classes, dict):
                raise ReleaseOperationError("PTH line classification is malformed")
            for name in ("blank", "comment", "executable", "path"):
                value = classes.get(name)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ReleaseOperationError("PTH line classification is malformed")
            if classes["executable"]:
                raise ReleaseOperationError("PTH import execution is forbidden")
            if classes["path"]:
                raise ReleaseOperationError("PTH path injection is forbidden")
            _require_sha256(row, "sha256")
            byte_count = row.get("bytes")
            if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
                raise ReleaseOperationError("PTH byte count is malformed")
            _require_empty_string_list(row, "symlink_components")
        else:
            text = row.get("text")
            if not isinstance(text, str):
                raise ReleaseOperationError("PTH inventory text is malformed")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("import ", "import\t")):
                    raise ReleaseOperationError("PTH import execution is forbidden")
                raise ReleaseOperationError("PTH path injection is forbidden")
            if strict:
                raise ReleaseOperationError("PTH probe exposed unsafe raw text")

    _require_positive_integer(document, "installed_file_count")
    _require_sha256(document, "installed_tree_sha256")
    if strict:
        module_raw = Path(_require_string(document, "module_raw")).absolute()
        if module_raw.resolve() != module:
            raise ReleaseOperationError("module raw and resolved paths disagree")
        _require_empty_string_list(document, "module_symlink_components")
        _require_empty_string_list(document, "sys_executable_symlink_components")
        _require_empty_string_list(document, "installed_symlink_components")
        _require_empty_string_list(document, "package_symlink_components")
        _require_positive_integer(document, "package_file_count")
        _require_sha256(document, "package_tree_sha256")
        if expected_wheel is not None:
            wheel_payload = _wheel_payload_facts(expected_wheel)
            if (
                document["package_file_count"] != wheel_payload["package_file_count"]
                or document["package_tree_sha256"] != wheel_payload["package_tree_sha256"]
            ):
                raise ReleaseOperationError(
                    "installed package tree does not match the requested wheel"
                )
            expected_entry_points = [
                {
                    "group": "console_scripts",
                    "name": "quant-system",
                    "value": EXPECTED_CONSOLE_ENTRY_POINT,
                }
            ]
            if wheel_payload.get("console_entry_points") != expected_entry_points:
                raise ReleaseOperationError("wheel console entry point is not canonical")
            if document.get("console_entry_points") != expected_entry_points:
                raise ReleaseOperationError(
                    "installed console entry point does not match the wheel"
                )
        _require_positive_integer(document, "environment_inventory_count")
        _require_sha256(document, "environment_inventory_sha256")
        if document.get("network_attempt_count") != 0:
            raise ReleaseOperationError("installed import attempted network access")

        prefix = Path(_require_string(document, "sys_prefix")).resolve()
        base_prefix = Path(_require_string(document, "sys_base_prefix")).resolve()
        if prefix != environment_root:
            raise ReleaseOperationError("probe prefix is not the requested environment")
        if prefix == base_prefix:
            raise ReleaseOperationError("probe did not run in an isolated virtual environment")
        roots = document.get("site_roots")
        if (
            not isinstance(roots, list)
            or not roots
            or any(not isinstance(item, str) for item in roots)
            or site_packages not in {Path(item).resolve() for item in roots}
        ):
            raise ReleaseOperationError("probe site-packages roots are malformed")
        resolved_roots = {Path(item).resolve() for item in roots}
        pth_paths: set[Path] = set()
        for row in rows:
            pth_path = Path(_require_string(row, "path")).resolve()
            if (
                pth_path.suffix != ".pth"
                or pth_path.parent not in resolved_roots
                or pth_path in pth_paths
            ):
                raise ReleaseOperationError("PTH inventory path is outside site-packages")
            pth_paths.add(pth_path)
        search_path = document.get("sys_path")
        if (
            not isinstance(search_path, list)
            or not search_path
            or any(not isinstance(item, str) for item in search_path)
        ):
            raise ReleaseOperationError("probe sys.path is malformed")
        for entry in search_path:
            resolved = Path(entry).resolve()
            if not (_is_within(resolved, prefix) or _is_within(resolved, base_prefix)):
                raise ReleaseOperationError("probe sys.path escapes its Python environments")

    return {
        "module": str(module),
        "site_packages": str(site_packages),
        "sys_executable": str(executable),
        "forbidden_source_roots": [str(root) for root in forbidden_roots],
        "editable": False,
        "source_root_import": False,
        "source_root_pth": False,
        "target_environment_bound": True,
        "credential_safe_metadata": strict,
        "network_attempt_count": document.get("network_attempt_count"),
    }


def _validate_upgrade_continuity(
    baseline: dict[str, Any],
    after_dependency_sync: dict[str, Any],
) -> dict[str, object]:
    """Prove dependency synchronization did not turn an upgrade into a fresh install."""

    if after_dependency_sync.get("distribution") != baseline.get("distribution"):
        raise ReleaseOperationError(
            "baseline distribution was removed during final dependency synchronization"
        )
    stable_fields = (
        "version",
        "module",
        "site_packages",
        "sys_executable",
        "direct_url",
        "pth",
        "installed_file_count",
        "installed_tree_sha256",
        "installed_symlink_components",
        "package_file_count",
        "package_tree_sha256",
        "package_symlink_components",
    )
    for field in stable_fields:
        if after_dependency_sync.get(field) != baseline.get(field):
            raise ReleaseOperationError(
                f"baseline distribution changed during final dependency synchronization: {field}"
            )
    return {
        "baseline_distribution_preserved": True,
        "stable_fields": list(stable_fields),
    }


def _validate_final_environment_equivalence(
    upgraded: dict[str, Any],
    fresh: dict[str, Any],
) -> dict[str, object]:
    """Require a fresh final control that shares no interpreter or site-packages."""

    independence_fields = ("sys_executable", "site_packages", "module")
    if any(upgraded.get(field) == fresh.get(field) for field in independence_fields):
        raise ReleaseOperationError("upgraded and fresh final environments are not independent")
    equivalent_fields = (
        "distribution",
        "version",
        "environment_inventory_count",
        "environment_inventory_sha256",
        "package_file_count",
        "package_tree_sha256",
    )
    for field in equivalent_fields:
        if upgraded.get(field) != fresh.get(field):
            raise ReleaseOperationError(f"final installations differ: {field}")
    return {
        "independent_environments": True,
        "equivalent_final_installations": True,
        "equivalent_fields": list(equivalent_fields),
    }


def _validate_repository_postcondition(
    repository_root: Path,
    before: Any,
    *,
    env: dict[str, str],
) -> Any:
    """Re-read the release checkout and reject any clean/tree/commit drift."""

    after = _git_identity_in_environment(
        repository_root,
        env=env,
        require_clean=True,
    )
    if after != before:
        raise ReleaseOperationError("release repository identity changed during upgrade rehearsal")
    return after


def _git_identity_in_environment(
    root: Path,
    *,
    env: dict[str, str],
    require_clean: bool,
) -> GitIdentity:
    """Read repository identity without inheriting operator HOME or config env."""

    resolved = root.resolve()
    if not (resolved / ".git").exists():
        raise ReleaseOperationError(f"not a git checkout: {resolved}")

    def git(*arguments: str, binary: bool = False) -> str | bytes:
        completed = _run_git(
            resolved,
            *arguments,
            env=env,
        )
        if completed.returncode != 0:
            raise ReleaseOperationError(
                f"git {' '.join(arguments)} failed in contained environment"
            )
        if binary:
            return completed.stdout
        return completed.stdout.decode("utf-8", "strict").strip()

    replace_refs = git(
        "for-each-ref",
        "--format=%(refname)",
        "refs/replace",
        binary=True,
    )
    assert isinstance(replace_refs, bytes)
    if replace_refs:
        raise ReleaseOperationError("release checkout contains replace refs")

    graft_path_value = git("rev-parse", "--git-path", "info/grafts")
    assert isinstance(graft_path_value, str)
    if not graft_path_value:
        raise ReleaseOperationError("release checkout grafts path is unavailable")
    graft_path = Path(graft_path_value)
    if not graft_path.is_absolute():
        graft_path = resolved / graft_path
    try:
        graft_stat = graft_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ReleaseOperationError("release checkout grafts path is unreadable") from exc
    else:
        if not stat.S_ISREG(graft_stat.st_mode) or graft_stat.st_size != 0:
            raise ReleaseOperationError("release checkout contains nonempty or unsafe grafts")

    index_entries = git("ls-files", "-v", "-z", binary=True)
    assert isinstance(index_entries, bytes)
    for entry in index_entries.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 3 or entry[1:2] != b" ":
            raise ReleaseOperationError("release checkout index flags are malformed")
        tag = entry[0]
        if tag == ord("S") or ord("a") <= tag <= ord("z"):
            raise ReleaseOperationError("release checkout contains hidden index bits")

    status = git("status", "--porcelain=v2", "-z", binary=True)
    branch = git("branch", "--show-current")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    fetch_urls = git("remote", "get-url", "--all", "github")
    push_urls = git("remote", "get-url", "--push", "--all", "github")
    assert isinstance(status, bytes)
    assert all(isinstance(item, str) for item in (branch, commit, tree, fetch_urls, push_urls))
    if str(fetch_urls).splitlines() != [CANONICAL_GITHUB_REMOTE] or str(push_urls).splitlines() != [
        CANONICAL_GITHUB_REMOTE
    ]:
        raise ReleaseOperationError("github remote is not the canonical publication URL")
    clean = status == b""
    if require_clean and not clean:
        raise ReleaseOperationError(f"release checkout is dirty: {resolved}")
    return GitIdentity(
        path=str(resolved),
        branch=str(branch),
        commit=str(commit),
        tree=str(tree),
        origin_url=CANONICAL_GITHUB_REMOTE,
        status_sha256=sha256_bytes(status),
        clean=clean,
    )


def _json_probe(
    *,
    python: Path,
    cwd: Path,
    forbidden_roots: tuple[Path, ...],
    log_path: Path,
    env: dict[str, str],
    expected_wheel: Path,
    expected_version: str,
) -> tuple[dict[str, Any], dict[str, object], dict[str, object]]:
    script = _probe_script()
    argv = _guarded_argv([str(python), "-I", "-B", "-c", script])
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    safe_argv = [
        *argv[:-1],
        f"<probe-script-sha256:{sha256_bytes(script.encode('utf-8'))}>",
    ]
    command = {
        "argv": safe_argv,
        "exit_code": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout),
        "stdout_bytes": len(completed.stdout),
        "stderr_sha256": sha256_bytes(completed.stderr),
        "stderr_bytes": len(completed.stderr),
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "raw_stderr_persisted": False,
        "log_path": str(log_path),
    }
    if completed.returncode != 0:
        write_immutable(log_path, canonical_json_bytes(command))
        raise ReleaseOperationError(f"non-editable import probe failed: {log_path.name}")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        write_immutable(log_path, canonical_json_bytes(command))
        raise ReleaseOperationError("non-editable import probe output is not JSON") from exc
    if not isinstance(document, dict):
        write_immutable(log_path, canonical_json_bytes(command))
        raise ReleaseOperationError("non-editable import probe output is not an object")
    try:
        validation = _validate_import_probe(
            document,
            forbidden_roots=forbidden_roots,
            expected_python=python,
            expected_wheel=expected_wheel,
            expected_version=expected_version,
        )
    except ReleaseOperationError as exc:
        write_immutable(
            log_path,
            canonical_json_bytes(
                {
                    "command": command,
                    "probe": document,
                    "validation": {
                        "status": "rejected",
                        "error": str(exc),
                    },
                }
            ),
        )
        raise
    write_immutable(
        log_path,
        canonical_json_bytes(
            {
                "command": command,
                "probe": document,
                "validation": validation,
            }
        ),
    )
    return document, validation, command


def _single_wheel(directory: Path) -> Path:
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ReleaseOperationError("wheel build did not produce exactly one wheel")
    wheel = wheels[0]
    wheel.chmod(0o600)
    return wheel


def _wheel_payload_facts(wheel: Path) -> dict[str, object]:
    """Hash sorted uncompressed wheel members, excluding ZIP metadata."""

    digest = hashlib.sha256()
    package_digest = hashlib.sha256()
    names: set[str] = set()
    package_names: set[str] = set()
    entry_point_payloads: list[bytes] = []
    total_bytes = 0
    with zipfile.ZipFile(wheel) as bundle:
        members = sorted(
            (member for member in bundle.infolist() if not member.is_dir()),
            key=lambda member: member.filename,
        )
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.filename in names
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
            ):
                raise ReleaseOperationError("wheel contains an unsafe or duplicate member")
            names.add(member.filename)
            payload = bundle.read(member)
            if (
                len(path.parts) == 2
                and path.parts[0].endswith(".dist-info")
                and path.parts[1] == "entry_points.txt"
            ):
                entry_point_payloads.append(payload)
            total_bytes += len(payload)
            digest.update(member.filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)
            digest.update(b"\0")
            if len(path.parts) > 1 and path.parts[0] == "quant_system":
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                package_names.add(relative)
                package_digest.update(relative.encode("utf-8"))
                package_digest.update(b"\0")
                package_digest.update(payload)
                package_digest.update(b"\0")
    if not names:
        raise ReleaseOperationError("wheel has no payload members")
    if not package_names:
        raise ReleaseOperationError("wheel has no quant_system package payload")
    if len(entry_point_payloads) != 1:
        raise ReleaseOperationError("wheel must contain one entry_points.txt")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(entry_point_payloads[0].decode("utf-8", "strict"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise ReleaseOperationError("wheel entry-point metadata is malformed") from exc
    console_scripts = parser["console_scripts"] if parser.has_section("console_scripts") else {}
    console_entry_points = [
        {
            "group": "console_scripts",
            "name": name,
            "value": value.strip(),
        }
        for name, value in sorted(console_scripts.items())
    ]
    return {
        "member_count": len(names),
        "uncompressed_bytes": total_bytes,
        "normalized_payload_sha256": digest.hexdigest(),
        "package_file_count": len(package_names),
        "package_tree_sha256": package_digest.hexdigest(),
        "console_entry_points": console_entry_points,
    }


def _symlink_components(path: Path) -> list[str]:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    components: list[str] = []
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            components.append(str(current))
    return components


def _cli_install_facts(
    *,
    cli_path: Path,
    expected_python: Path,
    expected_wheel: Path,
    import_probe: dict[str, Any],
) -> dict[str, object]:
    """Bind the console script to its exact interpreter and wheel metadata."""

    cli_path = cli_path.absolute()
    expected_python = expected_python.absolute()
    expected_path = expected_python.parent / "quant-system"
    if cli_path != expected_path:
        raise ReleaseOperationError("CLI path is not in the requested environment")
    if _symlink_components(cli_path):
        raise ReleaseOperationError("CLI path uses a symlink component")
    if _symlink_components(expected_python):
        raise ReleaseOperationError("CLI interpreter path uses a symlink component")
    try:
        info = cli_path.stat()
        payload = cli_path.read_bytes()
    except OSError as exc:
        raise ReleaseOperationError("installed CLI is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ReleaseOperationError("installed CLI is not an owner-controlled regular file")
    if not os.access(cli_path, os.X_OK):
        raise ReleaseOperationError("installed CLI is not executable")
    if len(payload) > 1024 * 1024 or b"\0" in payload:
        raise ReleaseOperationError("installed CLI script is unsafe")
    try:
        rendered = payload.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ReleaseOperationError("installed CLI script is not UTF-8") from exc
    lines = rendered.splitlines(keepends=True)
    expected_shebang = f"#!{expected_python}\n"
    if not lines or lines[0] != expected_shebang:
        raise ReleaseOperationError("installed CLI shebang targets a foreign interpreter")
    expected_entry_points = [
        {
            "group": "console_scripts",
            "name": "quant-system",
            "value": EXPECTED_CONSOLE_ENTRY_POINT,
        }
    ]
    wheel_facts = _wheel_payload_facts(expected_wheel)
    if wheel_facts.get("console_entry_points") != expected_entry_points:
        raise ReleaseOperationError("wheel console entry point is not canonical")
    if import_probe.get("console_entry_points") != expected_entry_points:
        raise ReleaseOperationError("installed console entry point is not canonical")
    script_body = "".join(lines[1:])
    if script_body != EXPECTED_CONSOLE_SCRIPT_BODY:
        raise ReleaseOperationError("installed CLI is not the canonical generated wrapper")
    normalized = "#!<TARGET_ENVIRONMENT_PYTHON>\n" + script_body
    return {
        "path": str(cli_path),
        "path_symlink_components": [],
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "owner_uid": info.st_uid,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "shebang_python": str(expected_python),
        "shebang_python_sha256": sha256_file(expected_python),
        "normalized_script_sha256": sha256_bytes(normalized.encode("utf-8")),
        "console_entry_point": EXPECTED_CONSOLE_ENTRY_POINT,
        "wheel_sha256": sha256_file(expected_wheel),
        "wheel_entry_points": expected_entry_points,
        "target_environment_bound": True,
    }


def _project_facts(root: Path) -> dict[str, object]:
    pyproject = root / "pyproject.toml"
    lock = root / "uv.lock"
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = document["project"]
        name = project["name"]
        version = project["version"]
    except (KeyError, OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseOperationError("project metadata is unavailable or malformed") from exc
    if name != "quant-system" or not isinstance(version, str) or not version:
        raise ReleaseOperationError("project name or version is not closure authority")
    return {
        "name": name,
        "version": version,
        "pyproject_sha256": sha256_file(pyproject),
        "uv_lock_sha256": sha256_file(lock),
    }


def _tool_version_facts(
    *,
    binary: Path,
    expected_name: str,
    version_args: list[str],
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> dict[str, object]:
    argv = _guarded_argv([str(binary), *version_args])
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    write_immutable(
        log_path,
        _safe_command_log_payload(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        ),
    )
    if completed.returncode != 0:
        raise ReleaseOperationError(f"tool version command failed: {log_path.name}")
    try:
        rendered = payload.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseOperationError("tool version output is not safe ASCII") from exc
    match = re.fullmatch(
        rf"{re.escape(expected_name)} ([0-9]+\.[0-9]+\.[0-9]+)"
        r"(?: \([A-Za-z0-9 ._+-]+\))?",
        rendered,
    )
    if match is None:
        raise ReleaseOperationError("tool version output is malformed")
    return {
        "path": str(binary.resolve()),
        "sha256": sha256_file(binary.resolve()),
        "version": match.group(1),
        "version_output_sha256": sha256_bytes(payload),
        "command": {
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stdout_bytes": len(completed.stdout),
            "stderr_sha256": sha256_bytes(completed.stderr),
            "stderr_bytes": len(completed.stderr),
            "log_path": str(log_path),
        },
    }


def _venv_environment(
    environment: dict[str, str],
    virtual_environment: Path,
) -> dict[str, str]:
    result = dict(environment)
    result["VIRTUAL_ENV"] = str(virtual_environment.resolve())
    return result


def _create_virtual_environment(
    *,
    base_python: Path,
    root: Path,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> dict[str, object]:
    command = _run(
        _guarded_argv(
            [
                str(base_python),
                "-I",
                "-B",
                "-m",
                "venv",
                "--copies",
                "--without-pip",
                str(root),
            ]
        ),
        cwd=cwd,
        env=env,
        log_path=log_path,
    )
    root.chmod(0o700)
    python = root / "bin" / "python"
    if not python.is_file() or python.is_symlink() or not os.access(python, os.X_OK):
        raise ReleaseOperationError("virtual environment Python is not an independent copy")
    command["python"] = str(python.resolve())
    command["python_sha256"] = sha256_file(python)
    return command


def verify_noneditable_upgrade(
    *,
    repository_root: Path,
    output_dir: Path,
    bootstrap_authority_path: Path,
    bootstrap_authority_sha256: str,
    uv_binary: str | None = None,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    output_candidate = Path(os.path.abspath(os.fspath(output_dir)))
    if _is_within(output_candidate, repository_root):
        raise ReleaseOperationError("upgrade evidence must be outside the release checkout")
    output_dir = ensure_private_directory(output_candidate)
    bootstrap_authority = _bootstrap_authority(
        repository_root=repository_root,
        output_dir=output_dir,
        authority_path=bootstrap_authority_path,
        authority_sha256=bootstrap_authority_sha256,
    )
    receipt_path = output_dir / "noneditable-upgrade-receipt.json"
    if receipt_path.exists():
        raise ReleaseOperationError("upgrade receipt already exists")
    work = output_dir / "work"
    if work.exists():
        raise ReleaseOperationError("upgrade work directory already exists")
    environment, environment_facts = _isolated_process_environment(output_dir)
    identity = _git_identity_in_environment(
        repository_root,
        env=environment,
        require_clean=True,
    )
    if identity.branch != RELEASE_BRANCH:
        raise ReleaseOperationError("upgrade rehearsal is not on the release branch")
    if (
        identity.commit != bootstrap_authority["commit"]
        or identity.tree != bootstrap_authority["tree"]
    ):
        raise ReleaseOperationError("release checkout identity changed after bootstrap capture")
    final_commit = identity.commit

    uv = uv_binary or shutil.which("uv")
    if not uv or not Path(uv).is_file() or not os.access(uv, os.X_OK):
        raise ReleaseOperationError("uv executable is unavailable")
    uv_path = Path(uv).resolve()
    if sys.version_info[:2] == (3, 11):
        base_python = Path(sys.executable).resolve()
    else:
        base_python_value = shutil.which("python3.11")
        if not base_python_value:
            raise ReleaseOperationError("Python 3.11 executable is unavailable")
        base_python = Path(base_python_value).resolve()
    work.mkdir(mode=0o700)

    ancestor_argv = _git_argv(
        repository_root,
        "merge-base",
        "--is-ancestor",
        PUBLISHED_BASELINE,
        final_commit,
    )
    ancestor = _run_git(
        repository_root,
        "merge-base",
        "--is-ancestor",
        PUBLISHED_BASELINE,
        final_commit,
        env=environment,
    )
    write_immutable(
        output_dir / "ancestry.log",
        _safe_command_log_payload(
            argv=ancestor_argv,
            exit_code=ancestor.returncode,
            stdout=ancestor.stdout,
            stderr=ancestor.stderr,
        ),
    )
    if ancestor.returncode != 0:
        raise ReleaseOperationError("published baseline is not an ancestor of final commit")

    uv_tool_facts = _tool_version_facts(
        binary=uv_path,
        expected_name="uv",
        version_args=["--version"],
        cwd=work,
        env=environment,
        log_path=output_dir / "uv-version.log",
    )
    git_tool_facts = _tool_version_facts(
        binary=GIT_BINARY,
        expected_name="git version",
        version_args=["--version"],
        cwd=work,
        env=environment,
        log_path=output_dir / "git-version.log",
    )
    python_tool_facts = _tool_version_facts(
        binary=base_python,
        expected_name="Python",
        version_args=["--version"],
        cwd=work,
        env=environment,
        log_path=output_dir / "python-version.log",
    )
    if not str(python_tool_facts["version"]).startswith("3.11."):
        raise ReleaseOperationError("upgrade rehearsal requires Python 3.11")

    baseline_root = work / "baseline"
    final_root = work / "final"
    baseline_archive = _archive_commit(
        repository_root=repository_root,
        commit=PUBLISHED_BASELINE,
        destination=baseline_root,
        archive_path=work / "baseline.tar",
        env=environment,
    )
    final_archive = _archive_commit(
        repository_root=repository_root,
        commit=final_commit,
        destination=final_root,
        archive_path=work / "final.tar",
        env=environment,
    )
    for root in (baseline_root, final_root):
        if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
            raise ReleaseOperationError("archive lacks pyproject.toml or uv.lock")
    baseline_project = _project_facts(baseline_root)
    final_project = _project_facts(final_root)

    upgrade_environment_root = baseline_root / ".venv"
    upgrade_environment_create = _create_virtual_environment(
        base_python=base_python,
        root=upgrade_environment_root,
        cwd=baseline_root,
        env=environment,
        log_path=output_dir / "upgrade-environment-create.log",
    )
    upgrade_python = upgrade_environment_root / "bin" / "python"
    upgrade_environment = _venv_environment(
        environment,
        upgrade_environment_root,
    )
    baseline_sync = _run(
        _guarded_argv(_uv_sync_argv(uv_path, inexact=False)),
        cwd=baseline_root,
        env=upgrade_environment,
        log_path=output_dir / "baseline-sync.log",
    )
    baseline_dist = ensure_private_directory(work / "baseline-dist")
    baseline_build = _run(
        _guarded_argv(
            [
                str(uv_path),
                "build",
                "--wheel",
                "--offline",
                "--out-dir",
                str(baseline_dist),
                "--python",
                str(upgrade_python),
                "--no-python-downloads",
            ]
        ),
        cwd=baseline_root,
        env=upgrade_environment,
        log_path=output_dir / "baseline-wheel-build.log",
    )
    baseline_wheel = _single_wheel(baseline_dist)
    baseline_wheel_payload = _wheel_payload_facts(baseline_wheel)
    baseline_install = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "install",
                "--offline",
                "--python",
                str(upgrade_python),
                "--reinstall",
                "--no-deps",
                str(baseline_wheel),
            ]
        ),
        cwd=baseline_root,
        env=upgrade_environment,
        log_path=output_dir / "baseline-wheel-install.log",
    )
    upgrade_cli_path = upgrade_environment_root / "bin" / "quant-system"
    if not upgrade_cli_path.is_file() or upgrade_cli_path.is_symlink():
        raise ReleaseOperationError("baseline wheel did not install the CLI")
    neutral = work / "neutral"
    neutral.mkdir(mode=0o700)
    forbidden = _forbidden_source_roots(
        repository_root,
        baseline_root,
        final_root,
    )
    baseline_probe, baseline_probe_validation, baseline_probe_command = _json_probe(
        python=upgrade_python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "baseline-import.log",
        env=upgrade_environment,
        expected_wheel=baseline_wheel,
        expected_version=str(baseline_project["version"]),
    )
    baseline_cli_facts = _cli_install_facts(
        cli_path=upgrade_cli_path,
        expected_python=upgrade_python,
        expected_wheel=baseline_wheel,
        import_probe=baseline_probe,
    )
    # The published baseline predates packaging its compatibility manifest, so
    # importing the installed distribution is the baseline smoke.  The CLI
    # smoke belongs after the upgrade; requiring it here would demand that the
    # historical baseline already contain the final packaging fix.

    final_sync = _run(
        _guarded_argv(_uv_sync_argv(uv_path, inexact=True)),
        cwd=final_root,
        env=upgrade_environment,
        log_path=output_dir / "final-sync.log",
    )
    (
        after_sync_probe,
        after_sync_probe_validation,
        after_sync_probe_command,
    ) = _json_probe(
        python=upgrade_python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "after-final-sync-import.log",
        env=upgrade_environment,
        expected_wheel=baseline_wheel,
        expected_version=str(baseline_project["version"]),
    )
    upgrade_continuity = _validate_upgrade_continuity(
        baseline_probe,
        after_sync_probe,
    )

    final_dist = ensure_private_directory(work / "final-dist")
    final_build = _run(
        _guarded_argv(
            [
                str(uv_path),
                "build",
                "--wheel",
                "--offline",
                "--out-dir",
                str(final_dist),
                "--python",
                str(upgrade_python),
                "--no-python-downloads",
            ]
        ),
        cwd=final_root,
        env=upgrade_environment,
        log_path=output_dir / "final-wheel-build.log",
    )
    final_wheel = _single_wheel(final_dist)
    final_wheel_payload = _wheel_payload_facts(final_wheel)
    if (
        final_wheel_payload["normalized_payload_sha256"]
        == baseline_wheel_payload["normalized_payload_sha256"]
    ):
        raise ReleaseOperationError("baseline and final wheel payloads are identical")
    upgrade = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "install",
                "--offline",
                "--python",
                str(upgrade_python),
                "--reinstall",
                "--no-deps",
                str(final_wheel),
            ]
        ),
        cwd=neutral,
        env=upgrade_environment,
        log_path=output_dir / "final-upgrade.log",
    )
    upgraded_dependency_check = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "check",
                "--offline",
                "--python",
                str(upgrade_python),
                "--no-python-downloads",
            ]
        ),
        cwd=neutral,
        env=upgrade_environment,
        log_path=output_dir / "upgraded-final-pip-check.log",
    )
    upgraded_inventory = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "freeze",
                "--strict",
                "--offline",
                "--python",
                str(upgrade_python),
                "--no-python-downloads",
            ]
        ),
        cwd=neutral,
        env=upgrade_environment,
        log_path=output_dir / "upgraded-final-pip-freeze.log",
    )
    upgraded_probe, upgraded_probe_validation, upgraded_probe_command = _json_probe(
        python=upgrade_python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "upgraded-final-import.log",
        env=upgrade_environment,
        expected_wheel=final_wheel,
        expected_version=str(final_project["version"]),
    )
    upgraded_cli_facts = _cli_install_facts(
        cli_path=upgrade_cli_path,
        expected_python=upgrade_python,
        expected_wheel=final_wheel,
        import_probe=upgraded_probe,
    )
    upgraded_cli = _run(
        _guarded_argv([str(upgrade_cli_path), "--help"]),
        cwd=neutral,
        env=upgrade_environment,
        log_path=output_dir / "upgraded-final-cli.log",
    )

    fresh_environment_root = final_root / ".venv"
    fresh_environment_create = _create_virtual_environment(
        base_python=base_python,
        root=fresh_environment_root,
        cwd=final_root,
        env=environment,
        log_path=output_dir / "fresh-final-environment-create.log",
    )
    fresh_python = fresh_environment_root / "bin" / "python"
    fresh_environment = _venv_environment(environment, fresh_environment_root)
    fresh_sync = _run(
        _guarded_argv(_uv_sync_argv(uv_path, inexact=False)),
        cwd=final_root,
        env=fresh_environment,
        log_path=output_dir / "fresh-final-sync.log",
    )
    fresh_install = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "install",
                "--offline",
                "--python",
                str(fresh_python),
                "--reinstall",
                "--no-deps",
                str(final_wheel),
            ]
        ),
        cwd=neutral,
        env=fresh_environment,
        log_path=output_dir / "fresh-final-wheel-install.log",
    )
    fresh_cli_path = fresh_environment_root / "bin" / "quant-system"
    if not fresh_cli_path.is_file() or fresh_cli_path.is_symlink():
        raise ReleaseOperationError("fresh final wheel did not install the CLI")
    fresh_dependency_check = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "check",
                "--offline",
                "--python",
                str(fresh_python),
                "--no-python-downloads",
            ]
        ),
        cwd=neutral,
        env=fresh_environment,
        log_path=output_dir / "fresh-final-pip-check.log",
    )
    fresh_inventory = _run(
        _guarded_argv(
            [
                str(uv_path),
                "pip",
                "freeze",
                "--strict",
                "--offline",
                "--python",
                str(fresh_python),
                "--no-python-downloads",
            ]
        ),
        cwd=neutral,
        env=fresh_environment,
        log_path=output_dir / "fresh-final-pip-freeze.log",
    )
    fresh_probe, fresh_probe_validation, fresh_probe_command = _json_probe(
        python=fresh_python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "fresh-final-import.log",
        env=fresh_environment,
        expected_wheel=final_wheel,
        expected_version=str(final_project["version"]),
    )
    fresh_cli_facts = _cli_install_facts(
        cli_path=fresh_cli_path,
        expected_python=fresh_python,
        expected_wheel=final_wheel,
        import_probe=fresh_probe,
    )
    fresh_cli = _run(
        _guarded_argv([str(fresh_cli_path), "--help"]),
        cwd=neutral,
        env=fresh_environment,
        log_path=output_dir / "fresh-final-cli.log",
    )

    if upgraded_probe["module"] != baseline_probe["module"]:
        raise ReleaseOperationError("wheel upgrade changed the isolated site-packages location")
    if upgraded_probe["installed_tree_sha256"] == baseline_probe["installed_tree_sha256"]:
        raise ReleaseOperationError("installed baseline and final trees are identical")
    final_environment_equivalence = _validate_final_environment_equivalence(
        upgraded_probe,
        fresh_probe,
    )
    if (
        upgraded_inventory["stdout_sha256"] != fresh_inventory["stdout_sha256"]
        or upgraded_inventory["stdout_bytes"] != fresh_inventory["stdout_bytes"]
    ):
        raise ReleaseOperationError("upgraded and fresh dependency inventories differ")
    if (
        upgraded_cli["stdout_sha256"] != fresh_cli["stdout_sha256"]
        or upgraded_cli["stderr_sha256"] != fresh_cli["stderr_sha256"]
        or upgraded_cli["stdout_bytes"] != fresh_cli["stdout_bytes"]
        or upgraded_cli["stderr_bytes"] != fresh_cli["stderr_bytes"]
    ):
        raise ReleaseOperationError("upgraded and fresh CLI smoke output differs")
    if (
        upgraded_cli_facts["normalized_script_sha256"]
        != fresh_cli_facts["normalized_script_sha256"]
        or upgraded_cli_facts["console_entry_point"] != fresh_cli_facts["console_entry_point"]
        or upgraded_cli_facts["wheel_sha256"] != fresh_cli_facts["wheel_sha256"]
    ):
        raise ReleaseOperationError("upgraded and fresh CLI installation facts differ")

    identity_after = _validate_repository_postcondition(
        repository_root,
        identity,
        env=environment,
    )

    receipt: dict[str, object] = {
        "schema_version": "agent-v0.2.2-noneditable-upgrade.v3",
        "status": "passed",
        "completed_at": utc_now(),
        "repository_before": asdict(identity),
        "repository_after": asdict(identity_after),
        "repository_identity_stable": True,
        "bootstrap_authority": bootstrap_authority,
        "bootstrap_authority_sha256": bootstrap_authority_sha256,
        "bootstrap_identity_bound": True,
        "published_baseline": PUBLISHED_BASELINE,
        "final_commit": final_commit,
        "baseline_is_ancestor": True,
        "process_isolation": environment_facts,
        "tools": {
            "uv": uv_tool_facts,
            "base_python": python_tool_facts,
            "git": git_tool_facts,
        },
        "baseline_archive": baseline_archive,
        "final_archive": final_archive,
        "baseline_project": baseline_project,
        "final_project": final_project,
        "forbidden_source_roots": [str(root) for root in forbidden],
        "upgrade_environment_create": upgrade_environment_create,
        "upgrade_environment_python": str(upgrade_python.resolve()),
        "baseline_sync": baseline_sync,
        "baseline_wheel_build": baseline_build,
        "baseline_wheel": {
            "filename": baseline_wheel.name,
            "sha256": sha256_file(baseline_wheel),
            "bytes": baseline_wheel.stat().st_size,
            "payload": baseline_wheel_payload,
        },
        "baseline_wheel_install": baseline_install,
        "baseline_import": baseline_probe,
        "baseline_import_validation": baseline_probe_validation,
        "baseline_import_command": baseline_probe_command,
        "baseline_cli_install": baseline_cli_facts,
        "baseline_cli_smoke": {
            "status": "not_required_before_upgrade",
            "reason": "import baseline, then smoke CLI after baseline-to-final upgrade",
        },
        "final_dependency_sync_in_upgrade_environment": final_sync,
        "final_dependency_sync_mode": {
            "inexact": True,
            "no_install_project": True,
            "baseline_distribution_preserved": True,
        },
        "after_final_sync_import": after_sync_probe,
        "after_final_sync_import_validation": after_sync_probe_validation,
        "after_final_sync_import_command": after_sync_probe_command,
        "upgrade_continuity": upgrade_continuity,
        "final_wheel_build": final_build,
        "final_wheel": {
            "filename": final_wheel.name,
            "sha256": sha256_file(final_wheel),
            "bytes": final_wheel.stat().st_size,
            "payload": final_wheel_payload,
        },
        "upgrade": upgrade,
        "upgraded_final_dependency_check": upgraded_dependency_check,
        "upgraded_final_inventory": upgraded_inventory,
        "upgraded_final_import": upgraded_probe,
        "upgraded_final_import_validation": upgraded_probe_validation,
        "upgraded_final_import_command": upgraded_probe_command,
        "upgraded_final_cli_install": upgraded_cli_facts,
        "upgraded_final_cli_smoke": upgraded_cli,
        "fresh_final_environment_create": fresh_environment_create,
        "fresh_final_environment_python": str(fresh_python.resolve()),
        "fresh_final_sync": fresh_sync,
        "fresh_final_wheel_install": fresh_install,
        "fresh_final_dependency_check": fresh_dependency_check,
        "fresh_final_inventory": fresh_inventory,
        "fresh_final_import": fresh_probe,
        "fresh_final_import_validation": fresh_probe_validation,
        "fresh_final_import_command": fresh_probe_command,
        "fresh_final_cli_install": fresh_cli_facts,
        "fresh_final_cli_smoke": fresh_cli,
        "final_environment_equivalence": final_environment_equivalence,
        "final_cli_equivalent": True,
        "final_inventory_equivalent": True,
        "noneditable": True,
        "isolated_import": True,
        "final_lock_consumed_in_same_environment": True,
        "fresh_final_control": True,
        "offline": True,
        "network_denied": True,
        "normalized_wheel_payload_changed": True,
        "installed_tree_changed": True,
    }
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt
