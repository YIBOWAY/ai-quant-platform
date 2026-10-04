"""Close-known component allocations and net targets for one real engine replay.

This module does not backtest, fetch, persist, admit or fund strategies. Component
return histories determine allocation only; their P&L is never added to produce
the combined portfolio's realized P&L. Unknown inputs fail before construction.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestResult
from quant_system.backtest.models import BacktestConfig
from quant_system.research.active_metrics import active_metrics
from quant_system.research.trials import date_aligned_correlation

HISTORY_OBSERVATIONS = 252
_ERC_SCRIPT = Path(__file__).resolve().parents[3] / "scripts/phase3_etf_research.py"
_EPS = 1e-12


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _time(value):
    stamp = pd.Timestamp(value)
    _require(not pd.isna(stamp) and stamp.tzinfo is not None, "combiner_timezone_required")
    return stamp.tz_convert("UTC")


def _dates(values):
    index = pd.DatetimeIndex(values)
    _require(index.tz is not None, "combiner_timezone_required")
    index = index.tz_convert("UTC")
    _require(
        not index.hasnans and index.is_unique and index.is_monotonic_increasing,
        "combiner_duplicate_or_unordered_sessions",
    )
    _require(index.equals(index.normalize()), "combiner_daily_session_labels_required")
    return index


@dataclass(frozen=True)
class AllocationPolicy:
    method: str
    gross_budget: float
    sleeve_cap: float
    require_full_budget: bool = False


def _erc(returns):
    """Reuse the actual fixed ETF solver, never an alternate local implementation."""
    _require(_ERC_SCRIPT.is_file(), "combiner_erc_source_unavailable")
    before = _sha(_ERC_SCRIPT)
    spec = importlib.util.spec_from_file_location("combiner_existing_erc", _ERC_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    weights, risk = module.equal_risk_weights(returns)
    _require(_sha(_ERC_SCRIPT) == before, "combiner_erc_source_changed")
    return weights, risk, {"path": str(_ERC_SCRIPT), "sha256": before}


def allocation_at(
    component_returns: pd.DataFrame,
    *,
    availability_times: pd.Series,
    expected_sessions,
    component_ids: tuple[str, ...],
    decision_at,
    policy: AllocationPolicy,
) -> dict:
    """Freeze equal-weight/ERC from exactly 252 declared daily observations.

    The caller supplies the frozen exchange-session calendar and actual time
    each return was available. Future rows are ignored; missing declared rows,
    unavailable observations, nonfinite values and duplicate identities fail.
    Caps reduce weights without redistribution; the remainder stays cash.
    """
    cutoff = _time(decision_at)
    expected = _dates(expected_sessions)
    index = _dates(component_returns.index)
    availability_index = _dates(availability_times.index)
    _require(
        len(component_ids) > 0
        and len(set(component_ids)) == len(component_ids)
        and all(isinstance(key, str) and key for key in component_ids)
        and list(component_returns.columns) == list(component_ids),
        "combiner_component_identity_mismatch",
    )
    _require(len(expected) == HISTORY_OBSERVATIONS, "combiner_history_window_incomplete")
    _require(
        expected[-1] <= cutoff
        and not len(expected.difference(index))
        and not len(expected.difference(availability_index)),
        "combiner_declared_session_missing_or_future",
    )
    history = component_returns.copy()
    history.index = index
    history = history.loc[expected]
    _require(
        all(
            isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, (bool, np.bool_))
            for value in history.to_numpy().ravel()
        ),
        "combiner_return_nonfinite_or_non_numeric",
    )
    availability = availability_times.copy()
    availability.index = availability_index
    known = [_time(value) for value in availability.loc[expected]]
    _require(
        all(
            session <= timestamp <= cutoff
            for session, timestamp in zip(expected, known, strict=True)
        ),
        "combiner_return_not_available_at_decision",
    )
    try:
        values = history.to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("combiner_return_nonfinite_or_non_numeric") from exc
    _require(
        np.isfinite(values).all() and np.all(values >= -1),
        "combiner_return_nonfinite_or_invalid",
    )
    _require(
        policy.method in {"equal_weight", "erc"}
        and np.isfinite([policy.gross_budget, policy.sleeve_cap]).all()
        and 0 <= policy.gross_budget <= 1
        and 0 < policy.sleeve_cap <= 1
        and type(policy.require_full_budget) is bool,
        "combiner_allocation_policy_invalid",
    )
    risk, source = None, None
    if policy.method == "erc":
        base, risk, source = _erc(history)
    else:
        base = {key: 1 / len(component_ids) for key in component_ids}
    weights = {
        key: min(base[key] * policy.gross_budget, policy.sleeve_cap) for key in component_ids
    }
    allocated = sum(weights.values())
    _require(
        not policy.require_full_budget or abs(allocated - policy.gross_budget) <= _EPS,
        "combiner_full_budget_cap_infeasible",
    )
    labels = [day.date().isoformat() for day in expected]
    correlations = {
        left: {
            right: date_aligned_correlation(history[left], labels, history[right], labels)
            for right in component_ids
        }
        for left in component_ids
    }
    inputs = {
        "component_ids": list(component_ids),
        "sessions": labels,
        "availability_times": [value.isoformat() for value in known],
        "returns": values.tolist(),
    }
    result = {
        "schema": "portfolio_allocation/v1",
        "decision_at": cutoff.isoformat(),
        "policy": asdict(policy),
        "component_ids": list(component_ids),
        "sleeve_weights_before_caps": {
            key: base[key] * policy.gross_budget for key in component_ids
        },
        "sleeve_weights": weights,
        "unallocated_cash_weight": 1 - allocated,
        "gross_budget_used": allocated,
        "cap_policy": "clip_without_redistribution_cash_retained",
        "erc_equal_risk_after_caps_claimed": policy.method == "erc"
        and all(
            abs(weights[key] - base[key] * policy.gross_budget) <= _EPS for key in component_ids
        ),
        "erc_diagnostics_before_caps": risk,
        "erc_source": source,
        "correlation": correlations,
        "correlation_unavailable_reason": "zero_variance"
        if any(value is None for row in correlations.values() for value in row.values())
        else None,
        "input_digest": _digest(inputs),
        "observation_count": len(expected),
        "first_session": labels[0],
        "last_session": labels[-1],
        "latest_available_at": max(known).isoformat(),
        "source_sha256": _sha(__file__),
        "research_only": True,
        "capital_authorized": False,
    }
    return {**result, "allocation_digest": _digest(result)}


def _cost_scope():
    return {
        "application": "once_by_real_engine_on_combined_symbol_trades",
        "component_costs_subtracted_again": False,
        "tiered_fees": {"status": "not_evaluated", "reason": "tier_schedule_not_supported"},
        "capacity": {"status": "not_evaluated", "reason": "volume_and_impact_inputs_not_supported"},
        "minimum_fees": {"status": "not_evaluated", "reason": "minimum_fee_model_not_supported"},
    }


def combine_targets(
    allocation: dict,
    component_target_snapshots: dict,
    *,
    execute_at,
    omitted_component: str | None = None,
) -> dict:
    """Net real symbol targets, retaining unallocated and component cash.

    Every component supplies an explicit point-in-time target, including an
    empty mapping for an all-cash component. No implicit forward-fill. Omission
    transfers that component's capital to cash; every other weight is unchanged.
    The downstream driver binds execute_at to its exchange-calendar next open.
    """
    _require(
        allocation.get("schema") == "portfolio_allocation/v1"
        and allocation.get("allocation_digest")
        == _digest({k: v for k, v in allocation.items() if k != "allocation_digest"}),
        "combiner_allocation_identity_changed",
    )
    execution, cutoff = _time(execute_at), _time(allocation["decision_at"])
    _require(execution > cutoff, "combiner_execution_not_after_decision")
    ids = allocation["component_ids"]
    _require(
        set(component_target_snapshots) == set(ids), "combiner_component_target_missing_or_extra"
    )
    _require(
        omitted_component is None or omitted_component in ids, "combiner_unknown_omitted_component"
    )
    net, inputs, internal_cash, contributions = {}, {}, {}, {}
    sleeves = dict(allocation["sleeve_weights"])
    for key in ids:
        snapshot = component_target_snapshots[key]
        _require(
            set(snapshot) == {"known_at", "execute_at", "weights", "source_digest"},
            "combiner_component_target_schema_invalid",
        )
        known = _time(snapshot["known_at"])
        _require(known <= cutoff, "combiner_component_target_from_future")
        _require(
            _time(snapshot["execute_at"]) == execution, "combiner_component_execution_mismatch"
        )
        _require(
            isinstance(snapshot["source_digest"], str)
            and re.fullmatch(r"[0-9a-f]{64}", snapshot["source_digest"]),
            "combiner_component_source_digest_required",
        )
        weights = snapshot["weights"]
        _require(isinstance(weights, dict), "combiner_component_weights_invalid")
        _require(
            all(
                isinstance(symbol, str)
                and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", symbol)
                and type(weight) in {int, float}
                and math.isfinite(weight)
                and 0 <= weight <= 1
                for symbol, weight in weights.items()
            )
            and sum(weights.values()) <= 1 + _EPS,
            "combiner_negative_nonfinite_or_leveraged_target",
        )
        if key == omitted_component:
            sleeves[key] = 0.0
        internal_cash[key] = sleeves[key] * (1 - sum(weights.values()))
        contributions[key] = {symbol: sleeves[key] * weight for symbol, weight in weights.items()}
        for symbol, weight in weights.items():
            net[symbol] = net.get(symbol, 0.0) + sleeves[key] * weight
        inputs[key] = {
            "known_at": known.isoformat(),
            "execute_at": execution.isoformat(),
            "source_digest": snapshot["source_digest"],
            "weights": weights,
        }
    net = {symbol: weight for symbol, weight in sorted(net.items()) if weight > 0}
    gross = sum(net.values())
    _require(gross <= allocation["gross_budget_used"] + _EPS, "combiner_gross_exposure_exceeded")
    result = {
        "schema": "portfolio_combined_target/v1",
        "allocation_digest": allocation["allocation_digest"],
        "decision_at": cutoff.isoformat(),
        "execute_at": execution.isoformat(),
        "execution_calendar_check": "required_in_replay_driver",
        "component_target_digest": _digest(inputs),
        "component_source_digests": {key: value["source_digest"] for key, value in inputs.items()},
        "sleeve_weights": sleeves,
        "symbol_weights": net,
        "symbol_contributions": contributions,
        "gross_exposure": gross,
        "cash_weight": 1 - gross,
        "component_cash_contributions": internal_cash,
        "omitted_component": omitted_component,
        "omission_policy": "removed_allocation_to_cash_others_unchanged",
        "costs": _cost_scope(),
        "pnl": None,
        "pnl_reason": "requires_one_real_engine_replay_of_netted_targets",
        "research_only": True,
        "capital_authorized": False,
    }
    return {**result, "target_digest": _digest(result)}


def _schedule_pair(full, without, removed):
    _require(full and set(full) == set(without), "combiner_paired_schedule_missing")
    identity = []
    for stamp in sorted(full):
        left, right = full[stamp], without[stamp]
        for record in (left, right):
            _require(
                record.get("schema") == "portfolio_combined_target/v1"
                and record.get("target_digest")
                == _digest({k: v for k, v in record.items() if k != "target_digest"}),
                "combiner_target_identity_changed",
            )
            _require(
                _time(stamp).normalize() == _time(record["execute_at"]).normalize(),
                "combiner_schedule_execution_date_mismatch",
            )
        _require(
            left["omitted_component"] is None
            and right["omitted_component"] == removed
            and left["allocation_digest"] == right["allocation_digest"]
            and left["component_target_digest"] == right["component_target_digest"]
            and left["execute_at"] == right["execute_at"]
            and set(left["sleeve_weights"]) == set(right["sleeve_weights"])
            and all(
                right["sleeve_weights"][key] == (0 if key == removed else weight)
                for key, weight in left["sleeve_weights"].items()
            ),
            "combiner_omission_must_move_to_cash_without_reoptimization",
        )
        identity.append([_time(stamp).isoformat(), left["target_digest"], right["target_digest"]])
    return _digest(identity)


def _frame_identity(frame):
    return _digest(
        {
            "columns": list(frame.columns),
            "dtypes": [str(x) for x in frame.dtypes],
            "content": hashlib.sha256(
                pd.util.hash_pandas_object(frame, index=True).values.tobytes()
            ).hexdigest(),
        }
    )


def _check_replay(result, config, expected):
    """Check supplied real-engine accounting; never recompute or combine sleeve P&L."""
    _require(isinstance(result, BacktestResult), "combiner_real_engine_result_required")
    curve, fills, positions = result.equity_curve, result.trade_blotter, result.positions
    _require(
        {"timestamp", "cash", "market_value", "equity"}.issubset(curve)
        and _dates(curve.timestamp).equals(expected),
        "combiner_replay_calendar_incomplete",
    )
    numeric = curve[["cash", "market_value", "equity"]].to_numpy(dtype=float)
    _require(
        np.isfinite(numeric).all()
        and (curve.equity > 0).all()
        and (curve.cash >= -1e-7).all()
        and (curve.market_value >= -1e-7).all(),
        "combiner_replay_nonfinite_or_invalid",
    )
    debits = pd.Series(0.0, index=expected)
    if not fills.empty:
        _require(
            {
                "fill_id",
                "symbol",
                "timestamp",
                "side",
                "quantity",
                "requested_price",
                "fill_price",
                "gross_value",
                "commission",
                "slippage_bps",
            }.issubset(fills),
            "combiner_fill_fields_missing",
        )
        _require(
            fills.fill_id.notna().all() and fills.fill_id.is_unique,
            "combiner_duplicate_fill_identity",
        )
        dates = pd.DatetimeIndex([_time(x) for x in fills.timestamp])
        _require(not len(dates.difference(expected)), "combiner_fill_date_outside_curve")
        numbers = fills[
            [
                "quantity",
                "requested_price",
                "fill_price",
                "gross_value",
                "commission",
                "slippage_bps",
            ]
        ].to_numpy(dtype=float)
        _require(np.isfinite(numbers).all() and (numbers[:, :4] > 0).all(), "combiner_invalid_fill")
        _require(fills.side.isin(["buy", "sell"]).all(), "combiner_fill_side_invalid")
        sign = np.where(fills.side == "buy", 1.0, -1.0)
        _require(
            np.allclose(fills.gross_value, fills.quantity * fills.fill_price, rtol=0, atol=1e-7)
            and np.allclose(
                fills.commission,
                fills.gross_value * config.commission_bps / 10000,
                rtol=0,
                atol=1e-7,
            )
            and np.allclose(
                fills.fill_price,
                fills.requested_price * (1 + sign * config.slippage_bps / 10000),
                rtol=0,
                atol=1e-7,
            )
            and (fills.slippage_bps == config.slippage_bps).all(),
            "combiner_cost_contract_mismatch",
        )
        cash_effect = (
            pd.Series(
                sign * fills.gross_value.to_numpy() + fills.commission.to_numpy(), index=dates
            )
            .groupby(level=0)
            .sum()
        )
        debits = cash_effect.reindex(expected, fill_value=0.0)
    expected_cash = config.initial_cash - debits.cumsum()
    _require(
        np.allclose(curve.cash, expected_cash, rtol=0, atol=1e-7),
        "combiner_cash_fill_reconciliation_failed",
    )
    _require(
        np.allclose(curve.equity, curve.cash + curve.market_value, rtol=0, atol=1e-7),
        "combiner_equity_accounting_failed",
    )
    if positions.empty:
        marked = pd.Series(0.0, index=expected)
    else:
        _require(
            {"timestamp", "symbol", "quantity", "close_price", "market_value"}.issubset(positions),
            "combiner_position_fields_missing",
        )
        position_dates = pd.DatetimeIndex([_time(value) for value in positions.timestamp])
        _require(
            not len(position_dates.difference(expected)), "combiner_position_date_outside_curve"
        )
        _require(
            not positions.duplicated(["timestamp", "symbol"]).any(), "combiner_duplicate_position"
        )
        _require(
            np.isfinite(positions[["quantity", "close_price", "market_value"]]).all().all()
            and (positions.quantity >= 0).all()
            and (positions.close_price > 0).all()
            and np.allclose(
                positions.market_value,
                positions.quantity * positions.close_price,
                rtol=0,
                atol=1e-7,
            ),
            "combiner_position_valuation_invalid",
        )
        marked = positions.groupby("timestamp").market_value.sum().reindex(expected, fill_value=0)
    _require(
        np.allclose(curve.market_value, marked, rtol=0, atol=1e-7),
        "combiner_position_curve_reconciliation_failed",
    )
    symbols = sorted(
        set(fills.symbol if not fills.empty else [])
        | set(positions.symbol if not positions.empty else [])
    )
    expected_quantity = pd.DataFrame(0.0, index=expected, columns=symbols)
    if not fills.empty:
        changes = (
            pd.DataFrame(
                {
                    "timestamp": dates,
                    "symbol": fills.symbol.to_numpy(),
                    "quantity": sign * fills.quantity.to_numpy(),
                }
            )
            .groupby(["timestamp", "symbol"])
            .quantity.sum()
            .unstack(fill_value=0.0)
        )
        expected_quantity = changes.reindex(
            index=expected, columns=symbols, fill_value=0.0
        ).cumsum()
    observed_quantity = pd.DataFrame(0.0, index=expected, columns=symbols)
    if not positions.empty:
        observed_quantity = (
            positions.pivot(index="timestamp", columns="symbol", values="quantity")
            .reindex(
                index=expected,
                columns=symbols,
                fill_value=0.0,
            )
            .fillna(0.0)
        )
    _require(
        (expected_quantity.to_numpy() >= -1e-8).all()
        and np.allclose(observed_quantity, expected_quantity, rtol=0, atol=1e-8),
        "combiner_position_fill_reconciliation_failed",
    )
    return {
        "curve_digest": _frame_identity(curve),
        "fill_digest": _frame_identity(fills),
        "position_digest": _frame_identity(positions),
        "commission_paid": float(fills.commission.sum()) if not fills.empty else 0.0,
        "trade_count": len(fills),
        "accounting_checked": True,
    }


def paired_sharpe_power(metrics: dict) -> dict:
    """Normal-approximation planning MDE using the observed paired jackknife SE.

    ``(z_(1-alpha/2) + z_power) * se`` is an approximate target-power effect
    size for a single normal test with fixed SE. It is neither calibrated power
    of the studentized bootstrap CI nor a hard detection threshold. The observed
    sample's SE does not establish power under unobserved alternatives.
    Normal planning formula: https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm
    """
    bootstrap = (metrics.get("vs_benchmark") or {}).get("block_bootstrap") or {}
    se = bootstrap.get("se")
    if not (
        bootstrap.get("status") == "ready"
        and isinstance(se, (int, float))
        and not isinstance(se, bool)
        and math.isfinite(se)
        and se > 0
    ):
        return {"status": "not_evaluated", "reason": "paired_bootstrap_se_unavailable"}
    if (
        bootstrap.get("method") != "moving_block_bootstrap_studentized"
        or bootstrap.get("statistic") != "paired_sharpe_difference"
        or bootstrap.get("studentization") != "delete_one_block_jackknife_se"
    ):
        return {"status": "not_evaluated", "reason": "paired_bootstrap_method_unavailable"}
    z_alpha, z_beta = 1.959964, 0.841621
    return {
        "status": "approximate",
        "method_role": "planning_diagnostic",
        "basis": "normal_approximation_using_paired_sharpe_difference_se",
        "se": se,
        "se_method": bootstrap["studentization"],
        "reference_ci_method": bootstrap["method"],
        "power_calibrated": False,
        "multiplicity_adjusted": False,
        "significance_computed": False,
        "observed": bootstrap.get("value"),
        "mde_80pct_two_sided_5pct": (z_alpha + z_beta) * se,
        "mde_90pct_two_sided_5pct": (z_alpha + 1.281552) * se,
        "n_observations": (metrics.get("vs_benchmark") or {}).get("n_observations"),
        "block_length": bootstrap.get("block_length"),
        "n_resamples": bootstrap.get("n_resamples"),
        "note": (
            "按本窗配对 Sharpe 差的 delete-one-block jackknife SE，"
            "给出单项双侧 5% 正态近似下达到约 80%/90% 检出概率所需的效应量。"
            "这不是 bootstrap 检验的已校准功效，也未校正多重比较；"
            "低于 MDE 仍可能检出，高于 MDE 也不保证检出。"
            "未确认不能单凭此诊断归因于功效不足，也不能据此断言差异不存在。"
        ),
    }


def compare_replayed_portfolios(
    combined_result: BacktestResult,
    without_result: BacktestResult,
    *,
    config: BacktestConfig,
    expected_sessions,
    combined_schedule: dict,
    without_schedule: dict,
    removed_component: str,
    bootstrap_seed: int = 20260918,
    bootstrap_resamples: int = 2000,
    block_length: int = 21,
) -> dict:
    """Paired comparison of two separately executed net portfolios.

    Estimand: full net portfolio minus one with a component's allocation moved
    to cash, leaving the remaining decisions unchanged. This is neither a
    linear combination of component P&L nor Numerai MPC. The caller/driver owns
    archive identity, market-data/calendar and schedule-to-engine provenance.
    """
    expected = _dates(expected_sessions)
    _require(
        isinstance(config, BacktestConfig)
        and config.initial_cash > 0
        and config.annualization_factor == 252
        and config.commission_bps in {1, 2, 3}
        and config.slippage_bps == 5 * config.commission_bps,
        "combiner_fixed_cost_contract_required",
    )
    schedule_digest = _schedule_pair(combined_schedule, without_schedule, removed_component)
    _require(
        all(_time(x).normalize() in expected for x in combined_schedule),
        "combiner_schedule_outside_evaluation",
    )
    full = _check_replay(combined_result, config, expected)
    without = _check_replay(without_result, config, expected)
    curve = pd.DataFrame(
        {
            "timestamp": expected,
            "equity": combined_result.equity_curve.equity.to_numpy(),
            "benchmark": without_result.equity_curve.equity.to_numpy(),
        }
    )
    comparison = active_metrics(
        curve,
        initial_cash=config.initial_cash,
        benchmark_symbol="without:" + removed_component,
        include_peer=False,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
        block_length=block_length,
    )
    return {
        "schema": "portfolio_component_removal_comparison/v1",
        "definition": "full_net_replay_minus_removed_component_to_cash_net_replay",
        "removed_component": removed_component,
        "remaining_allocations_reoptimized": False,
        "numerai_mpc_claimed": False,
        "combined": full,
        "without_component": without,
        "schedule_pair_digest": schedule_digest,
        "backtest_config": config.model_dump(mode="json"),
        "comparison": comparison,
        "paired_sharpe_difference": (comparison.get("vs_benchmark") or {}).get("block_bootstrap"),
        "paired_power": paired_sharpe_power(comparison),
        "costs": _cost_scope(),
        "provenance_limit": (
            "driver_must_bind_original_prices_schedules_and_actual_engine_execution"
        ),
        "research_only": True,
        "capital_authorized": False,
    }
