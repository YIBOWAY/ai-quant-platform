from __future__ import annotations

from dataclasses import dataclass
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
    ProviderBuilder,
    read_historical_prices,
)
from quant_system.data.provider_factory import build_ohlcv_provider

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
    "ytd": "calendar year first available close through latest shared session",
    "volatility": "63-session annualized realized volatility",
    "drawdown": "calendar-year maximum drawdown through latest shared session",
    "k_shape": "daily YTD cross-sectional top-three / bottom-three baskets",
}

TIMEZONE = "America/New_York"
_SESSION_CLOSE = time(16, 0)
_MIN_HISTORY_BARS = 64
_MIN_LOCAL_INDEX_BARS = 20
_SPARKLINE_BARS = 90
_LOOKBACK_CALENDAR_DAYS = 419


@dataclass(frozen=True)
class LocalIndexSpec:
    """Whitelisted local index verified against the local Futu OpenD."""

    market_id: str
    symbol: str
    name_en: str
    name_zh: str
    currency: str
    timezone: str
    session_close: time


# Slice 2A: only Hong Kong and Japan have verified local-index channels
# (2026-08-11 OpenD probe). Local indices are a display-only comparison lane:
# they are never blended into the USD ETF proxy metrics.
LOCAL_INDEX_SPECS: tuple[LocalIndexSpec, ...] = (
    LocalIndexSpec(
        market_id="hong-kong",
        symbol="HK.800000",
        name_en="Hang Seng Index",
        name_zh="恒生指数",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        session_close=time(16, 0),
    ),
    LocalIndexSpec(
        market_id="japan",
        symbol="JP..N225",
        name_en="Nikkei 225",
        name_zh="日经 225 指数",
        currency="JPY",
        timezone="Asia/Tokyo",
        session_close=time(15, 0),
    ),
)

# Honest pending state for the other ten markets:
# (reason_code, reason, intended index name en/zh when one is known).
LOCAL_INDEX_PENDING: dict[str, tuple[str, str, str | None, str | None]] = {
    "china-a": (
        "permission_not_granted",
        "Futu account has no A-share index quote permission; "
        "CSI 300 (SH.000300) unlocks once the permission is enabled in Futu.",
        "CSI 300",
        "沪深300",
    ),
    "south-korea": (
        "market_format_unsupported",
        "Futu OpenD does not support KS market codes; "
        "KOSPI awaits a Twelve Data/KRX channel.",
        "KOSPI",
        "KOSPI 指数",
    ),
    "taiwan": (
        "market_format_unsupported",
        "Futu OpenD does not support TW market codes; "
        "TAIEX awaits the keyless TWSE channel (Slice 2B).",
        "TAIEX",
        "台湾加权指数",
    ),
    "india": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "indonesia": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "singapore": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "thailand": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "malaysia": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "australia": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
    "philippines": (
        "no_verified_channel",
        "No verified local index channel for this market yet.",
        None,
        None,
    ),
}

LocalIndexOverlayReader = Any  # callable(settings=, now=, cache=) -> dict[str, dict]


