from __future__ import annotations

import math
from typing import Any, Literal

import pandas as pd

OptionType = Literal["call", "put"]
Action = Literal["buy", "sell"]


def calculate_greeks(
    *,
    spot: float,
    strike: float,
    expiry_days: int,
    iv: float,
    option_type: OptionType,
    rate: float = 0.04,
) -> dict[str, float]:
    option_type = _normalize_option_type(option_type)
    price = black_scholes_price(
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        iv=iv,
        option_type=option_type,
        rate=rate,
    )
    if expiry_days <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        intrinsic_delta = 1.0 if option_type == "call" and spot > strike else 0.0
        if option_type == "put":
            intrinsic_delta = -1.0 if spot < strike else 0.0
        return {
            "price": price,
            "delta": intrinsic_delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "charm": 0.0,
            "vanna": 0.0,
            "volga": 0.0,
        }

    t = expiry_days / 365.0
    sqrt_t = math.sqrt(t)
    d1 = _d1(spot=spot, strike=strike, expiry_years=t, iv=iv, rate=rate)
    d2 = d1 - iv * sqrt_t
    pdf = _norm_pdf(d1)
    if option_type == "call":
        delta = _norm_cdf(d1)
        theta_year = (
            -(spot * pdf * iv) / (2 * sqrt_t)
            - rate * strike * math.exp(-rate * t) * _norm_cdf(d2)
        )
        rho = strike * t * math.exp(-rate * t) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1
        theta_year = (
            -(spot * pdf * iv) / (2 * sqrt_t)
            + rate * strike * math.exp(-rate * t) * _norm_cdf(-d2)
        )
        rho = -strike * t * math.exp(-rate * t) * _norm_cdf(-d2)

    gamma = pdf / (spot * iv * sqrt_t)
    theta = theta_year / 365.0
    vega = spot * pdf * sqrt_t / 100.0
    vanna = -pdf * d2 / iv
    volga = spot * pdf * sqrt_t * d1 * d2 / iv / 100.0 if iv else 0.0
    charm = _charm(
        spot=spot,
        strike=strike,
        expiry_years=t,
        iv=iv,
        rate=rate,
        option_type=option_type,
    )
    return {
        "price": round(price, 6),
        "delta": round(delta, 9),
        "gamma": round(gamma, 9),
        "theta": round(theta, 9),
        "vega": round(vega, 9),
        "rho": round(rho / 100.0, 9),
        "charm": round(charm, 9),
        "vanna": round(vanna, 9),
        "volga": round(volga, 9),
    }


def black_scholes_price(
    *,
    spot: float,
    strike: float,
    expiry_days: int,
    iv: float,
    option_type: OptionType,
    rate: float = 0.04,
) -> float:
    option_type = _normalize_option_type(option_type)
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if expiry_days <= 0 or iv <= 0:
        if option_type == "call":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)
    t = expiry_days / 365.0
    sqrt_t = math.sqrt(t)
    d1 = _d1(spot=spot, strike=strike, expiry_years=t, iv=iv, rate=rate)
    d2 = d1 - iv * sqrt_t
    discounted_strike = strike * math.exp(-rate * t)
    if option_type == "call":
        return spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2)
    return discounted_strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_volatility(
    *,
    market_price: float,
    spot: float,
    strike: float,
    expiry_days: int,
    option_type: OptionType,
    rate: float = 0.04,
) -> float:
    option_type = _normalize_option_type(option_type)
    if not all(math.isfinite(value) for value in (market_price, spot, strike, rate)):
        raise ValueError("market_price, spot, strike, and rate must be finite")
    if market_price <= 0:
        raise ValueError("market_price must be positive")
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if expiry_days <= 0:
        raise ValueError("expiry_days must be positive")

    lower_bound, upper_bound = _option_price_bounds(
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        option_type=option_type,
        rate=rate,
    )
    tolerance = 1e-9
    if market_price < lower_bound - tolerance:
        raise ValueError(
            f"market_price is below no-arbitrage lower bound ({lower_bound:.6f})"
        )
    if market_price > upper_bound + tolerance:
        raise ValueError(
            f"market_price is above no-arbitrage upper bound ({upper_bound:.6f})"
        )

    low = 0.0001
    high = 5.0
    for _ in range(100):
        mid = (low + high) / 2
        price = black_scholes_price(
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            iv=mid,
            option_type=option_type,
            rate=rate,
        )
        if price > market_price:
            high = mid
        else:
            low = mid
    return round((low + high) / 2, 6)


