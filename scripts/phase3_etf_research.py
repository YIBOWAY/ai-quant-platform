"""Finite, preregistered ETF research over supplied real snapshots only.

This adapter owns targets, while the existing Platform engine owns orders,
fills, fees and NAV. It cannot register a definition, candidate or paper sleeve.
No provider calls, production storage or parameter search are available here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.research.active_metrics import active_metrics
from quant_system.research.profile_backtests import _month_boundaries, _ScheduledTargets
from quant_system.research.reference_backtests import _metrics, _prepare_prices
from quant_system.research.strategy_runtime import _calendar

SYMBOLS = ("SPY", "IWM", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC", "VNQ", "LQD")
CANDIDATES = ("B_MOM", "B_SMA", "B_COMBINED")
FIXED = {
    "symbols": list(SYMBOLS),
    "candidates": list(CANDIDATES),
    "momentum_months": 12,
    "skip_months": 1,
    "sma_months": 10,
    "covariance_days": 252,
    "covariance_diagonal_shrinkage": 0.1,
    "cost_multipliers": [1, 2, 3],
    "max_weight_per_asset": 0.25,
    "target_annual_volatility": 0.1,
    "max_gross_exposure": 1.0,
    "leverage": False,
    "cash_return": 0.0,
    "commission_bps": 1.0,
    "slippage_bps": 5.0,
}
INITIAL_CASH = 100_000.0
ERC_TOLERANCE = 1e-6
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src/quant_system"


def source_identity() -> dict:
    paths = [*sorted((SOURCE_ROOT / "backtest").glob("*.py"))]
    paths += sorted((SOURCE_ROOT / "trading_kernel").glob("*.py"))
    paths += [
        SOURCE_ROOT / "research" / filename
        for filename in (
            "profile_backtests.py",
            "reference_backtests.py",
            "active_metrics.py",
            "strategy_runtime.py",
        )
    ]
    return {str(path.relative_to(SOURCE_ROOT)): sha256(path) for path in paths}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read_preregistration(path: Path, expected_sha256: str) -> dict:
    if sha256(path) != expected_sha256:
        raise ValueError("etf_preregistration_digest_mismatch")
    document = json.loads(path.read_text())
    spec = document["family_b"]
    for key, expected in FIXED.items():
        if spec.get(key) != expected:
            raise ValueError(f"etf_preregistered_scope_mismatch:{key}")
    for key in ("history_start", "evaluation_start", "evaluation_end"):
        pd.Timestamp(spec[key])
    if not spec["history_start"] < spec["evaluation_start"] < spec["evaluation_end"]:
        raise ValueError("etf_preregistered_dates_invalid")
    if not spec.get("splits"):
        raise ValueError("etf_preregistered_splits_required")
    return spec


def expected_sessions(start: str, end: str) -> pd.DatetimeIndex:
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    sessions = _calendar(first.year - 1, last.year).sessions_in_range(first, last)
    return pd.DatetimeIndex(pd.to_datetime(sessions, utc=True)).normalize()


def input_coverage(prices: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, dict]:
    """Audit every frozen symbol/session; never silently shrink the universe."""
    frame = _prepare_prices(prices)
    first, last = pd.to_datetime([spec["history_start"], spec["evaluation_end"]], utc=True)
    frame = frame.loc[
        frame.symbol.isin(SYMBOLS) & frame.timestamp.between(first, last)
    ].copy()
    sessions = expected_sessions(spec["history_start"], spec["evaluation_end"])
    inventory = []
    for symbol in SYMBOLS:
        rows = frame.loc[frame.symbol == symbol]
        observed = pd.DatetimeIndex(rows.timestamp)
        missing, extra = sessions.difference(observed), observed.difference(sessions)
        inventory.append(
            {
                "symbol": symbol,
                "rows": len(rows),
                "missing_count": len(missing),
                "missing_dates": [day.date().isoformat() for day in missing],
                "extra_dates": [day.date().isoformat() for day in extra],
            }
        )
    ready = bool(len(sessions)) and all(
        not row["missing_count"] and not row["extra_dates"] for row in inventory
    )
    return frame, {
        "status": "ready" if ready else "waiting_data",
        "expected_sessions": len(sessions),
        "inventory": inventory,
        "provider": "futu",
        "adjustment": "qfq",
        "return_limitation": (
            "returns from Futu QFQ prices, which embed split and dividend adjustment "
            "(total-return-like); adjustment factors not independently re-derived"
        ),
    }


def equal_risk_weights(returns: pd.DataFrame) -> tuple[dict[str, float], dict]:
    """Convex equal-risk-contribution allocation with fixed diagonal shrinkage."""
    if len(returns) != 252 or not len(returns.columns):
        raise ValueError("etf_covariance_window_incomplete")
    values = returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("etf_covariance_nonfinite")
    covariance = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
    diagonal = np.diag(covariance)
    if not np.isfinite(covariance).all() or np.any(diagonal <= 1e-16):
        raise ValueError("etf_covariance_zero_or_invalid_variance")
    covariance = 0.9 * covariance + 0.1 * np.diag(diagonal)
    # Scaling leaves normalized ERC weights unchanged and improves conditioning.
    covariance = covariance / float(np.mean(diagonal))
    size = covariance.shape[0]
    budgets = np.full(size, 1.0 / size)

    # Minimize .5*x'C*x - sum(b_i*log(x_i)) on x>0. Each coordinate
    # update is the positive exact root of C_ii*x_i^2 + c_i*x_i - b_i.
    # This avoids line-search statuses being used as risk-budget evidence.
    x = 1.0 / np.sqrt(np.diag(covariance) * size)
    for _iteration in range(10000):
        for index in range(size):
            a = covariance[index, index]
            c = float(covariance[index] @ x - a * x[index])
            radical = np.sqrt(c * c + 4 * a * budgets[index])
            x[index] = (
                2 * budgets[index] / (c + radical)
                if c >= 0
                else (radical - c) / (2 * a)
            )
        risk = x * (covariance @ x)
        if np.max(np.abs(risk - budgets)) <= 1e-10:
            break
    else:
        raise ValueError("etf_erc_nonconvergence")
    weights = x / x.sum()
    variance = float(weights @ covariance @ weights)
    fractions = weights * (covariance @ weights) / variance
    error = float(np.max(np.abs(fractions - budgets)))
    if not np.isfinite(weights).all() or error > ERC_TOLERANCE:
        raise ValueError("etf_erc_risk_budget_mismatch")
    return dict(zip(returns.columns, weights.tolist(), strict=True)), {
        "risk_contribution_fractions": dict(
            zip(returns.columns, fractions.tolist(), strict=True)
        ),
        "maximum_budget_error": error,
        "covariance_observations": len(returns),
        "diagonal_shrinkage": 0.1,
        "solver": "positive_coordinate_convex_erc",
        "solver_sweeps": _iteration + 1,
    }


def constrained_risk_weights(returns: pd.DataFrame) -> tuple[dict[str, float], dict]:
    base, risk = equal_risk_weights(returns)
    weights = np.minimum(np.array(list(base.values())), 0.25)
    covariance = np.atleast_2d(np.cov(returns.to_numpy(), rowvar=False, ddof=1))
    covariance = 0.9 * covariance + 0.1 * np.diag(np.diag(covariance))
    annual_volatility = float(np.sqrt(weights @ covariance @ weights * 252))
    scale = min(1.0, 0.1 / annual_volatility) if annual_volatility > 0 else 1.0
    weights *= scale
    risk.update(
        erc_before_constraints=base,
        cap_per_asset=0.25,
        scale_down=scale,
        predicted_annual_volatility=annual_volatility * scale,
        cash_weight=float(1 - weights.sum()),
        note="ERC before caps; caps and scale-down may break equal risk, cash is not refilled",
    )
    return dict(zip(base, weights.tolist(), strict=True)), risk


def build_schedules(prices: pd.DataFrame, spec: dict) -> tuple[dict, dict]:
    frame, coverage = input_coverage(prices, spec)
    if coverage["status"] != "ready":
        raise ValueError("etf_complete_universe_prices_required")
    close = frame.pivot(index="timestamp", columns="symbol", values="close").reindex(
        columns=SYMBOLS
    )
    boundaries = _month_boundaries(close.index)
    monthly = close.reindex([signal for signal, _ in boundaries])
    monthly.index = pd.PeriodIndex([day.strftime("%Y-%m") for day in monthly.index], freq="M")
    monthly = monthly.reindex(pd.period_range(monthly.index.min(), monthly.index.max(), freq="M"))
    momentum = monthly.shift(1) / monthly.shift(12) - 1
    sma = monthly.rolling(10, min_periods=10).mean()
    daily_returns = close.pct_change(fill_method=None)
    targets = {key: {} for key in (*CANDIDATES, "EW")}
    records = {key: [] for key in (*CANDIDATES, "EW")}
    start, end = pd.to_datetime([spec["evaluation_start"], spec["evaluation_end"]], utc=True)
    for signal, trade in boundaries:
        if not start <= trade <= end:
            continue
        period = pd.Period(signal.strftime("%Y-%m"), freq="M")
        mom, trend = momentum.loc[period], monthly.loc[period] - sma.loc[period]
        window = daily_returns.loc[:signal].tail(252)
        if mom.isna().any() or trend.isna().any() or len(window) != 252:
            raise ValueError(f"etf_incomplete_formation_window:{signal.date()}")
        selections = {
            "B_MOM": mom > 0,
            "B_SMA": trend > 0,
            "B_COMBINED": (mom > 0) & (trend > 0),
        }
        for candidate, selected in selections.items():
            names = list(selected.index[selected])
            if names:
                allocation, risk = constrained_risk_weights(window.loc[:, names])
            else:
                allocation, risk = {}, {"status": "all_cash_no_eligible_assets"}
            targets[candidate][trade] = allocation
            records[candidate].append(
                {
                    "signal_date": signal.date().isoformat(),
                    "trade_date": trade.date().isoformat(),
                    "targets": allocation,
                    "eligible_symbols": names,
                    "risk_parity": risk,
                    "scores": [
                        {
                            "symbol": symbol,
                            "momentum": float(mom[symbol]),
                            "close": float(monthly.loc[period, symbol]),
                            "sma10": float(sma.loc[period, symbol]),
                        }
                        for symbol in SYMBOLS
                    ],
                }
            )
        targets["EW"][trade] = {symbol: 1.0 / len(SYMBOLS) for symbol in SYMBOLS}
        records["EW"].append(
            {
                "signal_date": signal.date().isoformat(),
                "trade_date": trade.date().isoformat(),
                "targets": targets["EW"][trade],
            }
        )
    if not targets["EW"]:
        raise ValueError("etf_no_evaluation_rebalances")
    return targets, records


def replay(prices: pd.DataFrame, targets: dict, multiplier: int = 1):
    if multiplier not in (1, 2, 3):
        raise ValueError("etf_unregistered_cost_multiplier")
    return BacktestEngine(
        BacktestConfig(
            initial_cash=INITIAL_CASH,
            commission_bps=1.0 * multiplier,
            slippage_bps=5.0 * multiplier,
        )
    ).run(prices, _ScheduledTargets(targets))


def _curve(strategy, benchmark, peer) -> pd.DataFrame:
    curve = strategy.equity_curve[["timestamp", "equity"]].copy()
    for key, result in (("benchmark", benchmark), ("peer", peer)):
        if not curve.timestamp.equals(result.equity_curve.timestamp):
            raise ValueError("etf_comparison_calendar_mismatch")
        curve[key] = result.equity_curve.equity.to_numpy()
    return curve


def _costs(result, multiplier: int) -> dict:
    trades = result.trade_blotter
    commission = float(trades.commission.sum())
    slippage = float(
        ((trades.fill_price - trades.requested_price).abs() * trades.quantity).sum()
    )
    return {
        "commission_bps": multiplier * 1.0,
        "slippage_bps": multiplier * 5.0,
        "commission": commission,
        "slippage": slippage,
        "total": commission + slippage,
    }


def paired_active_mean_test(curve: pd.DataFrame) -> dict:
    """Fixed paired circular-block null test; positive active mean, one-sided."""
    strategy = curve.equity.div(curve.equity.shift().fillna(INITIAL_CASH)).sub(1)
    peer = curve.peer.div(curve.peer.shift().fillna(INITIAL_CASH)).sub(1)
    active = (strategy - peer).to_numpy(dtype=float)
    if len(active) < 126 or not np.isfinite(active).all():
        return {"status": "unavailable", "reason": "need_126_finite_paired_days", "p": None}
    observed = float(active.mean())
    rng = np.random.default_rng(20260925)
    blocks = int(np.ceil(len(active) / 21))
    starts = rng.integers(0, len(active), size=(2000, blocks))
    indices = ((starts[..., None] + np.arange(21)) % len(active)).reshape(2000, -1)
    bootstrap_means = active[indices[:, : len(active)]].mean(axis=1)
    # Recenter the paired difference at the least-favorable null boundary zero.
    null_means = bootstrap_means - observed
    p_value = float((1 + np.count_nonzero(null_means >= observed)) / 2001)
    return {
        "status": "ready",
        "method": "paired_circular_block_centered_null_mean",
        "alternative": "mean_strategy_minus_same_pool_EW_gt_zero",
        "observations": len(active),
        "mean_daily_active_return": observed,
        "mean_annualized_active_return": observed * 252,
        "p": p_value,
        "block_days": 21,
        "resamples": 2000,
        "seed": 20260925,
        "unseen_holdout": False,
    }


def holm_adjusted(p_values: dict[str, float | None]) -> dict[str, float | None]:
    if set(p_values) != set(CANDIDATES):
        raise ValueError("etf_holm_complete_preregistered_family_required")
    if any(value is None or not np.isfinite(value) for value in p_values.values()):
        return {name: None for name in CANDIDATES}
    adjusted, previous = {}, 0.0
    for index, (name, value) in enumerate(sorted(p_values.items(), key=lambda item: item[1])):
        previous = max(previous, min(1.0, value * (len(p_values) - index)))
        adjusted[name] = previous
    return adjusted


def evaluate(prices: pd.DataFrame, spec: dict, output: Path) -> dict:
    """Run only the frozen 3 x 3 matrix; every outcome remains research-only."""
    targets, records = build_schedules(prices, spec)
    start, end = pd.to_datetime([spec["evaluation_start"], spec["evaluation_end"]], utc=True)
    frame = _prepare_prices(prices)
    frame = frame.loc[frame.symbol.isin(SYMBOLS) & frame.timestamp.between(start, end)]
    first = frame.timestamp.min()
    outcomes = []
    for multiplier in (1, 2, 3):
        peer = replay(frame, targets["EW"], multiplier)
        benchmark = replay(
            frame.loc[frame.symbol == "SPY"], {first: {"SPY": 1.0}}, multiplier
        )
        for candidate in CANDIDATES:
            trial_id = f"{candidate}-cost{multiplier}x"
            destination = output / trial_id
            destination.mkdir()
            identity = json.loads((output / "identity.json").read_text())
            trial = {
                "trial_id": trial_id,
                "status": "started",
                "started_at": datetime.now(UTC).isoformat(),
                "identity": identity,
            }
            save_json(destination / "trial-registration.json", trial)
            with (output / "research-index.jsonl").open("a") as handle:
                handle.write(json.dumps(trial, ensure_ascii=False) + "\n")
            result = replay(frame, targets[candidate], multiplier)
            curve = _curve(result, benchmark, peer)
            metrics = active_metrics(
                curve, initial_cash=INITIAL_CASH, benchmark_symbol="SPY", bootstrap_seed=20260925
            )
            split_metrics = []
            for label, dates in spec["splits"].items():
                partition = {"name": label, "start": dates[0], "end": dates[1]}
                begin, finish = pd.to_datetime([partition["start"], partition["end"]], utc=True)
                part = curve.loc[curve.timestamp.between(begin, finish)].copy()
                previous = curve.loc[curve.timestamp < begin]
                if not len(part):
                    split_metrics.append({**partition, "status": "unavailable_no_observations"})
                    continue
                # Each leg is independently rebased from its pre-partition NAV.
                # This is continuous-strategy attribution, not a new fitted trial.
                for column in ("equity", "benchmark", "peer"):
                    origin = float(previous.iloc[-1][column]) if len(previous) else INITIAL_CASH
                    part[column] = part[column] / origin * INITIAL_CASH
                split_metrics.append(
                    {
                        **partition,
                        "unseen_holdout": False,
                        "active_metrics": active_metrics(
                            part,
                            initial_cash=INITIAL_CASH,
                            benchmark_symbol="SPY",
                            bootstrap_seed=20260925,
                        ),
                        "active_mean_inference": paired_active_mean_test(part),
                    }
                )
            block = {
                "schema_version": "phase3_etf_research/v1",
                "trial_id": trial_id,
                "identity": identity,
                "status": "available",
                "evaluation_only": True,
                "paper_runtime_compatible": False,
                "admission_authority": False,
                "definition_kind": "research_saved_target_schedule_only",
                "definition": {
                    "symbols": list(SYMBOLS),
                    "benchmark_symbol": "SPY",
                    "initial_cash": INITIAL_CASH,
                    "commission_bps": 1.0 * multiplier,
                    "slippage_bps": 5.0 * multiplier,
                    "execution_price": "next_open",
                    "whole_share_orders": False,
                    "min_order_value": 0,
                },
                "start": first.date().isoformat(),
                "end": frame.timestamp.max().date().isoformat(),
                "evaluation_initial_cash": INITIAL_CASH,
                "metrics": _metrics(result.equity_curve, result.trade_blotter, INITIAL_CASH),
                "active_metrics": metrics,
                "active_mean_inference": paired_active_mean_test(curve),
                "splits": split_metrics,
                "costs": _costs(result, multiplier),
                "trade_count": len(result.trade_blotter),
                "signals": records[candidate],
                "peer_signals": records["EW"],
                "curve": [
                    {
                        "date": row.timestamp.date().isoformat(),
                        "equity": float(row.equity),
                        "benchmark": float(row.benchmark),
                        "peer": float(row.peer),
                    }
                    for row in curve.itertuples(index=False)
                ],
                "limits": [
                    "all historical partitions previously accessible; no unseen holdout claim",
                    "QFQ prices embed dividend adjustment (total-return-like); "
                    "adjustment factors not independently re-derived",
                    "ERC weights not supported by current production StrategyDefinition/runtime",
                    "Qlib saved-target replay checks execution, not independent factor generation",
                    "DSR/full-family/admission qualification not performed by this script",
                    "2x/3x costs are diagnostic; current Qlib replay only supports base costs",
                ],
            }
            for name in ("equity_curve", "trade_blotter", "orders", "positions", "attribution"):
                getattr(result, name).to_parquet(destination / f"{name}.parquet", index=False)
            curve.to_parquet(destination / "comparison_curve.parquet", index=False)
            save_json(destination / "result.json", block)
            with (output / "research-index.jsonl").open("a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "trial_id": trial_id,
                            "status": "completed_research_only",
                            "result_sha256": sha256(destination / "result.json"),
                        }
                    )
                    + "\n"
                )
            outcomes.append(
                {
                    "trial_id": trial_id,
                    "status": "research_only",
                    "result_sha256": sha256(destination / "result.json"),
                    "metrics": block["metrics"],
                    "same_pool_sharpe_difference": metrics["vs_peer"]["block_bootstrap"],
                    "split_active_mean_inference": {
                        row["name"]: row.get("active_mean_inference") for row in split_metrics
                    },
                    "qualification": "not_evaluated",
                }
            )
    base = {
        row["trial_id"].removesuffix("-cost1x"): row
        for row in outcomes
        if row["trial_id"].endswith("-cost1x")
    }
    p_values = {
        name: row["split_active_mean_inference"]["historical_recheck"]["p"]
        for name, row in base.items()
    }
    adjusted = holm_adjusted(p_values)
    decisions = []
    for name in CANDIDATES:
        parts = base[name]["split_active_mean_inference"]
        pressure = next(row for row in outcomes if row["trial_id"] == f"{name}-cost3x")
        pressure_parts = pressure["split_active_mean_inference"]
        positive = all(
            (test.get("mean_daily_active_return") or 0) > 0
            for test in (
                parts["validation"],
                parts["historical_recheck"],
                pressure_parts["historical_recheck"],
            )
        )
        decisions.append(
            {
                "candidate": name,
                "holm_p_historical_recheck": adjusted[name],
                "frozen_followup_criteria_met": positive,
                "historical_positive_mean_evidence": (
                    positive and adjusted[name] is not None and adjusted[name] <= 0.05
                ),
                "decision": (
                    "retain_for_further_validation" if positive else "archive_fixed_hypothesis"
                ),
                "paper_status": "blocked_unsupported_runtime_and_missing_current_qualification",
                "prospective_alpha_proven": False,
            }
        )
    return {
        "status": "research_complete_admission_not_evaluated",
        "strategy_hypotheses": 3,
        "cost_variants_per_hypothesis": 3,
        "research_units": 9,
        "all_trials": outcomes,
        "decisions": decisions,
        "selected_for_paper": [],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--expected-preregistration-sha256", required=True)
    parser.add_argument("--prices", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-only", action="store_true")
    args = parser.parse_args(argv)
    spec = read_preregistration(args.preregistration, args.expected_preregistration_sha256)
    args.output.mkdir(parents=True, exist_ok=False)
    identity = {
        "created_at": datetime.now(UTC).isoformat(),
        "preregistration_sha256": args.expected_preregistration_sha256,
        "script_sha256": sha256(Path(__file__)),
        "source_sha256": source_identity(),
        "inputs": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in args.prices],
        "spec": spec,
    }
    save_json(args.output / "identity.json", identity)
    (args.output / "preregistration.json").write_bytes(args.preregistration.read_bytes())
    try:
        prices = pd.concat([pd.read_parquet(path) for path in args.prices], ignore_index=True)
        frame, coverage = input_coverage(prices, spec)
        save_json(args.output / "input-coverage.json", coverage)
        if coverage["status"] != "ready":
            save_json(args.output / "summary.json", {"status": "waiting_data", "trials_run": 0})
            return 2
        if args.coverage_only:
            save_json(args.output / "summary.json", {"status": "input_ready", "trials_run": 0})
            return 0
        frame.to_parquet(args.output / "frozen-prices.parquet", index=False)
        identity["frozen_prices_sha256"] = sha256(args.output / "frozen-prices.parquet")
        save_json(args.output / "identity.json", identity)
        summary = evaluate(frame, spec, args.output)
        if source_identity() != identity["source_sha256"] or sha256(Path(__file__)) != identity[
            "script_sha256"
        ]:
            raise ValueError("etf_source_changed_during_evaluation")
        save_json(args.output / "summary.json", summary)
        save_json(
            args.output / "output-manifest.json",
            {
                str(path.relative_to(args.output)): sha256(path)
                for path in sorted(args.output.rglob("*"))
                if path.is_file()
            },
        )
        return 0
    except (ValueError, KeyError) as exc:
        save_json(
            args.output / "failure.json",
            {"status": "failed", "reason": str(exc), "qualification": "not_evaluated"},
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
