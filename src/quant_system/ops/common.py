"""Shared primitives for machine-judgeable release operations."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ReleaseOperationError(RuntimeError):
    """A release operation failed closed."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_private_directory(path: Path) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))

    def reject_unsafe_components() -> None:
        current = Path(candidate.anchor)
        for part in candidate.parts[1:]:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise ReleaseOperationError(f"symlink output component: {current}")
            if current != candidate and not stat.S_ISDIR(info.st_mode):
                raise ReleaseOperationError(f"non-directory output component: {current}")

    reject_unsafe_components()
    candidate.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_unsafe_components()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ReleaseOperationError(f"unsafe output directory: {candidate}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ReleaseOperationError(f"unsafe output directory: {candidate}")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)
    return candidate


def write_immutable(path: Path, payload: bytes) -> None:
    ensure_private_directory(path.parent)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError as exc:
        raise ReleaseOperationError(f"immutable output already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def read_private_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReleaseOperationError(f"not a private regular file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ReleaseOperationError(f"not an owned regular file: {path}")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ReleaseOperationError(f"file permissions are not owner-only: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@dataclass(frozen=True)
class GitIdentity:
    path: str
    branch: str
    commit: str
    tree: str
    origin_url: str
    status_sha256: str
    clean: bool


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ReleaseOperationError(f"git {' '.join(args)} failed: {detail}")
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8", "strict").strip()


def git_identity(root: Path, *, require_clean: bool) -> GitIdentity:
    resolved = root.resolve()
    if not (resolved / ".git").exists():
        # Linked worktrees use a .git regular file, so exists() is intentional.
        raise ReleaseOperationError(f"not a git checkout: {resolved}")
    status = _git(resolved, "status", "--porcelain=v2", "-z", binary=True)
    assert isinstance(status, bytes)
    branch = _git(resolved, "branch", "--show-current")
    commit = _git(resolved, "rev-parse", "HEAD")
    tree = _git(resolved, "rev-parse", "HEAD^{tree}")
    origin_url = _git(resolved, "remote", "get-url", "github")
    assert all(isinstance(item, str) for item in (branch, commit, tree, origin_url))
    clean = status == b""
    if require_clean and not clean:
        raise ReleaseOperationError(f"release checkout is dirty: {resolved}")
    return GitIdentity(
        path=str(resolved),
        branch=str(branch),
        commit=str(commit),
        tree=str(tree),
        origin_url=str(origin_url),
        status_sha256=sha256_bytes(status),
        clean=clean,
    )


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    stdin_path: Path | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> CommandResult:
    """Run a command without recording environment values.

    Callers must keep secret connection values in ``env`` rather than argv.
    """

    input_handle = stdin_path.open("rb") if stdin_path is not None else None
    output_handle = None
    if stdout_path is not None:
        descriptor = os.open(
            stdout_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        output_handle = os.fdopen(descriptor, "wb")
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=input_handle,
            stdout=output_handle if output_handle is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        if input_handle is not None:
            input_handle.close()
        if output_handle is not None:
            output_handle.close()
    stdout = b"" if output_handle is not None else completed.stdout
    stderr = completed.stderr
    if stderr_path is not None:
        write_immutable(stderr_path, stderr)
    return CommandResult(
        argv=tuple(argv),
        exit_code=completed.returncode,
        stdout_sha256=sha256_bytes(stdout),
        stderr_sha256=sha256_bytes(stderr),
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
    )


def dataclass_record(value: object) -> dict[str, Any]:
    return asdict(value)  # type: ignore[arg-type]
