from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant_system.config.settings import Settings
from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
    read_historical_prices,
)

# Phase 1.5: preset baskets only. No user-defined persistence, no write paths.
BASKETS: dict[str, dict[str, Any]] = {
    "ai_watch": {
        "label_en": "AI / semis watch",
        "label_zh": "AI / 半导体关注",
        "symbols": (
            "SPY",
            "QQQ",
            "SOXX",
            "IGV",
            "SMH",
            "NVDA",
            "MSFT",
            "GOOGL",
            "AMZN",
            "META",
            "AAPL",
            "TSLA",
        ),
    },
    "us_sectors": {
        "label_en": "US sector ETFs",
        "label_zh": "美股板块 ETF",
        "symbols": (
            "SPY",
            "XLB",
            "XLE",
            "XLF",
            "XLI",
            "XLK",
            "XLP",
            "XLU",
            "XLV",
            "XLY",
            "XLC",
            "XLRE",
        ),
    },
}

METHODOLOGY = {
    "week": "5 trading sessions",
    "month": "21 trading sessions",
    "ytd": "calendar year first available close through latest shared session",
    "volatility": "63-session annualized realized volatility",
    "drawdown": "calendar-year maximum drawdown through latest shared session",
}

TIMEZONE = "America/New_York"
_NEW_YORK = ZoneInfo(TIMEZONE)
_SESSION_CLOSE = time(16, 0)
_MIN_HISTORY_BARS = 64
_SPARKLINE_BARS = 90
_LOOKBACK_CALENDAR_DAYS = 419
_MAX_CUSTOM_SYMBOLS = 16
# Custom symbols must be plain US tickers (letters/digits only, no dots).
# FutuMarketDataProvider.normalize_symbol rejects dotted codes such as BRK.B
# for plain US market data and rewrites US.-prefixed codes — accepting either
# here would fail downstream or desync the universe from the price snapshot.
# So the whitelist rejects them up front with an explicit 400 instead of
# pretending to support them. Full-string match, not a first-character check.
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{1,12}")


