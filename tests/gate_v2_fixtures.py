"""Deterministic builders shared by the gate_v2 tests. No IO, no provider."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import ResearchTrial, universe_digest

DEFAULT_UNIVERSE = ("AAA", "BBB", "CCC", "DDD")


def business_days(periods: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="B")


def levels(returns: Sequence[float], initial_cash: float) -> list[float]:
    level = float(initial_cash)
    out: list[float] = []
    for value in returns:
        level *= 1.0 + float(value)
        out.append(level)
    return out


def curve_rows(
    *,
    equity_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    initial_cash: float = 100_000.0,
    start: str = "2020-01-02",
) -> list[dict[str, Any]]:
    dates = business_days(len(equity_returns), start)
    equity = levels(equity_returns, initial_cash)
    benchmark = levels(benchmark_returns, initial_cash)
    return [
        {
            "date": stamp.strftime("%Y-%m-%d"),
            "equity": float(equity[index]),
            "benchmark": float(benchmark[index]),
            "peer": float(equity[index]),
        }
        for index, stamp in enumerate(dates)
    ]


def platform_result(
    *,
    equity_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    initial_cash: float = 100_000.0,
    start: str = "2020-01-02",
) -> dict[str, Any]:
    rows = curve_rows(
        equity_returns=equity_returns,
        benchmark_returns=benchmark_returns,
        initial_cash=initial_cash,
        start=start,
    )
    return {"curve": rows, "evaluation_initial_cash": initial_cash}


def trial_row(
    *,
    trial_id: str,
    universe: Sequence[str] = DEFAULT_UNIVERSE,
    kind: str = "platform_backtest",
    n_periods: int = 200,
    metadata: dict[str, Any] | None = None,
    daily_returns: Sequence[float] | None = None,
) -> ResearchTrial:
    returns = list(daily_returns) if daily_returns is not None else [0.001] * n_periods
    return ResearchTrial.record(
        kind=kind,  # type: ignore[arg-type]
        subject="fixture",
        universe=universe,
        daily_returns=returns,
        source="fixture",
        metadata={"run_id": trial_id, **(metadata or {})},
    )


def equity_returns_of(payload: dict[str, Any]) -> list[float]:
    """Recover the strategy leg's daily returns from a serialized curve."""
    curve = payload["curve"]
    initial = payload.get("evaluation_initial_cash", 100_000.0)
    previous = initial
    out: list[float] = []
    for row in curve:
        out.append(float(row["equity"]) / previous - 1.0)
        previous = float(row["equity"])
    return out


def family_from_payloads(
    payloads: Sequence[dict[str, Any]],
    *,
    universe: Sequence[str] = DEFAULT_UNIVERSE,
    kind: str = "platform_backtest",
) -> list[ResearchTrial]:
    """One verified platform_backtest row per payload, digest bound to its curve."""
    rows: list[ResearchTrial] = []
    for index, payload in enumerate(payloads):
        daily = equity_returns_of(payload)
        rows.append(
            trial_row(
                trial_id=f"run-{index}",
                universe=universe,
                kind=kind,
                n_periods=len(daily),
                daily_returns=daily,
                metadata={
                    "strategy_definition_digest": f"def-{index}",
                    "equity_curve_digest": _hash(payload["curve"]),
                },
            )
        )
    return rows


def resolver_for(payloads: Sequence[dict[str, Any]]):
    index = {_hash(payload["curve"]): payload for payload in payloads}

    def resolve(row: Any) -> Any:
        digest = (getattr(row, "metadata", None) or {}).get("equity_curve_digest")
        return index.get(digest)

    return resolve


def noise_returns(periods: int, *, seed: int, vol: float = 0.01, mean: float = 0.0) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(value) for value in rng.normal(mean, vol, periods)]


def balanced_returns(
    periods: int, *, mean: float, spread: float, offset: float = 0.0
) -> list[float]:
    """Alternating ``mean +/- spread``: near-zero skew, a controlled dispersion."""
    high = mean + spread + offset
    low = mean - spread + offset
    return [high if index % 2 == 0 else low for index in range(periods)]


def active_series_from(returns: Sequence[float]) -> dict[str, Any]:
    from quant_system.research.gate_v2 import active_series

    return active_series(active_returns=returns, equity_returns=returns)


def tracking_returns(
    reference: Sequence[float], *, beta: float, vol: float, seed: int
) -> list[float]:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, vol, len(reference))
    return [beta * float(ref) + float(value) for ref, value in zip(reference, noise, strict=True)]


def universe_symbols() -> list[str]:
    return list(DEFAULT_UNIVERSE)


def digest_of_universe(symbols: Sequence[str] = DEFAULT_UNIVERSE) -> str:
    return universe_digest(symbols)
