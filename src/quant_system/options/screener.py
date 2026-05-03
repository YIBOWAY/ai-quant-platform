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
    scanned_expirations = _select_expirations(
        provider.fetch_option_expirations(plain_symbol),
        config=config,
    )
    option_type = "PUT" if config.strategy_type == "sell_put" else "CALL"
    underlying_snapshot = provider.fetch_underlying_snapshot(plain_symbol)
    underlying_price = _safe_float(
        underlying_snapshot.get("last")
        or underlying_snapshot.get("last_price")
        or underlying_snapshot.get("close")
    )
    if underlying_price is None or underlying_price <= 0:
        raise ValueError(f"underlying snapshot for {futu_symbol} has no valid price")

    history_start, history_end = _resolve_history_window(config)
    history = provider.fetch_ohlcv(
        [plain_symbol],
        start=history_start,
        end=history_end,
        interval="1d",
    )
    historical_volatility = _historical_volatility(history)
    trend_reference = _moving_average(history, window=20)
    trend_pass = _trend_pass(
        strategy_type=config.strategy_type,
        underlying_price=underlying_price,
        trend_reference=trend_reference,
    )
    avg_daily_volume = _average_volume(history, window=20)
    market_cap = _safe_float(
        underlying_snapshot.get("market_val")
        or underlying_snapshot.get("total_market_val")
    )
    rows = []
    option_quotes = _fetch_quotes_for_expirations(
        provider=provider,
        underlying=plain_symbol,
        expirations=scanned_expirations,
        option_type=option_type,
    )
    for row in option_quotes.to_dict(orient="records"):
        candidate = _build_candidate(
            row=row,
            config=config,
            underlying=futu_symbol,
            underlying_price=underlying_price,
            historical_volatility=historical_volatility,
            trend_pass=trend_pass,
            avg_daily_volume=avg_daily_volume,
            market_cap=market_cap,
        )
        rows.append(candidate)
    # Phase 12 fix: keep every row (including Avoid) so the UI/audit can show
    # why a contract was rejected. The sort ordering already pushes Avoid to
    # the bottom and `top_n` caps total output.
    ranked = sorted(
        rows,
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
        expiration=config.expiration,
        scanned_expirations=scanned_expirations,
        expiration_count=len(scanned_expirations),
        underlying_price=underlying_price,
        historical_volatility=historical_volatility,
        trend_reference=trend_reference,
        candidates=ranked[: config.top_n],
        assumptions=[
            "Read-only data mode; no order placement is available.",
            "When expiration is omitted, the screener scans all Futu expirations "
            "inside the configured DTE window.",
            "Premium uses mid price when bid and ask are available.",
            "Yield estimates are simplified and ignore assignment, taxes, and commissions.",
            "Missing IV/Greeks fields reduce confidence; they are not invented.",
        ],
    )


def _fetch_quotes_for_expirations(
    *,
    provider: FutuMarketDataProvider,
    underlying: str,
    expirations: list[str],
    option_type: str,
) -> pd.DataFrame:
    if len(expirations) == 1:
        return provider.fetch_option_quotes(
            underlying,
            expiration=expirations[0],
            option_type=option_type,
        )
    fetch_range = getattr(provider, "fetch_option_quotes_range", None)
    if callable(fetch_range):
        frames = []
        for chunk in _chunk_expirations_by_span(expirations, max_days=30):
            if len(chunk) == 1:
                frame = provider.fetch_option_quotes(
                    underlying,
                    expiration=chunk[0],
                    option_type=option_type,
                )
            else:
                frame = fetch_range(
                    underlying,
                    start_expiration=chunk[0],
                    end_expiration=chunk[-1],
                    option_type=option_type,
                )
            frames.append(frame.loc[frame["expiry"].astype(str).isin(chunk)])
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    rows = []
    for expiration in expirations:
        frame = provider.fetch_option_quotes(
            underlying,
            expiration=expiration,
            option_type=option_type,
        )
        rows.extend(frame.to_dict(orient="records"))
    return pd.DataFrame(rows)


