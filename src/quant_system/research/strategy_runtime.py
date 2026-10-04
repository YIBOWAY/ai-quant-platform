"""Pure, close-known decisions and in-memory historical evaluation of one recipe.

The decision date is the completed signal session. Calendar knowledge may name
the following trading session; no future price row is fabricated or consumed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import exchange_calendars
import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.d34.qlib_expr import compile_qlib_expr
from quant_system.experiments.scoring import _cross_sectional_zscore
from quant_system.factors.registry import build_factor_registry
from quant_system.research.active_metrics import active_metrics
from quant_system.research.profile_backtests import (
    _formula_scores,
    _monthly_signals,
    _ScheduledTargets,
    _unavailable,
    _wilder_rsi,
)
from quant_system.research.reference_backtests import _costs, _date, _metrics, _prepare_prices
from quant_system.research.strategy_definition import StrategyDefinition, validate_definition


@lru_cache(maxsize=32)
def _calendar(first_year: int, last_year: int):
    try:
        return exchange_calendars.get_calendar(
            "XNYS",
            start=f"{first_year}-01-01",
            end=f"{last_year + 1}-12-31",
        )
    except (ValueError, KeyError) as exc:
        raise ValueError("strategy_calendar_range_unavailable") from exc


def next_session(signal_session) -> pd.Timestamp:
    current = _date(signal_session)
    calendar = _calendar(current.year, current.year)
    try:
        return _date(calendar.next_session(current.tz_localize(None)))
    except (ValueError, KeyError) as exc:
        raise ValueError("strategy_signal_not_market_session") from exc


def latest_session(upper_date) -> pd.Timestamp:
    """Latest XNYS session on/before a date; does not assert its close has occurred."""
    upper = _date(upper_date)
    try:
        calendar = _calendar(upper.year - 1, upper.year)
        return _date(calendar.date_to_session(upper.tz_localize(None), direction="previous"))
    except (ValueError, KeyError) as exc:
        raise ValueError("strategy_calendar_range_unavailable") from exc


def session_open(session) -> pd.Timestamp:
    day = _date(session)
    try:
        opened = _calendar(day.year, day.year).session_open(day.tz_localize(None))
        return pd.Timestamp(opened).tz_convert("UTC")
    except (ValueError, KeyError) as exc:
        raise ValueError("strategy_signal_not_market_session") from exc


def _rebalance_due(definition, signal, trade):
    if definition.rebalance == "daily":
        return True
    if definition.rebalance == "weekly":
        return signal.isocalendar()[:2] != trade.isocalendar()[:2]
    return (signal.year, signal.month) != (trade.year, trade.month)


def _profile(definition: StrategyDefinition) -> dict:
    if definition.profile_snapshot is not None:
        return dict(definition.profile_snapshot)
    return {
        "id": "strategy:" + definition.content_digest[:20],
        "name": definition.title,
        "family": definition.kind,
        "symbols": list(definition.symbols),
        "peer_symbols": list(definition.symbols),
        "benchmark_symbol": definition.benchmark_symbol,
        "rebalance": definition.rebalance,
        "top_n": definition.top_n,
        "defensive_symbol": None,
    }


def _prepare_context(prices, definition, cutoff):
    needed = set(definition.symbols) | {definition.benchmark_symbol}
    history_start = _date(definition.history_start)
    if history_start > cutoff:
        raise ValueError("strategy_history_start_after_cutoff")
    # Initialize recursive indicators from exactly the frozen origin. Neither
    # earlier prices nor future prices may influence this definition's state.
    stamps = pd.to_datetime(prices["timestamp"], utc=True, errors="raise").dt.normalize()
    frame = _prepare_prices(
        prices.loc[
            stamps.between(history_start, cutoff)
            & prices.symbol.astype(str).str.upper().isin(needed)
        ]
    )
    if needed - set(frame.symbol):
        raise ValueError("strategy_missing_symbols:" + ",".join(sorted(needed - set(frame.symbol))))
    sessions = pd.DatetimeIndex(
        frame.loc[frame.symbol == definition.benchmark_symbol, "timestamp"].sort_values()
    )
    if not len(sessions):
        raise ValueError("strategy_no_benchmark_sessions")
    if set(frame.timestamp) - set(sessions):
        raise ValueError("strategy_benchmark_session_missing")
    # The origin may itself be a holiday (for example 2015-01-01); include
    # earlier sessions so the calendar can resolve that boundary without OOB.
    calendar = _calendar(history_start.year - 1, cutoff.year)
    expected = pd.DatetimeIndex(
        calendar.sessions_in_range(
            history_start.tz_localize(None),
            cutoff.tz_localize(None),
        )
    )
    expected = pd.to_datetime(expected, utc=True)
    if not sessions.equals(expected):
        raise ValueError("strategy_benchmark_calendar_incomplete")
    close = frame.pivot(index="timestamp", columns="symbol", values="close").reindex(sessions)
    profile = _profile(definition)
    context: dict[str, Any] = {
        "frame": frame,
        "sessions": sessions,
        "close": close,
        "profile": profile,
        "monthly": {},
        "scores": None,
    }
    if definition.kind == "profile" and profile["family"] == "rsi_reversion":
        values = close[profile["peer_symbols"][0]]
        context["rsi"] = _wilder_rsi(values)
        context["sma200"] = values.rolling(200, min_periods=200).mean()
    elif definition.profile_snapshot is not None:
        compiled = compile_qlib_expr(definition.formula.expression) if definition.formula else None
        formula_scores = _formula_scores(frame, sessions, profile, compiled) if compiled else None
        # Only a date index is extended. The entire added close row is NaN.
        following = next_session(sessions[-1])
        extended_close = close.reindex(sessions.append(pd.DatetimeIndex([following])))
        _, records = _monthly_signals(
            extended_close,
            profile,
            sessions[0],
            following,
            formula_scores,
        )
        context["monthly"] = {row["signal_date"]: row for row in records}
    elif definition.formula is not None:
        formula_profile = {
            "peer_symbols": list(definition.symbols),
            "eligibility_window": definition.formula.eligibility_window,
        }
        scores = _formula_scores(
            frame,
            sessions,
            formula_profile,
            compile_qlib_expr(definition.formula.expression),
        )
        if definition.formula.require_monthly_history:
            raise ValueError("strategy_formula_monthly_history_requires_frozen_profile")
        context["scores"] = scores
    else:
        context["scores"], context["components"] = _blend_scores(frame, sessions, definition)
    return context


def _blend_scores(frame, sessions, definition):
    index = pd.MultiIndex.from_product(
        [sessions, definition.symbols],
        names=["timestamp", "symbol"],
    )
    dense = frame.set_index(["timestamp", "symbol"]).reindex(index).reset_index()
    dense = dense.sort_values(["symbol", "timestamp"], ignore_index=True)
    registry = build_factor_registry()
    values = pd.DataFrame(index=pd.MultiIndex.from_frame(dense[["timestamp", "symbol"]]))
    for spec in definition.factors:
        if spec.expression is not None:
            # This helper executes only the existing whitelist compiler output,
            # retains missing fields, and enforces the frozen expression's window.
            expression_scores = _formula_scores(
                frame,
                sessions,
                {"peer_symbols": list(definition.symbols), "eligibility_window": spec.lookback},
                compile_qlib_expr(spec.expression),
            )
            values[spec.factor_id] = expression_scores.stack(future_stack=True).reindex(
                values.index
            )
            continue
        factor = registry.create(spec.factor_id, lookback=spec.lookback)
        prepared = factor._prepare_input(dense)
        # BaseFactor.compute intentionally drops its last row without a next bar.
        # Reuse the same value implementation, dating the final value by calendar.
        computed = factor._compute_values(prepared)
        if not computed.index.equals(prepared.index):
            raise ValueError("strategy_factor_value_index_mismatch")
        window = spec.lookback * (3 if spec.factor_id == "macd" else 1) + 1
        finite = np.isfinite(prepared[["close", "volume"]]).all(axis=1)
        complete = finite.groupby(prepared.symbol, sort=False).transform(
            lambda rows, window=window: rows.rolling(window, min_periods=window).sum().eq(window)
        )
        values[spec.factor_id] = pd.to_numeric(computed, errors="raise").where(complete).to_numpy()
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    # Every component is normalized on the same complete intersection, never zero-filled.
    components = pd.DataFrame(index=values.index)
    denominator = sum(abs(spec.weight) for spec in definition.factors)
    for spec in definition.factors:
        directed = values[spec.factor_id] * (-1 if spec.direction == "lower_is_better" else 1)
        if definition.normalization == "rank":
            normalized = directed.groupby(level="timestamp").rank(method="average", pct=True)
        else:
            normalized = directed.groupby(level="timestamp").transform(_cross_sectional_zscore)
        components[spec.factor_id] = normalized * spec.weight / denominator
    score = components.sum(axis=1).unstack("symbol")
    return score.reindex(sessions), components


def _weights(current_weights, definition):
    weights = {str(key).upper(): float(value) for key, value in (current_weights or {}).items()}
    if (
        set(weights) - set(definition.symbols)
        or any(not np.isfinite(value) or value < 0 for value in weights.values())
        or sum(weights.values()) > 1 + 1e-8
    ):
        raise ValueError("strategy_current_weights_invalid")
    return {key: value for key, value in weights.items() if value > 0}


def _decision(context, definition, signal, current_weights):
    trade = next_session(signal)
    result = {
        "signal_date": signal.date().isoformat(),
        "trade_date": trade.date().isoformat(),
        "definition_digest": definition.content_digest,
        "rebalance_due": _rebalance_due(definition, signal, trade),
        "targets": None,
        "scores": [],
        "eligible_symbols": [],
        "eligible_count": 0,
        "ready": False,
        "reason": None,
    }
    sessions = context["sessions"]
    if signal not in sessions:
        raise ValueError("strategy_signal_session_missing")
    current = _weights(current_weights, definition)
    if any(not np.isfinite(context["close"].loc[signal, symbol]) for symbol in current):
        raise ValueError("strategy_held_symbol_price_missing")
    if not result["rebalance_due"]:
        result.update(ready=True, reason="not_rebalance_session")
        return result
    profile = context["profile"]
    if definition.kind == "profile" and profile["family"] == "rsi_reversion":
        symbol = profile["peer_symbols"][0]
        position = sessions.get_loc(signal)
        tail = context["rsi"].iloc[max(0, position - 2) : position + 1]
        mean, price = context["sma200"].loc[signal], context["close"].loc[signal, symbol]
        if len(tail) != 3 or not np.isfinite([*tail, mean, price]).all():
            result["reason"] = "incomplete_history"
            return result
        r1, r2, rsi = tail
        action = "hold" if current else "flat"
        if current and rsi > 75:
            result["targets"], action = {}, "sell"
        elif not current and price > mean and r1 < 65 and r1 > r2 > rsi:
            result["targets"], action = {symbol: 1.0}, "buy"
        result.update(
            ready=True,
            eligible_count=1,
            eligible_symbols=[symbol],
            action=action,
            scores=[
                {
                    "symbol": symbol,
                    "rsi_day1": float(r1),
                    "rsi_day2": float(r2),
                    "rsi2": float(rsi),
                    "sma200": float(mean),
                    "close": float(price),
                }
            ],
        )
        return result
    if definition.profile_snapshot is not None:
        record = context["monthly"].get(result["signal_date"])
        if record is None:
            result["reason"] = "incomplete_history"
            return result
        if record["trade_date"] != result["trade_date"]:
            raise ValueError("strategy_calendar_price_session_mismatch")
        result.update(record)
        if not record["ready"]:
            result["reason"] = "incomplete_history"
        return result
    raw = context["scores"].loc[signal].dropna().sort_index()
    scores = [{"symbol": symbol, "score": float(value)} for symbol, value in raw.items()]
    if "components" in context and len(raw):
        components = context["components"].xs(signal, level="timestamp")
        for row in scores:
            row["components"] = {
                key: float(value) for key, value in components.loc[row["symbol"]].items()
            }
    scores.sort(
        key=lambda row: (
            row["score"] if definition.selection == "bottom" else -row["score"],
            row["symbol"],
        )
    )
    result.update(scores=scores, eligible_symbols=sorted(raw.index), eligible_count=len(raw))
    if not len(raw):
        result["reason"] = "incomplete_history"
        return result
    selected = [row for row in scores if definition.selection != "positive_top" or row["score"] > 0]
    selected = selected[: definition.top_n]
    weight = (
        min(definition.max_weight_per_symbol, definition.target_gross_exposure / len(selected))
        if selected
        else 0
    )
    result.update(ready=True, targets={row["symbol"]: weight for row in selected if weight > 0})
    return result


def decision_for_session(
    prices: pd.DataFrame,
    definition: StrategyDefinition | dict,
    decision_session,
    current_weights: dict[str, float] | None = None,
) -> dict:
    """Return close-known targets; ``None`` keeps holdings and ``{}`` liquidates.

    Callers provide actual current holdings for stateful profiles. The default is
    an empty portfolio, not a replay or inference of prior real executions.
    """
    definition = validate_definition(definition)
    signal = _date(decision_session)
    context = _prepare_context(prices, definition, signal)
    return _decision(context, definition, signal, current_weights)


def _run(frame, targets, definition, *, initial_cash, gross=False):
    return BacktestEngine(
        BacktestConfig(
            initial_cash=initial_cash,
            commission_bps=0 if gross else definition.commission_bps,
            slippage_bps=0 if gross else definition.slippage_bps,
            min_order_value=definition.min_order_value,
            whole_share_orders=definition.whole_share_orders,
        )
    ).run(frame, _ScheduledTargets(targets))


def _period(curve, results, initial_cash, start, end, label):
    group = curve.loc[curve.timestamp.between(start, end)]
    row = {
        "label": label,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "sessions": len(group),
        "status": "available" if len(group) else "unavailable",
    }
    for field, key, result in zip(
        ("equity", "benchmark", "peer"),
        ("metrics", "benchmark_metrics", "peer_metrics"),
        results,
        strict=True,
    ):
        prior = curve.loc[curve.timestamp < start, field]
        initial = float(prior.iloc[-1]) if len(prior) else initial_cash
        fills = result.trade_blotter
        if len(fills):
            fills = fills.loc[fills.timestamp.between(start, end)]
        row[key] = _metrics(
            group[["timestamp", field]].rename(columns={field: "equity"}), fills, initial
        )
    return row


def evaluate_definition(
    prices,
    definition: StrategyDefinition | dict,
    start,
    end,
    *,
    initial_cash: float | None = None,
) -> dict:
    """Evaluate at an optional cash scale without changing the frozen strategy recipe."""
    definition = validate_definition(definition)
    profile = _profile(definition)
    evaluation_cash = definition.initial_cash if initial_cash is None else float(initial_cash)

    def unavailable(status, reason):
        result = _unavailable(profile, status, reason)
        result["evaluation_initial_cash"] = evaluation_cash
        return result

    try:
        if not np.isfinite(evaluation_cash) or evaluation_cash <= 0:
            raise ValueError("strategy_evaluation_initial_cash_invalid")
        start, end = _date(start), _date(end)
        if start > end:
            raise ValueError("strategy_invalid_date_range")
        context = _prepare_context(prices, definition, end)
        sessions, frame = context["sessions"], context["frame"]
        evaluation_sessions = sessions[sessions >= start]
        if not len(evaluation_sessions):
            return unavailable("unavailable", "strategy_no_evaluation_sessions")
        targets, records, current = {}, [], {}
        for signal, trade in zip(sessions[:-1], sessions[1:], strict=True):
            if trade < start:
                continue
            decision = _decision(context, definition, signal, current)
            if decision["trade_date"] != trade.date().isoformat():
                raise ValueError("strategy_calendar_price_session_mismatch")
            if decision["targets"] is not None:
                targets[trade] = decision["targets"]
                current = decision["targets"]
            if decision["rebalance_due"] and (decision["ready"] or decision["targets"] is not None):
                records.append(decision)
        if not any(row["ready"] for row in records):
            return unavailable("unavailable", "strategy_no_signal_with_complete_history")
        evaluation = frame.loc[frame.timestamp.isin(evaluation_sessions)]
        result, gross = (
            _run(evaluation, targets, definition, initial_cash=evaluation_cash, gross=flag)
            for flag in (False, True)
        )
        benchmark = definition.benchmark_symbol
        benchmark_result = _run(
            evaluation.loc[evaluation.symbol == benchmark],
            {evaluation_sessions[0]: {benchmark: 1.0}},
            definition,
            initial_cash=evaluation_cash,
        )
        peer_symbols = profile["peer_symbols"]
        peer_targets = (
            {evaluation_sessions[0]: {peer_symbols[0]: 1.0}}
            if len(peer_symbols) == 1
            else {
                _date(row["trade_date"]): {
                    symbol: 1 / row["eligible_count"] for symbol in row["eligible_symbols"]
                }
                if row["ready"] and row["eligible_count"]
                else {}
                for row in records
            }
        )
        peer_result = _run(evaluation, peer_targets, definition, initial_cash=evaluation_cash)
        curve = result.equity_curve[["timestamp", "equity"]].copy()
        for key, other in (("benchmark", benchmark_result), ("peer", peer_result)):
            if not curve.timestamp.equals(other.equity_curve.timestamp):
                raise ValueError("strategy_comparison_sessions_mismatch")
            curve[key] = other.equity_curve.equity.to_numpy()
        results = result, benchmark_result, peer_result
        years = [
            {
                "year": int(year),
                **_period(
                    curve,
                    results,
                    evaluation_cash,
                    group.timestamp.iloc[0],
                    group.timestamp.iloc[-1],
                    str(year),
                ),
            }
            for year, group in curve.groupby(curve.timestamp.dt.year, sort=True)
        ]
        # Historical partitions are diagnostics, not unused test evidence.
        split_dates = (
            ("train", "2018-01-01", "2021-12-31"),
            ("validation", "2022-01-01", "2024-12-31"),
            ("test", "2025-01-01", max(end, _date("2025-01-01"))),
        )
        splits = {
            label: _period(curve, results, evaluation_cash, _date(lo), _date(hi), label)
            for label, lo, hi in split_dates
        }
        equity = result.equity_curve
        defensive = profile.get("defensive_symbol")
        risk_positions = result.positions.loc[result.positions.symbol != defensive]
        risk_values = (
            risk_positions.groupby("timestamp")
            .market_value.sum()
            .reindex(equity.timestamp, fill_value=0)
        )
        trades = [
            {
                "date": row.timestamp.date().isoformat(),
                "symbol": row.symbol,
                "side": row.side,
                "quantity": float(row.quantity),
                "requested_price": float(row.requested_price),
                "fill_price": float(row.fill_price),
                "commission": float(row.commission),
            }
            for row in result.trade_blotter.itertuples(index=False)
        ]
        return {
            "profile": profile,
            "definition": definition.model_dump(mode="json"),
            "definition_digest": definition.content_digest,
            "evaluation_initial_cash": evaluation_cash,
            "status": "available",
            "reason": None,
            "diagnostic": None,
            "metrics": _metrics(equity, result.trade_blotter, evaluation_cash),
            "gross_metrics": _metrics(gross.equity_curve, gross.trade_blotter, evaluation_cash),
            "benchmark_metrics": _metrics(
                benchmark_result.equity_curve,
                benchmark_result.trade_blotter,
                evaluation_cash,
            ),
            "peer_metrics": _metrics(
                peer_result.equity_curve, peer_result.trade_blotter, evaluation_cash
            ),
            "active_metrics": active_metrics(
                curve, initial_cash=evaluation_cash, benchmark_symbol=benchmark
            ),
            "curve": [
                {
                    "date": row.timestamp.date().isoformat(),
                    "equity": float(row.equity),
                    "benchmark": float(row.benchmark),
                    "peer": float(row.peer),
                }
                for row in curve.itertuples(index=False)
            ],
            "by_year": years,
            "splits": splits,
            "costs": _costs(result.trade_blotter),
            "benchmark_costs": _costs(benchmark_result.trade_blotter),
            "peer_costs": _costs(peer_result.trade_blotter),
            "average_exposure": float(equity.market_value.div(equity.equity).mean()),
            "average_risk_exposure": float(
                np.mean(risk_values.to_numpy() / equity.equity.to_numpy())
            ),
            "trade_count": len(trades),
            "signals": records,
            "trades": trades,
            "peer_signals": [
                {"trade_date": day.date().isoformat(), "targets": weights}
                for day, weights in peer_targets.items()
            ],
            "eligibility": {
                "peer_uses_strategy_eligible_set": len(peer_symbols) > 1,
                "signal_sessions": len(records),
                "ready_signal_sessions": sum(row["ready"] for row in records),
                "eligible_counts": [
                    {"signal_date": row["signal_date"], "count": row["eligible_count"]}
                    for row in records
                ],
            },
            "start": evaluation_sessions[0].date().isoformat(),
            "end": evaluation_sessions[-1].date().isoformat(),
            "source": "futu",
            "price_adjustment": "qfq",
            "frequency": "daily",
            "evaluation_note": (
                "历史分区已用于研发诊断，不是未见holdout；"
                "前瞻验证从冻结定义之后真实产生的记录开始。"
            ),
            "coverage": {
                "requested_start": start.date().isoformat(),
                "requested_end": end.date().isoformat(),
                "loaded_start": frame.timestamp.min().date().isoformat(),
                "loaded_end": frame.timestamp.max().date().isoformat(),
                "evaluation_sessions": len(evaluation_sessions),
                "universe_count": len(peer_symbols),
                "price_fill": "none",
                "holdings_missing_price": "failed",
            },
        }
    except (KeyError, ValueError, TypeError) as exc:
        return unavailable("failed", str(exc))
