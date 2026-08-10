from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)
from quant_system.factors.asia_radar import (
    ASIA_ETF_SYMBOLS,
    build_asia_radar_overview,
)


def _snapshot(*, start: str = "2025-12-31", periods: int = 64) -> HistoricalPriceSnapshot:
    dates = pd.bdate_range(start, periods=periods)
    daily_moves = {
        "EWY": -0.030,
        "EWT": -0.025,
        "EWJ": -0.020,
        "ASHR": -0.010,
        "INDA": -0.005,
        "EIDO": 0.000,
        "EWH": 0.004,
        "EWS": 0.008,
        "THD": 0.012,
        "EWM": 0.020,
        "EWA": 0.025,
        "EPHE": 0.030,
    }
    series = []
    for symbol in ASIA_ETF_SYMBOLS:
        rows = [
            {
                "date": day.date().isoformat(),
                "close": round(100.0 * ((1.0 + daily_moves[symbol]) ** index), 6),
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
        fetched_at=datetime(2026, 2, 13, 9, 30, tzinfo=UTC).isoformat(),
        symbols=list(ASIA_ETF_SYMBOLS),
        series=series,
    )


def test_overview_has_exact_real_futu_provenance_and_only_phase_one_metrics() -> None:
    overview = build_asia_radar_overview(_snapshot())

    assert overview["provider"] == "futu"
    assert overview["timezone"] == "America/New_York"
    assert overview["provenance"] == "futu"
    assert overview["as_of"] == "2026-03-30"
    assert [market["symbol"] for market in overview["markets"]] == list(
        ASIA_ETF_SYMBOLS
    )
    for market in overview["markets"]:
        assert market["data_status"] == "real"
        assert market["market_coverage"] == "proxy"
        assert market["meta"] == {
            "provider": "futu",
            "symbol": market["symbol"],
            "currency": "USD",
            "timezone": "America/New_York",
            "as_of": "2026-03-30",
            "adjustment": "qfq",
            "provenance": "futu",
        }
        assert set(market["returns"]) == {"week_pct", "month_pct", "ytd_pct"}
        assert isinstance(market["volatility_pct"], float)
        assert isinstance(market["max_drawdown_pct"], float)
        assert market["history"]

    forbidden = {"pe", "pb", "erp", "crowding", "risk_list", "valuation"}
    assert forbidden.isdisjoint(overview)
    assert all(forbidden.isdisjoint(market) for market in overview["markets"])


def test_k_shape_winners_and_laggards_are_computed_from_current_data() -> None:
    overview = build_asia_radar_overview(_snapshot())

    assert overview["k_shape"]["winners"] == ["EPHE", "EWA", "EWM"]
    assert overview["k_shape"]["laggards"] == ["EWY", "EWT", "EWJ"]
    assert overview["k_shape"]["series"][-1]["spread_pct"] > 0

    ranks = {market["symbol"]: market["rank"] for market in overview["markets"]}
    assert ranks["EPHE"] == 1
    assert ranks["EWY"] == 12


def test_winners_flip_when_performance_flips() -> None:
    snapshot = _snapshot()
    for item in snapshot.series:
        symbol = item["symbol"]
        multiplier = -1.0 if symbol in {"EPHE", "EWA", "EWM"} else 1.0
        base = 100.0
        rows = []
        for index, row in enumerate(item["rows"]):
            if multiplier < 0:
                drift = -0.030 if symbol == "EPHE" else -0.020
                value = base * ((1.0 + drift) ** index)
            else:
                drift = 0.030 if symbol == "EWY" else 0.020
                value = base * ((1.0 + drift) ** index)
            rows.append({"date": row["date"], "close": round(value, 6)})
        item["rows"] = rows

    overview = build_asia_radar_overview(snapshot)
    assert "EPHE" in overview["k_shape"]["laggards"]
    assert "EWY" in overview["k_shape"]["winners"]


def test_rejects_sample_provenance() -> None:
    snapshot = _snapshot()
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
        build_asia_radar_overview(bad)


def test_rejects_partial_universe() -> None:
    snapshot = _snapshot()
    bad = HistoricalPriceSnapshot(
        provider=snapshot.provider,
        source=snapshot.source,
        interval=snapshot.interval,
        adjustment=snapshot.adjustment,
        start=snapshot.start,
        end=snapshot.end,
        fetched_at=snapshot.fetched_at,
        symbols=list(ASIA_ETF_SYMBOLS[:-1]),
        series=snapshot.series[:-1],
    )
    with pytest.raises(HistoricalPriceReadError):
        build_asia_radar_overview(bad)


def test_rejects_insufficient_history() -> None:
    snapshot = _snapshot(periods=10)
    with pytest.raises(HistoricalPriceReadError):
        build_asia_radar_overview(snapshot)


def test_aligns_to_shared_session_instead_of_max() -> None:
    snapshot = _snapshot()
    # Give EWY one extra future session; shared as_of must stay the common last date.
    extra = pd.bdate_range(snapshot.series[0]["rows"][-1]["date"], periods=2)[-1]
    snapshot.series[0]["rows"].append(
        {"date": extra.date().isoformat(), "close": 99.0}
    )
    overview = build_asia_radar_overview(snapshot)
    expected_as_of = snapshot.series[1]["rows"][-1]["date"]
    assert overview["as_of"] == expected_as_of
    assert all(
        market["meta"]["as_of"] == expected_as_of for market in overview["markets"]
    )
