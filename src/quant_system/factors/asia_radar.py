from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from quant_system.config.settings import Settings
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
    read_historical_prices,
)

ASIA_ETF_SYMBOLS = (
    "EWY",
    "EWT",
    "EWJ",
    "ASHR",
    "INDA",
    "EIDO",
    "EWH",
    "EWS",
    "THD",
    "EWM",
    "EWA",
    "EPHE",
)

_MARKETS = {
    "EWY": ("south-korea", "South Korea", "韩国"),
    "EWT": ("taiwan", "Taiwan", "中国台湾"),
    "EWJ": ("japan", "Japan", "日本"),
    "ASHR": ("china-a", "China A-shares", "中国 A 股"),
    "INDA": ("india", "India", "印度"),
    "EIDO": ("indonesia", "Indonesia", "印度尼西亚"),
    "EWH": ("hong-kong", "Hong Kong", "中国香港"),
    "EWS": ("singapore", "Singapore", "新加坡"),
    "THD": ("thailand", "Thailand", "泰国"),
    "EWM": ("malaysia", "Malaysia", "马来西亚"),
    "EWA": ("australia", "Australia", "澳大利亚"),
    "EPHE": ("philippines", "Philippines", "菲律宾"),
}

METHODOLOGY = {
    "week": "5 trading sessions",
    "month": "21 trading sessions",
    "ytd": "calendar year",
    "volatility": "63-session annualized realized volatility",
    "drawdown": "calendar-year maximum drawdown",
    "k_shape": "daily YTD cross-sectional top/bottom quartiles",
}


def read_asia_radar_overview(
    *, settings: Settings, today: date | None = None
) -> dict[str, Any]:
    """Read the fixed Asia ETF universe from live Futu and calculate Phase 1 metrics."""
    active_day = today or date.today()
    start_day = active_day - timedelta(days=419)
    snapshot = read_historical_prices(
        settings=settings,
        symbols=list(ASIA_ETF_SYMBOLS),
        start=start_day.isoformat(),
        end=active_day.isoformat(),
        provider="futu",
        interval="1d",
        adjustment="qfq",
        cache=None,
    )
    return build_asia_radar_overview(snapshot)


def build_asia_radar_overview(
    snapshot: HistoricalPriceSnapshot,
) -> dict[str, Any]:
    _validate_snapshot(snapshot)
    closes_by_symbol = {
        item["symbol"]: _series_frame(item) for item in snapshot.series
    }
    ranked = sorted(
        ASIA_ETF_SYMBOLS,
        key=lambda symbol: (
            -_ytd_return(closes_by_symbol[symbol]),
            symbol,
        ),
    )
    ranks = {symbol: index + 1 for index, symbol in enumerate(ranked)}
    winners = ranked[:3]
    laggards = ranked[-3:][::-1]

    markets = [
        _market_payload(
            symbol,
            closes_by_symbol[symbol],
            rank=ranks[symbol],
            leg=(
                "winner"
                if symbol in winners
                else "laggard"
                if symbol in laggards
                else "middle"
            ),
            adjustment=snapshot.adjustment,
        )
        for symbol in ASIA_ETF_SYMBOLS
    ]
    as_of = max(market["meta"]["as_of"] for market in markets)
    return {
        "schema_version": "1.0",
        "provider": "futu",
        "as_of": as_of,
        "fetched_at": snapshot.fetched_at,
        "methodology": dict(METHODOLOGY),
        "markets": markets,
        "k_shape": {
            "winners": winners,
            "laggards": laggards,
            "series": _dynamic_k_shape_series(closes_by_symbol, as_of),
        },
    }


def _validate_snapshot(snapshot: HistoricalPriceSnapshot) -> None:
    if snapshot.provider != "futu" or snapshot.source != "futu":
        _invalid_contract("Asia Radar requires live Futu provenance")
    if snapshot.interval != "1d" or snapshot.adjustment != "qfq":
        _invalid_contract("Asia Radar requires Futu 1d QFQ history")
    if tuple(snapshot.symbols) != ASIA_ETF_SYMBOLS:
        _invalid_contract("Asia Radar history must contain the exact 12 ETF universe")
    if [item.get("symbol") for item in snapshot.series] != list(ASIA_ETF_SYMBOLS):
        _invalid_contract("Asia Radar series order does not match the ETF universe")


