"""Safe operator runner and builders for Agent v0.2 release evidence.

``run-suite`` executes exact, non-shell test argv and seals recomputable raw
output/JUnit receipts.  The builders consume only those receipts; they never
execute real flows.  Final evidence projects the five public flow receipts
from one exact, append-only PostgreSQL candidate-evidence set.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import psycopg
import typer

from quant_system.config.settings import Settings, load_settings
from quant_system.hermes.candidate_evidence import (
    CandidateEvidenceError,
    candidate_preflight_evidence_observation,
)
from quant_system.hermes.candidate_evidence_v3 import (
    candidate_evidence_runtime_security_is_ready,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    git_runtime_digest,
    release_evidence_observation,
)
from quant_system.hermes.test_execution_evidence import (
    TEST_EXECUTION_RECEIPT_CONTRACT,
    TestExecutionEvidenceError,
    ValidatedTestExecution,
    parse_junit_counts,
    validate_argv,
    validate_execution_plan,
    validate_suite_name,
    validate_test_execution_receipt,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

_ARTIFACT_CONTRACT = "agent-v0.2-release-artifact/v2"
_PREFLIGHT_CONTRACT = "agent-v0.2-candidate-evidence/v2"
_RELEASE_CONTRACT = "agent-v0.2-release-evidence/v4"
_FACTS_CONTRACT = "agent-v0.2-candidate-evidence-facts/v1"
_RUNTIME_NAMES = ("platform", "hqa", "hermes")
_TEST_NAMES = ("platform", "hqa", "hermes_focused", "frontend")
_CANDIDATE_FLOW_NAMES = (
    "web_chat_multi_turn",
    "hermes_restart_recovery",
    "exact_message_fork",
    "options_vertical_live_futu_ro",
    "paper_factor_gate_1_2_3_via_hermes",
)
_FLOW_NAMES = _CANDIDATE_FLOW_NAMES + (
    "hermes_command_approval_exact_cas",
    "hermes_run_stop_recovery",
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_FORK_POINT_RE = re.compile(r"^message:[1-9][0-9]*$")
_SAFE_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,199}\.(?:json|log|xml)$")
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_JUNIT_BYTES = 8 * 1024 * 1024
_MAX_TEST_OUTPUT_BYTES = 4 * 1024 * 1024


class EvidenceBuildError(RuntimeError):
    """Evidence could not be generated without weakening its bindings."""


class EvidenceBuildConflict(EvidenceBuildError):
    """A destination already contains different immutable evidence."""


@dataclass(frozen=True)
class EvidenceBuildResult:
    """The sealed manifest identity returned by either builder."""

    manifest_path: Path
    digest: str
    idempotent_replay: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "idempotent_replay": self.idempotent_replay,
            "manifest_path": str(self.manifest_path),
        }


@dataclass(frozen=True)
class TestSuiteRunResult:
    """Public identity and recomputed counts for one sealed suite execution."""

    name: str
    receipt_path: Path
    receipt_sha256: str
    output_path: Path
    output_sha256: str
    junit_path: Path
    junit_sha256: str
    passed: int
    failed: int
    skipped: int
    runtime: Mapping[str, Mapping[str, str]]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "failed": self.failed,
            "junit_path": str(self.junit_path),
            "junit_sha256": self.junit_sha256,
            "name": self.name,
            "output_path": str(self.output_path),
            "output_sha256": self.output_sha256,
            "passed": self.passed,
            "receipt_path": str(self.receipt_path),
            "receipt_sha256": self.receipt_sha256,
            "runtime": {name: dict(value) for name, value in self.runtime.items()},
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class _RuntimeIdentity:
    root: Path
    commit: str
    digest: str


@dataclass(frozen=True)
class _StoredEvidence:
    evidence_set_id: str
    admission_id: str
    admission_digest: str
    preflight_evidence_digest: str
    workspace_id: str
    runtime: Mapping[str, str]
    final_order_snapshot_digest: str
    facts_digest: str
    verified_at: datetime
    facts: Mapping[str, object]


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceBuildError("evidence contains a non-JSON value") from exc


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise EvidenceBuildError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise EvidenceBuildError(f"{field} must be a bounded identifier")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceBuildError(f"{field} must be a nonnegative integer")
    return value


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceBuildError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime, field: str) -> str:
    return _aware_utc(value, field).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvidenceBuildError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str, *, minimum: int = 1) -> list[object]:
    if not isinstance(value, list | tuple) or len(value) < minimum or len(value) > 256:
        raise EvidenceBuildError(f"{field} must be a bounded array")
    return list(value)


def _run_git(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceBuildError("runtime root is not a readable Git checkout") from exc
    if len(completed.stdout) > 1024 * 1024:
        raise EvidenceBuildError("runtime Git observation is oversized")
    return completed.stdout


def _clean_runtime_identity(root: Path, logical_name: str) -> _RuntimeIdentity:
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise EvidenceBuildError(f"{logical_name} runtime root is unavailable")
    commit_before = _run_git(
        path,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
    ).strip()
    if _COMMIT_RE.fullmatch(commit_before.decode("ascii", errors="ignore")) is None:
        raise EvidenceBuildError(f"{logical_name} runtime commit is invalid")
    try:
        digest_before = git_runtime_digest(path, logical_name=logical_name)
        digest_after = git_runtime_digest(path, logical_name=logical_name)
    except ReleaseRuntimeProbeError as exc:
        raise EvidenceBuildError(str(exc)) from exc
    commit_after = _run_git(
        path,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
    ).strip()
    if commit_before != commit_after or digest_before != digest_after or not commit_after:
        raise EvidenceBuildError("runtime identity changed during evidence capture")
    return _RuntimeIdentity(
        root=path,
        commit=commit_after.decode("ascii"),
        digest=digest_after,
    )


def _runtime_identities(
    runtime_roots: Mapping[str, Path],
) -> dict[str, _RuntimeIdentity]:
    if set(runtime_roots) != set(_RUNTIME_NAMES):
        raise EvidenceBuildError("runtime roots must identify exactly three repositories")
    return {name: _clean_runtime_identity(runtime_roots[name], name) for name in _RUNTIME_NAMES}


def _require_runtime_unchanged(runtime: Mapping[str, _RuntimeIdentity]) -> None:
    for name in _RUNTIME_NAMES:
        observed = _clean_runtime_identity(runtime[name].root, name)
        if (
            observed.root != runtime[name].root
            or observed.commit != runtime[name].commit
            or observed.digest != runtime[name].digest
        ):
            raise EvidenceBuildError("runtime identity changed during evidence generation")


def _open_directory_no_follow(path: Path, *, field: str) -> int:
    """Open one directory through no-follow dirfds for every path component."""

    target = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_fd = -1
    try:
        if os.name == "nt":
            directory_fd = os.open(target, flags)
        else:
            directory_fd = os.open(target.anchor, flags)
            for component in target.parts[1:]:
                next_fd = os.open(component, flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise EvidenceBuildError(f"{field} is not a directory")
        return directory_fd
    except EvidenceBuildError:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise
    except OSError as exc:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise EvidenceBuildError(f"{field} is unavailable or uses a symlink") from exc


def _safe_output_directory(
    output_dir: Path,
    runtime: Mapping[str, _RuntimeIdentity],
) -> Path:
    absolute = Path(os.path.abspath(os.fspath(Path(output_dir).expanduser())))
    directory_fd = -1
    try:
        directory_fd = _open_directory_no_follow(
            absolute,
            field="evidence output directory",
        )
        info = os.fstat(directory_fd)
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise EvidenceBuildError("evidence output directory must be operator-owned")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o022:
            raise EvidenceBuildError(
                "evidence output directory must not be group/world writable"
            )
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
    resolved = absolute.resolve(strict=True)
    for identity in runtime.values():
        try:
            resolved.relative_to(identity.root)
        except ValueError:
            continue
        raise EvidenceBuildError(
            "evidence output directory must be outside all runtime repositories"
        )
    return resolved


def _read_existing(dir_fd: int, name: str) -> bytes | None:
    maximum_bytes = _MAX_JUNIT_BYTES if name.endswith(".xml") else _MAX_FILE_BYTES
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EvidenceBuildConflict(f"evidence target {name} is not a safe regular file") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceBuildConflict(f"evidence target {name} is not a safe regular file")
        if info.st_nlink != 1:
            raise EvidenceBuildConflict(f"evidence target {name} must not be hard-linked")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise EvidenceBuildConflict(f"evidence target {name} is not operator-owned")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600:
            raise EvidenceBuildConflict(f"evidence target {name} must have mode 0600")
        if info.st_size > maximum_bytes:
            raise EvidenceBuildConflict(f"evidence target {name} has an invalid size")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > maximum_bytes:
            raise EvidenceBuildConflict(f"evidence target {name} has an invalid size")
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
            raise EvidenceBuildConflict(f"evidence target {name} changed while read")
        return content
    finally:
        os.close(fd)


def _write_once(dir_fd: int, name: str, content: bytes) -> bool:
    maximum_bytes = _MAX_JUNIT_BYTES if name.endswith(".xml") else _MAX_FILE_BYTES
    if _SAFE_FILE_RE.fullmatch(name) is None or len(content) > maximum_bytes:
        raise EvidenceBuildError("evidence output file is invalid")
    existing = _read_existing(dir_fd, name)
    if existing is not None:
        if existing == content:
            return False
        raise EvidenceBuildConflict(
            f"evidence target {name} already contains different immutable evidence"
        )

    temporary = f".{name}.{uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = -1
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=dir_fd)
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fchmod(fd, 0o600)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            raced = _read_existing(dir_fd, name)
            if raced == content:
                return False
            raise EvidenceBuildConflict(
                f"evidence target {name} already contains different immutable evidence"
            ) from None
        os.fsync(dir_fd)
        return True
    except EvidenceBuildError:
        raise
    except OSError as exc:
        raise EvidenceBuildError(f"could not atomically seal evidence target {name}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)


def _seal_bundle(
    *,
    output_dir: Path,
    artifacts: Mapping[str, bytes],
    manifest_name: str,
    manifest: bytes,
) -> tuple[Path, bool]:
    dir_fd = _open_directory_no_follow(
        output_dir,
        field="evidence output directory",
    )
    created = False
    try:
        for name in sorted(artifacts):
            created = _write_once(dir_fd, name, artifacts[name]) or created
        created = _write_once(dir_fd, manifest_name, manifest) or created
    finally:
        os.close(dir_fd)
    return output_dir / manifest_name, not created


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        with suppress(OSError, ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        with suppress(OSError):
            process.kill()
    if process.poll() is None:
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)


def _execute_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> tuple[int, bytes]:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 86_400
    ):
        raise EvidenceBuildError("test execution timeout is invalid")
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(env),
            shell=False,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise EvidenceBuildError("test suite could not be executed") from exc
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    chunks: list[bytes] = []
    size = 0
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise EvidenceBuildError("test suite execution timed out")
            for key, _events in selector.select(timeout=min(0.25, remaining)):
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                size += len(chunk)
                if size > _MAX_TEST_OUTPUT_BYTES:
                    _terminate_process(process)
                    raise EvidenceBuildError("test suite output is oversized")
                chunks.append(chunk)
        try:
            exit_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _terminate_process(process)
            raise EvidenceBuildError("test suite execution timed out") from None
        _terminate_process(process)
    except BaseException:
        _terminate_process(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
    return exit_code, b"".join(chunks)


def _sanitized_test_environment(directory: Path) -> dict[str, str]:
    path_parts = [os.defpath]
    for executable in ("node",):
        observed = shutil.which(executable)
        if observed is not None:
            path_parts.insert(0, str(Path(observed).resolve().parent))
    return {
        "CI": "1",
        "HOME": str(directory),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.pathsep.join(path_parts),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(directory),
        "TZ": "UTC",
    }


def _read_temporary_junit(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise EvidenceBuildError("test suite did not produce safe JUnit XML") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())
            or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600)
            or not 0 < info.st_size <= _MAX_JUNIT_BYTES
        ):
            raise EvidenceBuildError("test suite did not produce safe JUnit XML")
        chunks: list[bytes] = []
        remaining = _MAX_JUNIT_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if not content or len(content) > _MAX_JUNIT_BYTES:
            raise EvidenceBuildError("test suite did not produce bounded JUnit XML")
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
            raise EvidenceBuildError("test suite JUnit XML changed while read")
        return content
    finally:
        os.close(fd)


def run_test_suite(
    *,
    name: str,
    argv: Sequence[str],
    output_dir: Path,
    runtime_roots: Mapping[str, Path],
    cwd: Path,
    timeout_seconds: int = 3600,
) -> TestSuiteRunResult:
    """Execute one exact argv and seal raw output, JUnit, and its receipt."""

    try:
        suite_name = validate_suite_name(name)
        argv_template = validate_argv(argv, require_junit_placeholder=True)
    except TestExecutionEvidenceError as exc:
        raise EvidenceBuildError(str(exc)) from exc
    runtime = _runtime_identities(runtime_roots)
    directory = _safe_output_directory(output_dir, runtime)
    working_directory = Path(cwd).expanduser().resolve()
    if not working_directory.is_dir():
        raise EvidenceBuildError("test suite working directory is unavailable")
    try:
        cwd_document, executable_document = validate_execution_plan(
            name=suite_name,
            argv=argv_template,
            cwd=working_directory,
            runtime_roots={name: runtime[name].root for name in _RUNTIME_NAMES},
        )
    except TestExecutionEvidenceError as exc:
        raise EvidenceBuildError(str(exc)) from exc

    temporary_name = f".test-{suite_name}-{uuid4().hex}.junit.xml.tmp"
    temporary_path = directory / temporary_name
    executed_argv = tuple(
        argument.replace("{junit}", str(temporary_path)) for argument in argv_template
    )
    try:
        executed_argv = validate_argv(
            executed_argv,
            require_junit_placeholder=False,
        )
    except TestExecutionEvidenceError as exc:
        raise EvidenceBuildError(str(exc)) from exc
    temporary_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_fd = _open_directory_no_follow(
        directory,
        field="evidence output directory",
    )
    try:
        try:
            temporary_fd = os.open(
                temporary_name,
                temporary_flags,
                0o600,
                dir_fd=directory_fd,
            )
        except OSError as exc:
            raise EvidenceBuildError("could not reserve the test JUnit target") from exc
        os.close(temporary_fd)

        started_at = datetime.now(UTC)
        try:
            exit_code, output = _execute_bounded(
                executed_argv,
                cwd=working_directory,
                env=_sanitized_test_environment(directory),
                timeout_seconds=timeout_seconds,
            )
            completed_at = datetime.now(UTC)
            _require_runtime_unchanged(runtime)
            if exit_code != 0:
                raise EvidenceBuildError("test suite exit code is nonzero")
            junit = _read_temporary_junit(directory_fd, temporary_name)
            try:
                counts = parse_junit_counts(junit)
            except TestExecutionEvidenceError as exc:
                raise EvidenceBuildError(str(exc)) from exc
            if counts.failed != 0 or counts.passed < 1:
                raise EvidenceBuildError("test suite JUnit does not prove a passing suite")
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)

    output_digest = hashlib.sha256(output).hexdigest()
    junit_digest = hashlib.sha256(junit).hexdigest()
    stem = f"test-{suite_name.replace('_', '-')}"
    output_name = f"{stem}-output-{output_digest}.log"
    junit_name = f"{stem}-junit-{junit_digest}.xml"
    runtime_document = _runtime_document(runtime)
    receipt = {
        "argv": list(executed_argv),
        "completed_at": _timestamp(completed_at, "completed_at"),
        "contract": TEST_EXECUTION_RECEIPT_CONTRACT,
        "cwd": cwd_document,
        "executable": executable_document,
        "exit_code": exit_code,
        "junit": {
            "path": junit_name,
            "sha256": junit_digest,
            "size_bytes": len(junit),
        },
        "name": suite_name,
        "output": {
            "path": output_name,
            "sha256": output_digest,
            "size_bytes": len(output),
        },
        "runtime": runtime_document,
        "started_at": _timestamp(started_at, "started_at"),
        "summary": {
            "failed": counts.failed,
            "passed": counts.passed,
            "skipped": counts.skipped,
            "total": counts.total,
        },
    }
    receipt_content = _canonical_bytes(receipt)
    receipt_digest = hashlib.sha256(receipt_content).hexdigest()
    receipt_name = f"{stem}-receipt-{receipt_digest}.json"
    receipt_path, _replay = _seal_bundle(
        output_dir=directory,
        artifacts={
            output_name: output,
            junit_name: junit,
        },
        manifest_name=receipt_name,
        manifest=receipt_content,
    )
    _require_runtime_unchanged(runtime)
    try:
        validated = validate_test_execution_receipt(
            receipt_path,
            expected_name=suite_name,
            expected_runtime=runtime_document,
            expected_runtime_roots={name: runtime[name].root for name in _RUNTIME_NAMES},
        )
    except TestExecutionEvidenceError as exc:
        raise EvidenceBuildError("generated test receipt failed self-validation") from exc
    return TestSuiteRunResult(
        name=suite_name,
        receipt_path=receipt_path,
        receipt_sha256=receipt_digest,
        output_path=validated.output_path,
        output_sha256=output_digest,
        junit_path=validated.junit_path,
        junit_sha256=junit_digest,
        passed=counts.passed,
        failed=counts.failed,
        skipped=counts.skipped,
        runtime=runtime_document,
    )


def _runtime_document(
    runtime: Mapping[str, _RuntimeIdentity],
) -> dict[str, dict[str, str]]:
    return {
        name: {
            "commit": runtime[name].commit,
            "digest": runtime[name].digest,
        }
        for name in _RUNTIME_NAMES
    }


def _validated_test_receipts(
    receipt_paths: Sequence[Path],
    runtime: Mapping[str, _RuntimeIdentity],
) -> tuple[ValidatedTestExecution, ...]:
    if not isinstance(receipt_paths, list | tuple) or len(receipt_paths) != len(_TEST_NAMES):
        raise EvidenceBuildError("exactly four test execution receipts are required")
    expected_runtime = _runtime_document(runtime)
    by_name: dict[str, ValidatedTestExecution] = {}
    used_paths: set[Path] = set()
    for receipt_path in receipt_paths:
        path = Path(receipt_path).expanduser()
        absolute = Path(os.path.abspath(os.fspath(path)))
        if absolute in used_paths:
            raise EvidenceBuildError("test execution receipt path is duplicated")
        used_paths.add(absolute)
        try:
            receipt = validate_test_execution_receipt(
                path,
                expected_runtime=expected_runtime,
                expected_runtime_roots={name: runtime[name].root for name in _RUNTIME_NAMES},
            )
        except TestExecutionEvidenceError as exc:
            raise EvidenceBuildError(str(exc)) from exc
        if receipt.name in by_name:
            raise EvidenceBuildError("test execution receipt identity is duplicated")
        by_name[receipt.name] = receipt
    if set(by_name) != set(_TEST_NAMES):
        raise EvidenceBuildError("the four required test execution receipts are not exact")
    return tuple(by_name[name] for name in _TEST_NAMES)


def _test_documents(
    tests: Sequence[ValidatedTestExecution],
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    artifacts: dict[str, bytes] = {}
    suites: list[dict[str, object]] = []
    for test in tests:
        receipt_content = test.receipt_content
        output_content = test.output_content
        junit_content = test.junit_content
        receipt_name = test.receipt_path.name
        output_name = test.output_path.name
        junit_name = test.junit_path.name
        for filename, content in (
            (receipt_name, receipt_content),
            (output_name, output_content),
            (junit_name, junit_content),
        ):
            if filename in artifacts and artifacts[filename] != content:
                raise EvidenceBuildError("test evidence filename collision")
            artifacts[filename] = content
        suites.append(
            {
                "failed": test.counts.failed,
                "name": test.name,
                "passed": test.counts.passed,
                "receipt": {
                    "path": receipt_name,
                    "sha256": hashlib.sha256(receipt_content).hexdigest(),
                },
                "skipped": test.counts.skipped,
            }
        )
    return artifacts, suites


def _candidate_preflight_document(
    *,
    runtime: Mapping[str, _RuntimeIdentity],
    suites: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "contract": _PREFLIGHT_CONTRACT,
        "runtime": _runtime_document(runtime),
        "safety": {
            "kill_switch": True,
            "live_trading_enabled": False,
            "orders_created": 0,
        },
        "tests": {"passed": True, "suites": [dict(suite) for suite in suites]},
    }


def build_candidate_preflight(
    *,
    output_dir: Path,
    runtime_roots: Mapping[str, Path],
    test_receipts: Sequence[Path],
) -> EvidenceBuildResult:
    """Seal a test-only candidate preflight from exact execution receipts."""

    runtime = _runtime_identities(runtime_roots)
    directory = _safe_output_directory(output_dir, runtime)
    completed_tests = _validated_test_receipts(test_receipts, runtime)
    artifacts, suites = _test_documents(completed_tests)
    document = _candidate_preflight_document(runtime=runtime, suites=suites)
    manifest = _canonical_bytes(document)
    _require_runtime_unchanged(runtime)
    path, replay = _seal_bundle(
        output_dir=directory,
        artifacts=artifacts,
        manifest_name="agent-v0.2-candidate-evidence.json",
        manifest=manifest,
    )
    _require_runtime_unchanged(runtime)
    try:
        observation = candidate_preflight_evidence_observation(path)
    except CandidateEvidenceError as exc:
        raise EvidenceBuildError("generated candidate preflight failed self-validation") from exc
    expected = hashlib.sha256(manifest).hexdigest()
    if observation.digest != expected:
        raise EvidenceBuildError("candidate preflight self-validation digest drifted")
    return EvidenceBuildResult(
        manifest_path=path,
        digest=observation.digest,
        idempotent_replay=replay,
    )


def _stored_evidence(
    settings: Settings,
    *,
    database: Database | None,
    admission_id: str,
    admission_digest: str,
    evidence_set_id: str,
    evidence_set_digest: str,
    runtime_security_probe: Callable[[Settings], bool],
) -> _StoredEvidence:
    admission_id = _identifier(admission_id, "admission_id")
    admission_digest = _digest(admission_digest, "admission_digest")
    evidence_set_id = _identifier(evidence_set_id, "evidence_set_id")
    evidence_set_digest = _digest(evidence_set_digest, "evidence_set_digest")
    if not runtime_security_probe(settings):
        raise EvidenceBuildError("restricted candidate evidence DB role is not ready")
    selected_database = database or get_database(settings)
    if selected_database is None:
        raise EvidenceBuildError("candidate evidence PostgreSQL is unavailable")
    try:
        with selected_database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    evidence.evidence_set_id,
                    evidence.admission_id,
                    evidence.admission_digest,
                    admission.preflight_evidence_digest,
                    evidence.workspace_id,
                    evidence.platform_runtime_digest,
                    evidence.hqa_runtime_digest,
                    evidence.hermes_runtime_digest,
                    evidence.baseline_order_snapshot_digest,
                    evidence.final_order_snapshot_digest,
                    evidence.facts,
                    evidence.facts_digest,
                    encode(
                        sha256(
                            convert_to(evidence.facts::text, 'UTF8')
                        ),
                        'hex'
                    ) AS computed_facts_digest,
                    evidence.verified_at,
                    admission.status,
                    admission.evidence_set_id,
                    admission.evidence_set_digest,
                    admission.final_order_snapshot_digest
                FROM {SCHEMA}.agent_v02_candidate_evidence_sets AS evidence
                JOIN {SCHEMA}.agent_v02_candidate_admissions AS admission
                  ON admission.admission_id = evidence.admission_id
                 AND admission.owner_user_id = evidence.owner_user_id
                 AND admission.workspace_id = evidence.workspace_id
                 AND admission.admission_digest =
                        evidence.admission_digest
                WHERE evidence.owner_user_id = %s
                  AND admission.route = '/hermes'
                  AND (
                        (
                            admission.status = 'open'
                            AND admission.expires_at >
                                clock_timestamp()
                        )
                        OR admission.status = 'accepted'
                  )
                  AND evidence.admission_id = %s
                  AND evidence.admission_digest = %s
                  AND evidence.evidence_set_id = %s
                  AND evidence.facts_digest = %s
                """,
                (
                    ROOT_USER_ID,
                    admission_id,
                    admission_digest,
                    evidence_set_id,
                    evidence_set_digest,
                ),
            ).fetchone()
    except (DatabaseUnavailable, psycopg.Error) as exc:
        raise EvidenceBuildError("candidate evidence PostgreSQL query failed closed") from exc
    if row is None or len(row) != 18:
        raise EvidenceBuildError("exact verified candidate evidence set is unavailable")

    (
        stored_evidence_set_id,
        stored_admission_id,
        stored_admission_digest,
        stored_preflight_evidence_digest,
        workspace_id,
        platform_digest,
        hqa_digest,
        hermes_digest,
        baseline_orders,
        final_orders,
        raw_facts,
        stored_facts_digest,
        computed_facts_digest,
        verified_at,
        admission_status,
        accepted_evidence_set_id,
        accepted_evidence_set_digest,
        accepted_final_orders,
    ) = row
    preflight_evidence_digest = _digest(
        str(stored_preflight_evidence_digest).strip(),
        "preflight_evidence_digest",
    )
    if (
        str(stored_evidence_set_id) != evidence_set_id
        or str(stored_admission_id) != admission_id
        or str(stored_admission_digest).strip() != admission_digest
        or str(stored_facts_digest).strip() != evidence_set_digest
        or str(computed_facts_digest).strip() != evidence_set_digest
    ):
        raise EvidenceBuildError("verified candidate evidence identity is inconsistent")
    baseline = _digest(str(baseline_orders).strip(), "baseline_order_snapshot_digest")
    final = _digest(str(final_orders).strip(), "final_order_snapshot_digest")
    if baseline != final:
        raise EvidenceBuildError("candidate evidence no longer proves zero order drift")
    if admission_status == "accepted":
        if (
            accepted_evidence_set_id != evidence_set_id
            or str(accepted_evidence_set_digest).strip() != evidence_set_digest
            or str(accepted_final_orders).strip() != final
        ):
            raise EvidenceBuildError("accepted candidate evidence binding is inconsistent")
    elif admission_status == "open":
        if any(
            value is not None
            for value in (
                accepted_evidence_set_id,
                accepted_evidence_set_digest,
                accepted_final_orders,
            )
        ):
            raise EvidenceBuildError("open candidate contains a terminal evidence binding")
    else:
        raise EvidenceBuildError("candidate is not open or accepted")
    if not isinstance(verified_at, datetime):
        raise EvidenceBuildError("candidate evidence verification time is unavailable")
    facts = _mapping(raw_facts, "candidate facts")
    return _StoredEvidence(
        evidence_set_id=evidence_set_id,
        admission_id=admission_id,
        admission_digest=admission_digest,
        preflight_evidence_digest=preflight_evidence_digest,
        workspace_id=_identifier(workspace_id, "workspace_id"),
        runtime={
            "platform": _digest(str(platform_digest).strip(), "platform runtime"),
            "hqa": _digest(str(hqa_digest).strip(), "hqa runtime"),
            "hermes": _digest(str(hermes_digest).strip(), "hermes runtime"),
        },
        final_order_snapshot_digest=final,
        facts_digest=evidence_set_digest,
        verified_at=_aware_utc(verified_at, "verified_at"),
        facts=facts,
    )