def _option_price_bounds(
    *,
    spot: float,
    strike: float,
    expiry_days: int,
    option_type: OptionType,
    rate: float,
) -> tuple[float, float]:
    t = expiry_days / 365.0
    discounted_strike = strike * math.exp(-rate * t)
    if option_type == "call":
        return max(spot - discounted_strike, 0.0), spot
    return max(discounted_strike - spot, 0.0), discounted_strike


def simulate_option_position(
    *,
    symbol: str,
    spot: float,
    legs: list[dict[str, Any]],
    price_steps: int = 25,
    rate: float = 0.04,
) -> dict[str, Any]:
    normalized_legs = [_normalize_leg(leg, spot=spot, rate=rate) for leg in legs]
    strikes = [float(leg["strike"]) for leg in normalized_legs]
    lower = 0.0
    upper = max([spot * 1.5, *(strike * 1.5 for strike in strikes)])
    price_axis = [
        round(lower + (upper - lower) * index / max(price_steps - 1, 1), 4)
        for index in range(price_steps)
    ]
    price_axis = sorted({*price_axis, round(spot, 4), *(round(item, 4) for item in strikes)})
    pnl_axis = [round(_expiry_pnl(price, normalized_legs), 4) for price in price_axis]
    breakevens = _breakevens(price_axis, pnl_axis)
    max_profit, max_loss = _bounded_profit_loss(normalized_legs, pnl_axis)
    return {
        "ticker": symbol.upper().strip(),
        "price": spot,
        "position": {"legs": normalized_legs, "net_debit": _net_debit(normalized_legs)},
        "pnl_at_expiry": {"price_axis": price_axis, "pnl_axis": pnl_axis},
        "breakevens": breakevens,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "risk_reward_ratio": (
            round(max_profit / max_loss, 4)
            if max_profit is not None and max_loss not in {None, 0}
            else None
        ),
        "scenarios": {
            "price_down_10pct": _scenario(spot * 0.90, normalized_legs),
            "price_up_10pct": _scenario(spot * 1.10, normalized_legs),
            "iv_crush_50pct": _mark_to_model_scenario(
                spot=spot,
                legs=normalized_legs,
                iv_multiplier=0.5,
                rate=rate,
            ),
            "iv_spike_50pct": _mark_to_model_scenario(
                spot=spot,
                legs=normalized_legs,
                iv_multiplier=1.5,
                rate=rate,
            ),
        },
        "assumptions": [
            "Local Futu-compatible model; no AlphaGBM API call was made.",
            "Expiry payoff uses listed legs and entry prices.",
            "Before-expiry IV scenarios use Black-Scholes approximation.",
        ],
    }