def read_market_cross_section(
    *,
    settings: Settings,
    basket: str | None = None,
    symbols: list[str] | None = None,
    today: date | None = None,
    now: datetime | None = None,
    cache: EquityBarCache | None | bool = True,
    cache_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read a preset/custom symbol cross-section from strict Futu data."""
    universe, basket_id, basket_label = _resolve_universe(basket=basket, symbols=symbols)
    clock = now or datetime.now(tz=UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    active_day = today or _last_completed_us_session(clock)
    start_day = active_day - timedelta(days=_LOOKBACK_CALENDAR_DAYS)

    active_cache = _resolve_cache(cache=cache, cache_path=cache_path, settings=settings)
    snapshot = read_historical_prices(
        settings=settings,
        symbols=list(universe),
        start=start_day.isoformat(),
        end=active_day.isoformat(),
        provider="futu",
        interval="1d",
        adjustment="qfq",
        cache=active_cache,
    )
    return build_market_cross_section(
        snapshot,
        universe=universe,
        basket_id=basket_id,
        basket_label=basket_label,
        session_end=active_day,
    )


def build_market_cross_section(
    snapshot: HistoricalPriceSnapshot,
    *,
    universe: tuple[str, ...],
    basket_id: str | None,
    basket_label: dict[str, str] | None,
    session_end: date | None = None,
) -> dict[str, Any]:
    _validate_snapshot(snapshot, universe)
    closes_by_symbol = {
        item["symbol"]: _series_frame(item) for item in snapshot.series
    }
    aligned, as_of = _align_to_shared_session(closes_by_symbol, session_end=session_end)
    ranked = sorted(
        universe,
        key=lambda symbol: (-_ytd_return(aligned[symbol]), symbol),
    )
    ranks = {symbol: index + 1 for index, symbol in enumerate(ranked)}
    provenance = "futu_cache" if snapshot.source == "futu_cache" else "futu"

    rows = [
        _symbol_payload(
            symbol,
            aligned[symbol],
            rank=ranks[symbol],
            adjustment=snapshot.adjustment,
            provenance=provenance,
        )
        for symbol in universe
    ]
    return {
        "schema_version": "1.0",
        "provider": "futu",
        "as_of": as_of,
        "timezone": TIMEZONE,
        "fetched_at": snapshot.fetched_at,
        "provenance": provenance,
        "basket": basket_id,
        "basket_label": basket_label,
        "methodology": dict(METHODOLOGY),
        "rows": rows,
    }


def _resolve_universe(
    *,
    basket: str | None,
    symbols: list[str] | None,
) -> tuple[tuple[str, ...], str | None, dict[str, str] | None]:
    if symbols is not None and basket is not None:
        raise _invalid_request("pass either basket or symbols, not both")
    if symbols is not None:
        cleaned = []
        for raw in symbols:
            symbol = raw.upper().strip()
            if _SYMBOL_PATTERN.fullmatch(symbol) is None:
                raise _invalid_request(f"invalid symbol {raw!r}")
            if symbol not in cleaned:
                cleaned.append(symbol)
        if not cleaned:
            raise _invalid_request("at least one symbol is required")
        if len(cleaned) > _MAX_CUSTOM_SYMBOLS:
            raise _invalid_request(
                f"custom cross-section is limited to {_MAX_CUSTOM_SYMBOLS} symbols"
            )
        return tuple(cleaned), None, None

    basket_id = (basket or "ai_watch").lower().strip()
    if basket_id not in BASKETS:
        raise _invalid_request(f"unknown basket {basket!r}")
    entry = BASKETS[basket_id]
    return (
        entry["symbols"],
        basket_id,
        {"en": entry["label_en"], "zh": entry["label_zh"]},
    )


def _resolve_cache(
    *,
    cache: EquityBarCache | None | bool,
    cache_path: str | Path | None,
    settings: Settings,
) -> EquityBarCache | None:
    if cache is False or cache is None:
        return None
    if isinstance(cache, EquityBarCache):
        return cache
    path = Path(cache_path) if cache_path is not None else Path(settings.data.duckdb_path)
    if cache_path is None:
        path = path.parent / "futu_equity_bars.duckdb"
    try:
        return EquityBarCache(path, ttl_seconds=86_400.0)
    except Exception:  # noqa: BLE001 - optional cache must never block live Futu
        return None


def _last_completed_us_session(now: datetime) -> date:
    local = now.astimezone(_NEW_YORK)
    candidate = local.date()
    if local.weekday() >= 5 or local.time() < _SESSION_CLOSE:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _validate_snapshot(snapshot: HistoricalPriceSnapshot, universe: tuple[str, ...]) -> None:
    if snapshot.provider != "futu" or snapshot.source not in {"futu", "futu_cache"}:
        _invalid_contract("Market cross-section requires live Futu provenance")
    if snapshot.interval != "1d" or snapshot.adjustment != "qfq":
        _invalid_contract("Market cross-section requires Futu 1d QFQ history")
    if tuple(snapshot.symbols) != universe:
        _invalid_contract("Market cross-section history must match the requested universe")
    if [item.get("symbol") for item in snapshot.series] != list(universe):
        _invalid_contract("Market cross-section series order does not match the universe")


def _invalid_contract(message: str) -> None:
    raise HistoricalPriceReadError(
        code="market_cross_section_contract_invalid",
        message=message,
        provider="futu",
    )


def _invalid_request(message: str) -> HistoricalPriceReadError:
    return HistoricalPriceReadError(
        code="market_cross_section_invalid_request",
        message=message,
        provider="futu",
    )


def _series_frame(item: dict[str, Any]) -> pd.Series:
    rows = item.get("rows")
    if not isinstance(rows, list) or len(rows) < _MIN_HISTORY_BARS:
        _invalid_contract(
            f"Market cross-section has insufficient history for {item.get('symbol')} "
            f"(need >= {_MIN_HISTORY_BARS} sessions)"
        )
    frame = pd.DataFrame(rows)
    if set(frame.columns) != {"date", "close"}:
        _invalid_contract(f"Market cross-section history is invalid for {item.get('symbol')}")
    try:
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise HistoricalPriceReadError(
            code="market_cross_section_contract_invalid",
            message=f"Market cross-section history is invalid for {item.get('symbol')}",
            provider="futu",
        ) from exc
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        _invalid_contract(f"Market cross-section dates are invalid for {item.get('symbol')}")
    return pd.Series(frame["close"].to_numpy(dtype=float), index=frame["date"])


def _align_to_shared_session(
    closes_by_symbol: dict[str, pd.Series],
    *,
    session_end: date | None,
) -> tuple[dict[str, pd.Series], str]:
    last_dates = {symbol: series.index[-1].date() for symbol, series in closes_by_symbol.items()}
    shared = min(last_dates.values())
    if session_end is not None and shared > session_end:
        shared = session_end
    aligned: dict[str, pd.Series] = {}
    for symbol, series in closes_by_symbol.items():
        truncated = series[series.index.date <= shared]
        if len(truncated) < _MIN_HISTORY_BARS:
            _invalid_contract(
                f"Market cross-section shared session {shared.isoformat()} leaves "
                f"insufficient history for {symbol}"
            )
        if truncated.index[-1].date() != shared:
            _invalid_contract(
                f"Market cross-section missing shared session {shared.isoformat()} for {symbol}"
            )
        aligned[symbol] = truncated
    return aligned, shared.isoformat()


def _symbol_payload(
    symbol: str,
    closes: pd.Series,
    *,
    rank: int,
    adjustment: str,
    provenance: str,
) -> dict[str, Any]:
    as_of = closes.index[-1].date().isoformat()
    current_year = closes[closes.index.year == closes.index[-1].year]
    if current_year.empty:
        _invalid_contract(f"Market cross-section has no YTD history for {symbol}")
    daily_returns = closes.pct_change().dropna().tail(63)
    if len(daily_returns) < 20:
        _invalid_contract(f"Market cross-section has insufficient volatility window for {symbol}")
    volatility = float(daily_returns.std(ddof=1) * np.sqrt(252) * 100)
    drawdown = current_year / current_year.cummax() - 1.0
    spark = closes.tail(_SPARKLINE_BARS)
    first_close = float(spark.iloc[0])
    history = [
        {
            "date": timestamp.date().isoformat(),
            "close": round(float(close), 6),
            "indexed_return_pct": _round_pct(float(close) / first_close - 1.0),
        }
        for timestamp, close in spark.items()
    ]
    return {
        "symbol": symbol,
        "rank": rank,
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
            "timezone": TIMEZONE,
            "as_of": as_of,
            "adjustment": adjustment,
            "provenance": provenance,
        },
    }


def _period_return(closes: pd.Series, sessions: int) -> float:
    if len(closes) <= sessions:
        _invalid_contract(
            f"Market cross-section needs more than {sessions} sessions for period return"
        )
    baseline_index = len(closes) - sessions - 1
    return _round_pct(float(closes.iloc[-1] / closes.iloc[baseline_index] - 1.0))


def _ytd_return(closes: pd.Series) -> float:
    latest_year = closes.index[-1].year
    current_year = closes[closes.index.year == latest_year]
    if current_year.empty:
        return 0.0
    return float(current_year.iloc[-1] / current_year.iloc[0] - 1.0)


def _round_pct(value: float) -> float:
    return round(value * 100.0, 4)
