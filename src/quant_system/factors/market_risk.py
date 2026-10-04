"""Observable market pressure from price history, not a crash probability model."""

from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from quant_system.options.seller_score import is_us_market_session, latest_us_market_session

_THRESHOLDS = {
    "trend_200d": 0.0,
    "drawdown_252d": -10.0,
    "vix_level": 30.0,
    "vix_change": 20.0,
    "vix_term": 1.0,
}
_EXTENSION_PCT = 15.0


def _session_age(observed: date, expected: date) -> int:
    return sum(
        is_us_market_session(observed + timedelta(days=offset))
        for offset in range(1, (expected - observed).days + 1)
    )


def _observation(
    key: str,
    *,
    symbol: str,
    source: str,
    as_of: str | None,
    value: float | None = None,
    status: str = "unavailable",
    reason: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "symbol": symbol,
        "source": source,
        "as_of": as_of,
        "value": round(value, 4) if value is not None else None,
        "status": status,
        "reason": reason,
        "threshold": _THRESHOLDS[key],
    }


def build_market_risk(
    closes_by_symbol: dict[str, pd.Series],
    *,
    expected_session: date,
    price_source: str,
    daily_vix: pd.Series | None = None,
    daily_vix3m: pd.Series | None = None,
    vix_error: bool = False,
) -> dict[str, Any]:
    """Use complete windows and explicit source dates; missing inputs stay unknown."""
    observations = []
    for symbol in ("SPY", "QQQ"):
        closes = closes_by_symbol.get(symbol, pd.Series(dtype=float))
        as_of = closes.index[-1].date().isoformat() if len(closes) else None
        fresh = bool(
            as_of
            and date.fromisoformat(as_of) <= expected_session
            and is_us_market_session(date.fromisoformat(as_of))
            and _session_age(date.fromisoformat(as_of), expected_session) <= 1
        )
        valid = len(closes) > 0 and all(isfinite(float(value)) and value > 0 for value in closes)
        for key, required in (("trend_200d", 200), ("drawdown_252d", 252)):
            reason = "price_stale" if not fresh else "insufficient_history"
            if not valid:
                reason = "invalid_price" if len(closes) else "benchmark_not_in_basket"
            value = None
            status = "unavailable"
            if fresh and valid and len(closes) >= required:
                baseline = (
                    float(closes.tail(200).mean())
                    if key == "trend_200d"
                    else float(closes.tail(252).max())
                )
                value = round((float(closes.iloc[-1]) / baseline - 1) * 100, 4)
                if key == "trend_200d":
                    status = "attention" if value < _THRESHOLDS[key] else "normal"
                    reason = (
                        "below_200dma"
                        if value < _THRESHOLDS[key]
                        else "extended_above_200dma"
                        if value > _EXTENSION_PCT
                        else "above_200dma"
                    )
                else:
                    status = "attention" if value <= _THRESHOLDS[key] else "normal"
                    reason = (
                        "drawdown_pressure"
                        if value <= _THRESHOLDS[key]
                        else "drawdown_below_threshold"
                    )
            observations.append(
                _observation(
                    key,
                    symbol=symbol,
                    source=price_source,
                    as_of=as_of,
                    value=value,
                    status=status,
                    reason=reason,
                )
            )

    def current(series: pd.Series | None) -> tuple[pd.Series, str | None, str | None]:
        if series is None or series.empty:
            return (
                pd.Series(dtype=float),
                None,
                "vix_cache_unreadable" if vix_error else "missing_history",
            )
        eligible = series.loc[series.index.date <= expected_session].sort_index()
        if eligible.empty:
            return eligible, None, "missing_history"
        latest_date = eligible.index[-1].date()
        as_of = latest_date.isoformat()
        if (
            eligible.index.duplicated().any()
            or not isfinite(float(eligible.iloc[-1]))
            or eligible.iloc[-1] <= 0
        ):
            return eligible, as_of, "invalid_observation"
        if not is_us_market_session(latest_date) or _session_age(latest_date, expected_session) > 1:
            return eligible, as_of, "volatility_stale"
        return eligible, as_of, None

    vix, vix_date, vix_reason = current(daily_vix)
    vix3m, vix3m_date, vix3m_reason = current(daily_vix3m)
    level = float(vix.iloc[-1]) if vix_reason is None else None
    observations.append(
        _observation(
            "vix_level",
            symbol="VIX",
            source="public_cache",
            as_of=vix_date,
            value=level,
            status="unavailable"
            if level is None
            else "attention"
            if level >= _THRESHOLDS["vix_level"]
            else "normal",
            reason=vix_reason
            or (
                "volatility_elevated"
                if level >= _THRESHOLDS["vix_level"]
                else "volatility_below_threshold"
            ),
        )
    )
    change = None
    change_reason = vix_reason or "insufficient_history"
    if vix_reason is None and len(vix) >= 2:
        previous_date = latest_us_market_session(date.fromisoformat(vix_date) - timedelta(days=1))
        previous = float(vix.iloc[-2])
        if vix.index[-2].date() == previous_date and isfinite(previous) and previous > 0:
            change = round((level / previous - 1) * 100, 4)
            change_reason = (
                "volatility_rising"
                if change >= _THRESHOLDS["vix_change"]
                else "volatility_change_below_threshold"
            )
        else:
            change_reason = "nonconsecutive_sessions"
    observations.append(
        _observation(
            "vix_change",
            symbol="VIX",
            source="public_cache",
            as_of=vix_date,
            value=change,
            status="unavailable"
            if change is None
            else "attention"
            if change >= _THRESHOLDS["vix_change"]
            else "normal",
            reason=change_reason,
        )
    )
    ratio = None
    ratio_reason = vix_reason or vix3m_reason
    if ratio_reason is None and vix_date != vix3m_date:
        ratio_reason = "session_mismatch"
    if ratio_reason is None:
        ratio = level / float(vix3m.iloc[-1])
        ratio_reason = "term_inverted" if ratio >= _THRESHOLDS["vix_term"] else "term_upward"
    observations.append(
        _observation(
            "vix_term",
            symbol="VIX / VIX3M",
            source="public_cache",
            as_of=vix3m_date,
            value=ratio,
            status="unavailable"
            if ratio is None
            else "attention"
            if ratio >= _THRESHOLDS["vix_term"]
            else "normal",
            reason=ratio_reason,
        )
    )
    attention_count = sum(item["status"] == "attention" for item in observations)
    unavailable_count = sum(item["status"] == "unavailable" for item in observations)
    return {
        "status": "attention"
        if attention_count
        else "unavailable"
        if unavailable_count or not observations
        else "normal",
        "expected_session": expected_session.isoformat(),
        "trend_extension_pct": _EXTENSION_PCT,
        "attention_count": attention_count,
        "unavailable_count": unavailable_count,
        "observations": observations,
    }