def strategy_templates() -> list[dict[str, Any]]:
    return [
        {"id": "long_call", "name": "Long Call", "market_view": "bullish", "legs": 1},
        {"id": "long_put", "name": "Long Put", "market_view": "bearish", "legs": 1},
        {"id": "bull_call_spread", "name": "Bull Call Spread", "market_view": "bullish", "legs": 2},
        {"id": "bull_put_spread", "name": "Bull Put Spread", "market_view": "bullish", "legs": 2},
        {"id": "bear_put_spread", "name": "Bear Put Spread", "market_view": "bearish", "legs": 2},
        {"id": "bear_call_spread", "name": "Bear Call Spread", "market_view": "bearish", "legs": 2},
        {"id": "covered_call", "name": "Covered Call", "market_view": "income", "legs": 1},
        {"id": "cash_secured_put", "name": "Cash-Secured Put", "market_view": "income", "legs": 1},
        {"id": "collar", "name": "Collar", "market_view": "hedge", "legs": 2},
        {"id": "long_straddle", "name": "Long Straddle", "market_view": "volatile", "legs": 2},
        {"id": "short_straddle", "name": "Short Straddle", "market_view": "neutral", "legs": 2},
        {"id": "long_strangle", "name": "Long Strangle", "market_view": "volatile", "legs": 2},
        {"id": "short_strangle", "name": "Short Strangle", "market_view": "neutral", "legs": 2},
        {"id": "iron_condor", "name": "Iron Condor", "market_view": "neutral", "legs": 4},
        {"id": "iron_butterfly", "name": "Iron Butterfly", "market_view": "neutral", "legs": 4},
        {"id": "synthetic_long", "name": "Synthetic Long", "market_view": "bullish", "legs": 2},
        {"id": "synthetic_short", "name": "Synthetic Short", "market_view": "bearish", "legs": 2},
    ]


def build_strategy_from_template(
    *,
    template_id: str,
    spot: float,
    expiry_days: int,
    strikes: list[float],
    iv: float = 0.30,
    symbol: str = "LOCAL",
    rate: float = 0.04,
) -> dict[str, Any]:
    template = next((item for item in strategy_templates() if item["id"] == template_id), None)
    if template is None:
        raise ValueError(f"unsupported strategy template: {template_id}")
    selected = _select_template_legs(template_id, sorted({float(item) for item in strikes}), spot)
    priced_legs = []
    for leg in selected:
        expiry = expiry_days
        option_price = black_scholes_price(
            spot=spot,
            strike=leg["strike"],
            expiry_days=expiry,
            iv=iv,
            option_type=leg["option_type"],
            rate=rate,
        )
        priced_legs.append(
            {
                "action": leg["action"],
                "option_type": leg["option_type"],
                "strike": leg["strike"],
                "expiry_days": expiry,
                "iv": iv,
                "entry_price": round(option_price, 4),
                "quantity": leg.get("quantity", 1),
            }
        )
    simulation = simulate_option_position(
        symbol=symbol,
        spot=spot,
        legs=priced_legs,
        rate=rate,
    )
    return {
        "mode": "template",
        "template_id": template_id,
        "strategy": template["name"],
        "spot": spot,
        "expiry_days": expiry_days,
        "legs": priced_legs,
        "net_debit": simulation["position"]["net_debit"],
        "max_profit": simulation["max_profit"],
        "max_loss": simulation["max_loss"],
        "breakevens": simulation["breakevens"],
        "risk_reward_ratio": simulation["risk_reward_ratio"],
        "assumptions": simulation["assumptions"],
    }


def compute_options_snapshot(provider, ticker: str) -> dict[str, Any]:
    symbol, _futu_symbol = provider.normalize_symbol(ticker)
    spot = _spot_price(provider.fetch_underlying_snapshot(symbol))
    expirations = _select_expirations(provider.fetch_option_expirations(symbol), limit=1)
    if not expirations:
        raise ValueError(f"no option expiration is available for {symbol}")
    nearest_expiry = expirations[0]
    chain = provider.fetch_option_quotes(symbol, expiration=nearest_expiry, option_type="ALL")
    atm_iv = _atm_iv(chain, spot)
    history = _fetch_history(provider, symbol)
    hv_30d = _historical_volatility(history, window=30)
    iv_rank, iv_percentile = _iv_rank_from_hv_proxy(history, atm_iv)
    vrp = atm_iv - hv_30d if atm_iv is not None and hv_30d is not None else None
    return {
        "success": True,
        "ticker": symbol,
        "source": "futu",
        "price": spot,
        "nearest_expiry": nearest_expiry,
        "atm_iv": atm_iv,
        "hv_30d": hv_30d,
        "iv_rank": iv_rank,
        "iv_percentile": iv_percentile,
        "iv_rank_source": "local_hv_proxy" if iv_rank is not None else "unavailable",
        "vrp": vrp,
        "vrp_level": _vrp_level(vrp),
        "assumptions": [
            "Futu provides current option IV; historical IV is approximated locally "
            "from price history unless a persisted IV cache is available.",
            "This endpoint is read-only and does not place orders.",
        ],
    }


def build_vol_surface(provider, ticker: str, *, max_expirations: int = 4) -> dict[str, Any]:
    symbol, _futu_symbol = provider.normalize_symbol(ticker)
    spot = _spot_price(provider.fetch_underlying_snapshot(symbol))
    expirations = _select_expirations(
        provider.fetch_option_expirations(symbol),
        limit=max_expirations,
    )
    frames = []
    for expiry in expirations:
        frame = provider.fetch_option_quotes(symbol, expiration=expiry, option_type="ALL")
        frames.append(frame.assign(expiry=str(expiry)))
    chain = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    points = _surface_points(chain, spot)
    axis = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    grid = []
    term = {}
    for expiry in expirations:
        expiry_points = [item for item in points if item["expiry"] == expiry]
        grid_row = []
        for target in axis:
            chosen = _nearest_by(expiry_points, "moneyness", target)
            grid_row.append(chosen["iv"] if chosen else None)
        atm = _nearest_by(expiry_points, "moneyness", 1.0)
        if atm:
            term[expiry] = atm["iv"]
        grid.append(grid_row)
    return {
        "success": True,
        "ticker": symbol,
        "source": "futu",
        "price": spot,
        "surface": {
            "moneyness_axis": axis,
            "expiry_axis": expirations,
            "iv_grid": grid,
            "points": points,
        },
        "atm_term_structure": term,
        "shape": _term_shape(term),
        "assumptions": [
            "Surface grid uses nearest listed contracts for each moneyness bucket.",
            "Only current Futu option quotes are used.",
        ],
    }


def build_vol_smile(provider, ticker: str, *, expiry: str | None = None) -> dict[str, Any]:
    symbol, _futu_symbol = provider.normalize_symbol(ticker)
    spot = _spot_price(provider.fetch_underlying_snapshot(symbol))
    selected_expiry = expiry
    if selected_expiry is None:
        expirations = _select_expirations(provider.fetch_option_expirations(symbol), limit=1)
        if not expirations:
            raise ValueError(f"no option expiration is available for {symbol}")
        selected_expiry = expirations[0]
    chain = provider.fetch_option_quotes(symbol, expiration=selected_expiry, option_type="ALL")
    frame = _with_normalized_iv(chain)
    frame = frame.loc[frame["implied_volatility"].notna() & frame["strike"].notna()].copy()
    frame["moneyness"] = pd.to_numeric(frame["strike"], errors="coerce") / spot
    frame = frame.sort_values(["strike", "option_type"]).reset_index(drop=True)
    calls = frame.loc[frame["option_type"].astype(str).str.upper() == "CALL"]
    puts = frame.loc[frame["option_type"].astype(str).str.upper() == "PUT"]
    call_25 = _nearest_delta(calls, 0.25)
    put_25 = _nearest_delta(puts, -0.25)
    atm = _nearest_by(frame.to_dict(orient="records"), "moneyness", 1.0)
    skew_25d = None
    if call_25 is not None and put_25 is not None:
        skew_25d = (put_25["implied_volatility"] - call_25["implied_volatility"]) * 100
    return {
        "success": True,
        "ticker": symbol,
        "source": "futu",
        "price": spot,
        "expiry": selected_expiry,
        "dte": _days_to_expiry(selected_expiry),
        "smile": {
            "strikes": _float_series_to_list(frame["strike"], digits=4),
            "ivs": _float_series_to_list(frame["implied_volatility"], digits=6),
            "deltas": _float_series_to_list(
                frame["delta"] if "delta" in frame else pd.Series([None] * len(frame)),
                digits=6,
            ),
            "option_types": frame["option_type"].astype(str).tolist(),
            "moneyness": _float_series_to_list(frame["moneyness"], digits=6),
        },
        "skew_metrics": {
            "skew_25d": skew_25d,
            "atm_iv": atm["implied_volatility"] if atm else None,
        },
        "shape": _smile_shape(skew_25d),
        "assumptions": [
            "Smile uses current Futu option-chain snapshots.",
            "25-delta skew is approximated by the listed contract closest to target delta.",
        ],
    }


def _d1(*, spot: float, strike: float, expiry_years: float, iv: float, rate: float) -> float:
    return (math.log(spot / strike) + (rate + 0.5 * iv * iv) * expiry_years) / (
        iv * math.sqrt(expiry_years)
    )


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _charm(
    *,
    spot: float,
    strike: float,
    expiry_years: float,
    iv: float,
    rate: float,
    option_type: OptionType,
) -> float:
    d1 = _d1(spot=spot, strike=strike, expiry_years=expiry_years, iv=iv, rate=rate)
    d2 = d1 - iv * math.sqrt(expiry_years)
    numerator = 2 * rate * expiry_years - d2 * iv * math.sqrt(expiry_years)
    raw = -_norm_pdf(d1) * numerator / (2 * expiry_years * iv * math.sqrt(expiry_years))
    if option_type == "call":
        return raw / 365.0
    return raw / 365.0


def _normalize_option_type(value: str) -> OptionType:
    normalized = value.lower().strip()
    if normalized not in {"call", "put"}:
        raise ValueError("option_type must be call or put")
    return normalized  # type: ignore[return-value]


def _normalize_action(value: str) -> Action:
    normalized = value.lower().strip()
    if normalized not in {"buy", "sell"}:
        raise ValueError("action must be buy or sell")
    return normalized  # type: ignore[return-value]


def _normalize_leg(leg: dict[str, Any], *, spot: float, rate: float) -> dict[str, Any]:
    action = _normalize_action(str(leg.get("action", "buy")))
    option_type = _normalize_option_type(str(leg.get("option_type", leg.get("type", "call"))))
    strike = float(leg["strike"])
    expiry_days = int(leg["expiry_days"])
    iv = float(leg.get("iv", 0.30))
    entry_price = leg.get("entry_price", leg.get("price"))
    if entry_price is None:
        entry_price = black_scholes_price(
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            iv=iv,
            option_type=option_type,
            rate=rate,
        )
    return {
        "action": action,
        "option_type": option_type,
        "strike": strike,
        "expiry_days": expiry_days,
        "iv": iv,
        "entry_price": float(entry_price),
        "quantity": int(leg.get("quantity", leg.get("qty", 1))),
        "contract_size": int(leg.get("contract_size", 100)),
    }


def _net_debit(legs: list[dict[str, Any]]) -> float:
    debit = 0.0
    for leg in legs:
        direction = 1 if leg["action"] == "buy" else -1
        debit += direction * leg["entry_price"] * leg["quantity"] * leg["contract_size"]
    return round(debit, 4)


def _expiry_pnl(price: float, legs: list[dict[str, Any]]) -> float:
    total = 0.0
    for leg in legs:
        if leg["option_type"] == "call":
            payoff = max(price - leg["strike"], 0.0)
        else:
            payoff = max(leg["strike"] - price, 0.0)
        direction = 1 if leg["action"] == "buy" else -1
        total += direction * (
            payoff - leg["entry_price"]
        ) * leg["quantity"] * leg["contract_size"]
    return total


def _scenario(price: float, legs: list[dict[str, Any]]) -> dict[str, float]:
    pnl = _expiry_pnl(price, legs)
    basis = abs(_net_debit(legs)) or 1.0
    return {
        "underlying_price": round(price, 4),
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl / basis, 4),
    }


