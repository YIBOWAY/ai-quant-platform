"""Small in-process admission guard for the local single-user mutation BFF."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class MutationRateLimitExceeded(RuntimeError):
    code = "mutation_rate_limited"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("mutation rate limit exceeded")
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class OwnerMutationRateLimiter:
    """Thread-safe sliding window keyed by signed owner session ID.

    This is a local BFF abuse/accident guard, not a distributed entitlement
    authority.  The durable action idempotency contract remains the correctness
    boundary across restarts and multiple processes.
    """

    def __init__(
        self,
        *,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_sessions: int = 1_024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1 or window_seconds <= 0 or max_sessions < 1:
            raise ValueError("mutation rate limit values must be positive")
        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self.max_sessions = int(max_sessions)
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = {}

    def consume(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id is required")
        now = float(self._clock())
        cutoff = now - self.window_seconds
        with self._lock:
            window = self._windows.setdefault(session_id, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.max_requests:
                retry = math.ceil(window[0] + self.window_seconds - now)
                raise MutationRateLimitExceeded(retry)
            window.append(now)
            self._prune(cutoff, protected=session_id)

    def _prune(self, cutoff: float, *, protected: str) -> None:
        empty_or_stale = [
            key
            for key, values in self._windows.items()
            if key != protected and (not values or values[-1] <= cutoff)
        ]
        for key in empty_or_stale:
            self._windows.pop(key, None)
        if len(self._windows) <= self.max_sessions:
            return
        oldest = sorted(
            (
                (values[-1] if values else float("-inf"), key)
                for key, values in self._windows.items()
                if key != protected
            )
        )
        for _last_seen, key in oldest[: len(self._windows) - self.max_sessions]:
            self._windows.pop(key, None)
