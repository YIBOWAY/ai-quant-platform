"""Dirfd-only filesystem boundary for candidate integrity.

All trusted candidate I/O starts by lexically walking absolute paths from `/`
with O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC, then uses held directory FDs plus single
component names only. No Path.open / path-string os.replace for content writes.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import platform
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

__all__ = [
    "CandidateConflictError",
    "CandidateIntegrityError",
    "OpenedDirectory",
    "assert_entry_is_open_fd",
    "atomic_write_noreplace_at",
    "locked_candidates_root",
    "mkdir_exclusive_at",
    "open_absolute_directory",
    "open_directory_at",
    "read_regular_bytes_at",
    "remove_entry_tree_at",
    "rename_directory_noreplace_at",
    "write_regular_exclusive_at",
]


class CandidateIntegrityError(RuntimeError):
    """Candidate path, type, identity, or byte-boundary violation."""


class CandidateConflictError(RuntimeError):
    """No-replace publication/control write conflict (destination exists)."""


_RUNTIME_OK: bool | None = None
_DIR_FLAGS = 0
_FILE_READ_FLAGS = 0
_FILE_CREATE_FLAGS = 0


def _ensure_runtime_support() -> None:
    global _RUNTIME_OK, _DIR_FLAGS, _FILE_READ_FLAGS, _FILE_CREATE_FLAGS
    if _RUNTIME_OK is True:
        return
    if _RUNTIME_OK is False:
        raise CandidateIntegrityError("candidate filesystem runtime is unsupported")

    required = (
        "O_NOFOLLOW",
        "O_DIRECTORY",
        "O_CLOEXEC",
        "O_RDONLY",
        "O_WRONLY",
        "O_CREAT",
        "O_EXCL",
    )
    missing = [name for name in required if not hasattr(os, name)]
    if missing:
        _RUNTIME_OK = False
        raise CandidateIntegrityError(
            f"candidate filesystem runtime missing flags: {', '.join(missing)}"
        )

    # dir_fd and follow_symlinks=False must be usable on this platform.
    try:
        root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        _RUNTIME_OK = False
        raise CandidateIntegrityError("cannot open filesystem root") from exc
    try:
        os.stat(".", dir_fd=root_fd, follow_symlinks=False)
    except TypeError as exc:
        _RUNTIME_OK = False
        raise CandidateIntegrityError(
            "candidate filesystem runtime lacks dir_fd/follow_symlinks support"
        ) from exc
    except OSError as exc:
        _RUNTIME_OK = False
        raise CandidateIntegrityError("candidate filesystem stat probe failed") from exc
    finally:
        os.close(root_fd)

    _DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    _RUNTIME_OK = True


def _validate_single_component(name: str, *, what: str = "path component") -> str:
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or PurePosixPath(name).name != name
        or not name.isascii()
    ):
        raise CandidateIntegrityError(f"{what} is not a canonical single component")
    return name


@dataclass
class OpenedDirectory:
    fd: int
    parent_fd: int
    name: str
    st_dev: int
    st_ino: int


def open_directory_at(parent_fd: int, name: str) -> int:
    _ensure_runtime_support()
    _validate_single_component(name, what="directory name")
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot open directory component {name!r}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise CandidateIntegrityError(f"{name!r} is not a directory")
    except Exception:
        os.close(fd)
        raise
    return fd


def assert_entry_is_open_fd(parent_fd: int, name: str, opened_fd: int) -> None:
    """Require the parent's current no-follow entry still is the opened inode."""
    _ensure_runtime_support()
    _validate_single_component(name, what="directory name")
    try:
        entry_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise CandidateIntegrityError(
            f"directory entry {name!r} is missing or inaccessible"
        ) from exc
    if stat.S_ISLNK(entry_st.st_mode):
        raise CandidateIntegrityError(f"directory entry {name!r} is a symlink")
    try:
        opened_st = os.fstat(opened_fd)
    except OSError as exc:
        raise CandidateIntegrityError("opened directory fd is invalid") from exc
    if (entry_st.st_dev, entry_st.st_ino) != (opened_st.st_dev, opened_st.st_ino):
        raise CandidateIntegrityError(f"directory entry {name!r} identity does not match held fd")
    if not stat.S_ISDIR(opened_st.st_mode):
        raise CandidateIntegrityError(f"held fd for {name!r} is not a directory")


