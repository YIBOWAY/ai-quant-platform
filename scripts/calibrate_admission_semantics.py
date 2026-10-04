"""Bounded synthetic quality calibration and real-engine algebra verification.

Requires an owner-frozen JSON mechanism and exact source SHA before Monte Carlo.
Never reads or writes a formal book/ledger, submits research or creates capital.
Synthetic statistical qualification is conditional on no existing peer sleeves;
it is not full money-consumer Monte Carlo or evidence of market alpha.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 252
CASH = 10_000.0
CASE_NAMES = ("null", "pure_beta", "positive_ir05", "positive_ir1", "positive_ir2")
IR_VALUES = (0.0, 0.0, 0.5, 1.0, 2.0)
ROOT_SEEDS = (2026100302, 2026100303, 2026100304, 2026100304, 2026100304)
OBJECTS = ("arithmetic_net_active", "net_total_return", "net_total_return")
OBJECT_NAMES = ("arithmetic_net_active", "net_total_return", "net_total_qlib_combined")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    with path.open("x") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def publish_final(path, document):
    """Completed identical resumes leave the original dated bytes intact."""
    if path.exists():
        previous = json.loads(path.read_text())
        ignored = {"started_at", "completed_at"}
        if {k: v for k, v in previous.items() if k not in ignored} != {
            k: v for k, v in document.items() if k not in ignored
        }:
            raise ValueError("calibration_final_summary_changed")
        return previous
    write(path, document)
    return document


def cells():
    return [
        {
            "index": index,
            "object_index": object_index,
            "return_object": OBJECTS[object_index],
            "object_name": OBJECT_NAMES[object_index],
            "cost_model": "qlib_combined_bps" if object_index == 2 else "proportional_bps",
            "n": n,
            "rho": rho,
            "frequency": frequency,
            "case": name,
            "case_index": kind,
            "net_ir": IR_VALUES[kind],
            "primary_null": name == "null",
            "primary_positive": (n, rho, frequency, name) == (2016, 0.0, 21, "positive_ir2"),
        }
        for index, (object_index, n, rho, frequency, kind, name) in enumerate(
            (object_index, n, rho, frequency, kind, name)
            for object_index in (0, 1, 2)
            for n in (126, 504, 2016)
            for rho in (0.0, 0.3)
            for frequency in (1, 5, 21)
            for kind, name in enumerate(CASE_NAMES)
        )
    ]


def fee_rates(multiplier, cost_model):
    if cost_model == "proportional_bps":
        return multiplier / 10_000, 5 * multiplier / 10_000
    if cost_model == "qlib_combined_bps":
        return 6 * multiplier / 10_000, 0.0
    raise ValueError("calibration_unsupported_cost_model")


def trade_factors(n, frequency, multiplier=1, cost_model="proportional_bps"):
    """Exact all-invested entry/switch cash factors, including both commissions."""
    if n < 1 or frequency < 1 or multiplier not in (1, 2, 3):
        raise ValueError("calibration_trade_parameters_invalid")
    commission, slip = fee_rates(multiplier, cost_model)
    buy = (1 + slip) * (1 + commission)
    sell = (1 - slip) * (1 - commission)
    factor = np.ones(n)
    factor[0] = 1 / buy
    factor[frequency::frequency] = sell / buy
    return factor


def exact_cost_path(gross_returns, frequency, multiplier=1, cost_model="proportional_bps"):
    """Analytic no-cash all-invested path; independently checked against engine."""
    gross = np.asarray(gross_returns, dtype=float)
    factor = trade_factors(len(gross), frequency, multiplier, cost_model)
    returns = factor * (1 + gross) - 1
    if not np.isfinite(returns).all() or (returns <= -1).any():
        raise ValueError("calibration_nonpositive_or_nonfinite_returns")
    nav = CASH * np.cumprod(1 + returns)
    prior = np.concatenate(([CASH], nav[:-1]))
    commission, slip = fee_rates(multiplier, cost_model)
    traded = np.zeros(len(gross))
    traded[0] = CASH / (1 + commission)
    switched = np.arange(frequency, len(gross), frequency)
    sales = prior[switched] * (1 - slip)
    buys = sales * (1 - commission) / (1 + commission)
    traded[switched] = sales + buys
    if not np.isfinite(nav).all() or (nav <= 0).any():
        raise ValueError("calibration_nonpositive_or_nonfinite_nav")
    return {
        "returns": returns,
        "nav": nav,
        "gross_traded": traded,
        "turnover": float(math.fsum(traded) / CASH),
        "commission": float(math.fsum(traded) * commission),
    }


def gross_for_net(net_returns, frequency, cost_model="proportional_bps"):
    """Explicit engineered BASE-cost compensation, never reapplied at2x/3x."""
    values = np.asarray(net_returns, dtype=float)
    if not np.isfinite(values).all() or (values <= -1).any():
        raise ValueError("calibration_net_target_invalid")
    return (1 + values) / trade_factors(len(values), frequency, cost_model=cost_model) - 1


def artificial_prices(gross_returns, market_returns, frequency, dates):
    """Two priced synthetic assets and decisions known before innovations."""
    gross, market = np.asarray(gross_returns), np.asarray(market_returns)
    if len(gross) != len(dates) or len(market) != len(dates):
        raise ValueError("calibration_calendar_length_mismatch")
    opens = {"ARTIFICIAL.A": 100.0, "ARTIFICIAL.B": 100.0}
    rows, schedule, signals = [], {}, []
    for index, day in enumerate(dates):
        selected = "ARTIFICIAL.A" if (index // frequency) % 2 == 0 else "ARTIFICIAL.B"
        if index % frequency == 0:
            key = day.date().isoformat()
            schedule[key] = {selected: 1.0}
            signals.append(
                {
                    "signal_date": (day - pd.Timedelta(days=1)).date().isoformat(),
                    "trade_date": key,
                    "targets": schedule[key],
                }
            )
        for symbol in opens:
            move = gross[index] if symbol == selected else market[index]
            close = opens[symbol] * (1 + move)
            if not math.isfinite(close) or close <= 0:
                raise ValueError("calibration_invalid_synthetic_price")
            rows.append(
                {
                    "timestamp": day,
                    "symbol": symbol,
                    "open": opens[symbol],
                    "close": close,
                    "data_kind": "ARTIFICIAL_SYNTHETIC",
                }
            )
            opens[symbol] = close
    return pd.DataFrame(rows), schedule, signals


def innovations(seed, object_index, cell_index, replicate, stream, n):
    generator = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence([seed, object_index, cell_index, replicate, stream]))
    )
    return generator.standard_normal(n)


def sample(cell, replicate, *, holdout=False, engine_example=False):
    # Explicit independent streams; no rejection/redraw or demeaning of samples.
    from scipy.signal import lfilter

    n, rho, cost_model = cell["n"], cell["rho"], cell["cost_model"]
    seed = (
        2026100301 if engine_example else 2026100305 if holdout else ROOT_SEEDS[cell["case_index"]]
    )
    sigma = 0.10 / math.sqrt(252)
    market_target = 0.06 / 252 + sigma * innovations(
        seed, cell["object_index"], cell["index"], replicate, 0, n
    )
    # Construct an actual one-entry buy-and-hold reference contract. It is
    # synthetic and net of base costs; no zero reference is invented for total.
    benchmark_gross = gross_for_net(market_target, n + 1, cost_model)
    market = exact_cost_path(benchmark_gross, n + 1, cost_model=cost_model)["returns"]
    selected = []
    object_beta = 1.0 if cell["object_index"] == 0 else 0.0
    for member in range(12):
        normal = innovations(
            seed, cell["object_index"], cell["index"], replicate, member + 1, n + 256
        )
        residual = lfilter([sigma * math.sqrt(1 - rho * rho)], [1, -rho], normal)[256:]
        if member == 0:
            if cell["case"] == "pure_beta":
                residual = np.zeros(n)
                own = 1.2 * market
            else:
                own = object_beta * market + cell["net_ir"] * sigma / math.sqrt(252) + residual
        else:
            own = object_beta * market + residual
        # Use the actual analytic base-cost arithmetic, not a hand-tagged series.
        gross = gross_for_net(own, cell["frequency"], cost_model)
        reconstructed = exact_cost_path(gross, cell["frequency"], cost_model=cost_model)
        selected.append(
            reconstructed["returns"] - market
            if cell["object_index"] == 0
            else reconstructed["returns"]
        )
        if member == 0:
            candidate = {
                "total": reconstructed["returns"],
                "gross": gross,
                "path": reconstructed,
                "known_beta": 1.2 if cell["case"] == "pure_beta" else object_beta,
                "desired_net": own,
            }
    return {
        **candidate,
        "market": market,
        "benchmark_gross": benchmark_gross,
        "family_selected": selected,
        "seed": seed,
    }


def source_identity():
    """Bind the actually imported root implementation and the exact driver."""
    import quant_system
    from quant_system.research.cost_replay import cost_replay_source_identity

    package = Path(quant_system.__file__).resolve().parent
    paths = [
        package / "research/capital_quality.py",
        package / "research/trials.py",
        package / "execution/assistant_remote.py",
        package / "research/active_metrics.py",
        *sorted((package / "research/gate_v2").glob("*.py")),
    ]
    return {
        "package_path": str(package),
        "driver_sha256": sha(__file__),
        "quality_sources": {str(path.relative_to(package)): sha(path) for path in paths},
        "cost_sources": cost_replay_source_identity(),
        "python": sys.version,
        "environment": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "pydantic")
        },
    }


def evaluate_sample(cell, generated):
    """Actual shared minimum-quality function, conditional on the named inputs."""
    from quant_system.execution.assistant_remote import _certify_cost_sensitivity
    from quant_system.research.capital_quality import evaluate_new_capital_quality
    from quant_system.research.gate_v2.correlation_v2 import concentration_v2
    from quant_system.research.gate_v2.family import FAMILY_RULE_VERSION, _compatibility_contract
    from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG
    from quant_system.research.trials import performance_from_daily_returns

    dates = pd.bdate_range("2000-01-03", periods=cell["n"]).strftime("%Y-%m-%d").tolist()
    contract = _compatibility_contract(
        {
            "schema": "research_family_compatibility/v1",
            "return_definition": cell["return_object"],
            "benchmark": (
                {"symbol": "ARTIFICIAL_MARKET", "method": "net_buy_and_hold"}
                if cell["object_index"] == 0
                else {"symbol": None, "method": "none"}
            ),
            "frequency": "daily",
            "cost_definition": (
                {
                    "model": "proportional_bps",
                    "commission_bps": 1.0,
                    "slippage_bps": 5.0,
                    "cash_interest": 0.0,
                }
                if cell["cost_model"] == "proportional_bps"
                else {
                    "model": "qlib_combined_bps",
                    "one_way_bps": 6.0,
                    "min_cost": 0.0,
                    "cash_interest": 0.0,
                }
            ),
            "market_data_contract": {
                "provider": "ARTIFICIAL_SYNTHETIC",
                "price_adjustment": "unadjusted",
                "currency": "USD",
                "bar": "1d",
            },
        }
    )
    members = []
    for index, values in enumerate(generated["family_selected"]):
        perf = performance_from_daily_returns(values.tolist())
        members.append(
            {
                "trial_id": f"ARTIFICIAL-{index}",
                "n_periods": cell["n"],
                "returns_digest": digest(values.tolist()),
                "recomputed_sharpe": perf["sharpe_period"],
            }
        )
    family = {
        "members": members,
        "excluded": [],
        "trusted": True,
        "n_trials": len(members),
        "n_applicable_trials": len(members),
        "coverage_shortfall": 0.0,
        "evidence_state": "complete",
        "compatibility_contract": contract,
        "rule_version": FAMILY_RULE_VERSION,
    }
    family["family_digest"] = digest(family)
    total, selected = generated["total"].tolist(), generated["family_selected"][0].tolist()
    perf = performance_from_daily_returns(total)
    annual = (1 + perf["total_return"]) ** (252 / cell["n"]) - 1
    cost = _certify_cost_sensitivity(
        {"performance": {**perf, "turnover_period": generated["path"]["turnover"]}}, cost_bps=6
    )
    concentration = concentration_v2(
        active={"equity_returns": total, "dates": dates},
        hung_sleeves=[],
        config=GATE_V2_CONFIG,
        require_dates=True,
    )
    quality = evaluate_new_capital_quality(
        selected_returns=selected,
        total_returns=total,
        dates=dates,
        return_contract=contract,
        family=family,
        concentration=concentration,
        cost=cost,
        config=GATE_V2_CONFIG,
    )
    risk_adjusted = generated["total"] - generated["known_beta"] * generated["market"]
    return {
        "eligible": quality["eligible"],
        "tier": quality["tier"],
        "reasons": quality["reasons"],
        "dsr_passed": quality["dsr"]["passed"],
        "health_passed": quality["health"]["passed"],
        "cost_passed": cost["passed"],
        "dsr_value": quality["dsr"]["value"],
        "threshold_sr": quality["dsr"]["threshold_sr"],
        "family_digest": family["family_digest"],
        "quality_digest": digest(quality),
        "gross_mean": float(generated["gross"].mean()),
        "selected_mean": float(np.mean(selected)),
        "ordinary_active_mean": float(np.mean(selected)) if cell["object_index"] == 0 else None,
        "known_beta_adjusted_mean": float(risk_adjusted.mean()),
        "known_beta_adjusted_max_abs": float(np.max(np.abs(risk_adjusted))),
        "turnover": generated["path"]["turnover"],
        "net_total_cagr": annual,
        "linear_cost_margin": cost["net_return_at_2x"],
        "linear_cost": cost,
        "base_cost_compensation_mean": float(
            np.mean(generated["gross"] - generated["desired_net"])
        ),
        "stress_total_cagr": {
            str(multiplier): float(
                (
                    exact_cost_path(
                        generated["gross"], cell["frequency"], multiplier, cell["cost_model"]
                    )["nav"][-1]
                    / CASH
                )
                ** (252 / cell["n"])
                - 1
            )
            for multiplier in (1, 2, 3)
        },
    }


def interval(successes, total, alpha=0.05):
    from scipy.stats import beta

    return {
        "lower": 0.0
        if successes == 0
        else float(beta.ppf(alpha, successes, total - successes + 1)),
        "upper": 1.0
        if successes == total
        else float(beta.ppf(1 - alpha, successes + 1, total - successes)),
        "method": "one_sided_exact_clopper_pearson",
        "alpha": alpha,
    }


def summarize(cell, rows):
    successes = sum(row.get("eligible") is True for row in rows)
    failures = sum(row.get("status") == "failed" for row in rows)
    bounds = interval(successes, len(rows))
    passed = None
    if cell["primary_null"]:
        passed = successes / len(rows) <= 0.05 and bounds["upper"] <= 0.05 and failures == 0
    if cell["primary_positive"]:
        passed = bounds["lower"] >= 0.80 and failures == 0
    return {
        "cell": cell,
        "replicates": len(rows),
        "failed_replicates": failures,
        "eligible": successes,
        "eligible_rate": successes / len(rows),
        "interval": bounds,
        "simultaneous_57_primary_interval": interval(successes, len(rows), alpha=0.05 / 57),
        "primary_acceptance": passed,
        "counts": {
            key: sum(row.get(key) is True for row in rows)
            for key in ("dsr_passed", "health_passed", "cost_passed")
        },
        "tiers": dict(Counter(row.get("tier", "failed") for row in rows)),
        "reason_counts": dict(Counter(reason for row in rows for reason in row.get("reasons", []))),
        "pure_beta_risk_adjusted_zero": (
            all(row.get("known_beta_adjusted_max_abs", 1) <= 1e-14 for row in rows)
            if cell["case"] == "pure_beta"
            else None
        ),
    }


def engine_example(cell, output):
    return verify_engine_case(cell, sample(cell, 0, engine_example=True), output)


def replay_declared_combined(prices, base, schedule, config, dates):
    """Actual engine at6/12/18bp; not Qlib software or1+5 cost-seam equivalence."""
    from quant_system.backtest.engine import BacktestEngine
    from quant_system.research.cost_replay import _base_equivalence, _records, audit_cost_replay
    from quant_system.research.profile_backtests import _ScheduledTargets

    scenarios = []
    for multiplier in (1, 2, 3):
        scaled = config.model_copy(update={"commission_bps": 6 * multiplier, "slippage_bps": 0})
        actual = BacktestEngine(scaled).run(
            prices,
            _ScheduledTargets(
                {pd.Timestamp(day, tz="UTC"): weights for day, weights in schedule.items()}
            ),
        )
        accounting = audit_cost_replay(
            actual, prices=prices, config=scaled, target_schedule=schedule, expected_sessions=dates
        )
        if multiplier == 1:
            _base_equivalence(actual, base, scaled)
        scenarios.append(
            {
                "multiplier": multiplier,
                "config": scaled.model_dump(mode="json"),
                "accounting": accounting,
                "costs": {"commission_usd": math.fsum(actual.trade_blotter.commission)},
                **{
                    name: _records(getattr(actual, name))
                    for name in ("equity_curve", "orders", "trade_blotter", "positions")
                },
            }
        )
    return {
        "schema": "ARTIFICIAL_combined_cost_replay/v1",
        "scenarios": scenarios,
        "cost_contract": "qlib_combined_bps",
        "engine_runs": 3,
        "funding_authority": False,
        "qlib_software_validation": False,
    }


def verify_engine_case(cell, generated, output):
    """Saved artificial arrays -> actual base engine -> actual three-cost seam."""
    from quant_system.backtest.engine import BacktestEngine
    from quant_system.backtest.models import BacktestConfig
    from quant_system.research.cost_replay import (
        cost_replay_input_digest,
        cost_replay_source_identity,
        replay_cost_scenarios,
    )
    from quant_system.research.profile_backtests import _ScheduledTargets
    from quant_system.research.reference_backtests import _metrics

    dates = pd.bdate_range("2000-01-03", periods=cell["n"], tz="UTC")
    prices, schedule, signals = artificial_prices(
        generated["gross"], generated["market"], cell["frequency"], dates
    )
    # Preserve the declared bps inputs exactly. Converting 6/10000 back by
    # multiplication can yield 5.999999999999999 and break identical-base replay.
    commission_bps, slippage_bps = (
        (6.0, 0.0) if cell["cost_model"] == "qlib_combined_bps" else (1.0, 5.0)
    )
    config = BacktestConfig(
        initial_cash=CASH, commission_bps=commission_bps, slippage_bps=slippage_bps
    )
    directory = output / f"cell-{cell['index']:03d}"
    directory.mkdir()
    write(
        directory / "attempt.json",
        {
            "cell": cell,
            "status": "started",
            "source_digest": digest(source_identity()),
            "planned_engine_invocations": 4,
            "artificial": True,
            "schedule_digest": digest(schedule),
        },
    )
    first = BacktestEngine(config).run(
        prices,
        _ScheduledTargets(
            {pd.Timestamp(day, tz="UTC"): weights for day, weights in schedule.items()}
        ),
    )
    definition_digest = digest(
        {"schema": "ARTIFICIAL_SCHEDULE_ONLY/v1", "cell": cell, "schedule": schedule}
    )
    base = {
        "status": "available",
        "definition_digest": definition_digest,
        "definition": {
            key: getattr(config, key)
            for key in (
                "commission_bps",
                "slippage_bps",
                "min_order_value",
                "whole_share_orders",
                "execution_price",
            )
        },
        "evaluation_initial_cash": CASH,
        "start": dates[0].date().isoformat(),
        "end": dates[-1].date().isoformat(),
        "curve": [
            {"date": row.timestamp.date().isoformat(), "equity": row.equity}
            for row in first.equity_curve.itertuples()
        ],
        "trades": [
            {
                "date": row.timestamp.date().isoformat(),
                "symbol": row.symbol,
                "side": row.side,
                "quantity": row.quantity,
                "requested_price": row.requested_price,
                "fill_price": row.fill_price,
                "commission": row.commission,
            }
            for row in first.trade_blotter.itertuples()
        ],
        "metrics": _metrics(first.equity_curve, first.trade_blotter, CASH),
        "costs": {"commission_bps": config.commission_bps, "slippage_bps": config.slippage_bps},
        "signals": signals,
    }
    inputs = dict(
        prices=prices,
        base_result=base,
        config=config,
        target_schedule=schedule,
        source_identity=cost_replay_source_identity(),
    )
    input_digest = cost_replay_input_digest(**inputs)
    prices.to_parquet(directory / "ARTIFICIAL-prices.parquet", index=False)
    write(
        directory / "input.json",
        {
            "cell": cell,
            "input_digest": input_digest,
            "generated_total": generated["total"].tolist(),
            "gross": generated["gross"].tolist(),
            "market": generated["market"].tolist(),
            "benchmark_gross": generated["benchmark_gross"].tolist(),
            "source_identity": inputs["source_identity"],
            "base_result": base,
        },
    )
    report = (
        replay_cost_scenarios(**inputs, expected_input_digest=input_digest)
        if cell["cost_model"] == "proportional_bps"
        else replay_declared_combined(prices, base, schedule, config, dates)
    )
    max_nav_error, max_turnover_usd_error, max_commission_error = 0.0, 0.0, 0.0
    for scenario in report["scenarios"]:
        analytic = exact_cost_path(
            generated["gross"], cell["frequency"], scenario["multiplier"], cell["cost_model"]
        )
        actual = np.array([row["equity"] for row in scenario["equity_curve"]])
        error = float(np.max(np.abs(actual - analytic["nav"])))
        turnover_error = abs(
            math.fsum(row["gross_value"] for row in scenario["trade_blotter"])
            - math.fsum(analytic["gross_traded"])
        )
        commission_error = abs(scenario["costs"]["commission_usd"] - analytic["commission"])
        max_nav_error = max(max_nav_error, error)
        max_turnover_usd_error = max(max_turnover_usd_error, turnover_error)
        max_commission_error = max(max_commission_error, commission_error)
        if max(error, turnover_error, commission_error) > 1e-7:
            raise ValueError("calibration_engine_scalar_accounting_mismatch")
    with gzip.open(directory / "cost-replay.json.gz", "wt") as handle:
        json.dump(report, handle, sort_keys=True, allow_nan=False)
    result = {
        "cell": cell,
        "status": "completed",
        "engine_invocations": 4,
        "source_digest": digest(source_identity()),
        "input_digest": input_digest,
        "max_nav_error_usd": max_nav_error,
        "max_gross_turnover_error_usd": max_turnover_usd_error,
        "max_commission_error_usd": max_commission_error,
        "accounting_tolerance_usd": 1e-7,
        "rtol": 0,
        "inputs_sha256": sha(directory / "input.json"),
        "prices_sha256": sha(directory / "ARTIFICIAL-prices.parquet"),
        "outputs_sha256": sha(directory / "cost-replay.json.gz"),
    }
    write(directory / "summary.json", result)
    return result


def validate_contract(contract, addendum):
    expected_cases = [row["name"] for row in contract["grid"]["cases"]]
    if (
        expected_cases != list(CASE_NAMES)
        or contract["grid"]["n_sessions"] != [126, 504, 2016]
        or contract["grid"]["residual_ar1"] != [0.0, 0.3]
        or contract["grid"]["switch_every_sessions"] != [1, 5, 21]
        or contract["grid"]["replicates_each"] != 500
        or contract["grid"]["main_cells"] != 180
        or [row["return_definition"] for row in contract["objects"]] != list(OBJECTS[:2])
        or contract["generator"]["market_mean_annual_arithmetic"] != 0.06
        or contract["generator"]["market_volatility_annual"] != 0.10
        or contract["generator"]["residual_volatility_annual"] != 0.10
    ):
        raise ValueError("calibration_frozen_contract_implementation_mismatch")
    if (
        addendum["matrix"]["objects"] != 3
        or addendum["matrix"]["main_cells"] != 270
        or addendum["matrix"]["total_quality_calls"] != 163500
        or addendum["matrix"]["primary_cells_per_split"] != 57
        or addendum["new_scope"]["object_index"] != 2
        or addendum["new_scope"]["cost_contract"]
        != {"model": "qlib_combined_bps", "one_way_bps": 6.0, "min_cost": 0.0, "cash_interest": 0.0}
    ):
        raise ValueError("calibration_frozen_addendum_implementation_mismatch")


def _require_source(expected):
    if digest(source_identity()) != expected:
        raise ValueError("calibration_source_changed")


def row_identity(cell, replicate, holdout):
    return {
        "replicate": replicate,
        "cell_index": cell["index"],
        "object_index": cell["object_index"],
        "holdout": holdout,
        "return_object": cell["return_object"],
        "seed": 2026100305 if holdout else ROOT_SEEDS[cell["case_index"]],
    }


def read_rows(path, cell, holdout, *, complete=False):
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    if len(rows) > 500 or (complete and len(rows) != 500):
        raise ValueError("calibration_cached_count_invalid")
    for index, row in enumerate(rows):
        if any(row.get(key) != value for key, value in row_identity(cell, index, holdout).items()):
            raise ValueError("calibration_cached_split_seed_or_replicate_mismatch")
    return rows


def load_completed_cell(cell, *, holdout, output, expected_source):
    label = f"cell-{cell['index']:03d}"
    path = output / (label + ".jsonl")
    rows = read_rows(path, cell, holdout, complete=True)
    expected = {
        **summarize(cell, rows),
        "holdout": holdout,
        "source_digest": expected_source,
        "rows_sha256": sha(path),
    }
    saved = json.loads((output / (label + ".summary.json")).read_text())
    if saved != expected:
        raise ValueError("calibration_cached_summary_changed")
    return expected


def recover_engine_directory(directory, *, output, cell, expected_source):
    """Keep interrupted bytes, then allow same frozen mechanical work to resume.

    A recorded calculation failure is never retried. An interruption before a
    terminal record leaves the number of engine calls unknown (upper bound4);
    this is retained in the final report, not silently counted as152 total calls.
    """
    if not directory.exists():
        return None
    if (directory / "failure.json").exists():
        raise ValueError("calibration_failed_engine_attempt_requires_diagnosis")
    recovery_root = output / "interrupted-engine-attempts"
    recovery_root.mkdir(exist_ok=True)
    index = len(list(recovery_root.glob(directory.name + "-*"))) + 1
    if index > 1:
        raise ValueError("calibration_repeated_engine_interruption_requires_diagnosis")
    archived = recovery_root / f"{directory.name}-{index}"
    directory.rename(archived)
    record = {
        "cell": cell,
        "source_digest": expected_source,
        "original": str(directory),
        "preserved": str(archived),
        "reason": "interrupted_before_terminal_record",
        "same_inputs_and_seed": True,
        "prior_invocation_count": None,
        "prior_invocation_upper_bound": 4,
        "files": {
            str(p.relative_to(archived)): sha(p) for p in sorted(archived.rglob("*")) if p.is_file()
        },
    }
    write(archived / "recovery.json", record)
    return record


def run_cell(cell, *, holdout, output, expected_source):
    _require_source(expected_source)
    label = f"cell-{cell['index']:03d}"
    data, summary_path = output / (label + ".jsonl"), output / (label + ".summary.json")
    if summary_path.exists():
        return load_completed_cell(
            cell, holdout=holdout, output=output, expected_source=expected_source
        )
    rows = read_rows(data, cell, holdout)
    consecutive_errors = 0
    for row in reversed(rows):
        if row.get("status") != "failed":
            break
        consecutive_errors += 1
    if consecutive_errors >= 3:
        raise RuntimeError("calibration_three_errors_stop_for_diagnosis")
    with data.open("a") as handle:
        for replicate in range(len(rows), 500):
            try:
                generated = sample(cell, replicate, holdout=holdout)
                record = {
                    **row_identity(cell, replicate, holdout),
                    "status": "completed",
                    **evaluate_sample(cell, generated),
                }
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                record = {
                    **row_identity(cell, replicate, holdout),
                    "status": "failed",
                    "eligible": False,
                    "reasons": [type(exc).__name__ + ":" + str(exc)],
                }
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            rows.append(record)
            if consecutive_errors >= 3:
                raise RuntimeError("calibration_three_errors_stop_for_diagnosis")
    _require_source(expected_source)
    summary = {
        **summarize(cell, rows),
        "holdout": holdout,
        "source_digest": expected_source,
        "rows_sha256": sha(data),
    }
    write(summary_path, summary)
    print(
        json.dumps(
            {
                "cell": cell["index"],
                "object": cell["return_object"],
                "holdout": holdout,
                "eligible": summary["eligible"],
                "failed": summary["failed_replicates"],
                "primary_acceptance": summary["primary_acceptance"],
            }
        ),
        flush=True,
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--expected-contract-sha", required=True)
    parser.add_argument("--addendum", type=Path, required=True)
    parser.add_argument("--expected-addendum-sha", required=True)
    parser.add_argument("--expected-source-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--engine-only", action="store_true")
    args = parser.parse_args()
    if (
        sha(args.contract) != args.expected_contract_sha
        or sha(args.addendum) != args.expected_addendum_sha
    ):
        raise ValueError("calibration_contract_changed")
    contract = json.loads(args.contract.read_text())
    addendum = json.loads(args.addendum.read_text())
    if addendum["parent_contract_sha256"] != args.expected_contract_sha:
        raise ValueError("calibration_addendum_parent_changed")
    validate_contract(contract, addendum)
    args.output = args.output.resolve()
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    if not args.output.is_relative_to(artifacts) or args.output == artifacts:
        raise ValueError("calibration_isolated_artifact_output_required")
    _require_source(args.expected_source_digest)
    bound = {
        "contract_sha256": args.expected_contract_sha,
        "contract": contract,
        "addendum": addendum,
        "addendum_sha256": args.expected_addendum_sha,
        "source_identity": source_identity(),
        "source_digest": args.expected_source_digest,
    }
    if args.resume:
        if json.loads((args.output / "binding.json").read_text()) != bound:
            raise ValueError("calibration_resume_binding_changed")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        write(args.output / "binding.json", bound)
        for directory in ("engine", "main", "holdout"):
            (args.output / directory).mkdir()
    started = datetime.now(UTC).isoformat()
    # Preload dependencies before a no-network/no-external-write process guard.
    import scipy.signal  # noqa: F401
    import scipy.stats  # noqa: F401

    from quant_system.execution.assistant_remote import _certify_cost_sensitivity  # noqa: F401
    from quant_system.research.capital_quality import evaluate_new_capital_quality  # noqa: F401

    sys.dont_write_bytecode = True
    forbidden = []

    def audit(event, values):
        if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system"}:
            forbidden.append(event)
            raise PermissionError("calibration_forbidden:" + event)
        if event == "open" and isinstance(values[0], (str, bytes)):
            mode, flags = values[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or flags & 3
            if writing and not Path(values[0]).resolve().is_relative_to(args.output):
                forbidden.append("write:" + str(values[0]))
                raise PermissionError("calibration_write_outside_output")

    sys.addaudithook(audit)
    engine_rows = []
    for cell in cells():
        selected = (
            cell["n"] == 126 and cell["case"] in {"null", "pure_beta", "positive_ir2"}
        ) or cell["primary_positive"]
        if not selected:
            continue
        _require_source(args.expected_source_digest)
        summary = args.output / "engine" / f"cell-{cell['index']:03d}" / "summary.json"
        if summary.exists():
            row = json.loads(summary.read_text())
            directory = summary.parent
            saved_inputs = json.loads((directory / "input.json").read_text())
            if (
                row.get("cell") != cell
                or saved_inputs.get("cell") != cell
                or row.get("source_digest") != args.expected_source_digest
                or row.get("engine_invocations") != 4
                or row.get("input_digest") != saved_inputs.get("input_digest")
            ):
                raise ValueError("calibration_engine_cached_identity_changed")
            for name, key in (
                ("input.json", "inputs_sha256"),
                ("ARTIFICIAL-prices.parquet", "prices_sha256"),
                ("cost-replay.json.gz", "outputs_sha256"),
            ):
                if sha(directory / name) != row[key]:
                    raise ValueError("calibration_engine_artifact_changed")
        else:
            recover_engine_directory(
                summary.parent,
                output=args.output,
                cell=cell,
                expected_source=args.expected_source_digest,
            )
            try:
                row = engine_example(cell, args.output / "engine")
            except Exception as exc:
                summary.parent.mkdir(exist_ok=True)
                write(
                    summary.parent / "failure.json",
                    {
                        "cell": cell,
                        "source_digest": args.expected_source_digest,
                        "reason": type(exc).__name__ + ":" + str(exc),
                    },
                )
                raise
        engine_rows.append(row)
    if args.engine_only:
        print(json.dumps({"engine_examples": len(engine_rows), "status": "engine_only_complete"}))
        return
    summaries = []
    for holdout in (False, True):
        for cell in cells():
            if holdout and not (cell["primary_null"] or cell["primary_positive"]):
                continue
            summaries.append(
                run_cell(
                    cell,
                    holdout=holdout,
                    output=args.output / ("holdout" if holdout else "main"),
                    expected_source=args.expected_source_digest,
                )
            )
    _require_source(args.expected_source_digest)
    primary = [row for row in summaries if row["primary_acceptance"] is not None]
    passed = (
        all(row["primary_acceptance"] for row in primary)
        and not any(row["failed_replicates"] for row in summaries)
        and not any(row["pure_beta_risk_adjusted_zero"] is False for row in summaries)
        and not forbidden
    )
    publish_final(
        args.output / "summary.json",
        {
            "schema": "admission_semantics_synthetic_calibration_result/v1",
            "status": "passed" if passed else "failed",
            "scope": contract["scope"],
            "contract_sha256": args.expected_contract_sha,
            "addendum_sha256": args.expected_addendum_sha,
            "source_digest": args.expected_source_digest,
            "started_at": started,
            "completed_at": datetime.now(UTC).isoformat(),
            "quality_calls": sum(row["replicates"] for row in summaries),
            "failed_replicates": sum(row["failed_replicates"] for row in summaries),
            "forbidden": forbidden,
            "engine_examples": engine_rows,
            "confirmed_completed_engine_invocations": sum(
                row["engine_invocations"] for row in engine_rows
            ),
            "interrupted_engine_attempts": [
                json.loads(path.read_text())
                for path in sorted(
                    (args.output / "interrupted-engine-attempts").glob("*/recovery.json")
                )
            ],
            "cells": summaries,
            "primary_failed_cells": [
                row["cell"] | {"holdout": row["holdout"]}
                for row in primary
                if not row["primary_acceptance"]
            ],
            "explicit_non_claims": contract["explicit_non_claims"],
        },
    )


if __name__ == "__main__":
    main()
