from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from quant_system.data.price_history import HistoricalPriceSnapshot
from quant_system.factors.asia_radar import ASIA_ETF_SYMBOLS, build_asia_radar_overview


def _snapshot() -> HistoricalPriceSnapshot:
    dates = pd.bdate_range("2025-12-31", periods=33)
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
    assert overview["as_of"] == "2026-02-13"
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
            "as_of": "2026-02-13",
            "adjustment": "qfq",
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
