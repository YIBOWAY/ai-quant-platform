from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class TokenBucket:
    """Windowed token bucket for Futu quote pacing.

    Futu quote endpoints are documented as 10 calls per 30 seconds per endpoint.
    This implementation starts with one full burst and then refills the whole
    bucket on the next window boundary. That conservative pacing is predictable
    and easy to test with an injected clock.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 10,
        refill_seconds: float = 30.0,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if refill_seconds <= 0:
            raise ValueError("refill_seconds must be positive")
        self.max_tokens = max_tokens
        self.refill_seconds = refill_seconds
        self._time_func = time_func
        self._sleep_func = sleep_func
        self._tokens = max_tokens
        self._window_started_at = time_func()

    def acquire(self) -> None:
        self._refill_if_ready()
        if self._tokens <= 0:
            wait_seconds = max(
                self.refill_seconds - (self._time_func() - self._window_started_at),
                0.0,
            )
            if wait_seconds > 0:
                self._sleep_func(wait_seconds)
            self._window_started_at = self._time_func()
            self._tokens = self.max_tokens
        self._tokens -= 1

    def _refill_if_ready(self) -> None:
        elapsed = self._time_func() - self._window_started_at
        if elapsed >= self.refill_seconds:
            self._window_started_at = self._time_func()
            self._tokens = self.max_tokens


class RateLimitedFutuProvider:
    """Small facade that paces read-only Futu provider calls."""

    def __init__(self, provider: Any, *, bucket: TokenBucket) -> None:
        self._provider = provider
        self._bucket = bucket

    def fetch_ohlcv(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_ohlcv(*args, **kwargs)

    def fetch_option_expirations(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_option_expirations(*args, **kwargs)

    def fetch_option_chain(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_option_chain(*args, **kwargs)

    def fetch_option_chain_range(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_option_chain_range(*args, **kwargs)

    def fetch_option_quotes(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_option_quotes(*args, **kwargs)

    def fetch_option_quotes_range(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_option_quotes_range(*args, **kwargs)

    def fetch_market_snapshots(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_market_snapshots(*args, **kwargs)

    def fetch_underlying_snapshot(self, *args: Any, **kwargs: Any) -> Any:
        self._bucket.acquire()
        return self._provider.fetch_underlying_snapshot(*args, **kwargs)

    def normalize_symbol(self, *args: Any, **kwargs: Any) -> Any:
        return self._provider.normalize_symbol(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)