def _facts_flows(
    stored: _StoredEvidence,
    runtime: Mapping[str, _RuntimeIdentity],
) -> Mapping[str, object]:
    facts = stored.facts
    expected_root = {
        "admission_digest",
        "admission_id",
        "contract",
        "database_schema_fingerprint",
        "final_order_snapshot_digest",
        "flows",
        "runtime",
        "workspace_id",
    }
    if set(facts) != expected_root or facts.get("contract") != _FACTS_CONTRACT:
        raise EvidenceBuildError("candidate facts contract is invalid")
    if (
        facts.get("admission_id") != stored.admission_id
        or facts.get("admission_digest") != stored.admission_digest
        or facts.get("workspace_id") != stored.workspace_id
        or facts.get("final_order_snapshot_digest") != stored.final_order_snapshot_digest
    ):
        raise EvidenceBuildError("candidate facts identity is inconsistent")
    _digest(
        facts.get("database_schema_fingerprint"),
        "candidate facts database_schema_fingerprint",
    )
    facts_runtime = _mapping(facts.get("runtime"), "candidate facts runtime")
    if set(facts_runtime) != set(_RUNTIME_NAMES):
        raise EvidenceBuildError("candidate facts runtime is invalid")
    for name in _RUNTIME_NAMES:
        value = _digest(facts_runtime.get(name), f"candidate facts runtime.{name}")
        if value != stored.runtime[name] or value != runtime[name].digest:
            raise EvidenceBuildError("candidate runtime does not match clean repositories")
    flows = _mapping(facts.get("flows"), "candidate facts flows")
    if set(flows) != set(_CANDIDATE_FLOW_NAMES):
        raise EvidenceBuildError("candidate facts are missing a required flow")
    return flows