def read_asia_radar_summary(
    *,
    settings: Settings,
    today: date | None = None,
    now: datetime | None = None,
    cache: EquityBarCache | None | bool = True,
    cache_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read a compact Asia Radar summary from the same fail-closed Futu path.

    Intended for daily-brief / notification surfaces. Contains no valuation
    estimates and no narrative text.
    """
    overview = read_asia_radar_overview(
        settings=settings,
        today=today,
        now=now,
        cache=cache,
        cache_path=cache_path,
        # The summary payload only carries ETF fields, so skip the local-index
        # overlay lane entirely and keep this surface single-context.
        local_index_reader=lambda **_: {},
    )
    return build_asia_radar_summary(overview)


def build_asia_radar_summary(overview: dict[str, Any]) -> dict[str, Any]:
    markets = overview.get("markets", [])
    market_summaries = [
        {
            "symbol": market["symbol"],
            "market_id": market["market_id"],
            "name_en": market["name_en"],
            "name_zh": market["name_zh"],
            "rank": market["rank"],
            "k_leg": market["k_leg"],
            "ytd_pct": market["returns"]["ytd_pct"],
            "week_pct": market["returns"]["week_pct"],
            "month_pct": market["returns"]["month_pct"],
            "volatility_pct": market["volatility_pct"],
            "max_drawdown_pct": market["max_drawdown_pct"],
            "as_of": market["meta"]["as_of"],
        }
        for market in markets
    ]
    k_shape = overview.get("k_shape", {})
    latest_spread = None
    series = k_shape.get("series") or []
    if series:
        latest_spread = series[-1].get("spread_pct")
    ranked_markets = sorted(markets, key=lambda market: market["rank"])
    top = ranked_markets[0] if ranked_markets else None
    bottom = ranked_markets[-1] if ranked_markets else None
    return {
        "schema_version": "1.1",
        "provider": overview["provider"],
        "as_of": overview["as_of"],
        "timezone": overview["timezone"],
        "fetched_at": overview["fetched_at"],
        "provenance": overview["provenance"],
        "status": "available",
        "market_count": len(market_summaries),
        "winner_symbols": k_shape.get("winners", []),
        "laggard_symbols": k_shape.get("laggards", []),
        "spread_pct": latest_spread,
        "top_ytd_symbol": top["symbol"] if top else None,
        "top_ytd_pct": top["returns"]["ytd_pct"] if top else None,
        "bottom_ytd_symbol": bottom["symbol"] if bottom else None,
        "bottom_ytd_pct": bottom["returns"]["ytd_pct"] if bottom else None,
        "markets": market_summaries,
    }


def read_asia_radar_overview(
    *,
    settings: Settings,
    today: date | None = None,
    now: datetime | None = None,
    cache: EquityBarCache | None | bool = True,
    cache_path: str | Path | None = None,
    local_index_reader: LocalIndexOverlayReader | None = None,
) -> dict[str, Any]:
    """Read the fixed Asia ETF universe from Futu (with optional bar cache).

    Calculates Phase 1 metrics, then attaches per-market local-index overlays
    (Slice 2A). Overlay failures degrade only the affected market's
    ``local_index`` field; the ETF main path keeps its existing fail-closed
    503 contract.
    """
    clock = now or datetime.now(tz=UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    active_day = today or _last_completed_us_session(clock)
    start_day = active_day - timedelta(days=_LOOKBACK_CALENDAR_DAYS)

    active_cache = _resolve_cache(cache=cache, cache_path=cache_path, settings=settings)
    snapshot = read_historical_prices(
        settings=settings,
        symbols=list(ASIA_ETF_SYMBOLS),
        start=start_day.isoformat(),
        end=active_day.isoformat(),
        provider="futu",
        interval="1d",
        adjustment="qfq",
        cache=active_cache,
    )
    overview = build_asia_radar_overview(snapshot, session_end=active_day)
    overlay_reader = local_index_reader or read_local_index_overlays
    try:
        overlays = overlay_reader(settings=settings, now=clock, cache=active_cache)
    except Exception:  # noqa: BLE001 - index lane must never 503 the ETF main path
        overlays = {}
    return attach_local_index_overlays(overview, overlays)


def read_local_index_overlays(
    *,
    settings: Settings,
    now: datetime | None = None,
    cache: EquityBarCache | None = None,
    provider_builder: ProviderBuilder = build_ohlcv_provider,
) -> dict[str, dict[str, Any]]:
    """Read whitelisted local indices (HK/JP) for the Asia Radar index tab.

    Display-only lane: every one of the 12 markets gets an explicit overlay —
    available ones carry real Futu series, the rest an honest pending or
    provider-error reason. This reader never raises.
    """
    clock = now or datetime.now(tz=UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    specs = {spec.market_id: spec for spec in LOCAL_INDEX_SPECS}
    overlays: dict[str, dict[str, Any]] = {}
    for market_id, _name_en, _name_zh in _MARKETS.values():
        spec = specs.get(market_id)
        if spec is None:
            overlays[market_id] = _pending_local_index_overlay(market_id)
            continue
        overlays[market_id] = _read_local_index_overlay(
            spec,
            settings=settings,
            clock=clock,
            cache=cache,
            provider_builder=provider_builder,
        )
    return overlays


def attach_local_index_overlays(
    overview: dict[str, Any],
    overlays: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach local-index overlays after ETF metrics are computed.

    This is the single integration point between the two lanes: index series
    never enter ``build_asia_radar_overview`` (returns/volatility/drawdown/
    K-shape), so no cross-currency or cross-calendar metric can be mixed.
    """
    for market in overview.get("markets", []):
        overlay = overlays.get(market.get("market_id"))
        if overlay is None:
            overlay = _local_index_overlay_base()
            overlay.update(
                {
                    "reason_code": "overlay_missing",
                    "reason": "Local index overlay was not loaded for this market.",
                }
            )
        market["local_index"] = overlay
    overview["schema_version"] = "1.2"
    return overview


def _read_local_index_overlay(
    spec: LocalIndexSpec,
    *,
    settings: Settings,
    clock: datetime,
    cache: EquityBarCache | None,
    provider_builder: ProviderBuilder,
) -> dict[str, Any]:
    try:
        end_day = _last_completed_local_session(clock, spec.timezone, spec.session_close)
        start_day = end_day - timedelta(days=_LOOKBACK_CALENDAR_DAYS)
        snapshot = read_historical_prices(
            settings=settings,
            symbols=[spec.symbol],
            start=start_day.isoformat(),
            end=end_day.isoformat(),
            provider="futu",
            interval="1d",
            adjustment="qfq",
            provider_builder=provider_builder,
            cache=cache,
            allow_local_markets=True,
        )
    except HistoricalPriceReadError as exc:
        return _error_local_index_overlay(
            spec,
            reason=exc.message,
            provider_code=exc.provider_code or exc.code,
        )
    except Exception as exc:  # noqa: BLE001 - overlay lane must never break the ETF path
        return _error_local_index_overlay(
            spec,
            reason=f"local index read failed: {type(exc).__name__}",
            provider_code=type(exc).__name__,
        )
    rows = snapshot.series[0]["rows"]
    if len(rows) < _MIN_LOCAL_INDEX_BARS:
        return _error_local_index_overlay(
            spec,
            reason=(
                f"local index history too short: {len(rows)} bars "
                f"(need >= {_MIN_LOCAL_INDEX_BARS})"
            ),
            provider_code="insufficient_history",
        )
    display = rows[-_SPARKLINE_BARS:]
    first_close = float(display[0]["close"])
    series = [
        {
            "date": row["date"],
            "close": round(float(row["close"]), 6),
            "indexed_return_pct": _round_pct(float(row["close"]) / first_close - 1.0),
        }
        for row in display
    ]
    return {
        "status": "available",
        "index_symbol": spec.symbol,
        "index_name_en": spec.name_en,
        "index_name_zh": spec.name_zh,
        "currency": spec.currency,
        "timezone": spec.timezone,
        "as_of": rows[-1]["date"],
        "provider": "futu",
        "provenance": "futu_cache" if snapshot.source == "futu_cache" else "futu",
        "fetched_at": snapshot.fetched_at,
        "adjustment": snapshot.adjustment,
        "series": series,
        "reason_code": None,
        "reason": None,
        "provider_code": None,
    }


def _local_index_overlay_base() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "index_symbol": None,
        "index_name_en": None,
        "index_name_zh": None,
        "currency": None,
        "timezone": None,
        "as_of": None,
        "provider": None,
        "provenance": None,
        "fetched_at": None,
        "adjustment": None,
        "series": [],
        "reason_code": None,
        "reason": None,
        "provider_code": None,
    }


