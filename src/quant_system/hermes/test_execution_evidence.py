"""Strict execution receipts for release-gating test suites.

The receipt is deliberately not a test-result form.  It binds one exact
process invocation to immutable raw output and JUnit XML files, and every
consumer reopens and recomputes those files before trusting the derived
counts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TEST_EXECUTION_RECEIPT_CONTRACT = "agent-v0.2-test-execution-receipt/v2"
RUNTIME_NAMES = ("platform", "hqa", "hermes")
REQUIRED_TEST_SUITES = frozenset({"platform", "hqa", "hermes_focused", "frontend"})

_HEX_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_EXECUTABLE_RE = re.compile(r"^python(?:3(?:\.[0-9]+)?)?$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_SAFE_SUITE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
# The Platform's full 2.6k-case JUnit document is currently ~4.6 MiB because
# parameterized node IDs are evidence too. Keep a separate, still-bounded
# allowance instead of widening logs, receipts, or release manifests.
_MAX_JUNIT_BYTES = 8 * 1024 * 1024
_MAX_ARGV_ITEMS = 64
_MAX_ARG_BYTES = 4096
_MAX_ARGV_BYTES = 32 * 1024
_MAX_EXECUTABLE_BYTES = 128 * 1024 * 1024
_MAX_RECEIPT_AGE = timedelta(hours=24)
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_SUITE_RUNTIME = {
    "platform": "platform",
    "hqa": "hqa",
    "hermes_focused": "hermes",
    "frontend": "platform",
}
_APPROVED_PYTEST_SELECTORS = {
    "platform": ("tests",),
    "hqa": ("tests",),
    "hermes_focused": (
        "tests/gateway/test_api_server.py",
        "tests/gateway/test_api_server_managed_runs.py",
        "tests/tools/test_local_env_session_leak.py",
    ),
}
_APPROVED_PYTEST_FLAGS = frozenset(
    {
        "-q",
        "-qq",
        "-s",
        "--capture=no",
        "--color=no",
        "--disable-warnings",
        "--strict-config",
        "--strict-markers",
    }
)
_FORBIDDEN_TEST_SELECTION_ARGS = frozenset(
    {
        "--collect-only",
        "--deselect",
        "--ff",
        "--ignore",
        "--ignore-glob",
        "--lf",
        "--maxfail",
        "--stepwise",
        "-k",
        "-m",
    }
)
_FORBIDDEN_XML_DECLARATION_RE = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)",
    re.IGNORECASE,
)
_XML_ENCODING_RE = re.compile(
    r"<\?xml\b[^>]*\bencoding\s*=\s*(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)
_SENSITIVE_ARG_RE = re.compile(
    r"^(?:"
    r"(?:--?)(?:[a-z0-9]+[-_])*(?:"
    r"api[-_]?key|authorization|bearer|body|cookie|credential|"
    r"database[-_]?url|dsn|message|password|prompt|secret|session[-_]?key|token"
    r")(?:[-_][a-z0-9]+)*(?:$|[=:])"
    r"|(?:api[-_]?key|authorization|bearer|body|cookie|credential|"
    r"database[-_]?url|dsn|message|password|prompt|secret|session[-_]?key|token)"
    r"(?:$|[=:])"
    r")",
    re.IGNORECASE,
)


class TestExecutionEvidenceError(RuntimeError):
    """A test execution receipt or one of its immutable files is invalid."""


@dataclass(frozen=True)
class TestCounts:
    passed: int
    failed: int
    skipped: int

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


@dataclass(frozen=True)
class ValidatedTestExecution:
    name: str
    argv: tuple[str, ...]
    counts: TestCounts
    started_at: datetime
    completed_at: datetime
    runtime: Mapping[str, Mapping[str, str]]
    cwd_runtime: str
    cwd_relative: str
    runner_kind: str
    executable_path: Path
    executable_sha256: str
    suite_entry_path: Path | None
    suite_entry_sha256: str | None
    receipt_path: Path
    receipt_content: bytes
    output_path: Path
    output_content: bytes
    junit_path: Path
    junit_content: bytes


def runtime_digest_from_commit(logical_name: str, commit: str) -> str:
    if logical_name not in RUNTIME_NAMES or _HEX_COMMIT_RE.fullmatch(commit) is None:
        raise TestExecutionEvidenceError("test receipt runtime identity is invalid")
    payload = b"agent-v0.2-runtime\x00" + logical_name.encode("ascii")
    payload += b"\x00commit\x00" + commit.encode("ascii") + b"\x00"
    return hashlib.sha256(payload).hexdigest()


def validate_argv(value: object, *, require_junit_placeholder: bool) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not value or len(value) > _MAX_ARGV_ITEMS:
        raise TestExecutionEvidenceError("test receipt argv is invalid")
    total_bytes = 0
    placeholder_count = 0
    result: list[str] = []
    for argument in value:
        if (
            not isinstance(argument, str)
            or not argument
            or "\x00" in argument
            or any(ord(character) < 0x20 for character in argument)
            or len(argument.encode("utf-8")) > _MAX_ARG_BYTES
            or _SENSITIVE_ARG_RE.search(argument)
        ):
            raise TestExecutionEvidenceError(
                "test argv must be bounded and contain no sensitive arguments"
            )
        placeholder_count += argument.count("{junit}")
        total_bytes += len(argument.encode("utf-8"))
        result.append(argument)
    if total_bytes > _MAX_ARGV_BYTES:
        raise TestExecutionEvidenceError("test receipt argv is invalid")
    if require_junit_placeholder and placeholder_count != 1:
        raise TestExecutionEvidenceError("test argv must contain exactly one {junit} placeholder")
    if not require_junit_placeholder and placeholder_count:
        raise TestExecutionEvidenceError(
            "executed test argv must not retain the {junit} placeholder"
        )
    return tuple(result)


def validate_suite_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or _SAFE_SUITE_RE.fullmatch(value) is None
        or value not in REQUIRED_TEST_SUITES
    ):
        raise TestExecutionEvidenceError("test receipt suite identity is invalid")
    return value


def _hash_regular_file(path: Path, *, field: str) -> str:
    target = Path(path).expanduser().resolve()
    file_fd = -1
    directory_fd = -1
    try:
        file_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if os.name == "nt":
            file_fd = os.open(target, file_flags)
        else:
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            directory_fd = os.open(target.anchor, directory_flags)
            for component in target.parts[1:-1]:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(target.name, file_flags, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size < 1
            or info.st_size > _MAX_EXECUTABLE_BYTES
        ):
            raise TestExecutionEvidenceError(f"test receipt {field} is not a bounded regular file")
        digest = hashlib.sha256()
        remaining = _MAX_EXECUTABLE_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(128 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
        if (
            remaining < 0
            or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise TestExecutionEvidenceError(
                f"test receipt {field} changed while it was being hashed"
            )
        return digest.hexdigest()
    except OSError as exc:
        raise TestExecutionEvidenceError(f"test receipt {field} is unavailable") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _mode_text(mode: int) -> str:
    return f"{stat.S_IMODE(mode):04o}"


def _trusted_owner(uid: int) -> bool:
    return uid == 0 or not hasattr(os, "geteuid") or uid == os.geteuid()


def _file_identity(
    path: Path,
    *,
    root: Path,
    field: str,
    require_executable: bool,
) -> dict[str, object]:
    try:
        realpath = Path(path).expanduser().resolve(strict=True)
        root_realpath = Path(root).expanduser().resolve(strict=True)
        relative = realpath.relative_to(root_realpath)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TestExecutionEvidenceError(
            f"test receipt {field} is outside its trusted root"
        ) from exc
    if not relative.parts:
        raise TestExecutionEvidenceError(
            f"test receipt {field} must be below its trusted root"
        )
    root_info = root_realpath.stat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or not _trusted_owner(root_info.st_uid)
        or stat.S_IMODE(root_info.st_mode) & 0o022
    ):
        raise TestExecutionEvidenceError(
            f"test receipt {field} trusted root is not owner-controlled"
        )
    current = root_realpath
    for component in relative.parts[:-1]:
        current = current / component
        info = current.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or not _trusted_owner(info.st_uid)
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise TestExecutionEvidenceError(
                f"test receipt {field} path is not owner-controlled"
            )
    info = realpath.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or not _trusted_owner(info.st_uid)
        or stat.S_IMODE(info.st_mode) & 0o022
        or (require_executable and not stat.S_IMODE(info.st_mode) & 0o111)
    ):
        raise TestExecutionEvidenceError(
            f"test receipt {field} is not an approved owner-controlled file"
        )
    return {
        "mode": _mode_text(info.st_mode),
        "nlink": info.st_nlink,
        "realpath": str(realpath),
        "relative": relative.as_posix(),
        "root": {
            "mode": _mode_text(root_info.st_mode),
            "realpath": str(root_realpath),
            "uid": root_info.st_uid,
        },
        "sha256": _hash_regular_file(realpath, field=field),
        "uid": info.st_uid,
    }


def _executable_root(path: Path) -> Path:
    realpath = Path(path).expanduser().resolve(strict=True)
    if realpath.parent.name in {"bin", "Scripts"}:
        return realpath.parent.parent
    return realpath.parent


def executable_evidence(path: Path) -> dict[str, object]:
    realpath = Path(path).expanduser().resolve(strict=True)
    return _file_identity(
        realpath,
        root=_executable_root(realpath),
        field="executable",
        require_executable=True,
    )


def _suite_entry_evidence(path: Path) -> dict[str, object]:
    realpath = Path(path).expanduser().resolve(strict=True)
    return _file_identity(
        realpath,
        root=realpath.parent,
        field="suite_entry",
        require_executable=False,
    )


def _validated_file_identity(
    value: object,
    *,
    field: str,
    require_executable: bool,
) -> tuple[Path, str]:
    document = _exact_mapping(
        value,
        keys=frozenset(
            {"mode", "nlink", "realpath", "relative", "root", "sha256", "uid"}
        ),
        field=field,
    )
    root = _exact_mapping(
        document["root"],
        keys=frozenset({"mode", "realpath", "uid"}),
        field=f"{field}.root",
    )
    realpath = document["realpath"]
    root_realpath = root["realpath"]
    digest = document["sha256"]
    if (
        not isinstance(realpath, str)
        or not Path(realpath).is_absolute()
        or not isinstance(root_realpath, str)
        or not Path(root_realpath).is_absolute()
        or not isinstance(digest, str)
        or _HEX_DIGEST_RE.fullmatch(digest) is None
    ):
        raise TestExecutionEvidenceError(
            f"test receipt {field} identity is invalid"
        )
    observed = _file_identity(
        Path(realpath),
        root=Path(root_realpath),
        field=field,
        require_executable=require_executable,
    )
    if dict(document) != observed:
        raise TestExecutionEvidenceError(
            f"test receipt {field} identity is invalid"
        )
    return Path(realpath), digest


def _approved_pytest_selectors(
    *,
    name: str,
    arguments: tuple[str, ...],
) -> None:
    selectors: list[str] = []
    plugin: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-p":
            if index + 1 >= len(arguments) or plugin is not None:
                raise TestExecutionEvidenceError(
                    "test receipt argv contains an invalid pytest plugin binding"
                )
            plugin = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--junitxml="):
            index += 1
            continue
        if argument in _APPROVED_PYTEST_FLAGS:
            index += 1
            continue
        if argument.startswith("--tb=") and argument.removeprefix("--tb=") in {
            "auto",
            "line",
            "long",
            "native",
            "no",
            "short",
        }:
            index += 1
            continue
        if argument.startswith("--durations=") and argument.removeprefix(
            "--durations="
        ).isascii() and argument.removeprefix("--durations=").isdigit():
            index += 1
            continue
        if argument.startswith("-"):
            raise TestExecutionEvidenceError(
                "test receipt argv contains an unapproved pytest option"
            )
        logical = argument.replace("\\", "/")
        if (
            logical != argument
            or logical.startswith("/")
            or "//" in logical
            or any(part in {"", ".", ".."} for part in logical.split("/"))
        ):
            raise TestExecutionEvidenceError(
                "test receipt argv contains an invalid test selector"
            )
        selectors.append(logical)
        index += 1
    if tuple(selectors) != _APPROVED_PYTEST_SELECTORS[name]:
        raise TestExecutionEvidenceError(
            "test receipt argv does not bind the approved suite selector"
        )
    expected_plugin = "pytest_asyncio.plugin" if name == "hermes_focused" else None
    if plugin != expected_plugin:
        raise TestExecutionEvidenceError(
            "test receipt argv does not bind the approved suite plugin"
        )


def _approved_frontend_arguments(arguments: tuple[str, ...]) -> None:
    remaining = list(arguments)
    if remaining and remaining[0] == "--":
        remaining.pop(0)
    expected = {"--reporter=junit"}
    observed: set[str] = set()
    for argument in remaining:
        if argument == "--reporter=junit":
            if argument in observed:
                raise TestExecutionEvidenceError(
                    "frontend suite argv selects multiple JUnit reporters"
                )
            observed.add(argument)
            continue
        if argument.startswith("--outputFile="):
            if "--outputFile" in observed:
                raise TestExecutionEvidenceError(
                    "frontend suite argv binds multiple JUnit outputs"
                )
            observed.add("--outputFile")
            continue
        raise TestExecutionEvidenceError(
            "frontend suite argv contains an unapproved selector or option"
        )
    if observed != expected | {"--outputFile"}:
        raise TestExecutionEvidenceError(
            "frontend suite argv does not bind the full approved Vitest suite"
        )


def _validate_execution_policy(
    *,
    name: str,
    argv: tuple[str, ...],
    cwd: object,
    executable: object,
    runner_kind: object,
    suite_entry: object,
    require_junit_placeholder: bool,
) -> tuple[str, str, str, Path, str, Path | None, str | None]:
    cwd_document = _exact_mapping(
        cwd,
        keys=frozenset({"realpath", "relative", "runtime"}),
        field="cwd",
    )
    cwd_runtime = cwd_document["runtime"]
    cwd_relative = cwd_document["relative"]
    cwd_realpath = cwd_document["realpath"]
    if (
        cwd_runtime != _SUITE_RUNTIME[name]
        or not isinstance(cwd_relative, str)
        or cwd_relative not in {".", "src/frontend"}
        or (name == "frontend" and cwd_relative != "src/frontend")
        or (name != "frontend" and cwd_relative != ".")
        or not isinstance(cwd_realpath, str)
        or not Path(cwd_realpath).is_absolute()
        or str(Path(cwd_realpath).resolve()) != cwd_realpath
    ):
        raise TestExecutionEvidenceError("test receipt cwd is not approved for its suite")

    executable_path, executable_digest = _validated_file_identity(
        executable,
        field="executable",
        require_executable=True,
    )
    argv_executable = Path(argv[0]).expanduser()
    if (
        not argv_executable.is_absolute()
        or argv_executable.resolve() != executable_path
    ):
        raise TestExecutionEvidenceError("test receipt executable identity is invalid")

    executable_name = executable_path.name
    is_python_executable = (
        _PYTHON_EXECUTABLE_RE.fullmatch(executable_name) is not None
    )
    uv_identity_is_approved = (
        argv_executable.name == "uv" and executable_name == "uv"
    )
    is_pytest_script = (
        executable_name == "pytest"
        and executable_path.parent.name == "bin"
        and executable_path.parent.parent == Path(str(cwd_realpath)) / ".venv"
    )
    is_uv_pytest = (
        uv_identity_is_approved
        and len(argv) >= 6
        and argv[1:5] == ("run", "--frozen", "--extra", "dev")
        and argv[5] == "pytest"
    )
    is_node_vitest = (
        name == "frontend"
        and runner_kind == "node_vitest"
        and argv_executable.name == "node"
        and executable_name == "node"
        and len(argv) >= 3
        and Path(argv[1]).is_absolute()
        and Path(argv[1])
        == Path(str(cwd_realpath)) / "node_modules" / "vitest" / "vitest.mjs"
        and argv[2] == "run"
    )
    is_python_pytest = (
        is_python_executable
        and len(argv) >= 3
        and argv[1:3] == ("-m", "pytest")
    )
    approved_runner = is_node_vitest if name == "frontend" else (
        runner_kind == "python"
        and (is_python_pytest or is_pytest_script or is_uv_pytest)
    )
    if not approved_runner:
        raise TestExecutionEvidenceError("test receipt argv does not use an approved suite runner")
    entry_path: Path | None = None
    entry_digest: str | None = None
    if is_node_vitest:
        entry_path, entry_digest = _validated_file_identity(
            suite_entry,
            field="suite_entry",
            require_executable=False,
        )
        if Path(argv[1]).resolve() != entry_path:
            raise TestExecutionEvidenceError(
                "test receipt Vitest entry identity is invalid"
            )
    elif suite_entry is not None:
        raise TestExecutionEvidenceError(
            "Python test receipt must not contain a suite entry"
        )
    test_args_start = (
        3
        if is_python_pytest
        else 1
        if is_pytest_script
        else 6
        if is_uv_pytest
        else 3
    )
    if any(
        argument == forbidden or argument.startswith(f"{forbidden}=")
        for forbidden in _FORBIDDEN_TEST_SELECTION_ARGS
        for argument in argv[test_args_start:]
    ):
        raise TestExecutionEvidenceError(
            "test receipt argv contains an unapproved test-selection override"
        )
    placeholder = "{junit}" if require_junit_placeholder else ""
    if is_node_vitest:
        junit_args = [argument for argument in argv if argument.startswith("--outputFile=")]
        if "--reporter=junit" not in argv:
            raise TestExecutionEvidenceError("frontend suite argv must select the JUnit reporter")
        _approved_frontend_arguments(argv[3:])
    else:
        junit_args = [argument for argument in argv if argument.startswith("--junitxml=")]
        _approved_pytest_selectors(
            name=name,
            arguments=argv[test_args_start:],
        )
    if len(junit_args) != 1:
        raise TestExecutionEvidenceError("test receipt argv must bind exactly one JUnit output")
    junit_value = junit_args[0].split("=", 1)[1]
    if require_junit_placeholder:
        if junit_value != placeholder:
            raise TestExecutionEvidenceError(
                "test suite argv must bind the approved {junit} output"
            )
    elif not junit_value.endswith(".junit.xml.tmp"):
        raise TestExecutionEvidenceError(
            "test receipt argv does not bind the runner-owned JUnit target"
        )
    return (
        str(cwd_runtime),
        cwd_relative,
        str(runner_kind),
        executable_path,
        executable_digest,
        entry_path,
        entry_digest,
    )


def validate_execution_plan(
    *,
    name: str,
    argv: tuple[str, ...],
    cwd: Path,
    runtime_roots: Mapping[str, Path],
) -> tuple[
    dict[str, str],
    dict[str, object],
    str,
    dict[str, object] | None,
]:
    """Bind an operator command to its suite's approved runner and repository."""

    suite_name = validate_suite_name(name)
    planned_argv = validate_argv(argv, require_junit_placeholder=True)
    if set(runtime_roots) != set(RUNTIME_NAMES):
        raise TestExecutionEvidenceError("test runtime roots are invalid")
    cwd_realpath = Path(cwd).expanduser().resolve()
    runtime_name = _SUITE_RUNTIME[suite_name]
    runtime_root = Path(runtime_roots[runtime_name]).expanduser().resolve()
    try:
        relative = cwd_realpath.relative_to(runtime_root)
    except ValueError as exc:
        raise TestExecutionEvidenceError("test suite cwd is outside its approved runtime") from exc
    relative_text = "." if not relative.parts else relative.as_posix()
    cwd_document = {
        "realpath": str(cwd_realpath),
        "relative": relative_text,
        "runtime": runtime_name,
    }
    executable_path = Path(planned_argv[0]).expanduser()
    if not executable_path.is_absolute():
        raise TestExecutionEvidenceError("test suite executable must be an explicit absolute path")
    executable_document = executable_evidence(executable_path)
    runner_kind = "node_vitest" if suite_name == "frontend" else "python"
    suite_entry_document: dict[str, object] | None = None
    if suite_name == "frontend":
        if len(planned_argv) < 2 or not Path(planned_argv[1]).is_absolute():
            raise TestExecutionEvidenceError(
                "frontend suite requires an explicit absolute Vitest entry"
            )
        suite_entry_document = _suite_entry_evidence(Path(planned_argv[1]))
    _validate_execution_policy(
        name=suite_name,
        argv=planned_argv,
        cwd=cwd_document,
        executable=executable_document,
        runner_kind=runner_kind,
        suite_entry=suite_entry_document,
        require_junit_placeholder=True,
    )
    return (
        cwd_document,
        executable_document,
        runner_kind,
        suite_entry_document,
    )