def _flow_projection(name: str, source: object) -> dict[str, object]:
    flow = _mapping(source, f"candidate flow {name}")
    route = flow.get("route")
    if route != "/hermes":
        raise EvidenceBuildError(f"candidate flow {name} has the wrong route")
    if name == "web_chat_multi_turn":
        command_ids = [
            _identifier(value, "web command_id")
            for value in _sequence(flow.get("command_ids"), "web command_ids", minimum=2)
        ]
        run_ids = [
            _identifier(value, "web run_id")
            for value in _sequence(flow.get("run_ids"), "web run_ids", minimum=2)
        ]
        user_count = _nonnegative_int(
            flow.get("user_message_count"),
            "user_message_count",
        )
        assistant_count = _nonnegative_int(
            flow.get("assistant_message_count"),
            "assistant_message_count",
        )
        if (
            user_count < 2
            or assistant_count < 2
            or len(set(command_ids)) != len(command_ids)
            or len(set(run_ids)) != len(run_ids)
            or set(command_ids) & set(run_ids)
        ):
            raise EvidenceBuildError("web multi-turn candidate facts are invalid")
        return {
            "assistant_message_count": assistant_count,
            "command_ids": command_ids,
            "route": route,
            "run_ids": run_ids,
            "user_message_count": user_count,
        }
    if name == "hermes_restart_recovery":
        transcript = _digest(
            flow.get("transcript_digest"),
            "restart transcript_digest",
        )
        return {
            "after_transcript_digest": transcript,
            "before_transcript_digest": transcript,
            "route": route,
        }
    if name == "exact_message_fork":
        source = _identifier(
            flow.get("source_platform_session_id"),
            "fork source_platform_session_id",
        )
        child = _identifier(
            flow.get("child_platform_session_id"),
            "fork child_platform_session_id",
        )
        fork_point = _identifier(flow.get("fork_point"), "fork_point")
        if source == child or _FORK_POINT_RE.fullmatch(fork_point) is None:
            raise EvidenceBuildError("exact-message fork candidate facts are invalid")
        return {
            "child_session_id": child,
            "fork_point": fork_point,
            "preserve_source": True,
            "route": route,
            "source_session_id": source,
        }
    if name == "options_vertical_live_futu_ro":
        if flow.get("provider") != "futu":
            raise EvidenceBuildError("options evidence is not from Futu")
        orders_created = _nonnegative_int(
            flow.get("orders_created"),
            "options orders_created",
        )
        if orders_created != 0:
            raise EvidenceBuildError("options evidence created orders")
        return {
            "orders_created": orders_created,
            "provider": "futu",
            "provider_evidence_digest": _digest(
                flow.get("provider_receipt_digest"),
                "provider_receipt_digest",
            ),
            "route": route,
        }
    if name == "hermes_command_approval_exact_cas":
        if (
            flow.get("decision") not in {"allow_once", "deny"}
            or flow.get("choice") not in {"once", "deny"}
            or (
                flow.get("decision") == "allow_once"
                and flow.get("choice") != "once"
            )
            or (
                flow.get("decision") == "deny"
                and flow.get("choice") != "deny"
            )
            or flow.get("waiter_signal_status") != "confirmed"
            or flow.get("run_status") != "succeeded"
        ):
            raise EvidenceBuildError("Hermes approval candidate facts are invalid")
        event_ids = [
            _identifier(value, "approval event_id")
            for value in _sequence(
                flow.get("event_ids"),
                "approval event_ids",
                minimum=4,
            )
        ]
        if len(event_ids) != 4 or len(set(event_ids)) != 4:
            raise EvidenceBuildError("Hermes approval event chain is invalid")
        return {
            "action_digest": _digest(
                flow.get("action_digest"),
                "approval action_digest",
            ),
            "approval_id": _identifier(flow.get("approval_id"), "approval_id"),
            "challenge_id": _identifier(
                flow.get("challenge_id"),
                "challenge_id",
            ),
            "choice": flow["choice"],
            "command_digest": _digest(
                flow.get("command_digest"),
                "approval command_digest",
            ),
            "control_command_id": _identifier(
                flow.get("control_command_id"),
                "approval control_command_id",
            ),
            "decision": flow["decision"],
            "event_ids": event_ids,
            "expected_expires_at": _timestamp_text(
                flow.get("expected_expires_at"),
                "approval expected_expires_at",
            ),
            "platform_command_id": _identifier(
                flow.get("platform_command_id"),
                "approval platform_command_id",
            ),
            "route": route,
            "run_id": _identifier(flow.get("run_id"), "approval run_id"),
            "run_status": "succeeded",
            "waiter_signal_status": "confirmed",
        }
    if name == "hermes_run_stop_recovery":
        if (
            flow.get("status") != "stopped"
            or flow.get("terminal_event") != "run.cancelled"
            or flow.get("idempotent_recovery_proven") is not True
        ):
            raise EvidenceBuildError("Hermes stop candidate facts are invalid")
        return {
            "action_digest": _digest(
                flow.get("action_digest"),
                "stop action_digest",
            ),
            "control_command_id": _identifier(
                flow.get("control_command_id"),
                "stop control_command_id",
            ),
            "idempotent_recovery_proven": True,
            "platform_command_id": _identifier(
                flow.get("platform_command_id"),
                "stop platform_command_id",
            ),
            "post_restart_instance_id": _identifier(
                flow.get("post_restart_instance_id"),
                "stop post_restart_instance_id",
            ),
            "route": route,
            "run_id": _identifier(flow.get("run_id"), "stop run_id"),
            "status": "stopped",
            "stop_requested_event_id": _identifier(
                flow.get("stop_requested_event_id"),
                "stop_requested_event_id",
            ),
            "terminal_event": "run.cancelled",
            "terminal_event_id": _identifier(
                flow.get("terminal_event_id"),
                "stop terminal_event_id",
            ),
        }
    if name != "paper_factor_gate_1_2_3_via_hermes":
        raise EvidenceBuildError("unknown candidate flow")
    if flow.get("provider") != "futu":
        raise EvidenceBuildError("paper evidence is not from Futu")
    gate1 = _identifier(
        flow.get("gate1_confirmation_id"),
        "paper gate1_confirmation_id",
    )
    gate2 = _identifier(
        flow.get("gate2_id"),
        "paper gate2_id",
    )
    gate3 = _identifier(
        flow.get("promotion_id"),
        "paper promotion_id",
    )
    orders_created = _nonnegative_int(
        flow.get("orders_created"),
        "paper orders_created",
    )
    if len({gate1, gate2, gate3}) != 3 or orders_created != 0:
        raise EvidenceBuildError("paper Gate candidate facts are invalid")
    return {
        "candidate_digest": _digest(
            flow.get("candidate_digest"),
            "paper candidate_digest",
        ),
        "candidate_id": _identifier(flow.get("candidate_id"), "paper candidate_id"),
        "final_backtest_receipt_id": _identifier(
            flow.get("final_backtest_receipt_id"),
            "paper final_backtest_receipt_id",
        ),
        "gate1_confirmation_id": gate1,
        "gate2_decision_id": gate2,
        "gate3_promotion_id": gate3,
        "orders_created": orders_created,
        "provider": "futu",
        "reviewed_commit": _reviewed_commit(flow.get("reviewed_commit")),
        "route": route,
    }