def _pending_local_index_overlay(market_id: str) -> dict[str, Any]:
    reason_code, reason, name_en, name_zh = LOCAL_INDEX_PENDING[market_id]
    overlay = _local_index_overlay_base()
    overlay.update(
        {
            "index_name_en": name_en,
            "index_name_zh": name_zh,
            "reason_code": reason_code,
            "reason": reason,
        }
    )
    return overlay


def _error_local_index_overlay(
    spec: LocalIndexSpec,
    *,
    reason: str,
    provider_code: str,
) -> dict[str, Any]:
    overlay = _local_index_overlay_base()
    overlay.update(
        {
            "index_symbol": spec.symbol,
            "index_name_en": spec.name_en,
            "index_name_zh": spec.name_zh,
            "currency": spec.currency,
            "timezone": spec.timezone,
            "provider": "futu",
            "reason_code": "provider_error",
            "reason": reason,
            "provider_code": provider_code,
        }
    )
    return overlay


def build_asia_radar_overview(
    snapshot: HistoricalPriceSnapshot,
    *,
    session_end: date | None = None,
) -> dict[str, Any]:
    _validate_snapshot(snapshot)
    closes_by_symbol = {
        item["symbol"]: _series_frame(item) for item in snapshot.series
    }
    aligned, as_of = _align_to_shared_session(closes_by_symbol, session_end=session_end)
    ranked = sorted(
        ASIA_ETF_SYMBOLS,
        key=lambda symbol: (
            -_ytd_return(aligned[symbol]),
            symbol,
        ),
    )
    ranks = {symbol: index + 1 for index, symbol in enumerate(ranked)}
    winners = ranked[:3]
    laggards = ranked[-3:][::-1]
    provenance = "futu_cache" if snapshot.source == "futu_cache" else "futu"

    markets = [
        _market_payload(
            symbol,
            aligned[symbol],
            rank=ranks[symbol],
            leg=(
                "winner"
                if symbol in winners
                else "laggard"
                if symbol in laggards
                else "middle"
            ),
            adjustment=snapshot.adjustment,
            provenance=provenance,
        )
        for symbol in ASIA_ETF_SYMBOLS
    ]
    return {
        "schema_version": "1.1",
        "provider": "futu",
        "as_of": as_of,
        "timezone": TIMEZONE,
        "fetched_at": snapshot.fetched_at,
        "provenance": provenance,
        "methodology": dict(METHODOLOGY),
        "markets": markets,
        "k_shape": {
            "winners": winners,
            "laggards": laggards,
            "series": _dynamic_k_shape_series(aligned, as_of),
        },
    }


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
    # Keep equity bars in a sibling file so the main research duckdb stays clean.
    if cache_path is None:
        path = path.parent / "futu_equity_bars.duckdb"
    try:
        return EquityBarCache(path, ttl_seconds=86_400.0)
    except Exception:  # noqa: BLE001 - optional cache must never block live Futu
        return None