def _strict_json(content: bytes) -> object:
    def _without_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TestExecutionEvidenceError("test receipt contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_without_duplicates,
        )
    except TestExecutionEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TestExecutionEvidenceError("test receipt must be valid UTF-8 JSON") from exc


def _exact_mapping(
    value: object,
    *,
    keys: frozenset[str],
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TestExecutionEvidenceError(f"test receipt field {field} is invalid")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TestExecutionEvidenceError(f"test receipt field {field} is invalid")
    return value


def _utc_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise TestExecutionEvidenceError(f"test receipt field {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TestExecutionEvidenceError(f"test receipt field {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TestExecutionEvidenceError(f"test receipt field {field} is invalid")
    return parsed


def _read_owned_file(
    path: Path,
    *,
    maximum_bytes: int,
    allow_empty: bool,
    field: str,
) -> bytes:
    target = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = -1
    try:
        if os.name == "nt":
            fd = os.open(target, flags)
        else:
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            directory_fd = os.open(target.anchor, directory_flags)
            for component in target.parts[1:-1]:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            fd = os.open(target.name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise TestExecutionEvidenceError(
            f"test receipt {field} must be a safe regular file"
        ) from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())
            or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600)
        ):
            raise TestExecutionEvidenceError(
                f"test receipt {field} must be an owner-only, single-link regular file"
            )
        if info.st_size > maximum_bytes or (not allow_empty and info.st_size < 1):
            raise TestExecutionEvidenceError(
                f"test receipt {field} must be a bounded nonempty file"
            )
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > maximum_bytes or (not allow_empty and not content):
            raise TestExecutionEvidenceError(f"test receipt {field} is empty or oversized")
        after = os.fstat(fd)
        if (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise TestExecutionEvidenceError(
                f"test receipt {field} changed while it was being read"
            )
        return content
    finally:
        os.close(fd)


def read_owner_only_file(
    path: Path,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    """Read through no-follow directory FDs and require one exact 0600 inode."""

    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes < 1:
        raise TestExecutionEvidenceError("evidence file size bound is invalid")
    return _read_owned_file(
        path,
        maximum_bytes=maximum_bytes,
        allow_empty=allow_empty,
        field="evidence file",
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_junit_counts(content: bytes) -> TestCounts:
    """Derive test counts from testcase outcomes in bounded, DTD-free XML."""

    if not content or len(content) > _MAX_JUNIT_BYTES:
        raise TestExecutionEvidenceError("test JUnit XML is empty or oversized")
    try:
        xml_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TestExecutionEvidenceError("test JUnit XML must be UTF-8") from exc
    if "\x00" in xml_text:
        raise TestExecutionEvidenceError("test JUnit XML must be UTF-8")
    encoding_match = _XML_ENCODING_RE.search(xml_text[:512])
    if encoding_match is not None and encoding_match.group(2).lower() not in {
        "utf-8",
        "utf8",
    }:
        raise TestExecutionEvidenceError("test JUnit XML must be UTF-8")
    if _FORBIDDEN_XML_DECLARATION_RE.search(xml_text):
        raise TestExecutionEvidenceError("test JUnit XML must not contain a DTD or entity")
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        raise TestExecutionEvidenceError("test JUnit XML is malformed") from exc
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise TestExecutionEvidenceError("test JUnit XML root is invalid")

    passed = 0
    failures = 0
    errors = 0
    skipped = 0
    testcases = [element for element in root.iter() if _local_name(element.tag) == "testcase"]
    for testcase in testcases:
        outcomes = [
            _local_name(child.tag)
            for child in testcase
            if _local_name(child.tag) in {"failure", "error", "skipped"}
        ]
        if len(outcomes) > 1:
            raise TestExecutionEvidenceError("test JUnit testcase has conflicting outcomes")
        if "failure" in outcomes:
            failures += 1
        elif "error" in outcomes:
            errors += 1
        elif "skipped" in outcomes:
            skipped += 1
        else:
            passed += 1
        declared_outcomes = {
            "errors": int("error" in outcomes),
            "failures": int("failure" in outcomes),
            "skipped": int("skipped" in outcomes),
        }
        for field, expected_value in declared_outcomes.items():
            value = testcase.get(field)
            if value is None:
                continue
            if (
                not value.isascii()
                or not value.isdigit()
                or int(value) != expected_value
            ):
                raise TestExecutionEvidenceError(
                    "test JUnit testcase declared outcomes do not match its children"
                )
    counts = TestCounts(
        passed=passed,
        failed=failures + errors,
        skipped=skipped,
    )
    if counts.total < 1:
        raise TestExecutionEvidenceError("test JUnit XML contains no testcases")

    containers = [root]
    containers.extend(
        element
        for element in root.iter()
        if element is not root
        and _local_name(element.tag) == "testsuite"
    )
    for container in containers:
        descendants = [
            element for element in container.iter() if _local_name(element.tag) == "testcase"
        ]
        declared: dict[str, int] = {}
        for field in ("tests", "failures", "errors", "skipped"):
            value = container.get(field)
            if value is None:
                declared[field] = 0
                continue
            if not value.isascii() or not value.isdigit():
                raise TestExecutionEvidenceError(
                    "test JUnit XML contains an invalid declared count"
                )
            declared[field] = int(value)
        descendant_failures = 0
        descendant_errors = 0
        descendant_skipped = 0
        for testcase in descendants:
            child_names = {_local_name(child.tag) for child in testcase}
            descendant_failures += int("failure" in child_names)
            descendant_errors += int("error" in child_names)
            descendant_skipped += int("skipped" in child_names)
        expected = {
            "errors": descendant_errors,
            "failures": descendant_failures,
            "skipped": descendant_skipped,
            "tests": len(descendants),
        }
        for field, expected_value in expected.items():
            if container.get(field) is not None and declared[field] != expected_value:
                raise TestExecutionEvidenceError(
                    "test JUnit XML declared counts do not match testcase outcomes"
                )
    return counts


def _artifact_reference(
    value: object,
    *,
    receipt_directory: Path,
    suite_name: str,
    kind: str,
) -> tuple[Path, bytes]:
    reference = _exact_mapping(
        value,
        keys=frozenset({"path", "sha256", "size_bytes"}),
        field=kind,
    )
    digest = reference["sha256"]
    size = _nonnegative_int(reference["size_bytes"], field=f"{kind}.size_bytes")
    if not isinstance(digest, str) or _HEX_DIGEST_RE.fullmatch(digest) is None:
        raise TestExecutionEvidenceError(f"test receipt field {kind}.sha256 is invalid")
    suffix = "log" if kind == "output" else "xml"
    expected_name = f"test-{suite_name.replace('_', '-')}-{kind}-{digest}.{suffix}"
    if reference["path"] != expected_name:
        raise TestExecutionEvidenceError(f"test receipt {kind} is not content-addressed")
    path = receipt_directory / expected_name
    content = _read_owned_file(
        path,
        maximum_bytes=_MAX_OUTPUT_BYTES if kind == "output" else _MAX_JUNIT_BYTES,
        allow_empty=kind == "output",
        field=kind,
    )
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        raise TestExecutionEvidenceError(f"test receipt {kind} digest or size mismatches")
    return path, content


def _runtime_document(value: object) -> dict[str, dict[str, str]]:
    runtime = _exact_mapping(
        value,
        keys=frozenset(RUNTIME_NAMES),
        field="runtime",
    )
    result: dict[str, dict[str, str]] = {}
    for name in RUNTIME_NAMES:
        item = _exact_mapping(
            runtime[name],
            keys=frozenset({"commit", "digest"}),
            field=f"runtime.{name}",
        )
        commit = item["commit"]
        digest = item["digest"]
        if (
            not isinstance(commit, str)
            or _HEX_COMMIT_RE.fullmatch(commit) is None
            or not isinstance(digest, str)
            or _HEX_DIGEST_RE.fullmatch(digest) is None
            or digest != runtime_digest_from_commit(name, commit)
        ):
            raise TestExecutionEvidenceError(f"test receipt runtime.{name} is inconsistent")
        result[name] = {"commit": commit, "digest": digest}
    return result


def validate_test_execution_receipt(
    path: Path,
    *,
    expected_name: str | None = None,
    expected_runtime: Mapping[str, Mapping[str, str]] | None = None,
    expected_runtime_roots: Mapping[str, Path] | None = None,
) -> ValidatedTestExecution:
    """Reopen and recompute one complete test execution evidence bundle."""

    receipt_path = Path(path).expanduser()
    content = _read_owned_file(
        receipt_path,
        maximum_bytes=_MAX_RECEIPT_BYTES,
        allow_empty=False,
        field="execution receipt",
    )
    raw_receipt = _strict_json(content)
    if (
        not isinstance(raw_receipt, Mapping)
        or raw_receipt.get("contract") != TEST_EXECUTION_RECEIPT_CONTRACT
    ):
        raise TestExecutionEvidenceError(
            "test receipt contract version is invalid; v1 lacks required runner identity"
        )
    receipt = _exact_mapping(
        raw_receipt,
        keys=frozenset(
            {
                "argv",
                "completed_at",
                "contract",
                "cwd",
                "executable",
                "exit_code",
                "junit",
                "name",
                "output",
                "runtime",
                "runner_kind",
                "started_at",
                "suite_entry",
                "summary",
            }
        ),
        field="root",
    )
    name = validate_suite_name(receipt["name"])
    if expected_name is not None and name != expected_name:
        raise TestExecutionEvidenceError("test receipt suite identity mismatches")
    expected_receipt_name = (
        f"test-{name.replace('_', '-')}-receipt-{hashlib.sha256(content).hexdigest()}.json"
    )
    if receipt_path.name != expected_receipt_name:
        raise TestExecutionEvidenceError("test execution receipt is not content-addressed")

    argv = validate_argv(receipt["argv"], require_junit_placeholder=False)
    exit_code = _nonnegative_int(receipt["exit_code"], field="exit_code")
    if exit_code != 0:
        raise TestExecutionEvidenceError("test receipt exit code is nonzero")
    started_at = _utc_timestamp(receipt["started_at"], field="started_at")
    completed_at = _utc_timestamp(receipt["completed_at"], field="completed_at")
    if completed_at < started_at:
        raise TestExecutionEvidenceError("test receipt timestamps are invalid")
    now = datetime.now(UTC)
    if (
        started_at < now - _MAX_RECEIPT_AGE
        or completed_at < now - _MAX_RECEIPT_AGE
        or started_at > now + _MAX_FUTURE_SKEW
        or completed_at > now + _MAX_FUTURE_SKEW
        or completed_at - started_at > _MAX_RECEIPT_AGE
    ):
        raise TestExecutionEvidenceError("test receipt is outside the approved freshness window")

    (
        cwd_runtime,
        cwd_relative,
        runner_kind,
        executable_path,
        executable_sha256,
        suite_entry_path,
        suite_entry_sha256,
    ) = _validate_execution_policy(
        name=name,
        argv=argv,
        cwd=receipt["cwd"],
        executable=receipt["executable"],
        runner_kind=receipt["runner_kind"],
        suite_entry=receipt["suite_entry"],
        require_junit_placeholder=False,
    )

    runtime = _runtime_document(receipt["runtime"])
    if expected_runtime is not None:
        if set(expected_runtime) != set(RUNTIME_NAMES):
            raise TestExecutionEvidenceError("expected test runtime is invalid")
        for logical_name in RUNTIME_NAMES:
            expected = expected_runtime[logical_name]
            if set(expected) != {"commit", "digest"} or runtime[logical_name] != dict(expected):
                raise TestExecutionEvidenceError(
                    "test receipt runtime does not match current clean runtimes"
                )
    if expected_runtime_roots is not None:
        if set(expected_runtime_roots) != set(RUNTIME_NAMES):
            raise TestExecutionEvidenceError("expected test runtime roots are invalid")
        expected_cwd = (
            Path(expected_runtime_roots[cwd_runtime]).expanduser().resolve() / cwd_relative
        ).resolve()
        actual_cwd = Path(receipt["cwd"]["realpath"])  # type: ignore[index]
        if expected_cwd != actual_cwd or not actual_cwd.is_dir():
            raise TestExecutionEvidenceError(
                "test receipt cwd does not match current clean runtimes"
            )

    output_path, output_content = _artifact_reference(
        receipt["output"],
        receipt_directory=receipt_path.parent,
        suite_name=name,
        kind="output",
    )
    junit_path, junit_content = _artifact_reference(
        receipt["junit"],
        receipt_directory=receipt_path.parent,
        suite_name=name,
        kind="junit",
    )
    counts = parse_junit_counts(junit_content)
    summary = _exact_mapping(
        receipt["summary"],
        keys=frozenset({"failed", "passed", "skipped", "total"}),
        field="summary",
    )
    declared = TestCounts(
        passed=_nonnegative_int(summary["passed"], field="summary.passed"),
        failed=_nonnegative_int(summary["failed"], field="summary.failed"),
        skipped=_nonnegative_int(summary["skipped"], field="summary.skipped"),
    )
    total = _nonnegative_int(summary["total"], field="summary.total")
    if declared != counts or total != counts.total:
        raise TestExecutionEvidenceError(
            "test receipt counts do not match recomputed JUnit outcomes"
        )
    if counts.passed < 1 or counts.failed != 0:
        raise TestExecutionEvidenceError("test receipt does not prove a passing suite")

    return ValidatedTestExecution(
        name=name,
        argv=argv,
        counts=counts,
        started_at=started_at,
        completed_at=completed_at,
        runtime=runtime,
        cwd_runtime=cwd_runtime,
        cwd_relative=cwd_relative,
        runner_kind=runner_kind,
        executable_path=executable_path,
        executable_sha256=executable_sha256,
        suite_entry_path=suite_entry_path,
        suite_entry_sha256=suite_entry_sha256,
        receipt_path=receipt_path,
        receipt_content=content,
        output_path=output_path,
        output_content=output_content,
        junit_path=junit_path,
        junit_content=junit_content,
    )


__all__ = [
    "REQUIRED_TEST_SUITES",
    "RUNTIME_NAMES",
    "TEST_EXECUTION_RECEIPT_CONTRACT",
    "TestCounts",
    "TestExecutionEvidenceError",
    "ValidatedTestExecution",
    "executable_evidence",
    "parse_junit_counts",
    "read_owner_only_file",
    "runtime_digest_from_commit",
    "validate_argv",
    "validate_execution_plan",
    "validate_suite_name",
    "validate_test_execution_receipt",
]
