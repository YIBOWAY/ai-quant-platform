"""Bounded admission guard for the local owner mutation surface.

This limiter is deliberately small and process-local.  It reduces accidental
or abusive request bursts; durable idempotency remains the correctness
boundary.  Keys use the authenticated owner identity plus an explicit route
class, never a cookie, CSRF value, bootstrap token, prompt, or request body.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

OWNER_BOOTSTRAP_ROUTE = "owner.bootstrap"
WORKSPACE_ACT_ROUTE = "workspace.act"
WORKSPACE_SUBMIT_TURN_ROUTE = "workspace.submit-turn"
MUTATION_RATE_LIMIT_ROUTES = frozenset(
    {
        OWNER_BOOTSTRAP_ROUTE,
        WORKSPACE_ACT_ROUTE,
        WORKSPACE_SUBMIT_TURN_ROUTE,
    }
)


class MutationRateLimitExceeded(RuntimeError):
    """Stable admission failure surfaced as HTTP 429 by the transport layer."""

    code = "mutation_rate_limited"

    def __init__(self, retry_after_seconds: int, *, route: str) -> None:
        super().__init__("mutation rate limit exceeded")
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.route = route


class OwnerMutationRateLimiter:
    """Thread-safe sliding window keyed by ``(owner_id, route)``.

    The key set is bounded independently from each request window.  This
    matters even in a single-user product: untrusted values must never be able
    to grow process memory without limit.
    """

    def __init__(
        self,
        *,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        max_keys: int = 1_024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("mutation rate limit values must be positive")
        self.max_requests = int(max_requests)
        self.window_seconds = float(window_seconds)
        self.max_keys = int(max_keys)
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], deque[float]] = {}

    @property
    def tracked_key_count(self) -> int:
        with self._lock:
            return len(self._windows)

    def consume(self, owner_id: str, *, route: str) -> None:
        if (
            type(owner_id) is not str
            or not owner_id
            or len(owner_id) > 256
            or route not in MUTATION_RATE_LIMIT_ROUTES
        ):
            raise ValueError("valid owner_id and mutation route are required")

        now = float(self._clock())
        cutoff = now - self.window_seconds
        key = (owner_id, route)
        with self._lock:
            window = self._windows.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.max_requests:
                retry = math.ceil(window[0] + self.window_seconds - now)
                raise MutationRateLimitExceeded(retry, route=route)
            window.append(now)
            self._prune(cutoff, protected=key)

    def _prune(self, cutoff: float, *, protected: tuple[str, str]) -> None:
        stale = [
            key
            for key, values in self._windows.items()
            if key != protected and (not values or values[-1] <= cutoff)
        ]
        for key in stale:
            self._windows.pop(key, None)
        if len(self._windows) <= self.max_keys:
            return
        oldest = sorted(
            (
                (values[-1] if values else float("-inf"), key)
                for key, values in self._windows.items()
                if key != protected
            )
        )
        excess = len(self._windows) - self.max_keys
        for _last_seen, key in oldest[:excess]:
            self._windows.pop(key, None)
