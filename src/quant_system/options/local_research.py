from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Literal

from quant_system.options.local_tools import build_strategy_from_template

Objective = Literal["sell_premium", "buy_premium", "balanced"]


def rank_option_contracts(
    *,
    contracts: list[dict[str, Any]],
    spot: float,
    objective: Objective = "balanced",
    top_n: int | None = None,
) -> dict[str, Any]:
    ranked = [
        _score_contract(contract=contract, spot=spot, objective=objective)
        for contract in contracts
    ]
    ranked = sorted(
        ranked,
        key=lambda item: (
            -item["score"],
            item["spread_pct"] if item["spread_pct"] is not None else 999.0,
            -float(item.get("open_interest") or 0.0),
        ),
    )
    if top_n is not None:
        ranked = ranked[: max(top_n, 0)]
    return {
        "success": True,
        "objective": objective,
        "spot": spot,
        "ranked_contracts": ranked,
        "assumptions": [
            "Local contract score only; no AlphaGBM API call was made.",
            "Scores compare research candidates and do not create orders.",
        ],
    }


def rank_strategy_templates(
    *,
    market_view: str,
    spot: float,
    expiry_days: int,
    strikes: list[float],
    iv: float = 0.30,
    symbol: str = "LOCAL",
) -> dict[str, Any]:
    view = market_view.lower().strip()
    template_ids = _templates_for_view(view)
    rankings = []
    for template_id in template_ids:
        try:
            built = build_strategy_from_template(
                template_id=template_id,
                spot=spot,
                expiry_days=expiry_days,
                strikes=strikes,
                iv=iv,
                symbol=symbol,
            )
        except ValueError:
            continue
        rankings.append(_score_strategy_template(built, market_view=view, spot=spot))
    rankings = sorted(rankings, key=lambda item: (-item["score"], item["template_id"]))
    return {
        "success": True,
        "market_view": view,
        "rankings": rankings,
        "assumptions": [
            "Strategy rankings use local template payoff math.",
            "Rankings are research comparisons, not trading advice or executable orders.",
        ],
    }


def build_bull_put_spread_signal(
    *,
    contracts: list[dict[str, Any]],
    spot: float,
    fear_score: float,
) -> dict[str, Any]:
    puts = [
        contract
        for contract in contracts
        if str(contract.get("option_type", "")).upper() == "PUT"
        and (_safe_float(contract.get("strike")) or 0.0) < spot
    ]
    scored = rank_option_contracts(
        contracts=puts,
        spot=spot,
        objective="sell_premium",
    )["ranked_contracts"]
    sell_candidates = [
        item
        for item in scored
        if 0.15 <= abs(float(item.get("delta") or 0.0)) <= 0.35
        and item["mid"] is not None
    ]
    selected = None
    for sell_leg in sell_candidates:
        lower_puts = [
            item
            for item in scored
            if item["symbol"] != sell_leg["symbol"]
            and item["strike"] is not None
            and sell_leg["strike"] is not None
            and item["strike"] < sell_leg["strike"]
            and item["mid"] is not None
        ]
        if not lower_puts:
            continue
        buy_leg = max(lower_puts, key=lambda item: item["strike"])
        width = float(sell_leg["strike"]) - float(buy_leg["strike"])
        credit = (float(sell_leg["mid"]) - float(buy_leg["mid"])) * 100
        if credit <= 0:
            continue
        selected = {
            "sell_leg": sell_leg,
            "buy_leg": buy_leg,
            "credit": round(credit, 4),
            "width": round(width * 100, 4),
            "max_loss": round(width * 100 - credit, 4),
            "breakeven": round(float(sell_leg["strike"]) - credit / 100, 4),
        }
        break
    enter_signal = fear_score >= 60 and selected is not None
    return {
        "success": True,
        "fear_score": round(float(fear_score), 4),
        "enter_signal": enter_signal,
        "selected_spread": selected,
        "reasons": _bull_put_reasons(fear_score=fear_score, selected=selected),
        "assumptions": [
            "Fear-score threshold follows the local AlphaGBM-style research rule.",
            "The result is not an order and cannot place a trade.",
        ],
    }


def compute_fear_score(
    *,
    vix: float | None = None,
    iv_rank: float | None = None,
    rsi_14: float | None = None,
    options_volume_anomaly: float | None = None,
    put_call_ratio: float | None = None,
    consecutive_down_days: int | None = None,
) -> dict[str, Any]:
    components = {
        "vix": _vix_component(vix),
        "iv_rank": _component(iv_rank, low=20, high=85, inverse=False),
        "rsi_14": _component(rsi_14, low=65, high=25, inverse=True),
        "options_volume_anomaly": _component(
            options_volume_anomaly,
            low=1.0,
            high=3.0,
            inverse=False,
        ),
        "put_call_ratio": _component(put_call_ratio, low=0.8, high=1.4, inverse=False),
        "consecutive_down_days": _component(
            float(consecutive_down_days) if consecutive_down_days is not None else None,
            low=0,
            high=5,
            inverse=False,
        ),
    }
    weights = {
        "vix": 0.25,
        "iv_rank": 0.20,
        "rsi_14": 0.20,
        "options_volume_anomaly": 0.15,
        "put_call_ratio": 0.10,
        "consecutive_down_days": 0.10,
    }
    available = [
        (components[key], weight)
        for key, weight in weights.items()
        if components[key] is not None
    ]
    score = _weighted(available) if available else 0.0
    return {
        "success": True,
        "fear_score": round(score, 4),
        "tier": _fear_tier(score),
        "components": components,
        "bull_put_spread_signal": score >= 60,
        "assumptions": [
            "Fear score is computed from locally supplied inputs.",
            "It is a research signal, not financial advice.",
        ],
    }


def compute_iv_rank_dashboard(
    *,
    ticker: str,
    current_iv: float | None,
    history: list[float],
) -> dict[str, Any]:
    normalized_history = [
        value
        for value in (_normalize_iv(_safe_float(item)) for item in history)
        if value is not None
    ]
    active_iv = _normalize_iv(current_iv)
    iv_rank = None
    percentile = None
    if active_iv is not None and normalized_history:
        low = min(normalized_history)
        high = max(normalized_history)
        iv_rank = 50.0 if high <= low else (active_iv - low) / (high - low) * 100
        iv_rank = _clip(iv_rank, 0.0, 100.0)
        percentile = sum(1 for value in normalized_history if value < active_iv) / len(
            normalized_history
        ) * 100
    return {
        "success": True,
        "ticker": ticker.upper().strip(),
        "current_iv": active_iv,
        "sample_count": len(normalized_history),
        "iv_rank": round(iv_rank, 4) if iv_rank is not None else None,
        "iv_percentile": round(percentile, 4) if percentile is not None else None,
        "zone": _iv_zone(iv_rank),
        "assumptions": [
            "IV rank uses the supplied local history values.",
            "No live market data is fetched by this dashboard helper.",
        ],
    }


def compute_market_sentiment(
    *,
    vix: float | None = None,
    put_call_ratio: float | None = None,
    advance_decline_ratio: float | None = None,
    percent_above_200dma: float | None = None,
) -> dict[str, Any]:
    components = {
        "vix": _vix_component(vix),
        "put_call_ratio": _component(put_call_ratio, low=0.8, high=1.4, inverse=False),
        "breadth": _component(advance_decline_ratio, low=1.5, high=0.5, inverse=True),
        "trend": _component(percent_above_200dma, low=70, high=25, inverse=True),
    }
    score = _weighted(
        [
            (components["vix"], 0.35),
            (components["put_call_ratio"], 0.25),
            (components["breadth"], 0.20),
            (components["trend"], 0.20),
        ]
    )
    return {
        "success": True,
        "sentiment_score": round(score, 4),
        "regime": _sentiment_regime(score),
        "components": components,
        "assumptions": [
            "Sentiment is a local composite of supplied breadth and volatility inputs.",
            "It is not an investment recommendation.",
        ],
    }


def estimate_earnings_iv_crush(
    *,
    ticker: str,
    current_iv: float,
    historical_pre_post_iv: list[dict[str, Any]],
    implied_move_pct: float | None = None,
) -> dict[str, Any]:
    drops = []
    for row in historical_pre_post_iv:
        pre = _normalize_iv(_safe_float(row.get("pre_iv")))
        post = _normalize_iv(_safe_float(row.get("post_iv")))
        if pre is None or post is None or pre <= 0:
            continue
        drops.append((pre - post) / pre)
    avg_crush = sum(drops) / len(drops) if drops else None
    active_iv = _normalize_iv(current_iv)
    expected_post_iv = (
        active_iv * (1 - avg_crush)
        if active_iv is not None and avg_crush is not None
        else None
    )
    return {
        "success": True,
        "ticker": ticker.upper().strip(),
        "sample_count": len(drops),
        "average_crush_pct": round(avg_crush * 100, 4) if avg_crush is not None else None,
        "expected_post_event_iv": (
            round(expected_post_iv, 6) if expected_post_iv is not None else None
        ),
        "implied_move_pct": implied_move_pct,
        "strategy_tag": _earnings_strategy_tag(avg_crush, active_iv),
        "assumptions": [
            "Historical crush uses supplied pre/post IV observations.",
            "This workflow is read-only and approximate.",
        ],
    }


def build_hedge_advisor(
    *,
    ticker: str,
    shares: int,
    cost_basis: float,
    spot: float,
    purpose: str,
    contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    del purpose
    situation = _holding_situation(cost_basis=cost_basis, spot=spot)
    puts = _contracts_by_type(contracts, "PUT")
    calls = _contracts_by_type(contracts, "CALL")
    put = _nearest_strike(puts, spot * 0.90)
    call = _nearest_strike(calls, spot * 1.10)
    structures = []
    if put is not None:
        structures.append(
            {
                "structure": "long_put",
                "contracts_needed": max(math.ceil(shares / 100), 1),
                "protective_leg": put,
                "estimated_debit": _mid(put) * 100 if _mid(put) is not None else None,
                "research_note": "Downside hedge candidate based on nearest 90% strike put.",
            }
        )
    if put is not None and call is not None:
        debit = _mid(put)
        credit = _mid(call)
        structures.append(
            {
                "structure": "collar",
                "contracts_needed": max(math.ceil(shares / 100), 1),
                "protective_leg": put,
                "offset_leg": call,
                "estimated_net_debit": (
                    round((debit - credit) * 100, 4)
                    if debit is not None and credit is not None
                    else None
                ),
                "research_note": "Collar candidate pairs downside put with upside call cap.",
            }
        )
    return {
        "success": True,
        "ticker": ticker.upper().strip(),
        "situation": situation,
        "structures": structures,
        "assumptions": [
            "Hedge advisor uses supplied holdings and option contracts only.",
            "The output is not an order ticket and cannot submit trades.",
        ],
    }


def detect_unusual_options_activity(
    contracts: list[dict[str, Any]],
    *,
    min_volume_oi_ratio: float = 2.0,
    min_volume: float = 100,
) -> dict[str, Any]:
    events = []
    for contract in contracts:
        volume = _safe_float(contract.get("volume")) or 0.0
        open_interest = _safe_float(contract.get("open_interest")) or 0.0
        ratio = volume / open_interest if open_interest > 0 else (volume if volume > 0 else 0.0)
        mid = _mid(contract)
        premium_flow = volume * mid * 100 if mid is not None else None
        if volume >= min_volume and ratio >= min_volume_oi_ratio:
            payload = {
                "symbol": str(contract.get("symbol", "")),
                "option_type": str(contract.get("option_type", "")).upper(),
                "strike": _safe_float(contract.get("strike")),
                "volume": volume,
                "open_interest": open_interest,
                "volume_oi_ratio": round(ratio, 4),
                "estimated_premium_flow": (
                    round(premium_flow, 4) if premium_flow is not None else None
                ),
                "flags": ["volume_oi_spike"],
            }
            events.append(payload)
    events = sorted(
        events,
        key=lambda item: (
            -float(item["volume_oi_ratio"]),
            -float(item["volume"]),
        ),
    )
    return {
        "success": True,
        "events": events,
        "assumptions": [
            "Unusual activity is inferred from supplied volume and open-interest fields.",
            "Block-trade attribution is not available from this local helper.",
        ],
    }


class LocalWatchlistStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list(self) -> list[dict[str, Any]]:
        payload = self._read()
        return sorted(payload.get("watchlist", []), key=lambda item: item["ticker"])

    def add(self, ticker: str, *, tags: list[str] | None = None) -> list[dict[str, Any]]:
        normalized = ticker.upper().strip()
        if not normalized:
            raise ValueError("ticker is required")
        entries = {
            item["ticker"]: item
            for item in self.list()
        }
        entries[normalized] = {
            "ticker": normalized,
            "tags": list(tags or entries.get(normalized, {}).get("tags", [])),
        }
        self._write({"watchlist": sorted(entries.values(), key=lambda item: item["ticker"])})
        return self.list()

    def remove(self, ticker: str) -> list[dict[str, Any]]:
        normalized = ticker.upper().strip()
        entries = [item for item in self.list() if item["ticker"] != normalized]
        self._write({"watchlist": entries})
        return entries

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"watchlist": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def evaluate_local_alerts(
    *,
    alerts: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    ticker = str(context.get("ticker", "")).upper().strip()
    triggered = []
    for alert in alerts:
        if str(alert.get("ticker", "")).upper().strip() != ticker:
            continue
        if _alert_triggered(alert, context):
            triggered.append(
                {
                    "id": str(alert.get("id", "")),
                    "ticker": ticker,
                    "type": str(alert.get("type", "")),
                    "threshold": _safe_float(alert.get("threshold")),
                    "observed": _observed_value(alert, context),
                }
            )
    return {
        "success": True,
        "ticker": ticker,
        "triggered_alerts": triggered,
        "assumptions": [
            "Alert evaluation is local and stateless.",
            "Notifications are not sent by this endpoint.",
        ],
    }


def research_health_check(
    *,
    profiles: list[dict[str, Any]],
    today: str | None = None,
    stale_after_days: int = 14,
) -> dict[str, Any]:
    active_today = date.fromisoformat(today) if today else date.today()
    stale = []
    missing_thesis = []
    for profile in profiles:
        ticker = str(profile.get("ticker", "")).upper().strip()
        raw_updated = profile.get("updated_at")
        if ticker and not str(profile.get("thesis", "")).strip():
            missing_thesis.append(ticker)
        if not ticker or raw_updated is None:
            continue
        try:
            updated = date.fromisoformat(str(raw_updated))
        except ValueError:
            stale.append(ticker)
            continue
        if (active_today - updated).days > stale_after_days:
            stale.append(ticker)
    issue_count = len(set(stale)) + len(set(missing_thesis))
    total = max(len(profiles), 1)
    health_score = _clip(100 - issue_count / total * 50, 0, 100)
    return {
        "success": True,
        "health_score": round(health_score, 4),
        "stale_profiles": sorted(set(stale)),
        "missing_thesis": sorted(set(missing_thesis)),
        "assumptions": [
            "Health check only inspects supplied local profile metadata.",
            "It does not fetch news or account data.",
        ],
    }


def _score_contract(
    *,
    contract: dict[str, Any],
    spot: float,
    objective: Objective,
) -> dict[str, Any]:
    mid = _mid(contract)
    spread_pct = _spread_pct(contract)
    iv = _normalize_iv(_safe_float(contract.get("implied_volatility")))
    volume = _safe_float(contract.get("volume"))
    open_interest = _safe_float(contract.get("open_interest"))
    delta = _safe_float(contract.get("delta"))
    warnings = _contract_warnings(
        mid=mid,
        spread_pct=spread_pct,
        iv=iv,
        volume=volume,
        open_interest=open_interest,
    )
    liquidity = _average(
        [
            _spread_score(spread_pct),
            _activity_score(volume, good=500, acceptable=100),
            _activity_score(open_interest, good=1000, acceptable=300),
        ]
    )
    iv_score = _iv_value_score(iv, objective=objective)
    delta_score = _delta_score(delta, objective=objective)
    premium_score = _premium_score(mid, spot=spot)
    score = _weighted(
        [
            (liquidity, 0.45),
            (iv_score, 0.25),
            (delta_score, 0.15),
            (premium_score, 0.15),
        ]
    )
    return {
        "symbol": str(contract.get("symbol", "")),
        "option_type": str(contract.get("option_type", "")).upper(),
        "strike": _safe_float(contract.get("strike")),
        "bid": _safe_float(contract.get("bid")),
        "ask": _safe_float(contract.get("ask")),
        "mid": round(mid, 6) if mid is not None else None,
        "spread_pct": round(spread_pct, 6) if spread_pct is not None else None,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": iv,
        "delta": delta,
        "score": round(score, 4),
        "rating": _rating(score),
        "subscores": {
            "liquidity": round(liquidity, 4),
            "iv_value": round(iv_score, 4),
            "delta_fit": round(delta_score, 4),
            "premium": round(premium_score, 4),
        },
        "warnings": warnings,
    }


def _score_strategy_template(
    built: dict[str, Any],
    *,
    market_view: str,
    spot: float,
) -> dict[str, Any]:
    max_profit = _safe_float(built.get("max_profit"))
    max_loss = _safe_float(built.get("max_loss"))
    net_debit = _safe_float(built.get("net_debit")) or 0.0
    ratio = max_profit / max_loss if max_profit is not None and max_loss else None
    risk_reward = 70.0 if max_profit is None else _clip((ratio or 0.0) * 50, 0, 100)
    cost_score = 85.0 if net_debit < 0 else _clip(100 - abs(net_debit) / (spot * 100) * 100, 0, 100)
    view_fit = _strategy_view_fit(str(built["template_id"]), market_view)
    defined_risk = 100.0 if max_loss is not None else 60.0
    score = _weighted(
        [
            (view_fit, 0.35),
            (risk_reward, 0.25),
            (cost_score, 0.20),
            (defined_risk, 0.20),
        ]
    )
    return {
        "template_id": built["template_id"],
        "strategy": built["strategy"],
        "score": round(score, 4),
        "net_debit": built.get("net_debit"),
        "max_profit": built.get("max_profit"),
        "max_loss": built.get("max_loss"),
        "breakevens": built.get("breakevens", []),
        "rating": _rating(score),
    }


def _templates_for_view(view: str) -> list[str]:
    if view == "bearish":
        return ["long_put", "bear_put_spread", "bear_call_spread", "synthetic_short"]
    if view == "neutral":
        return ["short_straddle", "short_strangle", "iron_condor", "iron_butterfly"]
    if view == "volatile":
        return ["long_straddle", "long_strangle"]
    if view == "hedge":
        return ["collar", "long_put", "covered_call"]
    return ["long_call", "bull_call_spread", "bull_put_spread", "synthetic_long"]


def _bull_put_reasons(*, fear_score: float, selected: dict[str, Any] | None) -> list[str]:
    reasons = []
    if fear_score >= 60:
        reasons.append("fear_score_at_or_above_entry_threshold")
    else:
        reasons.append("fear_score_below_entry_threshold")
    if selected is None:
        reasons.append("no_valid_put_vertical_found")
    else:
        reasons.append("put_vertical_candidate_found")
    return reasons


def _strategy_view_fit(template_id: str, market_view: str) -> float:
    bullish = {"long_call", "bull_call_spread", "bull_put_spread", "synthetic_long"}
    bearish = {"long_put", "bear_put_spread", "bear_call_spread", "synthetic_short"}
    neutral = {"short_straddle", "short_strangle", "iron_condor", "iron_butterfly"}
    if market_view == "bullish":
        return 100.0 if template_id in bullish else 45.0
    if market_view == "bearish":
        return 100.0 if template_id in bearish else 45.0
    if market_view == "neutral":
        return 100.0 if template_id in neutral else 45.0
    return 80.0


def _contract_warnings(
    *,
    mid: float | None,
    spread_pct: float | None,
    iv: float | None,
    volume: float | None,
    open_interest: float | None,
) -> list[str]:
    warnings = []
    if mid is None:
        warnings.append("missing_quote")
    if spread_pct is not None and spread_pct > 0.25:
        warnings.append("wide_spread")
    if iv is None:
        warnings.append("missing_iv")
    if (volume or 0.0) <= 0:
        warnings.append("zero_volume")
    if (open_interest or 0.0) <= 0:
        warnings.append("zero_open_interest")
    if (open_interest or 0.0) < 50:
        warnings.append("poor_liquidity")
    return list(dict.fromkeys(warnings))


def _mid(contract: dict[str, Any]) -> float | None:
    bid = _safe_float(contract.get("bid"))
    ask = _safe_float(contract.get("ask"))
    if bid is not None and ask is not None and ask >= bid:
        value = (bid + ask) / 2
        return value if value > 0 else None
    last = _safe_float(contract.get("last"))
    return last if last is not None and last > 0 else None


def _spread_pct(contract: dict[str, Any]) -> float | None:
    bid = _safe_float(contract.get("bid"))
    ask = _safe_float(contract.get("ask"))
    mid = _mid(contract)
    if bid is None or ask is None or mid is None or ask < bid:
        return None
    return (ask - bid) / mid


def _spread_score(spread_pct: float | None) -> float:
    if spread_pct is None:
        return 25.0
    if spread_pct <= 0.05:
        return 100.0
    if spread_pct <= 0.10:
        return 80.0
    if spread_pct <= 0.20:
        return 55.0
    if spread_pct <= 0.35:
        return 30.0
    return 10.0


def _activity_score(value: float | None, *, good: float, acceptable: float) -> float:
    if value is None:
        return 20.0
    if value >= good:
        return 100.0
    if value >= acceptable:
        return 75.0
    if value > 0:
        return 35.0
    return 10.0


def _iv_value_score(iv: float | None, *, objective: Objective) -> float:
    if iv is None:
        return 35.0
    raw = _clip(iv * 200, 0, 100)
    if objective == "buy_premium":
        return 100 - raw
    if objective == "sell_premium":
        return raw
    return 70.0


def _delta_score(delta: float | None, *, objective: Objective) -> float:
    if delta is None:
        return 45.0
    target = 0.25 if objective == "sell_premium" else 0.55
    distance = abs(abs(delta) - target)
    return _clip(100 - distance / target * 100, 0, 100)


def _premium_score(mid: float | None, *, spot: float) -> float:
    if mid is None or spot <= 0:
        return 20.0
    del spot
    return _clip(mid * 20, 0, 100)


def _vix_component(vix: float | None) -> float | None:
    return _component(vix, low=15.0, high=35.0, inverse=False)


def _component(
    value: float | None,
    *,
    low: float,
    high: float,
    inverse: bool,
) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if inverse:
        denominator = low - high
        if denominator == 0:
            return 50.0
        return _clip((low - parsed) / denominator * 100, 0, 100)
    denominator = high - low
    if denominator == 0:
        return 50.0
    return _clip((parsed - low) / denominator * 100, 0, 100)


def _iv_zone(iv_rank: float | None) -> str:
    if iv_rank is None:
        return "unknown"
    if iv_rank >= 85:
        return "extreme"
    if iv_rank >= 70:
        return "high"
    if iv_rank <= 25:
        return "low"
    return "normal"


def _fear_tier(score: float) -> str:
    if score >= 75:
        return "panic"
    if score >= 60:
        return "elevated"
    if score >= 35:
        return "normal"
    return "calm"


def _sentiment_regime(score: float) -> str:
    if score >= 60:
        return "risk_off"
    if score <= 35:
        return "risk_on"
    return "neutral"


def _earnings_strategy_tag(avg_crush: float | None, current_iv: float | None) -> str:
    if avg_crush is None or current_iv is None:
        return "insufficient_history"
    if avg_crush >= 0.25 and current_iv >= 0.40:
        return "high_crush_risk"
    if avg_crush >= 0.15:
        return "moderate_crush_risk"
    return "low_crush_history"


def _holding_situation(*, cost_basis: float, spot: float) -> str:
    if spot >= cost_basis * 1.20:
        return "gain_protection"
    if spot <= cost_basis * 0.85:
        return "falling_knife"
    if spot <= cost_basis:
        return "bottom_fishing"
    return "normal"


def _contracts_by_type(contracts: list[dict[str, Any]], option_type: str) -> list[dict[str, Any]]:
    return [
        contract
        for contract in contracts
        if str(contract.get("option_type", "")).upper() == option_type
    ]


def _nearest_strike(contracts: list[dict[str, Any]], target: float) -> dict[str, Any] | None:
    available = [
        contract
        for contract in contracts
        if _safe_float(contract.get("strike")) is not None
    ]
    if not available:
        return None
    return min(available, key=lambda item: abs(float(item["strike"]) - target))


def _alert_triggered(alert: dict[str, Any], context: dict[str, Any]) -> bool:
    alert_type = str(alert.get("type", ""))
    threshold = _safe_float(alert.get("threshold"))
    observed = _observed_value(alert, context)
    if threshold is None or observed is None:
        return False
    if alert_type.endswith("_above") or alert_type == "price_above":
        return observed > threshold
    if alert_type.endswith("_below") or alert_type == "price_below":
        return observed < threshold
    if alert_type == "unusual_activity_count_at_least":
        return observed >= threshold
    return False


def _observed_value(alert: dict[str, Any], context: dict[str, Any]) -> float | None:
    alert_type = str(alert.get("type", ""))
    if alert_type.startswith("price_"):
        return _safe_float(context.get("price"))
    if alert_type.startswith("iv_rank_"):
        return _safe_float(context.get("iv_rank"))
    if alert_type == "unusual_activity_count_at_least":
        return _safe_float(context.get("unusual_activity_count"))
    return None


def _rating(score: float) -> str:
    if score >= 75:
        return "Strong"
    if score >= 55:
        return "Watch"
    return "Avoid"


def _normalize_iv(value: float | None) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return parsed / 100.0 if parsed > 5 else parsed


def _average(values: list[float | None]) -> float:
    available = [value for value in values if value is not None]
    if not available:
        return 0.0
    return sum(available) / len(available)


def _weighted(values: list[tuple[float | None, float]]) -> float:
    available = [(value, weight) for value, weight in values if value is not None]
    if not available:
        return 0.0
    total_weight = sum(weight for _value, weight in available)
    if total_weight <= 0:
        return 0.0
    return sum(float(value) * weight for value, weight in available) / total_weight


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed
