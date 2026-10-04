from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.options.iv_history import (
    IV_MEASURE_ATM30_STRADDLE_V1,
    compute_iv_rank,
    load_atm30_straddle_iv,
    option_contract_identity_matches,
    resolve_atm30_straddle_iv,
    resolve_trusted_underlying_quote,
)
from quant_system.options.iv_units import (
    IV_UNIT_RATIO,
    declare_unit,
    frame_unit,
    to_ratio,
)
from quant_system.options.screener import calculate_historical_volatility
from quant_system.options.seller_score import resolve_recommendation_quote


@dataclass(frozen=True)
class BuySideMarketInputs:
    option_chain: pd.DataFrame
    iv_rank: float
    iv_measure: str
    historical_volatility: float


@dataclass(frozen=True)
class BuySideUnderlyingQuote:
    ticker: str
    spot_price: float
    quote_as_of: str
    quote_session: str


def resolve_buy_side_underlying_quote(
    snapshot: dict[str, object],
    *,
    ticker: str,
    market_session: date,
    observed_at: str,
) -> BuySideUnderlyingQuote:
    try:
        quote = resolve_trusted_underlying_quote(
            snapshot,
            ticker=ticker,
            market_session=market_session,
            observed_at=observed_at,
        )
    except ValueError as exc:
        raise ValueError("buy_side_market_data_unavailable: " + str(exc)) from exc
    return BuySideUnderlyingQuote(
        ticker=quote.ticker,
        spot_price=quote.spot_price,
        quote_as_of=quote.quote_as_of,
        quote_session=quote.quote_session,
    )


def load_buy_side_market_inputs(
    *,
    provider: FutuMarketDataProvider,
    ticker: str,
    option_chain: pd.DataFrame,
    spot_price: float,
    market_session: date,
    option_chain_observed_at: str,
    iv_history_dir: str | Path,
) -> BuySideMarketInputs:
    normalized_chain = validate_buy_side_option_chain(
        option_chain,
        ticker=ticker,
        market_session=market_session,
        observed_at=option_chain_observed_at,
    )
    iv_observation = load_atm30_straddle_iv(
        provider,
        ticker=ticker,
        spot_price=spot_price,
        market_session=market_session,
    )
    history = provider.fetch_ohlcv(
        [ticker],
        start=(pd.Timestamp(market_session) - pd.Timedelta(days=90)).date().isoformat(),
        end=market_session.isoformat(),
        interval="1d",
    )
    observed_hv = calculate_historical_volatility(history)
    iv_rank = compute_iv_rank(
        ticker,
        iv_observation.current_iv,
        history_dir=iv_history_dir,
        measure=iv_observation.measure,
        as_of_session=market_session,
    )
    missing = []
    if observed_hv is None or observed_hv <= 0:
        missing.append("historical_volatility")
    if iv_rank is None:
        missing.append("iv_rank")
    if missing:
        raise ValueError("buy_side_volatility_data_unavailable: missing " + ", ".join(missing))
    return BuySideMarketInputs(
        option_chain=normalized_chain,
        iv_rank=float(iv_rank),
        iv_measure=iv_observation.measure,
        historical_volatility=float(observed_hv),
    )


