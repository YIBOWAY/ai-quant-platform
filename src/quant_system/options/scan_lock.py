from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

RADAR_SCAN_LOCK_FILENAME = "options_radar_scan.lock"


class OptionsRadarScanLocked(RuntimeError):
    """Raised when another radar scan already holds the cross-process lock."""


@contextmanager
def options_radar_scan_lock(
    output_dir: str | Path,
    *,
    timeout_seconds: float = 0.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Serialize radar snapshot writes across API, startup, CLI, and scheduler."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / RADAR_SCAN_LOCK_FILENAME
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            try:
                _lock_file(handle)
                break
            except OSError:
                if timeout_seconds <= 0 or time.monotonic() >= deadline:
                    raise OptionsRadarScanLocked(
                        f"options radar scan lock is already held: {lock_path}"
                    ) from None
                time.sleep(poll_seconds)
        try:
            yield
        finally:
            _unlock_file(handle)


def _lock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
