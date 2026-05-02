from __future__ import annotations

import math

import pandas as pd

from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.options.models import (
    OptionsScreenerCandidate,
    OptionsScreenerConfig,
    OptionsScreenerResult,
)


def run_options_screener(
    *,
    provider: FutuMarketDataProvider,
    config: OptionsScreenerConfig,
) -> OptionsScreenerResult:
    plain_symbol, futu_symbol = provider.normalize_symbol(config.ticker)
    expiration = config.expiration or _select_nearest_expiration(
        provider.fetch_option_expirations(plain_symbol)
    )
    option_type = "PUT" if config.strategy_type == "sell_put" else "CALL"
    option_quotes = provider.fetch_option_quotes(
        plain_symbol,
        expiration=expiration,
        option_type=option_type,
    )
    underlying_snapshot = provider.fetch_underlying_snapshot(plain_symbol)
    underlying_price = _safe_float(
        underlying_snapshot.get("last")
        or underlying_snapshot.get("last_price")
        or underlying_snapshot.get("close")
    )
    if underlying_price is None or underlying_price <= 0:
        raise ValueError(f"underlying snapshot for {futu_symbol} has no valid price")

    history = provider.fetch_ohlcv(
        [plain_symbol],
        start=config.history_start,
        end=config.history_end,
        interval="1d",
    )
    historical_volatility = _historical_volatility(history)
    trend_reference = _moving_average(history, window=20)
    trend_pass = _trend_pass(
        strategy_type=config.strategy_type,
        underlying_price=underlying_price,
        trend_reference=trend_reference,
    )
    rows = []
    for row in option_quotes.to_dict(orient="records"):
        candidate = _build_candidate(
            row=row,
            config=config,
            underlying=futu_symbol,
            underlying_price=underlying_price,
            historical_volatility=historical_volatility,
            trend_pass=trend_pass,
        )
        rows.append(candidate)
    filtered = [
        candidate
        for candidate in rows
        if candidate.rating != "Avoid"
        or (candidate.bid is not None and candidate.ask is not None)
    ]
    ranked = sorted(
        filtered,
        key=lambda item: (
            {"Strong": 0, "Watch": 1, "Avoid": 2}[item.rating],
            -(item.annualized_yield or 0.0),
            item.spread_pct if item.spread_pct is not None else math.inf,
        ),
    )
    return OptionsScreenerResult(
        ticker=plain_symbol,
        provider="futu",
        strategy_type=config.strategy_type,
        expiration=expiration,
        underlying_price=underlying_price,
        historical_volatility=historical_volatility,
        trend_reference=trend_reference,
        candidates=ranked[:50],
        assumptions=[
            "Read-only data mode; no order placement is available.",
            "Premium uses mid price when bid and ask are available.",
            "Yield estimates are simplified and ignore assignment, taxes, and commissions.",
            "Missing IV/Greeks fields reduce confidence; they are not invented.",
        ],
    )


def _select_nearest_expiration(expirations: pd.DataFrame) -> str:
    frame = expirations.copy()
    if "option_expiry_date_distance" in frame.columns:
        frame = frame.loc[pd.to_numeric(frame["option_expiry_date_distance"], errors="coerce") >= 0]
    if frame.empty:
        raise ValueError("no non-expired option expiration is available")
    return str(frame.sort_values("strike_time").iloc[0]["strike_time"])


def _build_candidate(
    *,
    row: dict[str, object],
    config: OptionsScreenerConfig,
    underlying: str,
    underlying_price: float,
    historical_volatility: float | None,
    trend_pass: bool | None,
) -> OptionsScreenerCandidate:
    bid = _safe_float(row.get("bid"))
    ask = _safe_float(row.get("ask"))
    mid = _mid_price(bid, ask)
    strike = _safe_float(row.get("strike")) or 0.0
    expiry = str(row.get("expiry"))
    dte = _days_to_expiry(expiry)
    spread_pct = _spread_pct(bid, ask, mid)
    iv = _safe_float(row.get("implied_volatility"))
    delta = _safe_float(row.get("delta"))
    open_interest = _safe_float(row.get("open_interest"))
    iv = _normalize_volatility(iv)
    hv_iv_ratio = _hv_iv_ratio(historical_volatility, iv)
    hv_iv_pass = (
        hv_iv_ratio is not None and hv_iv_ratio <= config.max_hv_iv
        if config.hv_iv_filter
        else None
    )
    option_type = "PUT" if config.strategy_type == "sell_put" else "CALL"
    distance = _distance_pct(
        strategy_type=config.strategy_type,
        underlying_price=underlying_price,
        strike=strike,
    )
    annualized_yield = _annualized_yield(
        strategy_type=config.strategy_type,
        mid=mid,
        strike=strike,
        underlying_price=underlying_price,
        days_to_expiry=dte,
    )
    notes = _candidate_notes(
        config=config,
        bid=bid,
        ask=ask,
        mid=mid,
        spread_pct=spread_pct,
        iv=iv,
        delta=delta,
        annualized_yield=annualized_yield,
        days_to_expiry=dte,
        open_interest=open_interest,
        trend_pass=trend_pass,
        hv_iv_pass=hv_iv_pass,
    )
    rating = _rating(notes)
    return OptionsScreenerCandidate(
        symbol=str(row.get("symbol")),
        underlying=underlying,
        strategy_type=config.strategy_type,
        option_type=option_type,
        expiry=expiry,
        strike=strike,
        underlying_price=underlying_price,
        bid=bid,
        ask=ask,
        mid=mid,
        volume=_safe_float(row.get("volume")),
        open_interest=open_interest,
        implied_volatility=iv,
        historical_volatility=historical_volatility,
        hv_iv_ratio=hv_iv_ratio,
        delta=delta,
        gamma=_safe_float(row.get("gamma")),
        theta=_safe_float(row.get("theta")),
        vega=_safe_float(row.get("vega")),
        premium_per_contract=mid * 100 if mid is not None else None,
        moneyness=strike / underlying_price if underlying_price else None,
        distance_pct=distance,
        days_to_expiry=dte,
        annualized_yield=annualized_yield,
        spread_pct=spread_pct,
        trend_pass=trend_pass,
        hv_iv_pass=hv_iv_pass,
        rating=rating,
        notes=notes,
    )