def _invalid_contract(message: str) -> None:
    raise HistoricalPriceReadError(
        code="asia_radar_contract_invalid",
        message=message,
        provider="futu",
    )


def _series_frame(item: dict[str, Any]) -> pd.Series:
    rows = item.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        _invalid_contract(f"Asia Radar has insufficient history for {item.get('symbol')}")
    frame = pd.DataFrame(rows)
    if set(frame.columns) != {"date", "close"}:
        _invalid_contract(f"Asia Radar history is invalid for {item.get('symbol')}")
    try:
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise HistoricalPriceReadError(
            code="asia_radar_contract_invalid",
            message=f"Asia Radar history is invalid for {item.get('symbol')}",
            provider="futu",
        ) from exc
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        _invalid_contract(f"Asia Radar dates are invalid for {item.get('symbol')}")
    return pd.Series(frame["close"].to_numpy(dtype=float), index=frame["date"])


def _market_payload(
    symbol: str,
    closes: pd.Series,
    *,
    rank: int,
    leg: str,
    adjustment: str,
) -> dict[str, Any]:
    as_of = closes.index[-1].date().isoformat()
    current_year = closes[closes.index.year == closes.index[-1].year]
    if current_year.empty:
        _invalid_contract(f"Asia Radar has no YTD history for {symbol}")
    daily_returns = closes.pct_change().dropna().tail(63)
    volatility = (
        float(daily_returns.std(ddof=1) * np.sqrt(252) * 100)
        if len(daily_returns) >= 2
        else 0.0
    )
    drawdown = current_year / current_year.cummax() - 1.0
    market_id, name_en, name_zh = _MARKETS[symbol]
    first_close = float(closes.iloc[0])
    history = [
        {
            "date": timestamp.date().isoformat(),
            "close": round(float(close), 6),
            "indexed_return_pct": _round_pct(float(close) / first_close - 1.0),
        }
        for timestamp, close in closes.items()
    ]
    return {
        "market_id": market_id,
        "name_en": name_en,
        "name_zh": name_zh,
        "symbol": symbol,
        "data_status": "real",
        "market_coverage": "proxy",
        "rank": rank,
        "k_leg": leg,
        "returns": {
            "week_pct": _period_return(closes, 5),
            "month_pct": _period_return(closes, 21),
            "ytd_pct": _round_pct(_ytd_return(closes)),
        },
        "volatility_pct": round(volatility, 4),
        "max_drawdown_pct": _round_pct(float(drawdown.min())),
        "history": history,
        "meta": {
            "provider": "futu",
            "symbol": symbol,
            "currency": "USD",
            "as_of": as_of,
            "adjustment": adjustment,
        },
    }


def _period_return(closes: pd.Series, sessions: int) -> float:
    baseline_index = max(0, len(closes) - sessions - 1)
    return _round_pct(float(closes.iloc[-1] / closes.iloc[baseline_index] - 1.0))


def _ytd_return(closes: pd.Series) -> float:
    latest_year = closes.index[-1].year
    current_year = closes[closes.index.year == latest_year]
    if current_year.empty:
        return 0.0
    return float(current_year.iloc[-1] / current_year.iloc[0] - 1.0)


def _dynamic_k_shape_series(
    closes_by_symbol: dict[str, pd.Series], as_of: str
) -> list[dict[str, Any]]:
    aligned = pd.concat(closes_by_symbol, axis=1, join="inner").dropna()
    current_year = aligned[aligned.index.year == date.fromisoformat(as_of).year]
    if current_year.empty:
        return []
    returns = current_year.divide(current_year.iloc[0]).subtract(1.0)
    result = []
    for timestamp, row in returns.iterrows():
        ordered = sorted(
            ASIA_ETF_SYMBOLS,
            key=lambda symbol: (-float(row[symbol]), symbol),
        )
        winner_average = float(row[ordered[:3]].mean())
        laggard_average = float(row[ordered[-3:]].mean())
        result.append(
            {
                "date": timestamp.date().isoformat(),
                "winner_avg_pct": _round_pct(winner_average),
                "laggard_avg_pct": _round_pct(laggard_average),
                "spread_pct": _round_pct(winner_average - laggard_average),
            }
        )
    return result


def _round_pct(value: float) -> float:
    return round(value * 100.0, 4)

