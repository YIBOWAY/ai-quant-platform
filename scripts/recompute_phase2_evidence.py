#!/usr/bin/env python3
"""Read saved real evidence; write an isolated historical-research receipt.

No provider model, order submission, official journal, canonical trial write,
gate switch, or deployment operation exists in this script. Random controls use
the real BacktestEngine and its cash-constrained BrokerSimulator. Scope is the
frozen 24-stock study universe, not a point-in-time broad-market universe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig, TargetWeight
from quant_system.research.active_metrics import (
    MIN_OBSERVATIONS,
    active_metrics,
    sleeve_active_metrics,
)
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.active_returns import recompute_active_returns
from quant_system.research.gate_v2.control import random_control_v2
from quant_system.research.gate_v2.dsr_v2 import evaluate_dsr_v2
from quant_system.research.gate_v2.family import project_family_v2
from quant_system.research.gate_v2.health_v2 import health_checks_v2
from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG
from quant_system.research.reference_backtests import (
    COMMISSION_BPS,
    INITIAL_CASH,
    SLIPPAGE_BPS,
    _costs,
    _prepare_prices,
)
from quant_system.research.trials import (
    ResearchTrial,
    TrialsLedger,
    deflated_sharpe_ratio,
    performance_from_daily_returns,
    universe_digest,
)

PROFILE = "stocks_momentum_12_2"
ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        handle.write("\n")


def append_index(path, value):
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class ScheduledTargets:
    def __init__(self, schedule):
        self.schedule = schedule

    def target_weights(self, timestamp):
        targets = self.schedule.get(pd.Timestamp(timestamp))
        if targets is None:
            return None
        return [
            TargetWeight(timestamp=timestamp, symbol=symbol, target_weight=weight)
            for symbol, weight in sorted(targets.items())
        ]


def random_schedule(rng, profile):
    schedule, records = {}, []
    for signal in profile["signals"]:
        eligible = sorted(signal["eligible_symbols"])
        trade, decision = pd.Timestamp(signal["trade_date"], tz="UTC"), signal["signal_date"]
        if trade.date().isoformat() <= decision:
            raise ValueError("signal_must_precede_fill")
        if signal["ready"] and len(eligible) >= 5:
            selected = sorted(rng.choice(eligible, size=5, replace=False).tolist())
            targets = {symbol: 0.2 for symbol in selected}
        else:
            targets = {}
        schedule[trade] = targets
        records.append(
            {
                "signal_date": decision,
                "trade_date": trade.date().isoformat(),
                "eligible_symbols": eligible,
                "targets": targets,
            }
        )
    return schedule, records


def run_variant(index, frame, schedule, schedule_records, profile, output, identity):
    started = time.monotonic()
    variant = Path(output) / f"variant-{index:04d}"
    variant.mkdir()
    config = BacktestConfig(
        initial_cash=INITIAL_CASH, commission_bps=COMMISSION_BPS, slippage_bps=SLIPPAGE_BPS
    )
    write_json(variant / "schedule.json", schedule_records)
    write_json(variant / "config.json", config.model_dump(mode="json"))
    result = BacktestEngine(config).run(frame, ScheduledTargets(schedule))
    if (result.equity_curve.cash < -1e-7).any() or (result.positions.quantity < -1e-10).any():
        raise ValueError("engine_cash_or_long_only_violation")
    for name in ("equity_curve", "trade_blotter", "orders", "positions", "attribution"):
        getattr(result, name).to_parquet(variant / f"{name}.parquet", index=False)
    benchmark = pd.DataFrame(profile["curve"])[["date", "benchmark"]]
    benchmark["timestamp"] = pd.to_datetime(benchmark.pop("date"), utc=True)
    curve = result.equity_curve[["timestamp", "equity"]].merge(
        benchmark, on="timestamp", validate="one_to_one"
    )
    if len(curve) != len(result.equity_curve):
        raise ValueError("benchmark_calendar_mismatch")
    rows = [
        {
            "date": row.timestamp.date().isoformat(),
            "equity": float(row.equity),
            "benchmark": float(row.benchmark),
        }
        for row in curve.itertuples(index=False)
    ]
    write_json(
        variant / "platform-result.json",
        {
            "curve": rows,
            "evaluation_initial_cash": INITIAL_CASH,
            "scope": "random_control_calibration",
        },
    )
    returns = curve.equity.div(curve.equity.shift(1).fillna(INITIAL_CASH)).sub(1).tolist()
    definition_digest = _hash({"generator": identity, "schedule": schedule_records})
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject=f"random-top5-{index:04d}",
        universe=profile["profile"]["peer_symbols"],
        daily_returns=returns,
        window_start=profile["start"],
        window_end=profile["end"],
        source="futu_saved_prices",
        metadata={
            "run_id": "phase2-null-" + definition_digest,
            "strategy_definition_digest": definition_digest,
            "equity_curve_digest": _hash(rows),
            "scope_tag": "random_control_calibration",
            "canonical_family_member": False,
            "source_identity": identity,
        },
    )
    receipt = {
        "index": index,
        "status": "completed",
        "elapsed_seconds": time.monotonic() - started,
        "metrics": result.metrics.model_dump(mode="json"),
        "costs": _costs(result.trade_blotter),
        "minimum_cash": float(result.equity_curve.cash.min()),
        "curve_digest": _hash(rows),
        "definition_digest": definition_digest,
        "trial": trial.model_dump(mode="json"),
        "files": {path.name: sha256(path) for path in sorted(variant.iterdir())},
    }
    write_json(variant / "receipt.json", receipt)
    return receipt


def saved_inputs(mirror):
    latest_path = mirror / "data/strategy_studies/latest.json"
    document = json.loads(latest_path.read_text())
    profile = next(row for row in document["results"] if row["profile"]["id"] == PROFILE)
    prices_path = mirror / "data/strategy_studies/runs" / document["run_id"] / "prices.parquet"
    prices = _prepare_prices(pd.read_parquet(prices_path))
    symbols = profile["profile"]["peer_symbols"]
    frame = prices[
        prices.symbol.isin(symbols)
        & (prices.timestamp >= pd.Timestamp(profile["start"], tz="UTC"))
        & (prices.timestamp <= pd.Timestamp(profile["end"], tz="UTC"))
    ]
    if len(symbols) != 24 or set(frame.provider) != {"futu"}:
        raise ValueError("frozen_24_stock_real_futu_scope_required")
    counts = frame.groupby("timestamp").symbol.nunique()
    if not counts.eq(24).all():
        raise ValueError("missing_prices_in_frozen_universe")
    identity = {
        "latest_path": str(latest_path),
        "latest_sha256": sha256(latest_path),
        "prices_path": str(prices_path),
        "prices_sha256": sha256(prices_path),
        "profile_digest": _hash(profile),
        "script_sha256": sha256(__file__),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [
                ROOT / "src/quant_system/backtest/engine.py",
                ROOT / "src/quant_system/backtest/broker.py",
                ROOT / "src/quant_system/backtest/order_generation.py",
                ROOT / "src/quant_system/backtest/portfolio.py",
                ROOT / "src/quant_system/research/active_metrics.py",
            ]
        },
    }
    return document, profile, frame, identity


def get_json(base_url, route):
    if base_url not in ("http://127.0.0.1:8765", "http://localhost:8765"):
        raise ValueError("readonly_local_api_only")
    with urllib.request.urlopen(base_url + route, timeout=30) as response:
        return json.load(response)


def reoutput_studies(document, output):
    directory = output / "studies"
    directory.mkdir()
    summaries = []
    for result in document["results"]:
        profile_id = result["profile"]["id"]
        entry = {
            "profile_id": profile_id,
            "original_status": result["status"],
            "old_metrics": result.get("metrics"),
            "old_active_metrics": result.get("active_metrics"),
            "source_result_digest": _hash(result),
            "evaluation_only": True,
            "new_research_trial": False,
            "initial_cash": INITIAL_CASH,
        }
        try:
            curve = pd.DataFrame(result["curve"]).rename(columns={"date": "timestamp"})
            curve["timestamp"] = pd.to_datetime(curve.timestamp, utc=True)
            entry["active_metrics"] = active_metrics(
                curve,
                initial_cash=INITIAL_CASH,
                benchmark_symbol=result["profile"]["benchmark_symbol"],
                include_peer=True,
            )
            entry["status"] = entry["active_metrics"]["status"]
        except Exception as exc:
            entry.update(status="unavailable", reason=str(exc), error_type=type(exc).__name__)
        write_json(directory / f"{profile_id}.json", entry)
        summaries.append(
            {
                "profile_id": profile_id,
                "status": entry["status"],
                "n_observations": entry.get("active_metrics", {}).get("n_observations"),
            }
        )
    return summaries


def seed_sleeve_observations(rows, detail, benchmark_prices):
    """Use persisted allocated capital before the first fill, never a guessed 10k."""
    from quant_system.d34.hung_sleeve_effect import _allocation_session

    unavailable = {
        "status": "unavailable",
        "rows": [],
        "reason": "initial_funding_basis_unavailable",
    }
    if not rows:
        return unavailable
    capital = detail["sleeve"].get("initial_allocated_cash")
    if not isinstance(capital, (int, float)) or not np.isfinite(capital) or capital <= 0:
        return unavailable
    first = rows[0]
    allocation_day = _allocation_session(datetime.fromisoformat(detail["sleeve"]["created_at"]))
    filled_days = [
        row["target_date"]
        for row in detail.get("executions", [])
        if row.get("status") == "filled" and row.get("fills")
    ]
    if first["date"] == allocation_day and not filled_days and first["sleeve_equity"] == capital:
        return {
            "status": "ready",
            "rows": rows,
            "seed_added": False,
            "initial_capital": capital,
            "initial_nav_source": "persisted_sleeve.initial_allocated_cash_cash_only",
        }
    if allocation_day >= first["date"] or any(day <= allocation_day for day in filled_days):
        return unavailable
    if benchmark_prices is None:
        return {**unavailable, "reason": "initial_benchmark_mark_unavailable"}
    prices = benchmark_prices.copy()
    if (
        set(prices.provider) != {"futu"}
        or set(prices.price_adjustment) != {"qfq"}
        or set(prices.symbol) != {"SPY"}
    ):
        return {**unavailable, "reason": "initial_benchmark_provenance_unverified"}
    prices["date"] = pd.to_datetime(prices.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    if prices.date.duplicated().any():
        return {**unavailable, "reason": "duplicate_benchmark_marks"}
    close = prices.set_index("date").close
    if allocation_day not in close or not np.isfinite(close[allocation_day]):
        return {**unavailable, "reason": "initial_benchmark_mark_unavailable"}
    for row in rows:
        if row["date"] not in close or not np.isclose(
            close[row["date"]], row["spy_close"], rtol=1e-10
        ):
            return {**unavailable, "reason": "benchmark_adjustment_basis_mismatch"}
    seed = {
        "date": allocation_day,
        "sleeve_equity": float(capital),
        "spy_close": float(close[allocation_day]),
        "filled": False,
        "source": "persisted_initial_capital_before_first_fill",
    }
    return {
        "status": "ready",
        "rows": [seed, *rows],
        "seed_added": True,
        "initial_capital": capital,
        "initial_nav_source": "persisted_sleeve.initial_allocated_cash",
        "first_observed_return": float(first["sleeve_equity"] / capital - 1),
    }


def reoutput_sleeves(api_url, output, benchmark_path=None):
    from quant_system.d34.hung_sleeve_effect import _allocation_session

    directory = output / "sleeves"
    directory.mkdir()
    listing = get_json(api_url, "/api/paper/strategy-sleeves")
    effect = get_json(api_url, "/api/paper/strategy-sleeves/hung-effect")
    write_json(directory / "list-snapshot.json", listing)
    write_json(directory / "aggregate-effect-snapshot.json", effect)
    running = [row for row in listing["sleeves"] if row["status"] == "running"]
    details = {}
    for sleeve in running:
        sleeve_id = sleeve["sleeve_id"]
        details[sleeve_id] = get_json(api_url, "/api/paper/strategy-sleeves/" + sleeve_id)
        write_json(directory / f"{sleeve_id}-detail-snapshot.json", details[sleeve_id])
    cash_only = [
        doc
        for doc in details.values()
        if not doc["lots"]
        and not doc["executions"]
        and doc["sleeve"]["cash"] == doc["sleeve"]["initial_allocated_cash"]
    ]
    allocations = {
        sid: _allocation_session(datetime.fromisoformat(doc["sleeve"]["created_at"]))
        for sid, doc in details.items()
    }
    decomposition_ok = len(running) == 2 and len(cash_only) == 1 and effect.get("hung_count") == 2
    rows_by_sleeve = {sid: [] for sid in details}
    if decomposition_ok:
        cash_doc = cash_only[0]
        cash_sid, cash_value = cash_doc["sleeve"]["sleeve_id"], cash_doc["sleeve"]["cash"]
        for row in effect["series"]:
            present = [sid for sid, day in allocations.items() if day <= row["date"]]
            expected_funding = sum(
                details[sid]["sleeve"]["initial_allocated_cash"] for sid in present
            )
            if len(present) != row["covered_sleeve_count"] or not np.isclose(
                expected_funding, row["allocated_cash"], atol=1e-8
            ):
                decomposition_ok = False
                break
            for sid in present:
                value = (
                    cash_value
                    if sid == cash_sid
                    else row["sleeve_equity"] - (cash_value if cash_sid in present else 0)
                )
                rows_by_sleeve[sid].append(
                    {
                        "date": row["date"],
                        "sleeve_equity": value,
                        "spy_close": row["spy_close"],
                        "filled": any(
                            execution.get("status") == "filled"
                            and execution.get("target_date") == row["date"]
                            for execution in details[sid]["executions"]
                        ),
                    }
                )
    summaries = []
    benchmark_prices, benchmark_binding = None, None
    if benchmark_path is not None:
        benchmark_path = Path(benchmark_path)
        metadata_path = benchmark_path.with_suffix(".metadata.json")
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("sha256") != sha256(benchmark_path):
            raise ValueError("benchmark_file_metadata_digest_mismatch")
        benchmark_prices = pd.read_parquet(benchmark_path)
        benchmark_binding = {
            "path": str(benchmark_path),
            "sha256": sha256(benchmark_path),
            "metadata_sha256": sha256(metadata_path),
        }
    for sid in details:
        observed_rows = rows_by_sleeve[sid] if decomposition_ok else []
        funding = seed_sleeve_observations(observed_rows, details[sid], benchmark_prices)
        rows = funding["rows"]
        metrics = sleeve_active_metrics(
            rows,
            unavailable_reason=(
                "per_sleeve_nav_not_resolvable_from_aggregate_api"
                if not decomposition_ok
                else funding.get("reason")
                if funding["status"] != "ready"
                else None
            ),
        )
        n = metrics["n_observations"]
        document = {
            "sleeve_id": sid,
            "schema": "sleeve_reoutput_funding_basis/v2",
            "observed_series_count": len(observed_rows),
            "funding_basis": {key: value for key, value in funding.items() if key != "rows"},
            "benchmark_binding": benchmark_binding,
            "observation_series": rows,
            "active_metrics": metrics,
            "status": "unavailable" if n < MIN_OBSERVATIONS else metrics["status"],
            "reason": funding.get("reason")
            or ("insufficient_observations_126" if n < MIN_OBSERVATIONS else metrics.get("reason")),
            "scope": "descriptive_only_not_significance",
            "decomposition": "verified_cash_only_sleeve_subtraction" if decomposition_ok else None,
            "source_digests": {"aggregate": _hash(effect), "details": _hash(details)},
            "journal_or_cycle_write": False,
        }
        write_json(directory / f"{sid}-active-metrics.json", document)
        summaries.append(
            {
                "sleeve_id": sid,
                "status": document["status"],
                "n_observations": n,
                "reason": document["reason"],
            }
        )
    return summaries


def project_real_families(mirror, output, document, profile):
    directory = output / "families"
    directory.mkdir()
    path = mirror / "data/trials/trials.jsonl"
    raw = path.read_text()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    (directory / "source-trials.jsonl").write_text(raw)
    payloads, files, failures = {}, [], []
    for candidate in sorted(
        (mirror / "data/strategy_library").glob("*/validations/*/platform-result.json")
    ):
        try:
            payload = json.loads(candidate.read_text())
            curve = payload.get("curve")
            if curve:
                key = _hash(curve)
                payloads[key] = payload
                files.append(
                    {"path": str(candidate), "sha256": sha256(candidate), "curve_digest": key}
                )
        except Exception as exc:
            failures.append(
                {"path": str(candidate), "error_type": type(exc).__name__, "reason": str(exc)}
            )

    def resolver(row):
        return payloads.get(row.get("metadata", {}).get("equity_curve_digest"))

    universe_hashes = sorted(
        {row["universe_digest"] for row in rows}
        | {universe_digest(profile["profile"]["peer_symbols"])}
    )
    families = {}
    for key in universe_hashes:
        families[key] = project_family_v2(
            trials_rows=rows, universe_digest=key, curve_resolver=resolver
        )
        write_json(directory / f"{key}.json", families[key])
    index = {
        "source_path": str(path),
        "source_sha256": sha256(path),
        "source_rows": len(rows),
        "validation_files": files,
        "validation_failures": failures,
        "family_scope": "unmodified_v2_membership_projection_over_all_source_rows",
        "families": {
            key: {
                "n_trials": value["n_trials"],
                "trusted": value["trusted"],
                "coverage_shortfall": value["coverage_shortfall"],
                "excluded_reasons": dict(Counter(row["reason"] for row in value["excluded"])),
            }
            for key, value in families.items()
        },
    }
    write_json(directory / "index.json", index)
    return rows, families, index


def classify_variant(receipt, output, family, real_rows, profile):
    path = output / f"variant-{receipt['index']:04d}" / "platform-result.json"
    active = recompute_active_returns(
        json.loads(path.read_text())["curve"], initial_cash=INITIAL_CASH
    )
    dsr = evaluate_dsr_v2(
        active=active, family=family, dsr_min=GATE_V2_CONFIG["dsr_v2_min"], config=GATE_V2_CONFIG
    )
    health = health_checks_v2(active=active, config=GATE_V2_CONFIG)
    digest = universe_digest(profile["profile"]["peer_symbols"])
    old_sharpes = [
        row["sharpe"]
        for row in real_rows
        if row["universe_digest"] == digest
        and row["n_periods"] >= 20
        and row.get("sharpe") is not None
    ]
    performance = performance_from_daily_returns(active["equity_returns"])
    legacy = deflated_sharpe_ratio(
        sharpe=performance["sharpe_period"],
        n_periods=performance["n_periods"],
        skewness=performance["skewness"],
        kurtosis=performance["kurtosis"],
        trial_sharpes=old_sharpes,
    )
    compared = {
        "index": receipt["index"],
        "active": active,
        "legacy_raw_dsr_recomputed": legacy,
        "active_dsr_v2": dsr,
        "health_v2": health,
        "family_trusted": family["trusted"],
        "limited_dsr_health_pass": bool(dsr["passed"] and health["passed"]),
        "full_admission_evaluated": False,
        "switch_authorized": False,
    }
    write_json(path.parent / "gate-comparison.json", compared)
    return compared


def audit_legacy_evidence(mirror, existing, output):
    """Add only exact historical bindings; never mint an old definition from current code."""
    source_rows = [
        json.loads(line)
        for line in (existing / "families/source-trials.jsonl").read_text().splitlines()
        if line
    ]
    studies = json.loads((existing / "saved-study-snapshot.json").read_text())
    profile = next(row for row in studies["results"] if row["profile"]["id"] == PROFILE)
    key = universe_digest(profile["profile"]["peer_symbols"])
    original = json.loads((existing / "families" / f"{key}.json").read_text())
    excluded = {row["trial_id"]: row["reason"] for row in original["excluded"]}
    candidates = {}
    scan_failures = []
    for report_path in sorted((mirror / "data/strategy_studies/runs").glob("*/report.json")):
        try:
            report = json.loads(report_path.read_text())
            prices_path = report_path.parent / "prices.parquet"
            prices_digest = sha256(prices_path)
            if prices_digest != report["source"]["prices_sha256"]:
                raise ValueError("saved_study_prices_digest_mismatch")
            results = list(report.get("results") or []) + list(
                (report.get("discovery") or {}).get("results") or []
            )
            for result in results:
                if not result.get("curve") or not result.get("profile"):
                    continue
                run_id = "recorded-study-" + _hash(
                    {
                        "profile": result["profile"],
                        "prices": prices_digest,
                        "curve": result["curve"],
                    }
                )
                proof = {
                    "binding_type": "exact_ledger_content_addressed_study_id",
                    "report_path": str(report_path),
                    "report_sha256": sha256(report_path),
                    "original_frozen_profile_digest": _hash(result["profile"]),
                    "prices_sha256": prices_digest,
                    "curve_digest": _hash(result["curve"]),
                    "run_id_recomputed": run_id,
                }
                candidates.setdefault(run_id, []).append((result, proof))
        except Exception as exc:
            scan_failures.append(
                {"path": str(report_path), "reason": str(exc), "error_type": type(exc).__name__}
            )
    for result_path in sorted(
        (mirror / "data/strategy_library").glob("*/validations/*/platform-result.json")
    ):
        try:
            result = json.loads(result_path.read_text())
            validation_path, qlib_path = (
                result_path.parent / "validation.json",
                result_path.parent / "qlib-replay.json",
            )
            validation, qlib = (
                json.loads(validation_path.read_text()),
                json.loads(qlib_path.read_text()),
            )
            prices_digest = sha256(result_path.parent / "prices.parquet")
            definition = result.get("definition_digest")
            if (
                validation.get("definition_digest") != definition
                or qlib.get("definition_digest") != definition
                or qlib.get("status") != "available"
                or qlib.get("source", {}).get("platform_result_sha256") != sha256(result_path)
                or qlib.get("source", {}).get("prices_sha256") != prices_digest
            ):
                raise ValueError("legacy_original_replay_binding_unverified")
            cash = result.get("evaluation_initial_cash")
            if cash != 10000:
                raise ValueError("legacy_bound_validation_cash_not_verified")
            content_id = "definition-validation-" + _hash(
                {
                    "definition": definition,
                    "prices": prices_digest,
                    "start": result["start"],
                    "end": result["end"],
                    "cash": 10000,
                }
            )
            proof = {
                "binding_type": "original_qlib_file_hash_plus_validation_receipt",
                "platform_result_path": str(result_path),
                "platform_result_sha256": sha256(result_path),
                "validation_path": str(validation_path),
                "validation_sha256": sha256(validation_path),
                "qlib_receipt_sha256": sha256(qlib_path),
                "prices_sha256": prices_digest,
                "definition_digest": definition,
                "curve_digest": _hash(result["curve"]),
                "original_validation_run_id": validation.get("run_id"),
                "content_addressed_run_id": content_id,
            }
            candidates.setdefault(content_id, []).append((result, proof))
            if validation.get("run_id") == result_path.parent.name:
                candidates.setdefault(validation["run_id"], []).append((result, proof))
        except Exception as exc:
            scan_failures.append(
                {"path": str(result_path), "reason": str(exc), "error_type": type(exc).__name__}
            )
    mapping, recovered, unresolved = [], [], []
    for row in source_rows:
        if row["trial_id"] not in excluded:
            continue
        metadata = row.get("metadata") or {}
        entry = {
            name: row.get(name)
            for name in (
                "trial_id",
                "subject",
                "source",
                "n_periods",
                "window_start",
                "window_end",
                "universe_digest",
            )
        }
        entry.update(
            original_exclusion_reason=excluded[row["trial_id"]],
            run_id=metadata.get("run_id"),
            metadata_keys=sorted(metadata),
            status="unrecoverable",
            reason="no_exact_original_artifact_and_receipt_binding",
        )
        matches = candidates.get(metadata.get("run_id"), [])
        for result, proof in matches:
            values = recompute_active_returns(
                result["curve"], initial_cash=result.get("evaluation_initial_cash", INITIAL_CASH)
            )
            total = performance_from_daily_returns(values["equity_returns"])
            if (
                values["n_periods"] != row["n_periods"]
                or values["start"] != row["window_start"]
                or values["end"] != row["window_end"]
                or result.get("source") != row["source"]
                or result["profile"]["id"] != row["subject"]
                or universe_digest(result["profile"]["symbols"]) != row["universe_digest"]
                or not np.isclose(total["total_return"], row["total_return"], rtol=1e-9, atol=1e-12)
                or (
                    metadata.get("strategy_definition_digest") is not None
                    and metadata["strategy_definition_digest"] != result.get("definition_digest")
                )
            ):
                entry["reason"] = "exact_id_found_but_trial_facts_mismatch"
                continue
            entry.update(
                status="recovered_in_independent_adapter",
                reason=None,
                evidence=proof,
                active_returns_digest=values["returns_digest"],
                raw_trial_metadata_unchanged=True,
                canonical_definition_minted=False,
            )
            member = {
                "trial_id": row["trial_id"],
                "run_id": metadata["run_id"],
                "n_periods": values["n_periods"],
                "recomputed_sharpe": performance_from_daily_returns(values["active_returns"])[
                    "sharpe_period"
                ],
                "curve_digest_verified": True,
                "legacy_adapter_evidence": proof,
            }
            recovered.append(member)
            write_json(
                output / f"{row['trial_id']}-bound-curve.json",
                {
                    "original_trial_id": row["trial_id"],
                    "curve": result["curve"],
                    "evaluation_initial_cash": result.get("evaluation_initial_cash", INITIAL_CASH),
                    "evidence": proof,
                },
            )
            break
        if entry["status"] == "unrecoverable":
            unresolved.append(
                {
                    "trial_id": row["trial_id"],
                    "run_id": metadata.get("run_id"),
                    "reason": entry["reason"],
                }
            )
        mapping.append(entry)
    members = sorted([*original["members"], *recovered], key=lambda row: row["trial_id"])
    if len({row["trial_id"] for row in members}) != len(members):
        raise ValueError("legacy_adapter_duplicate_member")
    original_ids = {row["trial_id"] for row in original["members"] + original["excluded"]}
    adapted_ids = {row["trial_id"] for row in members + unresolved}
    if original_ids != adapted_ids:
        raise ValueError("legacy_adapter_family_may_not_drop_trials")
    adapted = {
        **original,
        "members": members,
        "excluded": unresolved,
        "n_trials": len(members),
        "coverage_shortfall": len(unresolved) / len(original_ids),
        "trusted": not unresolved,
        "scope": "legacy_evidence_adapter_review_only",
        "canonical_writes": False,
        "switch_authorized": False,
        "recomputed_sharpes": [row["recomputed_sharpe"] for row in members],
        "membership_rule_extension": "original_content_address_or_original_qlib_hash_bound_receipt",
        "family_digest": _hash(
            {"base": original["family_digest"], "members": members, "excluded": unresolved}
        ),
    }
    write_json(output / "excluded-trial-mapping.json", mapping)
    write_json(output / "adapted-family.json", adapted)
    write_json(
        output / "summary.json",
        {
            "old_n_members": original["n_trials"],
            "new_n_members": len(members),
            "old_excluded_count": len(excluded),
            "new_excluded_count": len(unresolved),
            "family_trial_set_unchanged": True,
            "recovered": len(recovered),
            "unrecoverable": unresolved,
            "source_ledger_sha256": sha256(existing / "families/source-trials.jsonl"),
            "script_sha256": sha256(__file__),
            "scan_failures": scan_failures,
            "trusted": adapted["trusted"],
            "canonical_writes": False,
            "switch_authorized": False,
        },
    )
    (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(
        json.dumps(
            {
                "legacy_recovered": len(recovered),
                "unrecoverable": len(unresolved),
                "family_n": len(members),
                "trusted": adapted["trusted"],
            }
        ),
        flush=True,
    )


def recalibrate_saved_variants(existing, family_path, output):
    """Re-evaluate saved engine curves with an additive family; do not rerun trials."""
    family = json.loads(family_path.read_text())
    saved_identity = json.loads((existing / "inputs.json").read_text())
    studies = json.loads((existing / "saved-study-snapshot.json").read_text())
    profile = next(row for row in studies["results"] if row["profile"]["id"] == PROFILE)
    samples, verdicts = [], []
    for index in range(saved_identity["n_variants"]):
        directory = existing / f"variant-{index:04d}"
        receipt = json.loads((directory / "receipt.json").read_text())
        path = directory / "platform-result.json"
        if sha256(path) != receipt["files"]["platform-result.json"]:
            raise ValueError("saved_engine_curve_file_changed")
        payload = json.loads(path.read_text())
        if _hash(payload["curve"]) != receipt["curve_digest"]:
            raise ValueError("saved_engine_curve_content_changed")
        active = recompute_active_returns(
            payload["curve"], initial_cash=payload["evaluation_initial_cash"]
        )
        dsr = evaluate_dsr_v2(
            active=active,
            family=family,
            dsr_min=GATE_V2_CONFIG["dsr_v2_min"],
            config=GATE_V2_CONFIG,
        )
        health = health_checks_v2(active=active, config=GATE_V2_CONFIG)
        samples.append(active)
        verdicts.append(
            {
                "index": index,
                "curve_digest": receipt["curve_digest"],
                "active_dsr_v2": dsr,
                "health_v2": health,
                "limited_dsr_health_pass": dsr["passed"] and health["passed"],
            }
        )
    summary = random_control_v2(
        universe=profile["profile"]["peer_symbols"],
        eval_window={"start": profile["start"], "end": profile["end"]},
        curve_factory=lambda rng, index: samples[index],
        family=family,
        n_variants=len(samples),
        seed=saved_identity["seed"],
        artifact_hashes={
            "family": sha256(family_path),
            "original_inputs": sha256(existing / "inputs.json"),
            "original_research_index": sha256(existing / "research_index/trials.jsonl"),
            "script": sha256(__file__),
        },
    )
    summary.update(
        scope="DSR_and_health_only_not_full_admission",
        universe_scope="saved_static_24_stock_study_only",
        source_evidence_dir=str(existing),
        source_family_path=str(family_path),
        family_trusted=family["trusted"],
        new_engine_runs=0,
        new_research_trials=0,
        original_engine_trials=len(samples),
        false_pass_requirement_met=summary["false_pass_rate"] <= 0.05,
        dsr_value_min=min(row["active_dsr_v2"]["value"] for row in verdicts),
        dsr_value_max=max(row["active_dsr_v2"]["value"] for row in verdicts),
        dsr_paths=dict(Counter(row["active_dsr_v2"]["path"] for row in verdicts)),
        dsr_reasons=dict(Counter(str(row["active_dsr_v2"]["reason"]) for row in verdicts)),
        switch_authorized=False,
        canonical_writes=False,
    )
    write_json(output / "random-control-v2.json", summary)
    write_json(output / "all-verdicts.json", verdicts)
    (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(
        json.dumps(
            {
                "reused_curves": len(samples),
                "family_n": family["n_trials"],
                "false_pass_rate": summary["false_pass_rate"],
                "dsr_value_max": summary["dsr_value_max"],
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--n-variants", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument(
        "--mode",
        choices=("pilot", "full", "legacy-audit", "recalibrate", "sleeves-only"),
        default="full",
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8765")
    parser.add_argument("--existing-evidence-dir", type=Path)
    parser.add_argument("--family-path", type=Path)
    parser.add_argument("--benchmark-prices", type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.is_relative_to(args.mirror_root.resolve()):
        parser.error("output may not be in deployment mirror")
    if args.mode == "full" and args.n_variants < 500:
        parser.error("full calibration needs at least 500 variants")
    if not 1 <= args.n_variants <= 5000:
        parser.error("variant budget must be in [1, 5000]")
    output.mkdir(parents=True, exist_ok=False)
    if args.mode == "sleeves-only":
        summary = reoutput_sleeves(args.api_url, output, args.benchmark_prices)
        write_json(
            output / "summary.json",
            {
                "schema": "sleeve_reoutput_funding_basis/v2",
                "sleeves": summary,
                "script_sha256": sha256(__file__),
                "canonical_writes": False,
            },
        )
        (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
        return 0
    if args.mode == "recalibrate":
        if args.existing_evidence_dir is None or args.family_path is None:
            parser.error("recalibrate requires --existing-evidence-dir and --family-path")
        recalibrate_saved_variants(
            args.existing_evidence_dir.resolve(), args.family_path.resolve(), output
        )
        return 0
    if args.mode == "legacy-audit":
        if args.existing_evidence_dir is None:
            parser.error("legacy-audit requires --existing-evidence-dir")
        audit_legacy_evidence(
            args.mirror_root.resolve(), args.existing_evidence_dir.resolve(), output
        )
        return 0
    document, profile, frame, identity = saved_inputs(args.mirror_root.resolve())
    identity.update(
        seed=args.seed,
        n_variants=args.n_variants,
        generator="numpy.random.Generator(PCG64), sequential choices",
    )
    for source in sorted((ROOT / "src/quant_system/research/gate_v2").glob("*.py")):
        identity["source_hashes"][str(source.relative_to(ROOT))] = sha256(source)
    write_json(output / "inputs.json", identity)
    (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    write_json(output / "saved-study-snapshot.json", document)
    sections, failures = {}, []
    family, real_rows = None, []
    if args.mode == "full":
        for name, function in (
            ("studies", lambda: reoutput_studies(document, output)),
            ("sleeves", lambda: reoutput_sleeves(args.api_url, output, args.benchmark_prices)),
        ):
            try:
                sections[name] = function()
                print(json.dumps({"section": name, "result": sections[name]}), flush=True)
            except Exception as exc:
                failure = {"section": name, "error_type": type(exc).__name__, "reason": str(exc)}
                failures.append(failure)
                write_json(output / f"{name}-failure.json", failure)
        try:
            real_rows, families, family_index = project_real_families(
                args.mirror_root.resolve(), output, document, profile
            )
            family = families[universe_digest(profile["profile"]["peer_symbols"])]
            sections["families"] = family_index
            print(
                json.dumps(
                    {
                        "section": "family",
                        "source_rows": len(real_rows),
                        "n_trials": family["n_trials"],
                        "trusted": family["trusted"],
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            failure = {"section": "families", "error_type": type(exc).__name__, "reason": str(exc)}
            failures.append(failure)
            write_json(output / "families-failure.json", failure)
    ledger = TrialsLedger(output / "research_index")
    rng = np.random.default_rng(args.seed)
    receipts, comparisons = [], []
    for index in range(args.n_variants):
        schedule, records = random_schedule(rng, profile)
        try:
            receipt = run_variant(index, frame, schedule, records, profile, output, identity)
            ledger.append(ResearchTrial.model_validate(receipt["trial"]))
            if family is not None:
                try:
                    comparisons.append(
                        classify_variant(receipt, output, family, real_rows, profile)
                    )
                except Exception as exc:
                    failure = {
                        "section": "comparison",
                        "index": index,
                        "error_type": type(exc).__name__,
                        "reason": str(exc),
                    }
                    failures.append(failure)
                    write_json(output / f"variant-{index:04d}-comparison-failure.json", failure)
        except Exception as exc:
            receipt = {
                "index": index,
                "status": "failed",
                "error_type": type(exc).__name__,
                "reason": str(exc),
            }
            write_json(output / f"variant-{index:04d}-failure.json", receipt)
            ledger.append(
                ResearchTrial.skipped(
                    kind="platform_backtest",
                    subject=f"random-top5-{index:04d}-failed",
                    universe=profile["profile"]["peer_symbols"],
                    reason=str(exc),
                    source="phase2_random_control",
                    metadata={
                        "run_id": (
                            "phase2-null-failed-"
                            + identity["script_sha256"]
                            + f"-{args.seed}-{index}"
                        ),
                        "scope_tag": "random_control_calibration",
                        "failure": receipt,
                    },
                )
            )
        append_index(output / "research-index.jsonl", receipt)
        receipts.append(receipt)
        if index % 25 == 0 or index == args.n_variants - 1 or receipt["status"] != "completed":
            print(
                json.dumps(
                    {
                        key: receipt.get(key)
                        for key in ("index", "status", "elapsed_seconds", "reason")
                    }
                ),
                flush=True,
            )
    if args.mode == "full" and family is not None and len(comparisons) == args.n_variants:
        control = random_control_v2(
            universe=profile["profile"]["peer_symbols"],
            eval_window={"start": profile["start"], "end": profile["end"]},
            curve_factory=lambda rng, index: comparisons[index]["active"],
            family=family,
            n_variants=args.n_variants,
            seed=args.seed,
            artifact_hashes={
                "prices": identity["prices_sha256"],
                "script": identity["script_sha256"],
            },
        )
        control.update(
            universe_scope="saved_static_24_stock_study_only",
            scope="DSR_and_health_only_not_full_admission",
            family_trusted=family["trusted"],
            coverage_shortfall=family["coverage_shortfall"],
            runtime_engine="quant_system.backtest.engine.BacktestEngine",
            commission_bps=COMMISSION_BPS,
            slippage_bps=SLIPPAGE_BPS,
            no_leverage=True,
            switch_authorized=False,
            false_pass_requirement_met=bool(control["false_pass_rate"] <= 0.05),
            missing_full_gate_checks=[
                "upgrade_target",
                "correlation_and_residual_controls",
                "full_data_quality_and_sleeve_specific_admission",
            ],
        )
        write_json(output / "random-control-v2.json", control)
        sections["random_control"] = control
        metrics = pd.DataFrame(
            [
                {
                    "index": row["index"],
                    **{
                        key: value
                        for key, value in row["metrics"].items()
                        if isinstance(value, (float, int))
                    },
                }
                for row in receipts
            ]
        )
        metrics.to_csv(output / "all-random-metrics.csv", index=False)
        sections["random_distribution"] = (
            metrics.drop(columns="index").quantile([0.05, 0.25, 0.5, 0.75, 0.95]).to_dict()
        )
        sections["old_new_recomputed_comparison"] = {
            "legacy_raw_dsr_passes": sum(
                row["legacy_raw_dsr_recomputed"]["passed"] for row in comparisons
            ),
            "active_dsr_passes": sum(row["active_dsr_v2"]["passed"] for row in comparisons),
            "dsr_and_health_passes": sum(row["limited_dsr_health_pass"] for row in comparisons),
            "historical_saved_verdicts_overwritten": False,
        }
    write_json(
        output / "summary.json",
        {
            "identity": identity,
            "sections": sections,
            "completed_variants": sum(row["status"] == "completed" for row in receipts),
            "failed_variants": [row for row in receipts if row["status"] != "completed"],
            "section_failures": failures,
            "universe_scope": "saved_static_24_stock_study_only",
            "canonical_writes": False,
            "switch_authorized": False,
        },
    )
    return int(bool(failures) or any(row["status"] != "completed" for row in receipts))


if __name__ == "__main__":
    raise SystemExit(main())