def _candidate_notes(
    *,
    config: OptionsScreenerConfig,
    bid: float | None,
    ask: float | None,
    mid: float | None,
    spread_pct: float | None,
    iv: float | None,
    delta: float | None,
    annualized_yield: float | None = None,
    days_to_expiry: int | None = None,
    open_interest: float | None = None,
    trend_pass: bool | None,
    hv_iv_pass: bool | None,
) -> list[str]:
    notes: list[str] = []
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0:
        notes.append("missing or non-positive bid/ask")
    if mid is not None and mid < config.min_premium:
        notes.append("premium below minimum")
    if spread_pct is None or spread_pct > config.max_spread_pct:
        notes.append("spread too wide")
    if annualized_yield is None or annualized_yield * 100 < config.min_apr:
        notes.append("APR below minimum")
    if days_to_expiry is None:
        notes.append("DTE missing")
    elif days_to_expiry < config.min_dte or days_to_expiry > config.max_dte:
        notes.append("DTE outside range")
    if open_interest is None:
        notes.append("open interest missing")
    elif open_interest < config.min_open_interest:
        notes.append("open interest below minimum")
    if iv is None:
        notes.append("IV missing")
    elif iv < config.min_iv:
        notes.append("IV below minimum")
    if delta is None:
        notes.append("delta missing")
    elif abs(delta) > config.max_delta:
        notes.append("delta above limit")
    if config.trend_filter and trend_pass is False:
        notes.append("trend filter failed")
    if config.hv_iv_filter and hv_iv_pass is False:
        notes.append("IV/HV filter failed")
    return notes


def _rating(notes: list[str]) -> str:
    hard_failures = {
        "missing or non-positive bid/ask",
        "spread too wide",
        "trend filter failed",
        "IV/HV filter failed",
        "DTE outside range",
    }
    if any(note in hard_failures for note in notes):
        return "Avoid"
    if notes:
        return "Watch"
    return "Strong"


def _safe_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _normalize_volatility(value: float | None) -> float | None:
    if value is None:
        return None
    # Futu may return option_implied_volatility as either 0.224 or 22.4.
    # Internally the platform uses decimal volatility, so 22.4 becomes 0.224.
    return value / 100 if value > 2 else value


def _hv_iv_ratio(hv: float | None, iv: float | None) -> float | None:
    if hv is None or iv is None or iv <= 0:
        return None
    return hv / iv


def _mid_price(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2


def _spread_pct(bid: float | None, ask: float | None, mid: float | None) -> float | None:
    if bid is None or ask is None or mid is None or mid <= 0:
        return None
    return (ask - bid) / mid


def _distance_pct(
    *,
    strategy_type: str,
    underlying_price: float,
    strike: float,
) -> float | None:
    if underlying_price <= 0:
        return None
    if strategy_type == "sell_put":
        return (underlying_price - strike) / underlying_price
    return (strike - underlying_price) / underlying_price


def _annualized_yield(
    *,
    strategy_type: str,
    mid: float | None,
    strike: float,
    underlying_price: float,
    days_to_expiry: int | None,
) -> float | None:
    if mid is None or days_to_expiry is None or days_to_expiry <= 0:
        return None
    base = strike if strategy_type == "sell_put" else underlying_price
    if base <= 0:
        return None
    return (mid / base) * (365 / days_to_expiry)


def _days_to_expiry(expiry: str) -> int | None:
    expiry_ts = pd.Timestamp(expiry, tz="UTC")
    today = pd.Timestamp.now(tz="UTC").normalize()
    return max(int((expiry_ts - today).days), 0)


def _historical_volatility(ohlcv: pd.DataFrame, *, window: int = 20) -> float | None:
    if len(ohlcv) < 2:
        return None
    closes = pd.to_numeric(ohlcv.sort_values("timestamp")["close"], errors="coerce")
    returns = closes.pct_change().dropna()
    if returns.empty:
        return None
    sample = returns.tail(window)
    volatility = sample.std(ddof=0) * math.sqrt(252)
    return float(volatility) if not pd.isna(volatility) else None


def _moving_average(ohlcv: pd.DataFrame, *, window: int = 20) -> float | None:
    if ohlcv.empty:
        return None
    closes = pd.to_numeric(ohlcv.sort_values("timestamp")["close"], errors="coerce")
    average = closes.tail(window).mean()
    return float(average) if not pd.isna(average) else None


def _trend_pass(
    *,
    strategy_type: str,
    underlying_price: float,
    trend_reference: float | None,
) -> bool | None:
    if trend_reference is None:
        return None
    if strategy_type == "sell_put":
        return underlying_price >= trend_reference
    return underlying_price >= trend_reference


def _hv_iv_pass(iv: float | None, hv: float | None) -> bool | None:
    if iv is None or hv is None:
        return None
    return iv >= hv