def _reviewed_commit(value: object) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise EvidenceBuildError("paper reviewed_commit is invalid")
    return value


def _timestamp_text(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise EvidenceBuildError(f"{field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceBuildError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceBuildError(f"{field} is invalid")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _flow_source(name: str, flows: Mapping[str, object]) -> object:
    if name in _CANDIDATE_FLOW_NAMES:
        return flows[name]
    chat = _mapping(
        flows["web_chat_multi_turn"],
        "candidate flow web_chat_multi_turn",
    )
    nested_name = {
        "hermes_command_approval_exact_cas": "command_approval_exact_cas",
        "hermes_run_stop_recovery": "run_stop_recovery",
    }.get(name)
    if nested_name is None or nested_name not in chat:
        raise EvidenceBuildError("candidate control flow evidence is missing")
    return chat[nested_name]


def _flow_documents(
    flows: Mapping[str, object],
    runtime: Mapping[str, _RuntimeIdentity],
    verified_at: datetime,
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    artifacts: dict[str, bytes] = {}
    receipts: list[dict[str, object]] = []
    runtime_digests = {name: runtime[name].digest for name in _RUNTIME_NAMES}
    timestamp = _timestamp(verified_at, "verified_at")
    for name in _FLOW_NAMES:
        filename = f"real-flow-{name.replace('_', '-')}.json"
        artifact = {
            "completed_at": timestamp,
            "contract": _ARTIFACT_CONTRACT,
            "evidence": _flow_projection(name, _flow_source(name, flows)),
            "kind": "real_flow",
            "name": name,
            "passed": True,
            "runtime": runtime_digests,
            "started_at": timestamp,
        }
        content = _canonical_bytes(artifact)
        artifacts[filename] = content
        receipts.append(
            {
                "artifact": {
                    "path": filename,
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
                "name": name,
                "passed": True,
            }
        )
    return artifacts, receipts


def build_release_evidence(
    settings: Settings,
    *,
    output_dir: Path,
    runtime_roots: Mapping[str, Path],
    test_receipts: Sequence[Path],
    admission_id: str,
    admission_digest: str,
    evidence_set_id: str,
    evidence_set_digest: str,
    database: Database | None = None,
    runtime_security_probe: Callable[[Settings], bool] = (
        candidate_evidence_runtime_security_is_ready
    ),
) -> EvidenceBuildResult:
    """Seal final v4 release evidence from receipts and one verified fact set."""

    runtime = _runtime_identities(runtime_roots)
    directory = _safe_output_directory(output_dir, runtime)
    completed_tests = _validated_test_receipts(test_receipts, runtime)
    stored = _stored_evidence(
        settings,
        database=database,
        admission_id=admission_id,
        admission_digest=admission_digest,
        evidence_set_id=evidence_set_id,
        evidence_set_digest=evidence_set_digest,
        runtime_security_probe=runtime_security_probe,
    )
    flows = _facts_flows(stored, runtime)
    test_artifacts, suites = _test_documents(completed_tests)
    recomputed_preflight_digest = hashlib.sha256(
        _canonical_bytes(
            _candidate_preflight_document(
                runtime=runtime,
                suites=suites,
            )
        )
    ).hexdigest()
    if recomputed_preflight_digest != stored.preflight_evidence_digest:
        raise EvidenceBuildError(
            "final test receipts do not match the admitted candidate preflight"
        )
    flow_artifacts, receipts = _flow_documents(
        flows,
        runtime,
        stored.verified_at,
    )
    artifacts = {**test_artifacts, **flow_artifacts}
    document: dict[str, object] = {
        "candidate": {
            "admission_digest": stored.admission_digest,
            "admission_id": stored.admission_id,
            "evidence_set_digest": stored.facts_digest,
            "evidence_set_id": stored.evidence_set_id,
            "final_order_snapshot_digest": stored.final_order_snapshot_digest,
        },
        "contract": _RELEASE_CONTRACT,
        "real_flows": {"flows": receipts, "passed": True},
        "runtime": _runtime_document(runtime),
        "safety": {
            "kill_switch": True,
            "live_trading_enabled": False,
            "orders_created": 0,
        },
        "tests": {"passed": True, "suites": suites},
    }
    manifest = _canonical_bytes(document)
    _require_runtime_unchanged(runtime)
    path, replay = _seal_bundle(
        output_dir=directory,
        artifacts=artifacts,
        manifest_name="agent-v0.2-release-evidence.json",
        manifest=manifest,
    )
    _require_runtime_unchanged(runtime)
    try:
        observation = release_evidence_observation(path)
    except ReleaseRuntimeProbeError as exc:
        raise EvidenceBuildError("generated release evidence failed self-validation") from exc
    expected = hashlib.sha256(manifest).hexdigest()
    if (
        observation.digest != expected
        or observation.candidate_admission_id != stored.admission_id
        or observation.candidate_admission_digest != stored.admission_digest
        or observation.evidence_set_id != stored.evidence_set_id
        or observation.evidence_set_digest != stored.facts_digest
        or observation.final_order_snapshot_digest != stored.final_order_snapshot_digest
    ):
        raise EvidenceBuildError("release evidence self-validation binding drifted")
    return EvidenceBuildResult(
        manifest_path=path,
        digest=observation.digest,
        idempotent_replay=replay,
    )


app = typer.Typer(
    add_completion=False,
    help="Run test suites and seal Agent v0.2 release evidence; never run real flows.",
)


def _emit(result: EvidenceBuildResult | TestSuiteRunResult) -> None:
    typer.echo(
        json.dumps(
            result.to_public_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _run_cli(
    operation: Callable[[], EvidenceBuildResult | TestSuiteRunResult],
) -> None:
    try:
        _emit(operation())
    except (
        EvidenceBuildError,
        CandidateEvidenceError,
        ReleaseRuntimeProbeError,
        TestExecutionEvidenceError,
    ) as exc:
        typer.echo(
            json.dumps(
                {
                    "error": str(exc),
                    "ok": False,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None


@app.command("run-suite")
def run_suite_cli(
    name: Annotated[str, typer.Option()],
    output_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    platform_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hqa_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hermes_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    cwd: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    argv: Annotated[
        list[str],
        typer.Argument(
            help="Exact command argv; include exactly one {junit} placeholder.",
        ),
    ],
    timeout_seconds: Annotated[int, typer.Option(min=1, max=86_400)] = 3600,
) -> None:
    """Execute one test suite without a shell and seal its receipt."""

    _run_cli(
        lambda: run_test_suite(
            name=name,
            argv=argv,
            output_dir=output_dir,
            runtime_roots={
                "platform": platform_root,
                "hqa": hqa_root,
                "hermes": hermes_root,
            },
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
    )


@app.command("build-preflight")
def build_preflight_cli(
    output_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    platform_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hqa_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hermes_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    test_receipt: Annotated[
        list[Path],
        typer.Option("--test-receipt", exists=True, dir_okay=False),
    ],
) -> None:
    """Build the test-only candidate admission manifest."""

    _run_cli(
        lambda: build_candidate_preflight(
            output_dir=output_dir,
            runtime_roots={
                "platform": platform_root,
                "hqa": hqa_root,
                "hermes": hermes_root,
            },
            test_receipts=test_receipt,
        )
    )


@app.command("build-final")
def build_final_cli(
    admission_id: Annotated[str, typer.Option()],
    admission_digest: Annotated[str, typer.Option()],
    evidence_set_id: Annotated[str, typer.Option()],
    evidence_set_digest: Annotated[str, typer.Option()],
    output_dir: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    platform_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hqa_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    hermes_root: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False),
    ],
    test_receipt: Annotated[
        list[Path],
        typer.Option("--test-receipt", exists=True, dir_okay=False),
    ],
) -> None:
    """Build final evidence from one exact verified PostgreSQL fact set."""

    _run_cli(
        lambda: build_release_evidence(
            load_settings(),
            output_dir=output_dir,
            runtime_roots={
                "platform": platform_root,
                "hqa": hqa_root,
                "hermes": hermes_root,
            },
            test_receipts=test_receipt,
            admission_id=admission_id,
            admission_digest=admission_digest,
            evidence_set_id=evidence_set_id,
            evidence_set_digest=evidence_set_digest,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()


__all__ = [
    "EvidenceBuildConflict",
    "EvidenceBuildError",
    "EvidenceBuildResult",
    "TestSuiteRunResult",
    "app",
    "build_candidate_preflight",
    "build_release_evidence",
    "main",
    "run_test_suite",
]