def _mark_to_model_scenario(
    *,
    spot: float,
    legs: list[dict[str, Any]],
    iv_multiplier: float,
    rate: float,
) -> dict[str, float]:
    value = 0.0
    for leg in legs:
        adjusted_iv = max(0.0001, leg["iv"] * iv_multiplier)
        price = black_scholes_price(
            spot=spot,
            strike=leg["strike"],
            expiry_days=leg["expiry_days"],
            iv=adjusted_iv,
            option_type=leg["option_type"],
            rate=rate,
        )
        direction = 1 if leg["action"] == "buy" else -1
        value += direction * (
            price - leg["entry_price"]
        ) * leg["quantity"] * leg["contract_size"]
    basis = abs(_net_debit(legs)) or 1.0
    return {
        "underlying_price": round(spot, 4),
        "pnl": round(value, 4),
        "pnl_pct": round(value / basis, 4),
    }


def _breakevens(price_axis: list[float], pnl_axis: list[float]) -> list[float]:
    points = []
    for index in range(1, len(price_axis)):
        left_pnl = pnl_axis[index - 1]
        right_pnl = pnl_axis[index]
        if left_pnl == 0:
            points.append(price_axis[index - 1])
        if left_pnl * right_pnl < 0:
            left_price = price_axis[index - 1]
            right_price = price_axis[index]
            fraction = abs(left_pnl) / (abs(left_pnl) + abs(right_pnl))
            points.append(round(left_price + (right_price - left_price) * fraction, 4))
    return sorted(set(points))


def _bounded_profit_loss(
    legs: list[dict[str, Any]],
    pnl_axis: list[float],
) -> tuple[float | None, float | None]:
    del pnl_axis
    if not legs:
        return 0.0, 0.0

    call_high_slope = 0.0
    strikes = []
    for leg in legs:
        strikes.append(float(leg["strike"]))
        if leg["option_type"] != "call":
            continue
        direction = 1 if leg["action"] == "buy" else -1
        call_high_slope += direction * leg["quantity"] * leg["contract_size"]

    unbounded_profit = call_high_slope > 0
    unbounded_loss = call_high_slope < 0
    critical_prices = {0.0, *strikes}
    if strikes:
        critical_prices.add(max(strikes) * 2)

    sampled = [_expiry_pnl(price, legs) for price in sorted(critical_prices)]
    max_profit = None if unbounded_profit else max(sampled)
    max_loss = None if unbounded_loss else abs(min(sampled))
    return (
        round(max_profit, 4) if max_profit is not None else None,
        round(max_loss, 4) if max_loss is not None else None,
    )


def _select_template_legs(
    template_id: str,
    strikes: list[float],
    spot: float,
) -> list[dict[str, Any]]:
    if not strikes:
        raise ValueError("at least one strike is required")
    below = [strike for strike in strikes if strike <= spot]
    above = [strike for strike in strikes if strike >= spot]
    low = below[-1] if below else strikes[0]
    high = above[0] if above else strikes[-1]
    lower = below[-2] if len(below) >= 2 else strikes[0]
    higher = above[1] if len(above) >= 2 else strikes[-1]
    if template_id == "long_call":
        return [{"action": "buy", "option_type": "call", "strike": high}]
    if template_id == "long_put":
        return [{"action": "buy", "option_type": "put", "strike": low}]
    if template_id == "bull_call_spread":
        return [
            {"action": "buy", "option_type": "call", "strike": low},
            {"action": "sell", "option_type": "call", "strike": higher},
        ]
    if template_id == "bear_put_spread":
        return [
            {"action": "buy", "option_type": "put", "strike": high},
            {"action": "sell", "option_type": "put", "strike": lower},
        ]
    if template_id == "bull_put_spread":
        return [
            {"action": "sell", "option_type": "put", "strike": low},
            {"action": "buy", "option_type": "put", "strike": lower},
        ]
    if template_id == "bear_call_spread":
        return [
            {"action": "sell", "option_type": "call", "strike": high},
            {"action": "buy", "option_type": "call", "strike": higher},
        ]
    if template_id in {"covered_call"}:
        return [{"action": "sell", "option_type": "call", "strike": higher}]
    if template_id in {"cash_secured_put"}:
        return [{"action": "sell", "option_type": "put", "strike": lower}]
    if template_id == "collar":
        return [
            {"action": "buy", "option_type": "put", "strike": lower},
            {"action": "sell", "option_type": "call", "strike": higher},
        ]
    if template_id == "long_straddle":
        return [
            {"action": "buy", "option_type": "call", "strike": high},
            {"action": "buy", "option_type": "put", "strike": high},
        ]
    if template_id == "short_straddle":
        return [
            {"action": "sell", "option_type": "call", "strike": high},
            {"action": "sell", "option_type": "put", "strike": high},
        ]
    if template_id == "long_strangle":
        return [
            {"action": "buy", "option_type": "put", "strike": lower},
            {"action": "buy", "option_type": "call", "strike": higher},
        ]
    if template_id == "short_strangle":
        return [
            {"action": "sell", "option_type": "put", "strike": lower},
            {"action": "sell", "option_type": "call", "strike": higher},
        ]
    if template_id == "iron_condor":
        return [
            {"action": "buy", "option_type": "put", "strike": strikes[0]},
            {"action": "sell", "option_type": "put", "strike": lower},
            {"action": "sell", "option_type": "call", "strike": higher},
            {"action": "buy", "option_type": "call", "strike": strikes[-1]},
        ]
    if template_id == "iron_butterfly":
        return [
            {"action": "buy", "option_type": "put", "strike": strikes[0]},
            {"action": "sell", "option_type": "put", "strike": high},
            {"action": "sell", "option_type": "call", "strike": high},
            {"action": "buy", "option_type": "call", "strike": strikes[-1]},
        ]
    if template_id == "synthetic_long":
        return [
            {"action": "buy", "option_type": "call", "strike": high},
            {"action": "sell", "option_type": "put", "strike": high},
        ]
    if template_id == "synthetic_short":
        return [
            {"action": "sell", "option_type": "call", "strike": high},
            {"action": "buy", "option_type": "put", "strike": high},
        ]
    raise ValueError(f"unsupported strategy template: {template_id}")