def _last_completed_us_session(now: datetime) -> date:
    return _last_completed_local_session(now, TIMEZONE, _SESSION_CLOSE)


def _last_completed_local_session(
    now: datetime,
    timezone: str,
    session_close: time,
) -> date:
    local = now.astimezone(ZoneInfo(timezone))
    candidate = local.date()
    if local.weekday() >= 5 or local.time() < session_close:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _validate_snapshot(snapshot: HistoricalPriceSnapshot) -> None:
    if snapshot.provider != "futu" or snapshot.source not in {"futu", "futu_cache"}:
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
    if not isinstance(rows, list) or len(rows) < _MIN_HISTORY_BARS:
        _invalid_contract(
            f"Asia Radar has insufficient history for {item.get('symbol')} "
            f"(need >= {_MIN_HISTORY_BARS} sessions)"
        )
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
                f"Asia Radar shared session {shared.isoformat()} leaves "
                f"insufficient history for {symbol}"
            )
        if truncated.index[-1].date() != shared:
            _invalid_contract(
                f"Asia Radar missing shared session {shared.isoformat()} for {symbol}"
            )
        aligned[symbol] = truncated
    return aligned, shared.isoformat()


def _market_payload(
    symbol: str,
    closes: pd.Series,
    *,
    rank: int,
    leg: str,
    adjustment: str,
    provenance: str,
) -> dict[str, Any]:
    as_of = closes.index[-1].date().isoformat()
    current_year = closes[closes.index.year == closes.index[-1].year]
    if current_year.empty:
        _invalid_contract(f"Asia Radar has no YTD history for {symbol}")
    daily_returns = closes.pct_change().dropna().tail(63)
    if len(daily_returns) < 20:
        _invalid_contract(f"Asia Radar has insufficient volatility window for {symbol}")
    volatility = float(daily_returns.std(ddof=1) * np.sqrt(252) * 100)
    drawdown = current_year / current_year.cummax() - 1.0
    market_id, name_en, name_zh = _MARKETS[symbol]
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
            "timezone": TIMEZONE,
            "as_of": as_of,
            "adjustment": adjustment,
            "provenance": provenance,
        },
    }


def _period_return(closes: pd.Series, sessions: int) -> float:
    if len(closes) <= sessions:
        _invalid_contract(
            f"Asia Radar needs more than {sessions} sessions for period return"
        )
    baseline_index = len(closes) - sessions - 1
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
