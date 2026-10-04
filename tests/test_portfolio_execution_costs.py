"""Artificial net-order wiring and accounting checks; no market replay evidence."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_system.backtest.models import BacktestConfig, Order
from quant_system.backtest.portfolio import Portfolio
from quant_system.portfolio.combiner import AllocationPolicy, allocation_at, combine_targets
from quant_system.portfolio.execution_costs import (
    CostTier,
    ExecutionCostScenario,
    preflight_combined_targets,
    preflight_orders,
)


def fixture():
    dates = pd.bdate_range("2024-01-02", periods=252, tz="UTC")
    cutoff = dates[-1] + pd.Timedelta(hours=21)
    execution = cutoff + pd.Timedelta(hours=17, minutes=30)
    history = pd.DataFrame(
        {"a": np.sin(np.arange(252)) / 100, "b": np.cos(np.arange(252)) / 100}, index=dates
    )
    allocation = allocation_at(
        history,
        availability_times=pd.Series(dates + pd.Timedelta(hours=21), index=dates),
        expected_sessions=dates,
        component_ids=("a", "b"),
        decision_at=cutoff,
        policy=AllocationPolicy(method="equal_weight", gross_budget=1, sleeve_cap=0.5),
    )
    components = {
        key: {
            "known_at": cutoff,
            "execute_at": execution,
            "weights": {"SPY": 1},
            "source_digest": key * 64,
        }
        for key in ("a", "b")
    }
    combined = combine_targets(allocation, components, execute_at=execution)
    scenario = ExecutionCostScenario(
        scenario_id="artificial-contract-v1",
        interpretation="assumption_sensitivity_not_broker_tariff",
        tiers=(
            CostTier(
                minimum_daily_turnover_usd=0, commission_bps=20, minimum_fee_usd=3, slippage_bps=10
            ),
            CostTier(
                minimum_daily_turnover_usd=50_000,
                commission_bps=1,
                minimum_fee_usd=2,
                slippage_bps=5,
            ),
        ),
        max_prior_volume_participation=0.005,
        max_liquidity_age_hours=96,
    )
    prices = {
        "SPY": {
            "price": 100.0,
            "currency": "USD",
            "price_basis": "unadjusted",
            "as_of": execution.isoformat(),
            "available_at": execution.isoformat(),
            "source_digest": "c" * 64,
        }
    }
    liquidity = {
        "SPY": {
            "raw_volume_shares": 1000.0,
            "raw_turnover_usd": 100_000.0,
            "raw_low": 99.0,
            "raw_high": 101.0,
            "currency": "USD",
            "volume_unit": "shares",
            "price_basis": "unadjusted",
            "as_of": cutoff.isoformat(),
            "available_at": cutoff.isoformat(),
            "source_digest": "d" * 64,
        }
    }
    return combined, scenario, prices, liquidity


def test_real_combiner_to_order_generator_nets_then_charges_one_minimum_fee_without_fills():
    combined, scenario, prices, liquidity = fixture()
    portfolio = Portfolio(initial_cash=1000)
    config = BacktestConfig()
    before = copy.deepcopy((portfolio.__dict__, config.model_dump(), combined, prices, liquidity))
    result = preflight_combined_targets(
        combined,
        portfolio=portfolio,
        config=config,
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
    )
    assert result["order_count"] == 1  # Both sleeves want SPY; one net portfolio order.
    row = result["orders"][0]
    assert row["order"]["quantity"] == pytest.approx(10)
    assert row["requested_gross_usd"] == pytest.approx(1000.5)
    assert row["requested_commission_usd"] == 2
    assert row["requested_cash_debit_usd"] == pytest.approx(1002.5)
    assert row["capacity_budget_shares"] == 5
    assert row["budget_limited_quantity"] == row["over_budget_quantity"] == 5
    assert result["all_within_capacity_budget"] is False
    assert result["fills_created"] is result["nav_computed"] is False
    assert result["cash_and_inventory_feasibility"] == "not_evaluated"
    assert before == (portfolio.__dict__, config.model_dump(), combined, prices, liquidity)


@pytest.mark.parametrize(
    "defect",
    [
        "missing_volume",
        "currency",
        "availability",
        "as_of",
        "stale",
        "adjusted",
        "units",
        "inconsistent",
        "bool",
    ],
)
def test_unknown_or_inconsistent_liquidity_never_becomes_a_capacity_pass(defect):
    combined, scenario, prices, liquidity = fixture()
    row = liquidity["SPY"]
    if defect == "missing_volume":
        del row["raw_volume_shares"]
    elif defect == "currency":
        del row["currency"]
    elif defect == "availability":
        row["available_at"] = combined["execute_at"]
    elif defect == "as_of":
        del row["as_of"]
    elif defect == "stale":
        row["as_of"] = "2020-01-01T00:00:00+00:00"
    elif defect == "adjusted":
        row["price_basis"] = "qfq"
    elif defect == "units":
        row["volume_unit"] = "lots"
    elif defect == "inconsistent":
        row["raw_turnover_usd"] = 999_000.0
    else:
        row["raw_volume_shares"] = True
    result = preflight_combined_targets(
        combined,
        portfolio=Portfolio(initial_cash=1000),
        config=BacktestConfig(),
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
    )
    assert result["status"] == "not_evaluated"
    assert result["all_within_capacity_budget"] is None
    assert result["requested_commission_total_usd"] is None
    assert result["orders"][0]["status"] == "not_evaluated"


def test_duplicate_component_orders_are_refused_and_no_order_has_no_minimum_fee():
    combined, scenario, prices, liquidity = fixture()
    order = Order(
        order_id="one",
        timestamp=pd.Timestamp(combined["execute_at"]),
        symbol="SPY",
        side="buy",
        quantity=2,
    )
    with pytest.raises(ValueError, match="netted_once"):
        preflight_orders(
            [order, order],
            scenario=scenario,
            prices=prices,
            liquidity=liquidity,
            decision_at=combined["decision_at"],
            execute_at=combined["execute_at"],
        )
    portfolio = Portfolio(initial_cash=0)
    portfolio.positions["SPY"] = 10
    result = preflight_combined_targets(
        combined,
        portfolio=portfolio,
        config=BacktestConfig(),
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
    )
    assert result["order_count"] == 0 and result["requested_commission_total_usd"] == 0


def test_lower_liquidity_tier_and_sell_price_have_separate_net_fee_estimates():
    combined, scenario, prices, liquidity = fixture()
    liquidity["SPY"].update(raw_volume_shares=100.0, raw_turnover_usd=10_000.0)
    order = Order(
        order_id="one",
        timestamp=pd.Timestamp(combined["execute_at"]),
        symbol="SPY",
        side="sell",
        quantity=20,
    )
    result = preflight_orders(
        [order],
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
        decision_at=combined["decision_at"],
        execute_at=combined["execute_at"],
    )
    row = result["orders"][0]
    assert row["requested_gross_usd"] == pytest.approx(1998)
    assert row["requested_commission_usd"] == pytest.approx(3.996)
    assert row["requested_sale_proceeds_usd"] == pytest.approx(1994.004)
    assert row["requested_cash_debit_usd"] is None


def test_symbol_case_cannot_reuse_capacity_and_quote_overflow_stays_unevaluated():
    combined, scenario, prices, liquidity = fixture()
    order = Order(
        order_id="one",
        timestamp=pd.Timestamp(combined["execute_at"]),
        symbol="SPY",
        side="buy",
        quantity=10,
    )
    mixed_case = order.model_copy(update={"symbol": "spy"})
    kwargs = dict(
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
        decision_at=combined["decision_at"],
        execute_at=combined["execute_at"],
    )
    with pytest.raises(ValueError, match="netted_once"):
        preflight_orders([order, mixed_case], **kwargs)
    assert preflight_orders([mixed_case], **kwargs)["status"] == "not_evaluated"
    prices["SPY"]["price"] = 1e308
    result = preflight_orders([order], **kwargs)
    assert result["status"] == "not_evaluated"
    assert result["orders"][0]["reason"] == "cost_quote_nonfinite"
    assert result["requested_commission_total_usd"] is None
    json.dumps(result, allow_nan=False)


def test_existing_driver_cost_entry_reads_frozen_input_without_engine(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "portfolio_driver_cost_test",
        Path(__file__).parents[1] / "scripts/phase3_portfolio_research.py",
    )
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    monkeypatch.setattr(driver.BacktestEngine, "run", lambda *a, **k: pytest.fail("engine invoked"))
    combined, scenario, prices, liquidity = fixture()
    payload = {
        "schema": "portfolio_cost_preflight_input/v1",
        "combined_target": combined,
        "scenario": scenario.model_dump(mode="json"),
        "price_inputs": prices,
        "liquidity_inputs": liquidity,
        "portfolio_snapshot": {"cash": 1000, "positions": {}},
        "order_generation_config": BacktestConfig().model_dump(mode="json"),
    }
    path = tmp_path / "frozen-cost-input.json"
    path.write_text(json.dumps(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = driver.execution_cost_preflight(path, expected_input_digest=digest)
    assert result["order_count"] == 1 and result["actual_engine_invoked"] is False
    assert result["input_digest"] == digest
    assert "src/quant_system/portfolio/execution_costs.py" in result["source_identity"]["files"]
    assert "scripts/phase3_portfolio_research.py" in result["source_identity"]["files"]
    path.write_text(json.dumps({**payload, "changed": True}))
    with pytest.raises(ValueError, match="digest_changed"):
        driver.execution_cost_preflight(path, expected_input_digest=digest)


def test_finite_order_fees_cannot_overflow_the_report_total():
    combined, scenario, prices, liquidity = fixture()
    scenario = scenario.model_copy(
        update={
            "tiers": (
                CostTier(
                    minimum_daily_turnover_usd=0,
                    commission_bps=0,
                    minimum_fee_usd=8e307,
                    slippage_bps=0,
                ),
            )
        }
    )
    orders = [
        Order(
            order_id=symbol,
            timestamp=pd.Timestamp(combined["execute_at"]),
            symbol=symbol,
            side="buy",
            quantity=1,
        )
        for symbol in ("AAA", "BBB", "CCC")
    ]
    result = preflight_orders(
        orders,
        scenario=scenario,
        prices={order.symbol: prices["SPY"] for order in orders},
        liquidity={order.symbol: liquidity["SPY"] for order in orders},
        decision_at=combined["decision_at"],
        execute_at=combined["execute_at"],
    )
    assert all(row["status"] == "evaluated" for row in result["orders"])
    assert result["status"] == "not_evaluated"
    assert result["requested_commission_total_usd"] is None
    assert result["reason"] == "cost_commission_total_nonfinite"
    json.dumps(result, allow_nan=False)
