"""Bounded per-owner-session mutation admission."""

from __future__ import annotations

import pytest

from quant_system.api.safety.mutation_rate_limit import (
    MutationRateLimitExceeded,
    OwnerMutationRateLimiter,
)


def test_sliding_window_rejects_excess_and_recovers_after_window() -> None:
    now = 100.0
    limiter = OwnerMutationRateLimiter(
        max_requests=2,
        window_seconds=10.0,
        clock=lambda: now,
    )

    limiter.consume("session-a")
    limiter.consume("session-a")
    with pytest.raises(MutationRateLimitExceeded) as exc:
        limiter.consume("session-a")
    assert exc.value.retry_after_seconds == 10

    # Independent session is not penalised.
    limiter.consume("session-b")

    now = 110.1
    limiter.consume("session-a")