def validate_buy_side_option_chain(
    option_chain: pd.DataFrame,
    *,
    ticker: str,
    market_session: date,
    observed_at: str,
) -> pd.DataFrame:
    required = {
        "symbol",
        "underlying",
        "option_type",
        "expiry",
        "strike",
        "bid",
        "ask",
        "implied_volatility",
        "update_time",
    }
    missing = sorted(required.difference(option_chain.columns))
    if missing:
        raise ValueError(
            "buy_side_market_data_unavailable: missing_option_columns " + ", ".join(missing)
        )
    normalized_ticker = ticker.upper().strip().removeprefix("US.")
    frame = normalize_buy_side_option_chain(option_chain)
    canonical_times: list[str] = []
    for row in frame.to_dict(orient="records"):
        underlying = str(row.get("underlying") or "").upper().strip()
        if underlying.removeprefix(
            "US."
        ) != normalized_ticker or not option_contract_identity_matches(
            row, ticker=normalized_ticker
        ):
            raise ValueError("buy_side_market_data_unavailable: option_symbol_mismatch")
        resolution = resolve_recommendation_quote(
            run_date=market_session.isoformat(),
            quote_as_of=str(row.get("update_time") or ""),
            observed_at=observed_at,
        )
        if resolution.reason is not None or resolution.canonical_as_of is None:
            raise ValueError(
                "buy_side_market_data_unavailable: option_"
                + (resolution.reason or "quote_session_invalid")
            )
        canonical_times.append(resolution.canonical_as_of)
    frame["update_time"] = canonical_times
    for field in ("strike", "bid", "ask", "implied_volatility"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce").map(
            lambda value: (
                value
                if value is not None and pd.notna(value) and math.isfinite(float(value))
                else None
            )
        )
    frame = frame.loc[
        frame["strike"].notna()
        & (frame["strike"] > 0)
        & frame["bid"].notna()
        & (frame["bid"] > 0)
        & frame["ask"].notna()
        & (frame["ask"] >= frame["bid"])
        & frame["implied_volatility"].notna()
        & (frame["implied_volatility"] > 0)
    ].copy()
    if frame.empty:
        raise ValueError("buy_side_market_data_unavailable: option_quote_invalid")
    candidate_fields = ("delta", "gamma", "theta", "vega", "open_interest", "volume")
    missing_candidate_columns = [field for field in candidate_fields if field not in frame.columns]
    if missing_candidate_columns:
        raise ValueError(
            "buy_side_market_data_unavailable: missing_candidate_columns "
            + ", ".join(missing_candidate_columns)
        )
    calls = frame.loc[frame["option_type"].astype(str).str.upper() == "CALL"].copy()
    for field in candidate_fields:
        calls[field] = pd.to_numeric(calls[field], errors="coerce").map(
            lambda value: (
                value
                if value is not None and pd.notna(value) and math.isfinite(float(value))
                else None
            )
        )
    greek_fields = ("delta", "gamma", "theta", "vega")
    calls = calls.loc[calls[list(greek_fields)].notna().all(axis=1)].copy()
    if calls.empty:
        raise ValueError("buy_side_market_data_unavailable: candidate_greeks_missing")
    calls = calls.loc[
        calls[["open_interest", "volume"]].notna().all(axis=1)
        & (calls[["open_interest", "volume"]] > 0).all(axis=1)
    ].copy()
    if calls.empty:
        raise ValueError("buy_side_market_data_unavailable: candidate_liquidity_missing")
    puts = frame.loc[frame["option_type"].astype(str).str.upper() == "PUT"].copy()
    if calls.merge(puts, on=["expiry", "strike"]).empty:
        raise ValueError("buy_side_market_data_unavailable: atm_pair_missing")
    return pd.concat([calls, puts], axis=0).sort_index().reset_index(drop=True)


def buy_side_atm_implied_volatility(
    option_chain: pd.DataFrame,
    *,
    spot_price: float,
    as_of: date,
) -> float:
    try:
        observation = resolve_atm30_straddle_iv(
            normalize_buy_side_option_chain(option_chain),
            spot_price=spot_price,
            market_session=as_of,
        )
    except ValueError as exc:
        raise ValueError("buy_side_volatility_data_unavailable: " + str(exc)) from exc
    if observation.measure != IV_MEASURE_ATM30_STRADDLE_V1:
        raise ValueError("buy_side_volatility_data_unavailable: iv_measure_invalid")
    return observation.current_iv


def normalize_buy_side_option_chain(option_chain: pd.DataFrame) -> pd.DataFrame:
    if "implied_volatility" not in option_chain.columns:
        raise ValueError(
            "buy_side_volatility_data_unavailable: missing option columns implied_volatility"
        )
    frame = option_chain.copy()
    raw = pd.to_numeric(frame["implied_volatility"], errors="coerce")
    unit = frame_unit(option_chain)
    frame["implied_volatility"] = raw.map(
        lambda value: to_ratio(value, unit=unit) if pd.notna(value) else None
    )
    return declare_unit(frame, IV_UNIT_RATIO)


__all__ = [
    "BuySideMarketInputs",
    "BuySideUnderlyingQuote",
    "buy_side_atm_implied_volatility",
    "load_buy_side_market_inputs",
    "normalize_buy_side_option_chain",
    "resolve_buy_side_underlying_quote",
    "validate_buy_side_option_chain",
]
