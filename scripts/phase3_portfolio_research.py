"""Frozen T3.4 offline portfolio experiment; default is read-only preflight.

No provider, formal intake, candidate or account path is used. Component signal
and return inputs are the original archived experiments, never recomputed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.portfolio import Portfolio
from quant_system.portfolio.combiner import (
    AllocationPolicy,
    _check_replay,
    allocation_at,
    combine_targets,
    compare_replayed_portfolios,
    paired_sharpe_power,
)
from quant_system.research.active_metrics import active_metrics
from quant_system.research.factor_inference import adjust_pvalues
from quant_system.research.profile_backtests import _ScheduledTargets
from quant_system.research.reference_backtests import _metrics
from quant_system.research.strategy_runtime import _calendar

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HQA = Path("/Users/sunyibo/programs/Hermes-quant-agent")
EVIDENCE = HQA / "evidence/phase3-portfolio-20260926/portfolio"
DEFAULT_PLAN = EVIDENCE / "preregistration.json"
PLAN_SHA = "ab405b4a4e677dd2ee553e3e427a1c78f5559979f75a4dfb6baab280bc0ec4cc"
ADDENDUM_SHA = "0879dad8dabdd744c43ce75e3825feacb45ec27bdd4999e5bdc97b7eda412f3b"
COMPONENTS = ("B_MOM", "B_SMA", "B_COMBINED")
HYPOTHESES = ("P34_EQUAL", "P34_ERC")
PARQUETS = ("equity_curve", "orders", "trade_blotter", "positions", "attribution")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def etf_helper():
    path = ROOT / "scripts/phase3_etf_research.py"
    spec = importlib.util.spec_from_file_location("portfolio_fixed_etf_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_identity():
    import exchange_calendars
    import pyarrow
    import scipy

    base = ROOT / "src/quant_system"
    paths = {Path(__file__), ROOT / "scripts/phase3_etf_research.py"}
    for directory in ("backtest", "trading_kernel", "portfolio"):
        paths.update((base / directory).glob("*.py"))
    for name in (
        "research/active_metrics.py",
        "research/reference_backtests.py",
        "research/profile_backtests.py",
        "research/strategy_runtime.py",
        "research/trials.py",
        "research/factor_inference.py",
        "factors/evaluation.py",
        "factors/scorecard.py",
    ):
        paths.add(base / name)
    files = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    return {
        "files": files,
        "digest": digest(files),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "exchange_calendars": exchange_calendars.__version__,
        "pyarrow": pyarrow.__version__,
    }


def read_plan(path=DEFAULT_PLAN):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and sha(path) == PLAN_SHA,
        "portfolio_frozen_plan_changed",
    )
    return json.loads(path.read_text())


def read_addendum(plan_path=DEFAULT_PLAN):
    path = Path(plan_path).parent / "preregistration-addendum-1.json"
    require(
        path.is_file() and not path.is_symlink() and sha(path) == ADDENDUM_SHA,
        "portfolio_frozen_statistical_addendum_changed",
    )
    value = json.loads(path.read_text())
    require(
        value["parent_sha256"] == PLAN_SHA and value["main_holm_partition"] == "historical_recheck",
        "portfolio_primary_partition_changed",
    )
    return value


def verify_inputs(plan):
    current = {}
    for name, ref in plan["source_files"].items():
        path = Path(name)
        require(
            path.is_absolute() and path.is_file() and not path.is_symlink(),
            "portfolio_original_input_missing",
        )
        require(
            path.stat().st_size == ref["bytes"] and sha(path) == ref["sha256"],
            "portfolio_original_input_changed",
        )
        current[name] = ref["sha256"]
    require(len(current) == 23, "portfolio_original_input_population_changed")
    return current


def utc(value):
    return (
        pd.Timestamp(value, tz="UTC")
        if pd.Timestamp(value).tzinfo is None
        else pd.Timestamp(value).tz_convert("UTC")
    )


def calendar_sessions(calendar, start, end):
    return pd.DatetimeIndex(
        pd.to_datetime(calendar.sessions_in_range(start, end), utc=True)
    ).normalize()


def validate_original_signals(records, component, calendar, execution_sessions, plan):
    selected = {}
    for row in records:
        signal, trade = utc(row["signal_date"]), utc(row["trade_date"])
        if not execution_sessions[0] <= trade <= execution_sessions[-1]:
            continue
        require(trade not in selected, "portfolio_duplicate_original_signal")
        expected_trade = utc(calendar.next_session(signal.tz_localize(None)))
        require(
            trade == expected_trade and (signal.year, signal.month) != (trade.year, trade.month),
            "portfolio_original_signal_not_next_month_open",
        )
        require(trade in execution_sessions, "portfolio_original_signal_outside_calendar")
        weights = row["targets"]
        require(
            isinstance(weights, dict)
            and all(
                isinstance(v, (int, float)) and np.isfinite(v) and 0 <= v <= 1
                for v in weights.values()
            )
            and sum(weights.values()) <= 1 + 1e-12,
            "portfolio_original_target_invalid",
        )
        selected[trade] = {"signal": signal, "weights": weights, "component": component}
    previous = calendar_sessions(calendar, plan["first_signal_session"], plan["evaluation_end"])
    expected = [
        b
        for a, b in zip(previous[:-1], previous[1:], strict=True)
        if (a.year, a.month) != (b.year, b.month) and b in execution_sessions
    ]
    require(
        list(selected) == expected
        and selected[expected[0]]["signal"] == utc(plan["first_signal_session"]),
        "portfolio_original_signal_calendar_incomplete",
    )
    return selected


def load_inputs(plan):
    identities = verify_inputs(plan)
    price_path = next(Path(name) for name in identities if name.endswith("/frozen-prices.parquet"))
    original = price_path.parent
    helper = etf_helper()
    original_plan = json.loads((original / "preregistration.json").read_text())
    prices, coverage = helper.input_coverage(pd.read_parquet(price_path), original_plan["family_b"])
    require(
        coverage["status"] == "ready" and set(prices.symbol) == set(helper.SYMBOLS),
        "portfolio_original_price_calendar_incomplete",
    )
    cal = _calendar(2017, 2026)
    sessions = calendar_sessions(cal, plan["evaluation_start"], plan["evaluation_end"])
    history_sessions = calendar_sessions(cal, plan["formation_data_start"], plan["evaluation_end"])
    returns, signals, source_refs = {}, {}, {}
    for component in COMPONENTS:
        directory = original / (component + "-cost1x")
        curve = pd.read_parquet(directory / "equity_curve.parquet")
        report = json.loads((directory / "result.json").read_text())
        stamps = pd.DatetimeIndex(pd.to_datetime(curve.timestamp, utc=True))
        require(
            stamps.equals(history_sessions) and stamps.is_unique,
            "portfolio_component_history_calendar_incomplete",
        )
        values = curve.equity.to_numpy(dtype=float)
        require(
            np.isfinite(values).all() and (values > 0).all(), "portfolio_component_history_invalid"
        )
        original_rows = report["curve"]
        require(
            [row["date"] for row in original_rows] == [d.date().isoformat() for d in stamps]
            and np.array_equal(values, np.array([row["equity"] for row in original_rows])),
            "portfolio_original_json_curve_differs_from_parquet",
        )
        returns[component] = pd.Series(
            values / np.r_[plan["initial_research_cash_usd"], values[:-1]] - 1, index=stamps
        )
        signals[component] = validate_original_signals(
            report["signals"], component, cal, sessions, plan
        )
        source_refs[component] = {
            "result_sha256": sha(directory / "result.json"),
            "equity_curve_sha256": sha(directory / "equity_curve.parquet"),
            "signals_digest": digest(report["signals"]),
        }
    require(
        all(list(signals[key]) == list(signals[COMPONENTS[0]]) for key in COMPONENTS),
        "portfolio_component_signal_alignment_failed",
    )
    history = pd.DataFrame(returns).loc[:, list(COMPONENTS)]
    available = pd.Series(
        [utc(cal.session_close(day.tz_localize(None))) for day in history_sessions],
        index=history_sessions,
    )
    for row in signals[COMPONENTS[0]].values():
        require(
            len(history_sessions[history_sessions <= row["signal"]]) >= 252,
            "portfolio_component_real_history_warmup_incomplete",
        )
    decisions = json.loads((original / "summary.json").read_text())["decisions"]
    require(
        all(row["decision"] == "archive_fixed_hypothesis" for row in decisions)
        and {row["candidate"] for row in decisions} == set(COMPONENTS),
        "portfolio_original_archival_decisions_changed",
    )
    return {
        "prices": prices.loc[prices.timestamp.isin(sessions)].copy(),
        "sessions": sessions,
        "history": history,
        "availability": available,
        "signals": signals,
        "calendar": cal,
        "component_sources": source_refs,
        "source_files": identities,
        "coverage": coverage,
    }


def preflight(plan_path=DEFAULT_PLAN):
    plan = read_plan(plan_path)
    read_addendum(plan_path)
    before = source_identity()
    inputs = load_inputs(plan)
    require(
        verify_inputs(plan) == inputs["source_files"] and source_identity() == before,
        "portfolio_preflight_source_or_input_changed",
    )
    return {
        "status": "preflight_passed",
        "plan_sha256": PLAN_SHA,
        "statistical_addendum_sha256": ADDENDUM_SHA,
        "source_identity": before,
        "original_input_files": len(inputs["source_files"]),
        "component_history_sessions": len(inputs["history"]),
        "evaluation_sessions": len(inputs["sessions"]),
        "decision_count": len(inputs["signals"][COMPONENTS[0]]),
        "first_signal": plan["first_signal_session"],
        "price_rows": len(inputs["prices"]),
        "real_engine_runs": 0,
        "original_signal_recomputations": 0,
        "new_market_pnl_computed": False,
    }


def construct_targets(inputs, plan, hypothesis):
    method = {"P34_EQUAL": "equal_weight", "P34_ERC": "erc"}[hypothesis]
    schedules = {"full": {}, **{key: {} for key in COMPONENTS}}
    allocations = []
    policy = AllocationPolicy(
        method,
        plan["policy"]["gross_budget"],
        plan["policy"]["max_component_weight"],
        plan["policy"]["require_full_budget"],
    )
    for trade, row in inputs["signals"][COMPONENTS[0]].items():
        signal = row["signal"]
        known = utc(inputs["calendar"].session_close(signal.tz_localize(None)))
        execution = utc(inputs["calendar"].session_open(trade.tz_localize(None)))
        expected = inputs["history"].index[inputs["history"].index <= signal][-252:]
        allocation = allocation_at(
            inputs["history"],
            availability_times=inputs["availability"],
            expected_sessions=expected,
            component_ids=COMPONENTS,
            decision_at=known,
            policy=policy,
        )
        components = {
            key: {
                "known_at": known,
                "execute_at": execution,
                "source_digest": digest(inputs["component_sources"][key]),
                "weights": inputs["signals"][key][trade]["weights"],
            }
            for key in COMPONENTS
        }
        allocations.append(
            {
                "signal_session": signal.date().isoformat(),
                "trade_session": trade.date().isoformat(),
                "allocation": allocation,
                "component_sources": inputs["component_sources"],
            }
        )
        schedules["full"][trade] = combine_targets(allocation, components, execute_at=execution)
        for removed in COMPONENTS:
            schedules[removed][trade] = combine_targets(
                allocation, components, execute_at=execution, omitted_component=removed
            )
    return schedules, allocations


def population():
    cells = []
    for cost in (1, 2, 3):
        for reference in ("EW", "SPY"):
            cells.append(
                {
                    "trial_id": f"REF_{reference}-cost{cost}x",
                    "role": "reference",
                    "reference": reference,
                    "cost_multiplier": cost,
                }
            )
        for hypothesis in HYPOTHESES:
            for removed in (None, *COMPONENTS):
                suffix = "full" if removed is None else "without-" + removed
                cells.append(
                    {
                        "trial_id": f"{hypothesis}-{suffix}-cost{cost}x",
                        "role": "portfolio_hypothesis"
                        if removed is None
                        else "component_removal_counterfactual",
                        "hypothesis": hypothesis,
                        "removed_component": removed,
                        "cost_multiplier": cost,
                    }
                )
    return cells


def serial_schedule(schedule):
    return {utc(day).isoformat(): value for day, value in schedule.items()}


def execute_trial(cell, prices, targets, sessions, output, identity, plan):
    """Registration precedes actual engine invocation, including failed attempts."""
    directory = output / cell["trial_id"]
    directory.mkdir()
    multiplier = cell["cost_multiplier"]
    config = BacktestConfig(
        initial_cash=plan["initial_research_cash_usd"],
        commission_bps=multiplier,
        slippage_bps=5 * multiplier,
    )
    registration = {
        **cell,
        "status": "started",
        "started_at": datetime.now(UTC).isoformat(),
        "identity_digest": digest(identity),
        "target_schedule_digest": digest(serial_schedule(targets)),
        "config": config.model_dump(mode="json"),
        "actual_engine_invoked": True,
    }
    write(directory / "trial-registration.json", registration)
    append(output / "research-index.jsonl", registration)
    try:
        result = BacktestEngine(config).run(prices, _ScheduledTargets(targets))
        for name in PARQUETS:
            getattr(result, name).to_parquet(directory / f"{name}.parquet", index=False)
        write(directory / "engine-metrics.json", result.metrics.model_dump(mode="json"))
        accounting = _check_replay(result, config, sessions)
        parts = []
        for name, (start, end) in plan["partitions"].items():
            mask = result.equity_curve.timestamp.between(utc(start), utc(end))
            selected = result.equity_curve.loc[mask]
            previous = result.equity_curve.loc[result.equity_curve.timestamp < utc(start)]
            base = float(previous.iloc[-1].equity) if len(previous) else config.initial_cash
            trades = result.trade_blotter.loc[
                result.trade_blotter.timestamp.between(utc(start), utc(end))
            ]
            parts.append(
                {
                    "partition": name,
                    "start": start,
                    "end": end,
                    "metrics": _metrics(selected, trades, base),
                    "unseen_holdout": False,
                }
            )
        report = {
            **cell,
            "status": "completed",
            "actual_engine_invoked": True,
            "accounting": accounting,
            "metrics": result.metrics.model_dump(mode="json"),
            "partitions": parts,
            "costs": etf_helper()._costs(result, multiplier),
            "capital_authorized": False,
            "configuration_digest": digest(config.model_dump(mode="json")),
            "artifact_files": {str(p.name): sha(p) for p in sorted(directory.glob("*.parquet"))},
        }
        write(directory / "result.json", report)
        append(
            output / "research-index.jsonl",
            {**cell, "status": "completed", "result_sha256": sha(directory / "result.json")},
        )
        return result, report
    except Exception as exc:
        failure = {
            **cell,
            "status": "failed",
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "actual_engine_invoked": True,
            "capital_authorized": False,
        }
        write(directory / "failure.json", failure)
        (directory / "exception.txt").write_text(traceback.format_exc())
        append(output / "research-index.jsonl", failure)
        return None, failure


def partition_curve(curve, start, end, cash):
    part = curve.loc[curve.timestamp.between(utc(start), utc(end))].copy()
    previous = curve.loc[curve.timestamp < utc(start)]
    for column in ("equity", "benchmark", "peer"):
        if column in part:
            base = float(previous.iloc[-1][column]) if len(previous) else cash
            part[column] = part[column] / base * cash
    return part


def paired_power_block(active: dict) -> dict:
    """Carry the approximate MDE planning diagnostic with its method limitations."""
    return paired_sharpe_power(active)


def execution_cost_preflight(input_path, *, expected_input_digest):
    """Read one frozen scenario/snapshot and quote net orders without a replay."""
    from quant_system.portfolio.execution_costs import (
        ExecutionCostScenario,
        preflight_combined_targets,
    )

    raw = Path(input_path).read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    require(observed == expected_input_digest, "cost_preflight_input_digest_changed")
    payload = json.loads(raw)
    require(payload.get("schema") == "portfolio_cost_preflight_input/v1", "cost_input_schema")
    snapshot = payload["portfolio_snapshot"]
    require(
        np.isfinite(snapshot["cash"])
        and snapshot["cash"] >= 0
        and all(np.isfinite(value) and value >= 0 for value in snapshot["positions"].values()),
        "cost_portfolio_snapshot_invalid",
    )
    portfolio = Portfolio(initial_cash=snapshot["cash"])
    portfolio.positions = dict(snapshot["positions"])
    result = preflight_combined_targets(
        payload["combined_target"],
        portfolio=portfolio,
        config=BacktestConfig.model_validate(payload["order_generation_config"]),
        scenario=ExecutionCostScenario.model_validate(payload["scenario"]),
        prices=payload["price_inputs"],
        liquidity=payload["liquidity_inputs"],
    )
    return {
        **result,
        "input_digest": observed,
        "source_identity": source_identity(),
        "actual_engine_invoked": False,
    }


def paired_reports(full, reference, plan, *, reference_name):
    curve = pd.DataFrame(
        {
            "timestamp": full.equity_curve.timestamp,
            "equity": full.equity_curve.equity,
            "peer": reference.equity_curve.equity,
            "benchmark": reference.equity_curve.equity,
        }
    )
    rows = {}
    ranges = {"full": [plan["evaluation_start"], plan["evaluation_end"]], **plan["partitions"]}
    for name, (start, end) in ranges.items():
        part = partition_curve(curve, start, end, plan["initial_research_cash_usd"])
        mean_test = etf_helper().paired_active_mean_test(part)
        mean_test = {
            **mean_test,
            "reference": reference_name,
            "alternative": "mean_full_portfolio_minus_declared_reference_gt_zero",
        }
        metrics = active_metrics(
            part,
            initial_cash=plan["initial_research_cash_usd"],
            benchmark_symbol=reference_name,
            include_peer=False,
            bootstrap_seed=20260926,
        )
        rows[name] = {
            "active_metrics": metrics,
            "active_mean_test": mean_test,
            "paired_power": paired_power_block(metrics),
            "unseen_holdout": False,
        }
    return rows


@contextmanager
def isolated_side_effect_guard(output, forbidden):
    active = {"value": True}

    def audit(event, args):
        if not active["value"]:
            return
        if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
            forbidden.append({"event": event})
            raise PermissionError("portfolio_provider_or_subprocess_forbidden")
        paths = []
        if event == "open":
            path, mode, flags = args
            if (isinstance(mode, str) and any(x in mode for x in "wax+")) or (
                isinstance(flags, int)
                and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
            ):
                paths = [path]
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"}:
            paths = [args[0]]
        elif event in {"os.rename", "os.replace"}:
            paths = list(args[:2])
        for path in paths:
            if isinstance(path, int):
                continue
            resolved = Path(os.fsdecode(path)).resolve()
            if resolved == Path("/dev/null"):
                continue
            if not resolved.is_relative_to(output):
                forbidden.append({"event": event, "path": str(resolved)})
                raise PermissionError("portfolio_write_outside_isolated_output")

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active["value"] = False


def run(output, *, expected_source_digest, plan_path=DEFAULT_PLAN):
    output = Path(output).absolute()
    require(
        not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)),
        "portfolio_output_must_be_new_not_symlink",
    )
    require(
        any(output.is_relative_to(root) for root in (EVIDENCE, ROOT / "artifacts")),
        "portfolio_output_not_isolated",
    )
    plan = read_plan(plan_path)
    addendum = read_addendum(plan_path)
    source = source_identity()
    require(source["digest"] == expected_source_digest, "portfolio_expected_source_changed")
    output.mkdir(parents=True, mode=0o700)
    (output / "preregistration.json").write_bytes(Path(plan_path).read_bytes())
    (output / "preregistration-addendum-1.json").write_bytes(
        (Path(plan_path).parent / "preregistration-addendum-1.json").read_bytes()
    )
    identity = {
        "source_identity": source,
        "plan_sha256": PLAN_SHA,
        "statistical_addendum_sha256": ADDENDUM_SHA,
        "started_at": datetime.now(UTC).isoformat(),
        "input_files": plan["source_files"],
        "scope": "retrospective_T3.4_not_alpha_discovery",
        "information_time_limit": plan["information_time_limit"],
    }
    write(output / "identity.json", identity)
    write(output / "planned-population.json", {"cells": population(), "count": 30})
    outcomes, results, schedules, allocation_errors, forbidden, comparisons = [], {}, {}, {}, [], {}
    try:
        with isolated_side_effect_guard(output, forbidden):
            inputs = load_inputs(plan)
            for hypothesis in HYPOTHESES:
                try:
                    schedules[hypothesis], allocations = construct_targets(inputs, plan, hypothesis)
                    write(output / f"{hypothesis}-allocations.json", allocations)
                    write(
                        output / f"{hypothesis}-targets.json",
                        {
                            key: serial_schedule(value)
                            for key, value in schedules[hypothesis].items()
                        },
                    )
                except Exception as exc:
                    allocation_errors[hypothesis] = f"{type(exc).__name__}: {exc}"
                    write(
                        output / f"{hypothesis}-construction-failure.json",
                        {"reason": str(exc), "error_type": type(exc).__name__},
                    )
            for cell in population():
                if cell["role"] == "reference":
                    targets = (
                        {
                            day: {symbol: 0.1 for symbol in etf_helper().SYMBOLS}
                            for day in inputs["signals"][COMPONENTS[0]]
                        }
                        if cell["reference"] == "EW"
                        else {inputs["sessions"][0]: {"SPY": 1.0}}
                    )
                elif cell["hypothesis"] in allocation_errors:
                    outcome = {
                        **cell,
                        "status": "not_evaluated",
                        "actual_engine_invoked": False,
                        "reason": allocation_errors[cell["hypothesis"]],
                    }
                    append(output / "research-index.jsonl", outcome)
                    outcomes.append(outcome)
                    continue
                else:
                    key = cell["removed_component"] or "full"
                    targets = {
                        day: row["symbol_weights"]
                        for day, row in schedules[cell["hypothesis"]][key].items()
                    }
                result, outcome = execute_trial(
                    cell, inputs["prices"], targets, inputs["sessions"], output, identity, plan
                )
                results[cell["trial_id"]] = result
                outcomes.append(outcome)
                print(
                    json.dumps(
                        {
                            "event": "trial_finished",
                            "trial_id": cell["trial_id"],
                            "status": outcome["status"],
                        }
                    ),
                    flush=True,
                )
            comparisons = {}
            for cost in (1, 2, 3):
                for hypothesis in HYPOTHESES:
                    full = results.get(f"{hypothesis}-full-cost{cost}x")
                    for label in ("EW", "SPY", *COMPONENTS):
                        reference = results.get(
                            f"REF_{label}-cost{cost}x"
                            if label in {"EW", "SPY"}
                            else f"{hypothesis}-without-{label}-cost{cost}x"
                        )
                        key = f"{hypothesis}-vs-{label}-cost{cost}x"
                        if full is None or reference is None:
                            comparisons[key] = {
                                "status": "not_evaluated",
                                "reason": "underlying_real_replay_missing",
                            }
                            continue
                        try:
                            record = {
                                "status": "completed",
                                "partitions": paired_reports(
                                    full, reference, plan, reference_name=label
                                ),
                            }
                            if label in COMPONENTS:
                                record["component_removal"] = compare_replayed_portfolios(
                                    full,
                                    reference,
                                    config=BacktestConfig(
                                        initial_cash=plan["initial_research_cash_usd"],
                                        commission_bps=cost,
                                        slippage_bps=cost * 5,
                                    ),
                                    expected_sessions=inputs["sessions"],
                                    combined_schedule=schedules[hypothesis]["full"],
                                    without_schedule=schedules[hypothesis][label],
                                    removed_component=label,
                                    bootstrap_seed=20260926,
                                )
                        except Exception as exc:
                            record = {
                                "status": "not_evaluated",
                                "reason": str(exc),
                                "error_type": type(exc).__name__,
                            }
                        write(output / f"{key}.json", record)
                        comparisons[key] = {
                            "status": record["status"],
                            "reason": record.get("reason"),
                            "path": str(output / f"{key}.json"),
                            "sha256": sha(output / f"{key}.json"),
                            "partition_mean_tests": {
                                name: value["active_mean_test"]
                                for name, value in record.get("partitions", {}).items()
                            },
                        }
            family = [
                f"{hypothesis}-vs-{label}-cost1x"
                for hypothesis in HYPOTHESES
                for label in ("EW", *COMPONENTS)
            ]
            pvalues = [
                comparisons[key]
                .get("partition_mean_tests", {})
                .get(addendum["main_holm_partition"], {})
                .get("p")
                for key in family
            ]
            adjusted = adjust_pvalues(pvalues, method="holm")
            write(
                output / "comparisons.json",
                {
                    "all_comparisons": comparisons,
                    "primary_partition": addendum["main_holm_partition"],
                    "holm_family": [
                        {"comparison": key, "p": p, "holm_p": q}
                        for key, p, q in zip(family, pvalues, adjusted, strict=True)
                    ],
                    "family_size": 8,
                    "alpha_claimed": False,
                },
            )
    except Exception as exc:
        write(
            output / "driver-failure.json", {"reason": str(exc), "error_type": type(exc).__name__}
        )
        (output / "driver-exception.txt").write_text(traceback.format_exc())
    for cell in population():
        if cell["trial_id"] not in {row["trial_id"] for row in outcomes}:
            outcome = {
                **cell,
                "status": "not_evaluated",
                "actual_engine_invoked": False,
                "reason": "driver_failed_before_this_trial",
            }
            outcomes.append(outcome)
            append(output / "research-index.jsonl", outcome)
    checks = {
        "source_unchanged": False,
        "input_files_unchanged": False,
        "plan_unchanged": False,
        "forbidden_calls": forbidden,
    }
    try:
        checks["source_unchanged"] = source_identity() == source
        checks["input_files_unchanged"] = verify_inputs(plan) == {
            name: value["sha256"] for name, value in plan["source_files"].items()
        }
        checks["plan_unchanged"] = (
            read_plan(plan_path) == plan and read_addendum(plan_path) == addendum
        )
    except Exception as exc:
        checks["closing_error"] = f"{type(exc).__name__}: {exc}"
    write(output / "verification.json", checks)
    completed = sum(row["status"] == "completed" for row in outcomes)
    summary = {
        "status": "completed_research_diagnostic"
        if completed == 30
        and all(
            checks[key] for key in ("source_unchanged", "input_files_unchanged", "plan_unchanged")
        )
        and len(comparisons) == 30
        and all(row["status"] == "completed" for row in comparisons.values())
        and not forbidden
        and not (output / "driver-failure.json").exists()
        else "partial",
        "planned_engine_replays": 30,
        "completed_engine_replays": completed,
        "actual_engine_invocations": sum(row["actual_engine_invoked"] for row in outcomes),
        "real_portfolio_experiment_invocations": sum(
            row["actual_engine_invoked"] and row["role"] != "reference" for row in outcomes
        ),
        "reference_invocations": sum(
            row["actual_engine_invoked"] and row["role"] == "reference" for row in outcomes
        ),
        "outcomes": outcomes,
        "allocation_failures": allocation_errors,
        "comparison_failures": {
            key: value for key, value in comparisons.items() if value["status"] != "completed"
        },
        "capital_authorized": False,
        "admission_qualified": False,
        "original_B_archival_decisions_unchanged": True,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write(output / "summary.json", summary)
    write(
        output / "artifact-manifest.json",
        {
            "files": {
                str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*")) if p.is_file()
            }
        },
    )
    return {
        "status": summary["status"],
        "output": str(output),
        "summary_sha256": sha(output / "summary.json"),
        "completed_engine_replays": completed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-source-digest")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--cost-preflight-input", type=Path)
    parser.add_argument("--expected-cost-input-digest")
    args = parser.parse_args()
    if args.cost_preflight_input:
        if args.run or not args.expected_cost_input_digest:
            parser.error(
                "cost preflight requires its input digest and cannot be combined with --run"
            )
        result = execution_cost_preflight(
            args.cost_preflight_input,
            expected_input_digest=args.expected_cost_input_digest,
        )
        if args.output:
            args.output.mkdir(parents=True, exist_ok=False)
            write(args.output / "execution-cost-preflight.json", result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
        return 0 if result["status"] == "evaluated" else 1
    result = (
        run(args.output, expected_source_digest=args.expected_source_digest, plan_path=args.plan)
        if args.run
        else preflight(args.plan)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] in {"preflight_passed", "completed_research_diagnostic"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