def read_regular_bytes_at(
    parent_fd: int,
    name: str,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Read a single-link regular file via O_NOFOLLOW; never follow symlinks."""
    _ensure_runtime_support()
    _validate_single_component(name, what="file name")
    if max_bytes is not None and (
        isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0
    ):
        raise CandidateIntegrityError("max_bytes must be a non-negative integer")
    try:
        entry_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat {name!r}") from exc
    if stat.S_ISLNK(entry_st.st_mode):
        raise CandidateIntegrityError(f"{name!r} is a symlink")
    if not stat.S_ISREG(entry_st.st_mode):
        raise CandidateIntegrityError(f"{name!r} is not a regular file")
    if entry_st.st_nlink != 1:
        raise CandidateIntegrityError(f"{name!r} must have exactly one hard link")

    try:
        fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot open {name!r}") from exc
    try:
        opened_st = os.fstat(fd)
        if not stat.S_ISREG(opened_st.st_mode):
            raise CandidateIntegrityError(f"{name!r} is not a regular file")
        if opened_st.st_nlink != 1:
            raise CandidateIntegrityError(f"{name!r} must have exactly one hard link")
        if max_bytes is not None and opened_st.st_size > max_bytes:
            raise CandidateIntegrityError(f"{name!r} exceeds the safe byte limit")
        if (opened_st.st_dev, opened_st.st_ino) != (entry_st.st_dev, entry_st.st_ino):
            raise CandidateIntegrityError(f"{name!r} identity changed during open")
        chunks: list[bytes] = []
        remaining = opened_st.st_size
        read_size = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            read_size += len(chunk)
            remaining -= len(chunk)
            if remaining < 0:
                raise CandidateIntegrityError(f"{name!r} grew during read")
            if max_bytes is not None and read_size > max_bytes:
                raise CandidateIntegrityError(f"{name!r} exceeds the safe byte limit")
        payload = b"".join(chunks)
        final_st = os.fstat(fd)
        if final_st.st_size != opened_st.st_size or len(payload) != opened_st.st_size:
            raise CandidateIntegrityError(f"{name!r} changed during read")
        if final_st.st_nlink != 1:
            raise CandidateIntegrityError(f"{name!r} must have exactly one hard link")
        return payload
    finally:
        os.close(fd)


def _rename_noreplace_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    _ensure_runtime_support()
    _validate_single_component(source_name, what="source name")
    _validate_single_component(destination_name, what="destination name")
    system = platform.system()
    src = source_name.encode("utf-8", errors="strict")
    dst = destination_name.encode("utf-8", errors="strict")

    if system == "Darwin":
        # renameatx_np(fromfd, from, tofd, to, flags) with RENAME_EXCL.
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        RENAME_EXCL = 0x00000004
        ctypes.set_errno(0)
        rc = renameatx_np(source_parent_fd, src, destination_parent_fd, dst, RENAME_EXCL)
        if rc == 0:
            return
        err = ctypes.get_errno()
        if err in {errno.EEXIST, errno.EAGAIN}:
            # macOS may surface EAGAIN for exclusive rename collisions on some versions.
            raise CandidateConflictError(f"destination {destination_name!r} already exists")
        raise OSError(err, os.strerror(err))

    if system == "Linux":
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise CandidateIntegrityError("Linux renameat2 is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        RENAME_NOREPLACE = 1
        ctypes.set_errno(0)
        rc = renameat2(source_parent_fd, src, destination_parent_fd, dst, RENAME_NOREPLACE)
        if rc == 0:
            return
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise CandidateConflictError(f"destination {destination_name!r} already exists")
        raise OSError(err, os.strerror(err))

    raise CandidateIntegrityError(f"no-replace rename is unsupported on platform {system!r}")


def write_regular_exclusive_at(parent_fd: int, name: str, payload: bytes) -> None:
    """Create a new regular file exclusively and write payload; no overwrite."""
    _ensure_runtime_support()
    _validate_single_component(name, what="file name")
    try:
        fd = os.open(name, _FILE_CREATE_FLAGS, 0o644, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise CandidateConflictError(f"file {name!r} already exists") from exc
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise CandidateConflictError(f"file {name!r} already exists") from exc
        raise CandidateIntegrityError(f"cannot create {name!r}") from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:  # pragma: no cover - defensive
                raise CandidateIntegrityError(f"short write to {name!r}")
            view = view[written:]
        os.fsync(fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise CandidateIntegrityError(f"{name!r} is not a single-link regular file")
    except Exception:
        try:
            os.close(fd)
        finally:
            with suppress(OSError):
                os.unlink(name, dir_fd=parent_fd)
        raise
    else:
        os.close(fd)
    os.fsync(parent_fd)


def atomic_write_noreplace_at(parent_fd: int, name: str, payload: bytes) -> None:
    """Write payload to a temp name, fsync, no-replace rename into place."""
    _ensure_runtime_support()
    _validate_single_component(name, what="file name")
    tmp_name = f".tmp-{secrets.token_hex(16)}"
    _validate_single_component(tmp_name, what="temp file name")
    try:
        write_regular_exclusive_at(parent_fd, tmp_name, payload)
        try:
            _rename_noreplace_at(parent_fd, tmp_name, parent_fd, name)
        except Exception:
            with suppress(OSError):
                os.unlink(tmp_name, dir_fd=parent_fd)
            raise
        os.fsync(parent_fd)
    except CandidateConflictError:
        raise
    except OSError as exc:
        raise CandidateIntegrityError(f"atomic write failed for {name!r}") from exc


def rename_directory_noreplace_at(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    """Publish a directory with no-replace rename relative to held parent FDs."""
    _ensure_runtime_support()
    try:
        _rename_noreplace_at(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )
        os.fsync(destination_parent_fd)
    except CandidateConflictError:
        raise
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot publish directory {destination_name!r}") from exc


def _lexical_absolute_components(path: Path) -> list[str]:
    abs_path = Path(os.path.abspath(os.fspath(path)))
    if not abs_path.is_absolute() or (os.name == "posix" and not str(abs_path).startswith("/")):
        raise CandidateIntegrityError("path must be absolute after normalization")
    components = list(abs_path.parts[1:])
    if not components:
        raise CandidateIntegrityError("refusing to use filesystem root as candidate path")
    for component in components:
        _validate_single_component(component)
    return components


def mkdir_exclusive_at(parent_fd: int, name: str, mode: int = 0o755) -> None:
    """Create a single-component directory exclusively under a held parent FD."""
    _ensure_runtime_support()
    _validate_single_component(name, what="directory name")
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise CandidateConflictError(f"directory {name!r} already exists") from exc
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise CandidateConflictError(f"directory {name!r} already exists") from exc
        raise CandidateIntegrityError(f"cannot create directory {name!r}") from exc
    os.fsync(parent_fd)


def remove_entry_tree_at(parent_fd: int, name: str) -> None:
    """Recursively remove a single-component entry relative to a held parent FD."""
    _ensure_runtime_support()
    _validate_single_component(name, what="entry name")
    try:
        entry_st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot stat entry {name!r} for removal") from exc

    if stat.S_ISLNK(entry_st.st_mode) or stat.S_ISREG(entry_st.st_mode):
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError as exc:
            raise CandidateIntegrityError(f"cannot unlink {name!r}") from exc
        os.fsync(parent_fd)
        return

    if not stat.S_ISDIR(entry_st.st_mode):
        raise CandidateIntegrityError(f"cannot remove non-directory entry {name!r}")

    dir_fd = open_directory_at(parent_fd, name)
    try:
        assert_entry_is_open_fd(parent_fd, name, dir_fd)
        for child in os.listdir(dir_fd):
            remove_entry_tree_at(dir_fd, child)
        assert_entry_is_open_fd(parent_fd, name, dir_fd)
    finally:
        os.close(dir_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError as exc:
        raise CandidateIntegrityError(f"cannot rmdir {name!r}") from exc
    os.fsync(parent_fd)


@contextmanager
def locked_candidates_root(agent_output_dir: Path, *, create: bool) -> Iterator[OpenedDirectory]:
    """Open candidates root under exclusive flock on a verified regular pool lock."""
    from quant_system.agent.paths import resolve_candidates_dir

    candidates_path = resolve_candidates_dir(Path(agent_output_dir))
    with open_absolute_directory(candidates_path, create=create) as opened:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            lock_fd = os.open(".candidate-pool.lock", flags, 0o600, dir_fd=opened.fd)
        except OSError as exc:
            raise CandidateIntegrityError("cannot open candidate pool lock") from exc
        try:
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                raise CandidateIntegrityError("candidate pool lock must be regular")
            # Re-check the parent entry is still a single-link regular file and
            # not a symlink/hardlink swapped after open.
            try:
                entry_stat = os.stat(
                    ".candidate-pool.lock",
                    dir_fd=opened.fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise CandidateIntegrityError("candidate pool lock entry missing") from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                raise CandidateIntegrityError("candidate pool lock must be regular")
            if not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1:
                raise CandidateIntegrityError("candidate pool lock must be regular")
            if (entry_stat.st_dev, entry_stat.st_ino) != (
                lock_stat.st_dev,
                lock_stat.st_ino,
            ):
                raise CandidateIntegrityError("candidate pool lock identity does not match held fd")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
            # Confirm lock name still maps to the held lock fd.
            entry_stat = os.stat(
                ".candidate-pool.lock",
                dir_fd=opened.fd,
                follow_symlinks=False,
            )
            held = os.fstat(lock_fd)
            if (entry_stat.st_dev, entry_stat.st_ino) != (held.st_dev, held.st_ino):
                raise CandidateIntegrityError("candidate pool lock identity does not match held fd")
            if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
                raise CandidateIntegrityError("candidate pool lock must be regular")
            yield opened
            entry_stat = os.stat(
                ".candidate-pool.lock",
                dir_fd=opened.fd,
                follow_symlinks=False,
            )
            held = os.fstat(lock_fd)
            if (entry_stat.st_dev, entry_stat.st_ino) != (held.st_dev, held.st_ino):
                raise CandidateIntegrityError("candidate pool lock identity does not match held fd")
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        finally:
            with suppress(OSError):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            with suppress(OSError):
                os.close(lock_fd)


@contextmanager
def open_absolute_directory(path: Path, *, create: bool) -> Iterator[OpenedDirectory]:
    """Open an absolute directory by walking each component from `/` with O_NOFOLLOW."""
    _ensure_runtime_support()
    components = _lexical_absolute_components(path)

    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    parent_fd = root_fd
    child_fd: int | None = None
    intermediate_fds: list[int] = []
    try:
        for index, name in enumerate(components):
            is_last = index == len(components) - 1
            if create:
                try:
                    os.mkdir(name, 0o755, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise CandidateIntegrityError(
                        f"cannot create directory component {name!r}"
                    ) from exc
            try:
                next_fd = open_directory_at(parent_fd, name)
            except CandidateIntegrityError:
                raise
            # Track/close immediately on identity failure so a rename race
            # cannot leak FDs on the hot integrity path.
            try:
                assert_entry_is_open_fd(parent_fd, name, next_fd)
            except Exception:
                with suppress(OSError):
                    os.close(next_fd)
                raise
            if is_last:
                child_fd = next_fd
                st = os.fstat(child_fd)
                opened = OpenedDirectory(
                    fd=child_fd,
                    parent_fd=parent_fd,
                    name=name,
                    st_dev=st.st_dev,
                    st_ino=st.st_ino,
                )
                try:
                    yield opened
                    # Fail closed if the entry drifted before the caller released it.
                    assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
                finally:
                    pass
            else:
                intermediate_fds.append(next_fd)
                parent_fd = next_fd
    finally:
        if child_fd is not None:
            with suppress(OSError):
                os.close(child_fd)
        for fd in reversed(intermediate_fds):
            with suppress(OSError):
                os.close(fd)
        with suppress(OSError):
            os.close(root_fd)
