"""Parallel, proportional-cost replays of frozen targets; no admission authority.

Each cost level starts with empty inventory and independently runs the existing
engine. This does not change a definition, original metrics, a legacy cost gate,
or any stored artifact. Callers own immutable input/output persistence. The source
closure and in-memory input digest must be frozen before calling the replay.
Minimum fees, volume capacity, market impact and second-engine stress qualification
are outside this contract. Neither this result nor a positive net return is alpha.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.portfolio.combiner import _check_replay
from quant_system.research.profile_backtests import _ScheduledTargets
from quant_system.research.reference_backtests import _metrics

USD_ATOL = 1e-7
QUANTITY_ATOL = 1e-9
MULTIPLIERS = (1, 2, 3)
_SOURCE_FILES = (
    "research/cost_replay.py", "research/profile_backtests.py",
    "research/reference_backtests.py", "portfolio/combiner.py",
    "backtest/engine.py", "backtest/models.py", "backtest/broker.py",
    "backtest/order_generation.py", "backtest/portfolio.py", "backtest/metrics.py",
    "trading_kernel/__init__.py", "trading_kernel/accounting.py",
    "trading_kernel/weights.py", "trading_kernel/models.py",
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _json_default(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"cost_replay_unserializable:{type(value).__name__}")


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=_json_default,
    ).encode()).hexdigest()


def cost_replay_source_identity() -> dict:
    """Read-only source closure, not a qualification or funding certificate."""
    root = Path(__file__).resolve().parents[1]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in _SOURCE_FILES}


def cost_replay_input_digest(*, prices, base_result, target_schedule, config, source_identity):
    """Seal exact in-memory inputs; caller must separately bind its raw file SHAs."""
    return _digest({
        "schema": "parallel_cost_replay_input/v1",
        "prices": {"columns": list(prices.columns),
                   "dtypes": [str(dtype) for dtype in prices.dtypes],
                   "rows": prices.to_dict("records")},
        "base_result": base_result,
        "target_schedule": target_schedule,
        "config": config.model_dump(mode="json"),
        "source_identity": source_identity,
    })


def _day(value):
    _require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
             "cost_replay_invalid_date")
    stamp = pd.Timestamp(value, tz="UTC")
    _require(not pd.isna(stamp), "cost_replay_invalid_date")
    return stamp


def _prepare(prices, base, schedule, config):
    _require(isinstance(config, BacktestConfig), "cost_replay_config_required")
    _require(config.initial_cash == 10_000 and config.commission_bps == 1
             and config.slippage_bps == 5 and config.annualization_factor == 252
             and config.execution_price == "next_open" and config.terminal_valuation == "close"
             and config.rebalance_frequency == "every_bar"
             and config.max_weight_per_symbol is None and config.sector_cap is None
             and not config.sector_map and math.isfinite(config.min_order_value),
             "cost_replay_config_scope_unsupported")
    definition = base.get("definition")
    execution_fields = ("commission_bps", "slippage_bps", "min_order_value",
                        "whole_share_orders", "execution_price")
    _require(isinstance(definition, dict)
             and type(definition.get("whole_share_orders")) is bool
             and all(type(definition.get(key)) in (int, float)
                     and math.isfinite(definition[key])
                     for key in ("commission_bps", "slippage_bps", "min_order_value"))
             and all(definition.get(key) == getattr(config, key) for key in execution_fields),
             "cost_replay_definition_config_mismatch")
    _require(base.get("status") == "available"
             and base.get("evaluation_initial_cash") == config.initial_cash
             and base.get("costs", {}).get("commission_bps") == 1
             and base.get("costs", {}).get("slippage_bps") == 5
             and re.fullmatch(r"[0-9a-f]{64}", str(base.get("definition_digest", ""))),
             "cost_replay_base_contract_invalid")
    dates = pd.DatetimeIndex([_day(row["date"]) for row in base["curve"]])
    _require(len(dates) > 0 and dates.is_unique and dates.is_monotonic_increasing
             and dates[0] == _day(base["start"]) and dates[-1] == _day(base["end"]),
             "cost_replay_base_calendar_invalid")
    _require({"timestamp", "symbol", "open", "close"}.issubset(prices.columns),
             "cost_replay_price_columns_missing")
    frame = prices.copy(deep=True)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    _require(frame.timestamp.notna().all()
             and frame.timestamp.equals(frame.timestamp.dt.normalize())
             and not frame.duplicated(["timestamp", "symbol"]).any(),
             "cost_replay_price_calendar_invalid")
    _require(frame.symbol.map(lambda v: isinstance(v, str)
                             and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", v) is not None).all(),
             "cost_replay_symbol_invalid")
    _require(np.isfinite(frame[["open", "close"]].to_numpy(dtype=float)).all()
             and (frame[["open", "close"]] > 0).all().all(),
             "cost_replay_price_invalid")
    frame = frame.loc[frame.timestamp.between(dates[0], dates[-1])].copy()
    _require(pd.DatetimeIndex(sorted(frame.timestamp.unique())).equals(dates),
             "cost_replay_price_calendar_incomplete")
    _require(isinstance(schedule, dict), "cost_replay_schedule_invalid")
    signals = {}
    for signal in base.get("signals", []):
        trade, decision = _day(signal["trade_date"]), _day(signal["signal_date"])
        _require(trade in dates and decision < trade and signal["trade_date"] not in signals,
                 "cost_replay_signal_calendar_invalid")
        signals[signal["trade_date"]] = signal.get("targets")
    _require(schedule == signals, "cost_replay_frozen_signals_mismatch")
    targets = {}
    for date, weights in schedule.items():
        stamp = _day(date)
        _require(stamp in dates, "cost_replay_target_date_outside_calendar")
        if weights is not None:
            _require(isinstance(weights, dict)
                     and all(isinstance(symbol, str) and symbol in set(frame.symbol)
                             and type(weight) in (int, float) and math.isfinite(weight)
                             and 0 <= weight <= 1 for symbol, weight in weights.items())
                     and sum(weights.values()) <= 1 + 1e-10,
                     "cost_replay_target_invalid")
        targets[stamp] = weights
    return frame, dates, targets


def _close(left, right, tolerance, reason):
    _require(math.isfinite(float(left)) and math.isfinite(float(right))
             and abs(float(left) - float(right)) <= tolerance, reason)


def _base_equivalence(result, base, config):
    curve = result.equity_curve
    _require(len(curve) == len(base["curve"]), "cost_replay_base_curve_mismatch")
    for expected, actual in zip(base["curve"], curve.itertuples(), strict=True):
        _require(_day(expected["date"]) == actual.timestamp, "cost_replay_base_curve_mismatch")
        _close(expected["equity"], actual.equity, USD_ATOL, "cost_replay_base_curve_mismatch")
    fills = result.trade_blotter
    _require(len(base["trades"]) == len(fills), "cost_replay_base_trades_mismatch")
    for expected, actual in zip(base["trades"], fills.itertuples(), strict=True):
        _require(_day(expected["date"]) == actual.timestamp
                 and expected["symbol"] == actual.symbol and expected["side"] == actual.side,
                 "cost_replay_base_trades_mismatch")
        for field in ("quantity", "requested_price", "fill_price", "commission"):
            _close(expected[field], getattr(actual, field),
                   QUANTITY_ATOL if field == "quantity" else USD_ATOL,
                   "cost_replay_base_trades_mismatch")
    metrics = _metrics(curve, fills, config.initial_cash)
    _require(base.get("metrics") == metrics, "cost_replay_base_metrics_mismatch")
    return {"matched": True, "curve_rows": len(curve), "trade_rows": len(fills),
            "metrics": "exact_original_metric_object", "rtol": 0,
            "usd_atol": USD_ATOL, "quantity_atol": QUANTITY_ATOL}


def _records(frame):
    return [{key: value.isoformat() if isinstance(value, pd.Timestamp) else value
             for key, value in row.items()} for row in frame.to_dict("records")]


def audit_cost_replay(result, *, prices, config, target_schedule, expected_sessions):
    """Check real output against prices, orders, cash and inventory without a broker.

    The vector accounting checker is supplemented with a scalar reconstruction of
    target orders and executable quantities. This catches jointly missing orders
    and fills, wrong quote sources, cash affordability and the stricter share
    tolerance. It does not rerun the engine or call its order/accounting kernel.
    """
    checked = _check_replay(result, config, expected_sessions)
    orders, fills, positions = result.orders, result.trade_blotter, result.positions
    _require(orders.order_id.notna().all() and orders.order_id.is_unique,
             "cost_replay_order_identity_invalid")
    _require(set(orders.timestamp).issubset(set(expected_sessions)),
             "cost_replay_order_calendar_invalid")
    _require(fills.order_id.is_unique, "cost_replay_multiple_fills_unsupported")
    _require(set(fills.order_id).issubset(set(orders.order_id)),
             "cost_replay_fill_without_order")
    cash, inventory, count = float(config.initial_cash), {}, 0
    for day in expected_sessions:
        bars = prices.loc[prices.timestamp == day].set_index("symbol")
        opening, closing = bars.open.to_dict(), bars.close.to_dict()
        weights = target_schedule.get(day.date().isoformat())
        actual_orders = orders.loc[orders.timestamp == day].to_dict("records")
        planned = []
        if weights is not None:
            symbols = sorted(set(inventory) | set(weights))
            _require(set(symbols).issubset(opening), "cost_replay_missing_open")
            equity = cash + sum(quantity * opening[symbol]
                                for symbol, quantity in inventory.items())
            for index, symbol in enumerate(symbols, 1):
                amount = (equity * weights.get(symbol, 0)
                          - inventory.get(symbol, 0) * opening[symbol])
                quantity = abs(amount) / opening[symbol]
                if config.whole_share_orders:
                    quantity = math.floor(quantity)
                if (abs(amount) < config.min_order_value
                        or quantity * opening[symbol] < config.min_order_value or quantity <= 0):
                    continue
                planned.append({"order_id": f"{day:%Y%m%d}-{index:04d}", "symbol": symbol,
                                "side": "buy" if amount > 0 else "sell", "quantity": quantity})
        _require(len(actual_orders) == len(planned), "cost_replay_orders_do_not_match_targets")
        for expected, actual in zip(planned, actual_orders, strict=True):
            _require(all(expected[key] == actual[key] for key in ("order_id", "symbol", "side")),
                     "cost_replay_order_target_identity_mismatch")
            _close(actual["quantity"], expected["quantity"], QUANTITY_ATOL,
                   "cost_replay_order_target_quantity_mismatch")
            if config.whole_share_orders:
                _require(actual["quantity"] == expected["quantity"],
                         "cost_replay_integer_order_mismatch")
        by_order = fills.loc[fills.timestamp == day].set_index("order_id")
        expected_fill_ids = []
        for order in sorted(planned, key=lambda item: item["side"] != "sell"):
            symbol, side, requested = order["symbol"], order["side"], order["quantity"]
            price = opening[symbol] * (
                1 + (1 if side == "buy" else -1) * config.slippage_bps / 10000)
            possible = (cash / (price * (1 + config.commission_bps / 10000))
                        if side == "buy" else inventory.get(symbol, 0))
            quantity = min(requested, max(possible, 0))
            if config.whole_share_orders:
                quantity = math.floor(quantity)
            if quantity <= 0:
                continue
            expected_fill_ids.append(order["order_id"])
            _require(order["order_id"] in by_order.index, "cost_replay_executable_fill_missing")
            fill = by_order.loc[order["order_id"]]
            _require(fill.symbol == symbol and fill.side == side
                     and fill.fill_id == "fill-" + order["order_id"],
                     "cost_replay_fill_identity_mismatch")
            _close(fill.requested_price, opening[symbol], USD_ATOL, "cost_replay_quote_mismatch")
            _close(fill.quantity, quantity, QUANTITY_ATOL, "cost_replay_fill_quantity_mismatch")
            if config.whole_share_orders:
                _require(fill.quantity == quantity, "cost_replay_integer_fill_mismatch")
            _require(fill.status == ("partial" if quantity < requested else "filled"),
                     "cost_replay_fill_status_mismatch")
            # Apply recorded, already-checked fills in original engine precision.
            # Exact decimal fee/affordability oracles are separately tested.
            if side == "buy":
                cash -= fill.gross_value + fill.commission
                inventory[symbol] = inventory.get(symbol, 0) + fill.quantity
            else:
                cash += fill.gross_value - fill.commission
                inventory[symbol] -= fill.quantity
            if abs(inventory[symbol]) < 1e-10:
                del inventory[symbol]
            count += 1
        _require(list(by_order.index) == expected_fill_ids, "cost_replay_fill_sequence_mismatch")
        observed = positions.loc[positions.timestamp == day].set_index("symbol")
        _require(set(observed.index) == set(inventory), "cost_replay_inventory_symbols_mismatch")
        _require(set(inventory).issubset(closing), "cost_replay_missing_mark")
        for symbol, quantity in inventory.items():
            _close(observed.loc[symbol, "quantity"], quantity, QUANTITY_ATOL,
                   "cost_replay_inventory_quantity_mismatch")
            _close(observed.loc[symbol, "close_price"], closing[symbol], USD_ATOL,
                   "cost_replay_mark_price_mismatch")
        curve = result.equity_curve.loc[result.equity_curve.timestamp == day].iloc[0]
        _close(curve.cash, cash, USD_ATOL, "cost_replay_scalar_cash_mismatch")
    return {**checked, "scalar_order_checks": len(orders), "scalar_fill_checks": count,
            "rtol": 0, "usd_atol": USD_ATOL, "quantity_atol": QUANTITY_ATOL}


def replay_cost_scenarios(*, prices, base_result, target_schedule, config, source_identity,
                          expected_input_digest):
    """Run fixed 1x/2x/3x costs with base equivalence, without changing old gates."""
    inputs = dict(prices=prices, base_result=base_result, target_schedule=target_schedule,
                  config=config, source_identity=source_identity)
    _require(source_identity == cost_replay_source_identity(), "cost_replay_source_changed")
    observed = cost_replay_input_digest(**inputs)
    _require(expected_input_digest == observed, "cost_replay_input_changed")
    frame, dates, targets = _prepare(prices, base_result, target_schedule, config)
    scenarios = []
    for multiplier in MULTIPLIERS:
        scaled = config.model_copy(update={"commission_bps": multiplier,
                                           "slippage_bps": 5 * multiplier})
        result = BacktestEngine(scaled).run(frame, _ScheduledTargets(targets))
        accounting = audit_cost_replay(result, prices=frame, config=scaled,
                                       target_schedule=target_schedule, expected_sessions=dates)
        if multiplier == 1:
            base_equivalence = _base_equivalence(result, base_result, config)
        scenarios.append({
            "multiplier": multiplier, "config": scaled.model_dump(mode="json"),
            "accounting": accounting, "metrics": _metrics(
                result.equity_curve, result.trade_blotter, scaled.initial_cash),
            "costs": {
                "commission_bps": multiplier, "slippage_bps": 5 * multiplier,
                "commission_usd": math.fsum(result.trade_blotter.commission),
                "slippage_usd": math.fsum(
                    (row.fill_price - row.requested_price) * row.quantity
                    * (1 if row.side == "buy" else -1)
                    for row in result.trade_blotter.itertuples()),
            },
            **{name: _records(getattr(result, name))
               for name in ("orders", "trade_blotter", "positions", "equity_curve")},
        })
    _require(cost_replay_input_digest(**inputs) == observed, "cost_replay_input_changed")
    _require(source_identity == cost_replay_source_identity(), "cost_replay_source_changed")
    return {
        "schema": "parallel_cost_replay/v1", "status": "evaluated",
        "input_digest": observed, "source_identity": source_identity,
        "definition_digest": base_result["definition_digest"],
        "target_schedule_digest": _digest(target_schedule),
        "base_result_digest": _digest(base_result),
        "base_equivalence": base_equivalence, "scenarios": scenarios, "engine_runs": 3,
        "research_only": True, "admission_authority": False, "funding_authority": False,
        "return_object": "net_total_return",
        "old_platform_metrics_mutated": False, "old_cost_gate_replaced": False,
        "minimum_fee_capacity_impact": "not_evaluated", "second_engine_stress": "not_evaluated",
    }
