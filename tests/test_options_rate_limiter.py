from __future__ import annotations

import pytest

from quant_system.options.rate_limiter import RateLimitedFutuProvider, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_token_bucket_waits_after_initial_burst() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        max_tokens=10,
        refill_seconds=30,
        time_func=clock.time,
        sleep_func=clock.sleep,
    )

    for _ in range(10):
        bucket.acquire()
    bucket.acquire()

    assert clock.sleeps == [pytest.approx(30.0)]
    assert clock.now >= 30.0


def test_token_bucket_100_requests_respect_10_per_30s_limit() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        max_tokens=10,
        refill_seconds=30,
        time_func=clock.time,
        sleep_func=clock.sleep,
    )

    for _ in range(100):
        bucket.acquire()

    assert clock.now == pytest.approx(270.0)


def test_rate_limited_futu_provider_wraps_read_methods() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        max_tokens=1,
        refill_seconds=30,
        time_func=clock.time,
        sleep_func=clock.sleep,
    )
    calls: list[tuple[str, tuple, dict]] = []

    class FakeProvider:
        def fetch_ohlcv(self, *args, **kwargs):
            calls.append(("ohlcv", args, kwargs))
            return "history"

        def fetch_option_expirations(self, *args, **kwargs):
            calls.append(("expirations", args, kwargs))
            return "expirations"

    provider = RateLimitedFutuProvider(FakeProvider(), bucket=bucket)

    assert provider.fetch_ohlcv(["SPY"], start="2024-01-01", end="2024-01-31") == "history"
    assert provider.fetch_option_expirations("SPY") == "expirations"
    assert [item[0] for item in calls] == ["ohlcv", "expirations"]
    assert clock.now == pytest.approx(30.0)
