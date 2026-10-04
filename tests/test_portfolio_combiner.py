"""Artificial fixtures only: module contracts, never market or alpha evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.portfolio.combiner import (
    AllocationPolicy,
    allocation_at,
    combine_targets,
    compare_replayed_portfolios,
    paired_sharpe_power,
)
from quant_system.research.profile_backtests import _ScheduledTargets


def history():
    sessions = pd.bdate_range("2020-01-01", periods=255, tz="UTC")
    rng = np.random.default_rng(20260926)
    returns = pd.DataFrame(rng.normal(0, 0.01, (255, 2)), index=sessions, columns=["a", "b"])
    available = pd.Series(sessions + pd.Timedelta(hours=22), index=sessions)
    return returns, available, sessions[:252], sessions[251] + pd.Timedelta(hours=23)


def test_equal_weight_uses_complete_known_history_and_future_perturbation_is_irrelevant():
    returns, available, expected, cutoff = history()
    kwargs = dict(
        availability_times=available,
        expected_sessions=expected,
        component_ids=("a", "b"),
        decision_at=cutoff,
        policy=AllocationPolicy(method="equal_weight", gross_budget=0.8, sleeve_cap=0.5),
    )
    before = allocation_at(returns, **kwargs)
    returns.loc[returns.index > expected[-1]] = 999
    after = allocation_at(returns, **kwargs)
    assert before == after
    assert before["sleeve_weights"] == {"a": 0.4, "b": 0.4}
    assert abs(before["unallocated_cash_weight"] - 0.2) < 1e-12
    assert before["correlation"]["a"]["a"] == 1.0


def allocated():
    returns, available, expected, cutoff = history()
    return allocation_at(
        returns,
        availability_times=available,
        expected_sessions=expected,
        component_ids=("a", "b"),
        decision_at=cutoff,
        policy=AllocationPolicy(method="equal_weight", gross_budget=0.8, sleeve_cap=0.5),
    )


def snapshots(allocation, execution):
    return {
        "a": {
            "known_at": allocation["decision_at"],
            "execute_at": execution,
            "weights": {"SPY": 0.5, "IEF": 0.25},
            "source_digest": "a" * 64,
        },
        "b": {
            "known_at": allocation["decision_at"],
            "execute_at": execution,
            "weights": {"SPY": 0.25},
            "source_digest": "b" * 64,
        },
    }


def test_symbol_targets_net_once_and_omitted_component_moves_to_cash_without_reoptimization():
    allocation = allocated()
    execution = pd.Timestamp(allocation["decision_at"]) + pd.Timedelta(days=1)
    components = snapshots(allocation, execution)
    full = combine_targets(allocation, components, execute_at=execution)
    removed = combine_targets(allocation, components, execute_at=execution, omitted_component="a")
    assert full["symbol_weights"] == {"IEF": 0.1, "SPY": 0.30000000000000004}
    assert abs(full["cash_weight"] - 0.6) < 1e-12
    assert removed["symbol_weights"] == {"SPY": 0.1}
    assert removed["cash_weight"] == 0.9
    assert removed["sleeve_weights"]["b"] == full["sleeve_weights"]["b"] == 0.4
    assert removed["costs"]["capacity"]["status"] == "not_evaluated"


def prices(periods=4):
    sessions = pd.bdate_range("2021-01-04", periods=periods, tz="UTC")
    return pd.DataFrame(
        [
            {
                "timestamp": day,
                "symbol": symbol,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1_000_000,
            }
            for day in sessions
            for symbol in ("SPY", "IEF")
        ]
    )


def test_component_switches_net_before_actual_engine_and_charge_no_extra_internal_trade_fees():
    allocation = allocated()
    frame = prices()
    days = pd.DatetimeIndex(frame.timestamp.unique())
    signals = {}
    first = snapshots(allocation, days[0])
    first["a"]["weights"], first["b"]["weights"] = {"SPY": 1.0}, {"IEF": 1.0}
    last = snapshots(allocation, days[2])
    last["a"]["weights"], last["b"]["weights"] = {"IEF": 1.0}, {"SPY": 1.0}
    for day, target in ((days[0], first), (days[2], last)):
        signals[day] = combine_targets(allocation, target, execute_at=day)["symbol_weights"]
    config = BacktestConfig(initial_cash=100_000, commission_bps=1, slippage_bps=5)
    actual = BacktestEngine(config).run(frame, _ScheduledTargets(signals))
    unchanged = BacktestEngine(config).run(
        frame, _ScheduledTargets({day: {"IEF": 0.4, "SPY": 0.4} for day in signals})
    )
    pd.testing.assert_frame_equal(actual.trade_blotter, unchanged.trade_blotter)
    pd.testing.assert_frame_equal(actual.equity_curve, unchanged.equity_curve)
    assert actual.trade_blotter.commission.sum() > 0


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("row", "declared_session_missing"),
        ("value", "nonfinite"),
        ("availability", "not_available"),
        ("duplicate", "duplicate"),
        ("column", "component_identity"),
    ],
)
def test_missing_or_unknown_history_cannot_shrink_the_estimation_window(mutation, reason):
    returns, available, expected, cutoff = history()
    if mutation == "row":
        returns = returns.drop(expected[20])
    if mutation == "value":
        returns.loc[expected[20], "a"] = np.nan
    if mutation == "availability":
        available.loc[expected[-1]] = cutoff + pd.Timedelta(seconds=1)
    if mutation == "duplicate":
        returns = pd.concat([returns, returns.iloc[[0]]])
    if mutation == "column":
        returns = returns.drop(columns="a")
    with pytest.raises(ValueError, match=reason):
        allocation_at(
            returns,
            availability_times=available,
            expected_sessions=expected,
            component_ids=("a", "b"),
            decision_at=cutoff,
            policy=AllocationPolicy("erc", 1, 1),
        )


def test_erc_matches_existing_solver_and_caps_leave_cash_or_refuse_full_budget():
    returns, available, expected, cutoff = history()
    kwargs = dict(
        availability_times=available,
        expected_sessions=expected,
        component_ids=("a", "b"),
        decision_at=cutoff,
    )
    erc = allocation_at(returns, **kwargs, policy=AllocationPolicy("erc", 1, 1))
    assert erc["erc_diagnostics_before_caps"]["maximum_budget_error"] < 1e-6
    assert erc["erc_source"]["sha256"]
    capped = allocation_at(returns, **kwargs, policy=AllocationPolicy("erc", 1, 0.2))
    assert capped["sleeve_weights"] == {"a": 0.2, "b": 0.2}
    assert capped["unallocated_cash_weight"] == 0.6
    assert not capped["erc_equal_risk_after_caps_claimed"]
    with pytest.raises(ValueError, match="full_budget_cap_infeasible"):
        allocation_at(returns, **kwargs, policy=AllocationPolicy("erc", 1, 0.2, True))
    returns["a"] = 0
    with pytest.raises(ValueError, match="zero_or_invalid_variance"):
        allocation_at(returns, **kwargs, policy=AllocationPolicy("erc", 1, 1))


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "target_missing"),
        ("negative", "negative"),
        ("leveraged", "leveraged"),
        ("future", "target_from_future"),
        ("execute", "execution_mismatch"),
        ("fees", "target_schema"),
        ("allocation", "allocation_identity"),
    ],
)
def test_invalid_or_missing_component_targets_fail_closed(mutation, reason):
    allocation = allocated()
    execution = pd.Timestamp(allocation["decision_at"]) + pd.Timedelta(days=1)
    components = snapshots(allocation, execution)
    if mutation == "missing":
        components.pop("b")
    if mutation == "negative":
        components["a"]["weights"] = {"SPY": -0.1}
    if mutation == "leveraged":
        components["a"]["weights"] = {"SPY": 1, "IEF": 1}
    if mutation == "future":
        components["a"]["known_at"] = execution
    if mutation == "execute":
        components["a"]["execute_at"] = execution + pd.Timedelta(days=1)
    if mutation == "fees":
        components["a"]["component_fee_deduction"] = 5
    if mutation == "allocation":
        allocation["sleeve_weights"]["a"] = 0.9
    with pytest.raises(ValueError, match=reason):
        combine_targets(allocation, components, execute_at=execution)


def replay_pair():
    allocation = allocated()
    frame = prices(140)
    days = pd.DatetimeIndex(frame.timestamp.unique())
    for index, symbol in enumerate(("SPY", "IEF")):
        mask = frame.symbol == symbol
        value = 100 * np.exp(
            0.0003 * np.arange(len(days)) + 0.015 * np.sin(np.arange(len(days)) / (4 + index))
        )
        for column in ("open", "high", "low", "close"):
            frame.loc[mask, column] = value
    components = snapshots(allocation, days[0])
    full = combine_targets(allocation, components, execute_at=days[0])
    removed = combine_targets(allocation, components, execute_at=days[0], omitted_component="a")
    config = BacktestConfig(initial_cash=100_000, commission_bps=1, slippage_bps=5)

    def replay(target):
        return BacktestEngine(config).run(
            frame, _ScheduledTargets({days[0]: target["symbol_weights"]})
        )

    return replay(full), replay(removed), config, days, {days[0]: full}, {days[0]: removed}


def test_pair_report_uses_actual_net_engine_curves_and_rejects_double_fee_subtraction():
    full, removed, config, days, full_schedule, removed_schedule = replay_pair()
    kwargs = dict(
        config=config,
        expected_sessions=days,
        combined_schedule=full_schedule,
        without_schedule=removed_schedule,
        removed_component="a",
    )
    report = compare_replayed_portfolios(full, removed, **kwargs)
    assert report["comparison"]["status"] == "ready"
    assert report["paired_sharpe_difference"]["status"] == "ready"
    assert report["costs"]["component_costs_subtracted_again"] is False
    assert report["costs"]["tiered_fees"]["status"] == "not_evaluated"
    assert report["numerai_mpc_claimed"] is False
    altered = full.model_copy(deep=True)
    duplicate_fee = float(altered.trade_blotter.commission.sum())
    altered.equity_curve["cash"] -= duplicate_fee
    altered.equity_curve["equity"] -= duplicate_fee
    with pytest.raises(ValueError, match="cash_fill_reconciliation"):
        compare_replayed_portfolios(altered, removed, **kwargs)


def test_erc_future_perturbation_and_perfectly_correlated_history_keep_declared_shrinkage():
    returns, available, expected, cutoff = history()
    returns["b"] = 2 * returns["a"]
    kwargs = dict(
        availability_times=available,
        expected_sessions=expected,
        component_ids=("a", "b"),
        decision_at=cutoff,
        policy=AllocationPolicy("erc", 1, 1),
    )
    original = allocation_at(returns, **kwargs)
    returns.loc[returns.index > expected[-1]] = np.nan
    assert allocation_at(returns, **kwargs) == original
    assert original["erc_diagnostics_before_caps"]["diagonal_shrinkage"] == 0.1
    assert original["sleeve_weights"]["a"] == pytest.approx(2 / 3)
    assert original["sleeve_weights"]["b"] == pytest.approx(1 / 3)


def test_cash_component_requires_explicit_empty_target_instead_of_missing_record():
    allocation = allocated()
    execution = pd.Timestamp(allocation["decision_at"]) + pd.Timedelta(days=1)
    components = snapshots(allocation, execution)
    components["a"]["weights"] = {}
    result = combine_targets(allocation, components, execute_at=execution)
    assert result["symbol_weights"] == {"SPY": 0.1}
    assert result["cash_weight"] == 0.9


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("both_missing_session", "calendar_incomplete"),
        ("fee_pressure", "cost_contract"),
        ("extra_position_date", "position_date"),
        ("reoptimized", "omission_must"),
    ],
)
def test_paired_report_refuses_incomplete_calendar_cost_mismatch_and_changed_estimand(
    mutation, reason
):
    full, removed, config, days, full_schedule, removed_schedule = replay_pair()
    if mutation == "both_missing_session":
        full.equity_curve = full.equity_curve.drop(index=20)
        removed.equity_curve = removed.equity_curve.drop(index=20)
    if mutation == "fee_pressure":
        config = config.model_copy(update={"commission_bps": 2, "slippage_bps": 10})
    if mutation == "extra_position_date":
        row = full.positions.iloc[[0]].copy()
        row["timestamp"] = days[-1] + pd.Timedelta(days=1)
        full.positions = pd.concat([full.positions, row], ignore_index=True)
    if mutation == "reoptimized":
        original = allocated()
        alternative = allocated()
        original_returns, available, expected, cutoff = history()
        alternative = allocation_at(
            original_returns,
            availability_times=available,
            expected_sessions=expected,
            component_ids=("a", "b"),
            decision_at=cutoff,
            policy=AllocationPolicy("equal_weight", 1, 1),
        )
        removed_schedule = {
            days[0]: combine_targets(
                alternative, snapshots(original, days[0]), execute_at=days[0], omitted_component="a"
            )
        }
    with pytest.raises(ValueError, match=reason):
        compare_replayed_portfolios(
            full,
            removed,
            config=config,
            expected_sessions=days,
            combined_schedule=full_schedule,
            without_schedule=removed_schedule,
            removed_component="a",
        )


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("invented_inventory", "position_fill_reconciliation"),
        ("duplicate_fill", "duplicate_fill"),
        ("missing_position", "position_fill_reconciliation"),
        ("annualization", "fixed_cost_contract"),
    ],
)
def test_independent_review_inventory_and_annualization_counterexamples(defect, reason):
    full, removed, config, days, full_schedule, removed_schedule = replay_pair()
    if defect == "invented_inventory":
        mask = full.positions.symbol == "SPY"
        extra = full.positions.loc[mask].set_index("timestamp").close_price
        full.positions.loc[mask, "quantity"] += 1
        full.positions.loc[mask, "market_value"] += full.positions.loc[mask, "close_price"]
        for column in ("market_value", "equity"):
            full.equity_curve[column] += full.equity_curve.timestamp.map(extra).fillna(0)
    if defect == "duplicate_fill":
        full.trade_blotter = pd.concat([full.trade_blotter, full.trade_blotter.iloc[[0]]])
    if defect == "missing_position":
        row = full.positions.iloc[0]
        full.positions = full.positions.iloc[1:].copy()
        day = full.equity_curve.timestamp.eq(row.timestamp)
        for column in ("market_value", "equity"):
            full.equity_curve.loc[day, column] -= row.market_value
    if defect == "annualization":
        config = config.model_copy(update={"annualization_factor": 365})
    with pytest.raises(ValueError, match=reason):
        compare_replayed_portfolios(
            full,
            removed,
            config=config,
            expected_sessions=days,
            combined_schedule=full_schedule,
            without_schedule=removed_schedule,
            removed_component="a",
        )


def portfolio_driver():
    path = Path(__file__).parents[1] / "scripts/phase3_portfolio_research.py"
    spec = importlib.util.spec_from_file_location("portfolio_driver_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_driver_rejects_changed_plan_addendum_and_original_input_bytes(tmp_path):
    driver = portfolio_driver()
    plan = tmp_path / "preregistration.json"
    plan.write_text("{}")
    with pytest.raises(ValueError, match="frozen_plan_changed"):
        driver.read_plan(plan)
    with pytest.raises(ValueError, match="statistical_addendum_changed"):
        driver.read_addendum(plan)
    source = tmp_path / "artificial-source.txt"
    source.write_text("artificial original")
    descriptor = {
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "bytes": source.stat().st_size,
    }
    source.write_text("artificial mutation")
    with pytest.raises(ValueError, match="original_input_changed"):
        driver.verify_inputs({"source_files": {str(source): descriptor}})


def test_driver_records_real_engine_failure_before_call_and_preserves_failed_trial(tmp_path):
    driver = portfolio_driver()
    frame = prices().drop(columns="open")
    days = pd.DatetimeIndex(frame.timestamp.unique())
    plan = {"initial_research_cash_usd": 100000, "partitions": {}}
    cell = {"trial_id": "ARTIFICIAL-invalid-price", "cost_multiplier": 1, "role": "reference"}
    result, failure = driver.execute_trial(
        cell,
        frame,
        {days[0]: {"SPY": 0.5}},
        days,
        tmp_path,
        {"fixture": "artificial_not_market"},
        plan,
    )
    assert result is None and failure["status"] == "failed" and failure["actual_engine_invoked"]
    assert (
        json.loads((tmp_path / cell["trial_id"] / "trial-registration.json").read_text())["status"]
        == "started"
    )
    events = [
        json.loads(line) for line in (tmp_path / "research-index.jsonl").read_text().splitlines()
    ]
    assert [row["status"] for row in events] == ["started", "failed"]
    assert (tmp_path / cell["trial_id"] / "exception.txt").is_file()


def test_driver_write_guard_refuses_nonisolated_files_without_writing_them(tmp_path):
    driver = portfolio_driver()
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "not-authorized.txt"
    forbidden = []
    with (
        driver.isolated_side_effect_guard(output, forbidden),
        pytest.raises(PermissionError, match="outside_isolated_output"),
    ):
        outside.write_text("never written")
    assert not outside.exists()
    assert len(forbidden) == 1


@pytest.mark.parametrize("defect", ["missing", "shifted_open", "duplicate"])
def test_driver_requires_original_signal_to_next_xnys_open_complete_calendar(defect):
    driver = portfolio_driver()
    cal = driver._calendar(2020, 2021)
    sessions = driver.calendar_sessions(cal, "2021-01-04", "2021-01-29")
    row = {"signal_date": "2020-12-31", "trade_date": "2021-01-04", "targets": {"SPY": 0.5}}
    records = [row]
    if defect == "missing":
        records = []
    if defect == "shifted_open":
        row["trade_date"] = "2021-01-05"
    if defect == "duplicate":
        records = [row, dict(row)]
    with pytest.raises(ValueError, match="portfolio_"):
        driver.validate_original_signals(
            records,
            "artificial",
            cal,
            sessions,
            {"first_signal_session": "2020-12-31", "evaluation_end": "2021-01-29"},
        )


def test_driver_configuration_binds_recent_252_exchange_sessions_and_future_perturbation():
    driver = portfolio_driver()
    cal = driver._calendar(2019, 2021)
    sessions = driver.calendar_sessions(cal, "2019-12-01", "2021-01-29")
    rng = np.random.default_rng(903)
    history = pd.DataFrame(
        rng.normal(0, 0.01, (len(sessions), 3)), index=sessions, columns=driver.COMPONENTS
    )
    trade, signal = driver.utc("2021-01-04"), driver.utc("2020-12-31")
    inputs = {
        "history": history,
        "calendar": cal,
        "availability": pd.Series(
            [driver.utc(cal.session_close(day.tz_localize(None))) for day in sessions],
            index=sessions,
        ),
        "signals": {
            key: {trade: {"signal": signal, "weights": {"SPY": 0.5}}} for key in driver.COMPONENTS
        },
        "component_sources": {
            key: {"fixture": "artificial", "digest": str(index) * 64}
            for index, key in enumerate(driver.COMPONENTS)
        },
    }
    plan = {
        "policy": {"gross_budget": 1.0, "max_component_weight": 0.5, "require_full_budget": False}
    }
    first, allocations = driver.construct_targets(inputs, plan, "P34_ERC")
    history.loc[history.index > signal] = 999
    second, again = driver.construct_targets(inputs, plan, "P34_ERC")
    assert first == second and allocations == again
    assert allocations[0]["allocation"]["observation_count"] == 252
    assert allocations[0]["allocation"]["last_session"] == "2020-12-31"
    assert (
        first["full"][trade]["execute_at"]
        == driver.utc(cal.session_open(trade.tz_localize(None))).isoformat()
    )


def test_paired_sharpe_power_states_the_minimum_detectable_effect():
    metrics = {
        "vs_benchmark": {
            "n_observations": 421,
            "block_bootstrap": {
                "status": "ready",
                "se": 0.1969553680651409,
                "value": 0.2087492322750073,
                "block_length": 21,
                "n_resamples": 2000,
                "method": "moving_block_bootstrap_studentized",
                "statistic": "paired_sharpe_difference",
                "studentization": "delete_one_block_jackknife_se",
            },
        }
    }
    power = paired_sharpe_power(metrics)
    assert power["status"] == "approximate"
    assert power["basis"] == "normal_approximation_using_paired_sharpe_difference_se"
    assert power["se_method"] == "delete_one_block_jackknife_se"
    assert power["power_calibrated"] is False
    assert power["multiplicity_adjusted"] is False
    assert power["significance_computed"] is False
    assert power["method_role"] == "planning_diagnostic"
    assert power["mde_80pct_two_sided_5pct"] == pytest.approx(
        (1.959964 + 0.841621) * 0.1969553680651409
    )
    assert power["mde_90pct_two_sided_5pct"] == pytest.approx(
        (1.959964 + 1.281552) * 0.1969553680651409
    )
    assert power["observed"] == pytest.approx(0.2087492322750073)
    # Even in the assumed normal test, MDE is a target power level, not a hard
    # detection limit: an effect of one SE has a non-zero rejection probability.
    z = 1.959964

    def cdf(value):
        return (1 + math.erf(value / math.sqrt(2))) / 2

    below_mde_detection_probability = 1 - cdf(z - 1) + cdf(-z - 1)
    assert 0.16 < below_mde_detection_probability < 0.18
    assert "无法被确认" not in power["note"]
    assert "检出概率" in power["note"]
    assert (
        paired_sharpe_power({"vs_benchmark": {"block_bootstrap": {"status": "not_evaluated"}}})[
            "status"
        ]
        == "not_evaluated"
    )


def test_paired_power_binds_the_actual_standard_error_and_driver_preserves_disclosure():
    from quant_system.research.active_metrics import paired_block_bootstrap

    rng = np.random.default_rng(501)
    reference = pd.Series(rng.normal(0.0001, 0.01, 252))
    strategy = reference + pd.Series(rng.normal(0.0002, 0.003, 252))
    bootstrap = paired_block_bootstrap(strategy, reference, n_resamples=200)
    metrics = {"vs_benchmark": {"block_bootstrap": bootstrap, "n_observations": 252}}
    power = paired_sharpe_power(metrics)
    assert power["status"] == "approximate"
    assert power["se"] == bootstrap["se"]
    assert power["se_method"] == bootstrap["studentization"]
    assert power["reference_ci_method"] == bootstrap["method"]
    assert portfolio_driver().paired_power_block(metrics) == power
    bootstrap["method"] = "percentile_bootstrap"
    assert paired_sharpe_power(metrics) == {
        "status": "not_evaluated",
        "reason": "paired_bootstrap_method_unavailable",
    }
