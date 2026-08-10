from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)
from quant_system.factors.market_cross_section import (
    BASKETS,
    _resolve_universe,
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


def _custom_snapshot(
    closes_by_symbol: dict[str, list[float]],
    *,
    source: str = "futu",
) -> HistoricalPriceSnapshot:
    dates = pd.bdate_range("2026-01-02", periods=len(next(iter(closes_by_symbol.values()))))
    series = []
    for symbol, closes in closes_by_symbol.items():
        assert len(closes) == len(dates)
        rows = [
            {"date": day.date().isoformat(), "close": close}
            for day, close in zip(dates, closes, strict=True)
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
        source=source,
        interval="1d",
        adjustment="qfq",
        start=dates[0].date().isoformat(),
        end=dates[-1].date().isoformat(),
        fetched_at=datetime(2026, 4, 24, 9, 30, tzinfo=UTC).isoformat(),
        symbols=list(closes_by_symbol),
        series=series,
    )


def _expected_volatility_pct(closes: list[float]) -> float:
    # Methodology: 63-session annualized realized volatility, ddof=1.
    returns = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1)][-63:]
    return round(float(np.std(returns, ddof=1) * math.sqrt(252) * 100), 4)


def test_metrics_match_hand_computed_values() -> None:
    # AAA: arithmetic ramp 100..179 over 80 sessions, all inside 2026.
    # BBB: flat 150 then a single step down to 100 at session 50.
    aaa = [100.0 + i for i in range(80)]
    bbb = [150.0] * 50 + [100.0] * 30
    overview = build_market_cross_section(
        _custom_snapshot({"AAA": aaa, "BBB": bbb}),
        universe=("AAA", "BBB"),
        basket_id=None,
        basket_label=None,
    )

    rows = {row["symbol"]: row for row in overview["rows"]}

    # AAA exact hand-computed values.
    assert rows["AAA"]["returns"]["week_pct"] == round((179 / 174 - 1) * 100, 4)
    assert rows["AAA"]["returns"]["month_pct"] == round((179 / 158 - 1) * 100, 4)
    assert rows["AAA"]["returns"]["ytd_pct"] == 79.0
    assert rows["AAA"]["max_drawdown_pct"] == 0.0
    assert rows["AAA"]["volatility_pct"] == _expected_volatility_pct(aaa)
    # Sparkline indexes from its own first close.
    assert rows["AAA"]["history"][0]["indexed_return_pct"] == 0.0
    assert rows["AAA"]["history"][-1]["indexed_return_pct"] == 79.0

    # BBB: one -1/3 step down, flat afterwards.
    assert rows["BBB"]["returns"]["week_pct"] == 0.0
    assert rows["BBB"]["returns"]["month_pct"] == 0.0
    assert rows["BBB"]["returns"]["ytd_pct"] == round((100 / 150 - 1) * 100, 4)
    assert rows["BBB"]["max_drawdown_pct"] == round((100 / 150 - 1) * 100, 4)
    assert rows["BBB"]["volatility_pct"] == _expected_volatility_pct(bbb)

    # Rank follows YTD: AAA first, BBB second.
    assert rows["AAA"]["rank"] == 1
    assert rows["BBB"]["rank"] == 2
    assert overview["as_of"] == rows["AAA"]["meta"]["as_of"]


def test_futu_cache_provenance_is_propagated() -> None:
    closes = [100.0 + i for i in range(80)]
    overview = build_market_cross_section(
        _custom_snapshot({"AAA": closes}, source="futu_cache"),
        universe=("AAA",),
        basket_id=None,
        basket_label=None,
    )

    assert overview["provenance"] == "futu_cache"
    assert overview["rows"][0]["meta"]["provenance"] == "futu_cache"


def test_rejects_symbol_missing_the_shared_session() -> None:
    # AAA ends one session before BBB, and BBB is missing AAA's last date:
    # the shared session cannot be honored, so the read must fail closed.
    base_dates = pd.bdate_range("2026-01-02", periods=80)
    snapshot = _custom_snapshot(
        {"AAA": [100.0 + i for i in range(80)], "BBB": [100.0 + i for i in range(80)]}
    )
    bbb_rows = [
        row
        for row in snapshot.series[1]["rows"]
        if row["date"] != snapshot.series[0]["rows"][-1]["date"]
    ]
    extra_day = base_dates[-1] + pd.offsets.BDay(1)
    bbb_rows.append({"date": extra_day.date().isoformat(), "close": 200.0})
    snapshot.series[1]["rows"] = bbb_rows
    snapshot.series[1]["last_date"] = bbb_rows[-1]["date"]

    with pytest.raises(HistoricalPriceReadError) as excinfo:
        build_market_cross_section(
            snapshot,
            universe=("AAA", "BBB"),
            basket_id=None,
            basket_label=None,
        )
    assert excinfo.value.code == "market_cross_section_contract_invalid"


@pytest.mark.parametrize(
    "symbols",
    [
        ["A$%"],  # illegal characters must be rejected, not passed downstream
        ["BRK.B"],  # dotted codes are rejected by Futu normalize_symbol
        ["US.SPY"],  # US.-prefixed codes are not accepted by this endpoint
        [""],
        ["   "],
        ["TOOLONGSYMBOL13"],
        [f"S{index}" for index in range(17)],  # over the 16-symbol cap
    ],
)
def test_resolve_universe_rejects_invalid_custom_symbols(symbols: list[str]) -> None:
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        _resolve_universe(basket=None, symbols=symbols)
    assert excinfo.value.code == "market_cross_section_invalid_request"


def test_resolve_universe_rejects_ambiguous_or_empty_input() -> None:
    with pytest.raises(HistoricalPriceReadError):
        _resolve_universe(basket="ai_watch", symbols=["SPY"])
    with pytest.raises(HistoricalPriceReadError):
        _resolve_universe(basket=None, symbols=[])


def test_resolve_universe_normalizes_and_deduplicates() -> None:
    universe, basket_id, basket_label = _resolve_universe(
        basket=None, symbols=["spy", " QQQ ", "SPY"]
    )
    assert universe == ("SPY", "QQQ")
    assert basket_id is None
    assert basket_label is None