def _chunk_expirations_by_span(expirations: list[str], *, max_days: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_start: pd.Timestamp | None = None
    for expiration in expirations:
        expiry_ts = pd.Timestamp(expiration)
        if not current or current_start is None:
            current = [expiration]
            current_start = expiry_ts
            continue
        if (expiry_ts - current_start).days <= max_days:
            current.append(expiration)
            continue
        chunks.append(current)
        current = [expiration]
        current_start = expiry_ts
    if current:
        chunks.append(current)
    return chunks


def _select_expirations(expirations: pd.DataFrame, *, config: OptionsScreenerConfig) -> list[str]:
    frame = expirations.copy()
    if frame.empty or "strike_time" not in frame.columns:
        raise ValueError("no option expiration is available")
    frame["strike_time"] = frame["strike_time"].astype(str)
    if config.expiration:
        selected = frame.loc[frame["strike_time"] == config.expiration]
        if selected.empty:
            raise ValueError(f"requested expiration is not available: {config.expiration}")
        return [config.expiration]
    if "option_expiry_date_distance" in frame.columns:
        distance = pd.to_numeric(frame["option_expiry_date_distance"], errors="coerce")
    else:
        distance = frame["strike_time"].map(_days_to_expiry)
    frame = frame.assign(_dte=distance)
    frame = frame.loc[
        frame["_dte"].notna()
        & (frame["_dte"] >= config.min_dte)
        & (frame["_dte"] <= config.max_dte)
    ]
    if frame.empty:
        raise ValueError("no option expiration is available inside the configured DTE window")
    ordered = frame.sort_values(["_dte", "strike_time"])["strike_time"].tolist()
    return [str(value) for value in ordered]


def _build_candidate(
    *,
    row: dict[str, object],
    config: OptionsScreenerConfig,
    underlying: str,
    underlying_price: float,
    historical_volatility: float | None,
    trend_pass: bool | None,
    avg_daily_volume: float | None,
    market_cap: float | None,
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
        avg_daily_volume=avg_daily_volume,
        market_cap=market_cap,
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
        avg_daily_volume=avg_daily_volume,
        market_cap=market_cap,
        iv_rank=None,           # Phase 13: filled by radar scanner using IV history
        earnings_date=None,     # Phase 13: filled by radar scanner using calendar source
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
    avg_daily_volume: float | None = None,
    market_cap: float | None = None,
) -> list[str]:
    notes: list[str] = []
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0:
        notes.append("missing or non-positive bid/ask")
    if mid is not None and mid < config.min_premium:
        notes.append("premium below minimum")
    if config.min_mid_price > 0 and (mid is None or mid < config.min_mid_price):
        notes.append("mid below absolute floor")
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
    if config.min_avg_daily_volume > 0:
        if avg_daily_volume is None:
            notes.append("underlying ADV missing")
        elif avg_daily_volume < config.min_avg_daily_volume:
            notes.append("underlying ADV below minimum")
    if config.min_market_cap > 0:
        if market_cap is None:
            notes.append("market cap missing")
        elif market_cap < config.min_market_cap:
            notes.append("market cap below minimum")
    return notes


# Hard failures => rating becomes "Avoid". These represent constraints that
# completely break the trade thesis (no quote, blown spread, wrong trend,
# expiry outside the user's window, delta past the user's risk cap).
HARD_FAILURES = frozenset(
    {
        "missing or non-positive bid/ask",
        "spread too wide",
        "trend filter failed",
        "IV/HV filter failed",
        "DTE outside range",
        "delta above limit",  # Phase 12 fix: delta is the core seller risk knob
        "open interest below minimum",
        "mid below absolute floor",
        "underlying ADV below minimum",
        "market cap below minimum",
    }
)


def _rating(notes: list[str]) -> str:
    if any(note in HARD_FAILURES for note in notes):
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
    # Futu can return option_implied_volatility as percentage (22.4) or decimal
    # (0.224) depending on the SDK build. Anything above 5.0 (i.e. >500% IV) is
    # treated as percentage and divided by 100. Real-world IV almost never
    # exceeds 5.0 in decimal form, so this threshold is safe and deterministic.
    if value > 5:
        return value / 100
    return value


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
    # Anchor to America/New_York so a Beijing-time post-close cron does not
    # produce off-by-one DTE values just because UTC has rolled over.
    expiry_ts = pd.Timestamp(expiry, tz="America/New_York").normalize()
    today = pd.Timestamp.now(tz="America/New_York").normalize()
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
    """Trend gate using the 20-day moving average as a proxy.

    - **sell_put** (collect premium below price): pass when price >= MA20,
      i.e. trend is up or flat. Selling puts into a strong downtrend
      maximizes assignment risk.
    - **covered_call** (cap upside on owned shares): pass when price <= MA20,
      i.e. trend is flat or weak. Selling calls into a strong uptrend caps
      gains exactly when the market is paying up.
    """
    if trend_reference is None or trend_reference <= 0:
        return None
    if strategy_type == "sell_put":
        return underlying_price >= trend_reference
    # covered_call: prefer non-overbought tape
    return underlying_price <= trend_reference


def _hv_iv_pass(iv: float | None, hv: float | None) -> bool | None:
    if iv is None or hv is None:
        return None
    return iv >= hv


def _resolve_history_window(config: OptionsScreenerConfig) -> tuple[str, str]:
    """Resolve the rolling [start, end] window for HV/MA/ADV computation.

    Defaults to (today - lookback_days, today). Explicit history_start/
    history_end on the config still take precedence for reproducibility in
    tests and audits.
    """
    if config.history_start and config.history_end:
        return config.history_start, config.history_end
    today = pd.Timestamp.now(tz="America/New_York").normalize()
    end = config.history_end or today.strftime("%Y-%m-%d")
    if config.history_start:
        return config.history_start, end
    start = (today - pd.Timedelta(days=config.history_lookback_days)).strftime(
        "%Y-%m-%d"
    )
    return start, end


def _average_volume(ohlcv: pd.DataFrame, *, window: int = 20) -> float | None:
    if ohlcv.empty or "volume" not in ohlcv.columns:
        return None
    volumes = pd.to_numeric(
        ohlcv.sort_values("timestamp")["volume"], errors="coerce"
    )
    sample = volumes.tail(window).dropna()
    if sample.empty:
        return None
    value = float(sample.mean())
    return value if not math.isnan(value) else None
