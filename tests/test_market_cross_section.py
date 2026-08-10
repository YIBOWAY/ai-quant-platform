from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)
from quant_system.factors.market_cross_section import (
    BASKETS,
    build_market_cross_section,
)


def _snapshot(symbols: tuple[str, ...], *, periods: int = 64) -> HistoricalPriceSnapshot:
    dates = pd.bdate_range("2025-12-31", periods=periods)
    midpoint = (len(symbols) - 1) / 2
    drifts = {
        symbol: (index - midpoint) * 0.004
        for index, symbol in enumerate(symbols)
    }
    series = []
    for symbol in symbols:
        rows = [
            {
                "date": day.date().isoformat(),
                "close": round(100.0 * ((1.0 + drifts[symbol]) ** index), 6),
            }
            for index, day in enumerate(dates)
        ]
        series.append(
            {
                "symbol": symbol,
                "row_count": len(rows),
                "first_date": rows[0]["date"],
                "last_date": rows[-1]["date"],
                "rows": rows,
            }
        )
    return HistoricalPriceSnapshot(
        provider="futu",
        source="futu",
        interval="1d",
        adjustment="qfq",
        start=dates[0].date().isoformat(),
        end=dates[-1].date().isoformat(),
        fetched_at=datetime(2026, 3, 30, 9, 30, tzinfo=UTC).isoformat(),
        symbols=list(symbols),
        series=series,
    )


def test_build_cross_section_has_strict_provenance_and_no_valuation_metrics() -> None:
    universe = BASKETS["ai_watch"]["symbols"]
    overview = build_market_cross_section(
        _snapshot(universe),
        universe=universe,
        basket_id="ai_watch",
        basket_label={"en": "AI / semis watch", "zh": "AI / 半导体关注"},
    )

    assert overview["provider"] == "futu"
    assert overview["timezone"] == "America/New_York"
    assert overview["provenance"] == "futu"
    assert overview["basket"] == "ai_watch"
    assert [row["symbol"] for row in overview["rows"]] == list(universe)
    for row in overview["rows"]:
        assert row["meta"]["provider"] == "futu"
        assert row["meta"]["timezone"] == "America/New_York"
        assert row["meta"]["adjustment"] == "qfq"
        assert row["meta"]["provenance"] == "futu"
        assert set(row["returns"]) == {"week_pct", "month_pct", "ytd_pct"}
        assert row["history"]

    forbidden = {"pe", "pb", "erp", "crowding", "risk_list", "valuation"}
    assert forbidden.isdisjoint(overview)
    assert all(forbidden.isdisjoint(row) for row in overview["rows"])


def test_rank_is_dynamic_from_returns() -> None:
    universe = BASKETS["ai_watch"]["symbols"]
    snapshot = _snapshot(universe)
    overview = build_market_cross_section(
        snapshot,
        universe=universe,
        basket_id="ai_watch",
        basket_label=None,
    )
    ranks = {row["symbol"]: row["rank"] for row in overview["rows"]}
    # drift increases by index, so the last symbol should rank first
    assert ranks[universe[-1]] == 1
    assert ranks[universe[0]] == len(universe)


def test_rejects_non_futu_provenance() -> None:
    universe = BASKETS["ai_watch"]["symbols"]
    snapshot = _snapshot(universe)
    bad = HistoricalPriceSnapshot(
        provider="sample",
        source=snapshot.source,
        interval=snapshot.interval,
        adjustment=snapshot.adjustment,
        start=snapshot.start,
        end=snapshot.end,
        fetched_at=snapshot.fetched_at,
        symbols=snapshot.symbols,
        series=snapshot.series,
    )
    with pytest.raises(HistoricalPriceReadError):
        build_market_cross_section(
            bad,
            universe=universe,
            basket_id="ai_watch",
            basket_label=None,
        )


def test_rejects_missing_symbol_in_universe() -> None:
    universe = BASKETS["ai_watch"]["symbols"]
    snapshot = _snapshot(universe)
    bad = HistoricalPriceSnapshot(
        provider=snapshot.provider,
        source=snapshot.source,
        interval=snapshot.interval,
        adjustment=snapshot.adjustment,
        start=snapshot.start,
        end=snapshot.end,
        fetched_at=snapshot.fetched_at,
        symbols=list(universe[:-1]),
        series=snapshot.series[:-1],
    )
    with pytest.raises(HistoricalPriceReadError):
        build_market_cross_section(
            bad,
            universe=universe,
            basket_id="ai_watch",
            basket_label=None,
        )


def test_rejects_insufficient_history() -> None:
    universe = BASKETS["ai_watch"]["symbols"]
    snapshot = _snapshot(universe, periods=10)
    with pytest.raises(HistoricalPriceReadError):
        build_market_cross_section(
            snapshot,
            universe=universe,
            basket_id="ai_watch",
            basket_label=None,
        )