def _spot_price(snapshot: dict[str, Any]) -> float:
    for key in ("last", "last_price", "close", "price"):
        value = _safe_float(snapshot.get(key))
        if value is not None and value > 0:
            return value
    raise ValueError("underlying snapshot has no valid price")


def _select_expirations(frame: pd.DataFrame, *, limit: int) -> list[str]:
    if frame.empty or "strike_time" not in frame.columns:
        return []
    active = frame.copy()
    active["strike_time"] = active["strike_time"].astype(str)
    if "option_expiry_date_distance" in active.columns:
        active["_dte"] = pd.to_numeric(active["option_expiry_date_distance"], errors="coerce")
    else:
        active["_dte"] = active["strike_time"].map(_days_to_expiry)
    active = active.loc[active["_dte"].notna() & (active["_dte"] >= 1)]
    return active.sort_values(["_dte", "strike_time"])["strike_time"].head(limit).tolist()


def _fetch_history(provider, symbol: str) -> pd.DataFrame:
    today = pd.Timestamp.now(tz="America/New_York").normalize()
    start = (today - pd.Timedelta(days=210)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    return provider.fetch_ohlcv([symbol], start=start, end=end, interval="1d")


def _historical_volatility(history: pd.DataFrame, *, window: int) -> float | None:
    if len(history) < 2:
        return None
    closes = pd.to_numeric(history.sort_values("timestamp")["close"], errors="coerce")
    returns = closes.pct_change().dropna()
    if returns.empty:
        return None
    value = returns.tail(window).std(ddof=0) * math.sqrt(252)
    return None if pd.isna(value) else float(value)


def _iv_rank_from_hv_proxy(
    history: pd.DataFrame,
    current_iv: float | None,
) -> tuple[float | None, float | None]:
    if current_iv is None or len(history) < 35:
        return None, None
    closes = pd.to_numeric(history.sort_values("timestamp")["close"], errors="coerce")
    returns = closes.pct_change().dropna()
    rolling = returns.rolling(30).std(ddof=0).dropna() * math.sqrt(252)
    if rolling.empty:
        return None, None
    low = float(rolling.min())
    high = float(rolling.max())
    rank = None if high <= low else (current_iv - low) / (high - low) * 100
    percentile = (rolling < current_iv).mean() * 100
    return (
        round(max(0.0, min(100.0, rank)), 4) if rank is not None else None,
        round(max(0.0, min(100.0, float(percentile))), 4),
    )


def _atm_iv(chain: pd.DataFrame, spot: float) -> float | None:
    frame = _with_normalized_iv(chain)
    frame["strike"] = pd.to_numeric(frame.get("strike"), errors="coerce")
    frame = frame.loc[frame["implied_volatility"].notna() & frame["strike"].notna()].copy()
    if frame.empty:
        return None
    frame["_distance"] = (frame["strike"] - spot).abs()
    nearest_distance = frame["_distance"].min()
    nearest = frame.loc[frame["_distance"] == nearest_distance]
    value = nearest["implied_volatility"].mean()
    return None if pd.isna(value) else float(value)


def _with_normalized_iv(frame: pd.DataFrame) -> pd.DataFrame:
    active = frame.copy()
    active["implied_volatility"] = pd.to_numeric(
        active.get("implied_volatility"),
        errors="coerce",
    ).map(_normalize_iv)
    active["strike"] = pd.to_numeric(active.get("strike"), errors="coerce")
    return active


def _normalize_iv(value: float | None) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return parsed / 100.0 if parsed > 5 else parsed


def _surface_points(chain: pd.DataFrame, spot: float) -> list[dict[str, Any]]:
    frame = _with_normalized_iv(chain)
    frame = frame.loc[frame["implied_volatility"].notna() & frame["strike"].notna()]
    points = []
    for row in frame.to_dict(orient="records"):
        strike = float(row["strike"])
        points.append(
            {
                "expiry": str(row.get("expiry")),
                "strike": strike,
                "moneyness": round(strike / spot, 6),
                "iv": float(row["implied_volatility"]),
                "option_type": str(row.get("option_type", "")).upper(),
                "delta": _safe_float(row.get("delta")),
            }
        )
    return points


def _nearest_by(items: list[dict[str, Any]], key: str, target: float) -> dict[str, Any] | None:
    available = [item for item in items if _safe_float(item.get(key)) is not None]
    if not available:
        return None
    return min(available, key=lambda item: abs(float(item[key]) - target))


def _nearest_delta(frame: pd.DataFrame, target: float) -> dict[str, Any] | None:
    if frame.empty or "delta" not in frame.columns:
        return None
    active = frame.copy()
    active["delta"] = pd.to_numeric(active["delta"], errors="coerce")
    active = active.loc[active["delta"].notna()]
    if active.empty:
        return None
    active["_distance"] = (active["delta"] - target).abs()
    return active.sort_values("_distance").iloc[0].to_dict()


def _days_to_expiry(expiry: str) -> int:
    expiry_ts = pd.Timestamp(expiry, tz="America/New_York").normalize()
    today = pd.Timestamp.now(tz="America/New_York").normalize()
    return max(int((expiry_ts - today).days), 0)


def _term_shape(term: dict[str, float]) -> str:
    values = list(term.values())
    if len(values) < 2:
        return "unknown"
    if values[0] > values[-1] * 1.05:
        return "backwardation"
    if values[-1] > values[0] * 1.05:
        return "contango"
    return "flat"


def _smile_shape(skew_25d: float | None) -> str:
    if skew_25d is None:
        return "unknown"
    if skew_25d > 2:
        return "normal"
    if skew_25d < -2:
        return "reverse"
    return "flat"


def _vrp_level(vrp: float | None) -> str | None:
    if vrp is None:
        return None
    if vrp >= 0.15:
        return "very_high"
    if vrp >= 0.05:
        return "high"
    if vrp <= -0.15:
        return "very_low"
    if vrp <= -0.05:
        return "low"
    return "normal"


def _float_series_to_list(series: Any, *, digits: int) -> list[float | None]:
    if series is None:
        return []
    numeric = pd.to_numeric(series, errors="coerce").round(digits)
    return [None if pd.isna(value) else float(value) for value in numeric.tolist()]


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed
