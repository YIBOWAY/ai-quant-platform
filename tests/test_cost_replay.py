"""Artificial accounting contracts; no market, provider or funding claims."""

from copy import deepcopy
from decimal import Decimal

import pandas as pd
import pytest

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.research.cost_replay import (
    cost_replay_input_digest,
    cost_replay_source_identity,
    replay_cost_scenarios,
)
from quant_system.research.profile_backtests import _ScheduledTargets
from quant_system.research.reference_backtests import _metrics


def artificial_case(targets=None, config=None, fixed_price=None):
    dates = pd.date_range("2024-01-02", periods=4, freq="B", tz="UTC")
    prices = pd.DataFrame([
        {"timestamp": day, "symbol": symbol, "open": value, "close": value}
        for day, values in zip(dates, [(100, 40), (110, 43), (105, 46), (108, 45)], strict=True)
        for symbol, value in zip(("AAA", "BBB"), values, strict=True)
    ])
    prices = prices.astype({"open": float, "close": float})
    if fixed_price is not None:
        prices[["open", "close"]] = fixed_price
    config = config or BacktestConfig(initial_cash=10_000)
    schedule = targets if targets is not None else {
        str(dates[0].date()): {"AAA": 1.0},
        str(dates[1].date()): None,
        str(dates[2].date()): {"BBB": 1.0},
        str(dates[3].date()): {},
    }
    result = BacktestEngine(config).run(prices, _ScheduledTargets({
        pd.Timestamp(day, tz="UTC"): value for day, value in schedule.items()
    }))
    base = {
        "status": "available", "definition_digest": "a" * 64,
        "definition": {key: getattr(config, key) for key in
                       ("commission_bps", "slippage_bps", "min_order_value",
                        "whole_share_orders", "execution_price")},
        "evaluation_initial_cash": 10_000,
        "start": str(dates[0].date()), "end": str(dates[-1].date()),
        "curve": [{"date": str(row.timestamp.date()), "equity": row.equity}
                  for row in result.equity_curve.itertuples()],
        "trades": [{"date": str(row.timestamp.date()), "symbol": row.symbol,
                    "side": row.side, "quantity": row.quantity,
                    "requested_price": row.requested_price, "fill_price": row.fill_price,
                    "commission": row.commission}
                   for row in result.trade_blotter.itertuples()],
        "metrics": _metrics(result.equity_curve, result.trade_blotter, 10_000),
        "costs": {"commission_bps": 1, "slippage_bps": 5},
        "signals": [{"signal_date": str((pd.Timestamp(day) - pd.Timedelta(days=1)).date()),
                     "trade_date": day, "targets": weights}
                    for day, weights in schedule.items()],
    }
    return dict(prices=prices, base_result=base, target_schedule=schedule, config=config,
                source_identity=cost_replay_source_identity())


def run_case(inputs):
    return replay_cost_scenarios(
        **inputs, expected_input_digest=cost_replay_input_digest(**inputs)
    )


def test_each_cost_rebuilds_cash_constrained_fills_with_independent_decimal_oracle():
    inputs = artificial_case()
    original = deepcopy(inputs["base_result"])
    report = run_case(inputs)
    assert report["status"] == "evaluated"
    assert report["admission_authority"] is False
    assert report["base_equivalence"]["matched"] is True
    assert report["engine_runs"] == 3
    for multiplier, row in zip((1, 2, 3), report["scenarios"], strict=True):
        # Closed-form oracle never calls the tested engine/accounting functions.
        rate = Decimal(multiplier) / 10000
        slip = Decimal(5 * multiplier) / 10000
        cash = Decimal(10000)
        qa = cash / (100 * (1 + slip) * (1 + rate))
        cash = qa * 105 * (1 - slip) * (1 - rate)
        qb = cash / (46 * (1 + slip) * (1 + rate))
        cash = qb * 45 * (1 - slip) * (1 - rate)
        fills = row["trade_blotter"]
        assert [fill["symbol"] for fill in fills] == ["AAA", "AAA", "BBB", "BBB"]
        assert [fill["side"] for fill in fills] == ["buy", "sell", "buy", "sell"]
        assert fills[0]["quantity"] == pytest.approx(float(qa), rel=0, abs=1e-9)
        assert fills[2]["quantity"] == pytest.approx(float(qb), rel=0, abs=1e-9)
        assert row["equity_curve"][-1]["equity"] == pytest.approx(float(cash), rel=0, abs=1e-7)
        assert row["accounting"]["accounting_checked"] is True
    assert inputs["base_result"] == original


def test_no_trades_legitimately_has_same_nav_in_all_cost_scenarios():
    report = run_case(artificial_case(targets={"2024-01-02": {}, "2024-01-03": None}))
    for scenario in report["scenarios"]:
        assert scenario["orders"] == scenario["trade_blotter"] == scenario["positions"] == []
        assert {row["equity"] for row in scenario["equity_curve"]} == {10_000}


@pytest.mark.parametrize("damage", ["order", "fill", "fee", "inventory", "calendar", "price"])
def test_independent_audit_rejects_corrupt_accounting(damage):
    from quant_system.research.cost_replay import audit_cost_replay

    inputs = artificial_case()
    result = BacktestEngine(inputs["config"]).run(inputs["prices"], _ScheduledTargets({
        pd.Timestamp(day, tz="UTC"): value for day, value in inputs["target_schedule"].items()
    }))
    if damage == "order":
        result.orders = result.orders.iloc[1:].copy()
    elif damage == "fill":
        result.trade_blotter = pd.concat([result.trade_blotter, result.trade_blotter.iloc[:1]])
    elif damage == "fee":
        result.trade_blotter.loc[0, "commission"] += 1
    elif damage == "inventory":
        result.positions.loc[0, "quantity"] += 1
    elif damage == "calendar":
        result.equity_curve = result.equity_curve.iloc[1:].copy()
    elif damage == "price":
        inputs["prices"].loc[0, "open"] += 1
    with pytest.raises(ValueError):
        audit_cost_replay(result, prices=inputs["prices"], config=inputs["config"],
                          target_schedule=inputs["target_schedule"],
                          expected_sessions=pd.date_range("2024-01-02", periods=4,
                                                          freq="B", tz="UTC"))


@pytest.mark.parametrize("damage", ["price", "schedule", "base", "config", "source"])
def test_frozen_input_and_source_changes_are_rejected(damage):
    inputs = artificial_case()
    sealed = cost_replay_input_digest(**inputs)
    if damage == "price":
        inputs["prices"].loc[0, "open"] += 0.00000000001
    elif damage == "schedule":
        inputs["target_schedule"]["2024-01-02"] = {}
    elif damage == "base":
        inputs["base_result"]["metrics"]["sharpe"] += 1
    elif damage == "config":
        inputs["config"] = inputs["config"].model_copy(update={"min_order_value": 1})
    else:
        inputs["source_identity"]["backtest/broker.py"] = "0" * 64
    with pytest.raises(ValueError, match="cost_replay_(input|source)_changed"):
        replay_cost_scenarios(**inputs, expected_input_digest=sealed)


@pytest.mark.parametrize("damage", ["equity", "trades", "metrics", "signals"])
def test_same_hash_envelope_does_not_replace_base_equivalence_checks(damage):
    inputs = artificial_case()
    if damage == "equity":
        inputs["base_result"]["curve"][0]["equity"] += 1
    elif damage == "trades":
        inputs["base_result"]["trades"][0]["quantity"] += 1
    elif damage == "metrics":
        inputs["base_result"]["metrics"]["sharpe"] += 1
    else:
        inputs["target_schedule"]["2024-01-02"] = {"BBB": 1}
    with pytest.raises(ValueError, match="cost_replay_(base|frozen_signals)"):
        run_case(inputs)


@pytest.mark.parametrize("damage", ["held_quote", "duplicate_price", "nonfinite", "future_signal"])
def test_invalid_market_or_decision_input_never_silently_drops_a_session(damage):
    inputs = artificial_case()
    if damage == "held_quote":
        inputs["prices"] = inputs["prices"].drop(index=2)
    elif damage == "duplicate_price":
        inputs["prices"] = pd.concat([inputs["prices"], inputs["prices"].iloc[:1]])
    elif damage == "nonfinite":
        inputs["prices"].loc[0, "open"] = float("inf")
    else:
        inputs["base_result"]["signals"][0]["signal_date"] = "2024-01-02"
    with pytest.raises(ValueError):
        run_case(inputs)


def test_whole_shares_are_exact_and_large_minimum_order_can_prevent_all_trades():
    inputs = artificial_case(config=BacktestConfig(initial_cash=10_000, whole_share_orders=True))
    for row in run_case(inputs)["scenarios"]:
        assert all(fill["quantity"] == int(fill["quantity"]) for fill in row["trade_blotter"])
        assert row["equity_curve"][-1]["cash"] >= 0
    inputs = artificial_case(config=BacktestConfig(initial_cash=10_000, min_order_value=20_000))
    for row in run_case(inputs)["scenarios"]:
        assert row["orders"] == row["trade_blotter"] == []


def test_true_cost_sidecar_does_not_rewrite_original_increment_metrics():
    from quant_system.research.intake_evaluation import compare_increment

    inputs = artificial_case()
    metrics = deepcopy(inputs["base_result"]["metrics"])
    job = {"results": [], "proposal": {"increment_objective": {
        "metric": "sharpe", "minimum_improvement": 0.05, "max_regressions": {},
    }}}
    for variant in ("baseline", "augmented"):
        job["results"].append({
            "variant": variant, "evaluation": {"evaluation_id": "ARTIFICIAL-only"},
            "evaluation_calendar_digest": "ARTIFICIAL-calendar",
            "validation": {"comparison": {"accepted": True}, "start": "2024-01-02",
                           "end": "2024-01-05", "platform_metrics": deepcopy(metrics),
                           "gates": {"cost": {"passed": True}}},
        })
    before = compare_increment(job)
    assert before["passed"] is False
    report = run_case(inputs)
    job["results"][1]["validation"]["gates"]["cost"] = {"passed": False}
    job["results"][1]["validation"]["parallel_cost_replay"] = report
    assert compare_increment(job) == before
    assert inputs["base_result"]["metrics"] == metrics


def test_jointly_omitting_orders_fills_and_positions_cannot_fake_a_valid_cash_replay():
    from quant_system.research.cost_replay import audit_cost_replay

    inputs = artificial_case()
    # A coherent all-cash engine result is wrong for the requested invested target.
    cash_result = BacktestEngine(inputs["config"]).run(inputs["prices"], _ScheduledTargets({}))
    with pytest.raises(ValueError, match="orders_do_not_match_targets"):
        audit_cost_replay(cash_result, prices=inputs["prices"], config=inputs["config"],
                          target_schedule=inputs["target_schedule"],
                          expected_sessions=pd.date_range("2024-01-02", periods=4,
                                                          freq="B", tz="UTC"))


def test_quantity_tolerance_is_stricter_than_legacy_combiner_tolerance():
    from quant_system.research.cost_replay import audit_cost_replay

    inputs = artificial_case()
    result = BacktestEngine(inputs["config"]).run(inputs["prices"], _ScheduledTargets({
        pd.Timestamp(day, tz="UTC"): value for day, value in inputs["target_schedule"].items()
    }))
    result.orders.loc[0, "quantity"] += 2e-9
    with pytest.raises(ValueError, match="order_target_quantity_mismatch"):
        audit_cost_replay(result, prices=inputs["prices"], config=inputs["config"],
                          target_schedule=inputs["target_schedule"],
                          expected_sessions=pd.date_range("2024-01-02", periods=4,
                                                          freq="B", tz="UTC"))


def test_matching_base_by_coincidence_cannot_change_frozen_whole_share_rules():
    config = BacktestConfig(initial_cash=10_000, whole_share_orders=True)
    inputs = artificial_case(targets={"2024-01-02": {"AAA": 1}}, config=config,
                             fixed_price=10_000 / (100 * 1.0005 * 1.0001))
    assert inputs["base_result"]["trades"][0]["quantity"] == 100
    inputs["config"] = config.model_copy(update={"whole_share_orders": False})
    with pytest.raises(ValueError, match="definition_config_mismatch"):
        run_case(inputs)


@pytest.mark.parametrize("field,new_value", [("min_order_value", 1),
                                             ("execution_price", "same_close"),
                                             ("commission_bps", 2),
                                             ("slippage_bps", 6)])
def test_execution_contract_must_match_even_if_base_curve_would_match(field, new_value):
    inputs = artificial_case(targets={"2024-01-02": {}})
    inputs["base_result"]["definition"][field] = new_value
    with pytest.raises(ValueError, match="definition_config_mismatch"):
        run_case(inputs)


def test_missing_execution_definition_does_not_create_qualified_cost_sidecar():
    inputs = artificial_case(targets={"2024-01-02": {}})
    inputs["base_result"].pop("definition")
    with pytest.raises(ValueError, match="definition_config_mismatch"):
        run_case(inputs)
