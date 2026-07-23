"""Bounded per-owner, per-route mutation admission."""

from __future__ import annotations

import pytest

from quant_system.api.safety.mutation_rate_limit import (
    MutationRateLimitExceeded,
    OwnerMutationRateLimiter,
)


def test_sliding_window_is_independent_per_owner_and_route() -> None:
    now = 100.0
    limiter = OwnerMutationRateLimiter(
        max_requests=2,
        window_seconds=10.0,
        clock=lambda: now,
    )

    limiter.consume("owner-a", route="workspace.act")
    limiter.consume("owner-a", route="workspace.act")
    with pytest.raises(MutationRateLimitExceeded) as exc:
        limiter.consume("owner-a", route="workspace.act")
    assert exc.value.retry_after_seconds == 10
    assert exc.value.route == "workspace.act"

    # Neither a different route nor a different owner shares the exhausted key.
    limiter.consume("owner-a", route="workspace.submit-turn")
    limiter.consume("owner-b", route="workspace.act")

    now = 110.1
    limiter.consume("owner-a", route="workspace.act")


def test_limiter_rejects_invalid_identity_or_route_without_allocating_keys() -> None:
    limiter = OwnerMutationRateLimiter()

    for owner, route in [
        ("", "workspace.act"),
        ("owner-a", ""),
        ("owner-a", "unknown"),
        ("x" * 257, "workspace.act"),
    ]:
        with pytest.raises(ValueError):
            limiter.consume(owner, route=route)

    assert limiter.tracked_key_count == 0


def test_limiter_prunes_stale_keys_and_stays_bounded() -> None:
    now = 0.0
    limiter = OwnerMutationRateLimiter(
        max_requests=1,
        window_seconds=1.0,
        max_keys=2,
        clock=lambda: now,
    )

    limiter.consume("owner-a", route="workspace.act")
    limiter.consume("owner-b", route="workspace.act")
    limiter.consume("owner-c", route="workspace.act")
    assert limiter.tracked_key_count == 2

    now = 2.0
    limiter.consume("owner-d", route="workspace.submit-turn")
    assert limiter.tracked_key_count == 1
