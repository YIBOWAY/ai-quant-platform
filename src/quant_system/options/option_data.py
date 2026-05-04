from __future__ import annotations

import math
from typing import Literal, cast

import pandas as pd
from pydantic import BaseModel, Field

OptionSide = Literal["CALL", "PUT"]


class NormalizedOptionRecord(BaseModel):
    """Normalized read-only option quote for research modules.

    The record is intentionally data-only. It carries no order, routing, or
    execution semantics.
    """

    symbol: str
    underlying: str | None = None
    option_type: OptionSide | None = None
    expiry: str | None = None
    strike: float | None = None
    update_time: str | None = None
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    mid: float | None = None
    volume: float | None = None
    turnover: float | None = None
    open_interest: float | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    contract_size: float | None = None
    data_quality_warnings: list[str] = Field(default_factory=list)


def normalize_option_records(
    frame: pd.DataFrame,
    *,
    stale_after_minutes: int | None = None,
    now: pd.Timestamp | None = None,
) -> list[NormalizedOptionRecord]:
    """Convert provider option quote rows into stable research records."""

    if frame.empty:
        return []
    rows = []
    for raw in frame.to_dict(orient="records"):
        bid = _safe_float(raw.get("bid"))
        ask = _safe_float(raw.get("ask"))
        record = NormalizedOptionRecord(
            symbol=_normalize_option_symbol(raw.get("symbol")),
            underlying=_safe_string(raw.get("underlying")),
            option_type=_normalize_option_type(raw.get("option_type")),
            expiry=_safe_string(raw.get("expiry")),
            strike=_safe_float(raw.get("strike")),
            update_time=_safe_string(raw.get("update_time")),
            last=_safe_float(raw.get("last")),
            bid=bid,
            ask=ask,
            bid_size=_safe_float(raw.get("bid_size")),
            ask_size=_safe_float(raw.get("ask_size")),
            mid=_mid_price(bid, ask),
            volume=_safe_float(raw.get("volume")),
            turnover=_safe_float(raw.get("turnover")),
            open_interest=_safe_float(raw.get("open_interest")),
            implied_volatility=_normalize_volatility(
                _safe_float(raw.get("implied_volatility"))
            ),
            delta=_safe_float(raw.get("delta")),
            gamma=_safe_float(raw.get("gamma")),
            theta=_safe_float(raw.get("theta")),
            vega=_safe_float(raw.get("vega")),
            rho=_safe_float(raw.get("rho")),
            contract_size=_safe_float(raw.get("contract_size")),
        )
        record.data_quality_warnings = _quality_warnings(
            record,
            stale_after_minutes=stale_after_minutes,
            now=now,
        )
        rows.append(record)
    return rows


def _quality_warnings(
    record: NormalizedOptionRecord,
    *,
    stale_after_minutes: int | None,
    now: pd.Timestamp | None,
) -> list[str]:
    warnings: list[str] = []
    if record.bid is None or record.ask is None:
        warnings.append("missing_bid_ask")
    elif record.bid <= 0 or record.ask <= 0 or record.ask < record.bid:
        warnings.append("invalid_bid_ask")
    if record.implied_volatility is None:
        warnings.append("missing_iv")
    for greek in ("delta", "gamma", "theta", "vega", "rho"):
        if getattr(record, greek) is None:
            warnings.append(f"missing_{greek}")
    if record.open_interest is None:
        warnings.append("missing_open_interest")
    elif record.open_interest <= 0:
        warnings.append("zero_open_interest")
    if record.volume is None:
        warnings.append("missing_volume")
    elif record.volume <= 0:
        warnings.append("zero_volume")
    if record.contract_size is None:
        warnings.append("missing_contract_size")
    if _is_stale_quote(
        record.update_time,
        stale_after_minutes=stale_after_minutes,
        now=now,
    ):
        warnings.append("stale_quote")
    return warnings


def _normalize_option_symbol(value: object) -> str:
    symbol = _safe_string(value)
    if not symbol:
        raise ValueError("option symbol is required")
    return symbol.upper()


def _normalize_option_type(value: object) -> OptionSide | None:
    option_type = _safe_string(value)
    if option_type is None:
        return None
    normalized = option_type.upper()
    if normalized in {"CALL", "PUT"}:
        return cast(OptionSide, normalized)
    return None


def _safe_string(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _mid_price(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2


def _normalize_volatility(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100 if value > 5 else value


def _is_stale_quote(
    update_time: str | None,
    *,
    stale_after_minutes: int | None,
    now: pd.Timestamp | None,
) -> bool:
    if stale_after_minutes is None or stale_after_minutes <= 0 or update_time is None:
        return False
    quote_ts = _coerce_timestamp(update_time)
    if quote_ts is None:
        return False
    reference = now if now is not None else pd.Timestamp.now(tz="UTC")
    if reference.tzinfo is None:
        reference = reference.tz_localize("UTC")
    else:
        reference = reference.tz_convert("UTC")
    return (reference - quote_ts) > pd.Timedelta(minutes=stale_after_minutes)


def _coerce_timestamp(value: str) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp
