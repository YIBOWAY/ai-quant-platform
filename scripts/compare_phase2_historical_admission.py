#!/usr/bin/env python3
"""Read-only old-job comparison using saved curves, not a retrospective authorization.

Outputs are new standalone artifacts. The old job, validation, policy, trial ledger
and account are never changed. Current-family/current-peer counterfactuals are
explicitly NOT historical-time decisions; missing historical peer snapshots and
missing frozen v2 protocols stay unknown. No engine, model, provider or queue runs.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from quant_system.research import admission_v2
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import ArchivedCurveResolver
from quant_system.research.gate_v2.verdict import evaluate_gate_v2, verify_verdict_v2
from quant_system.research.trials import universe_digest
from quant_system.research.validation_receipts import verify_validation_receipt


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)


def compare(data_root: Path, output: Path):
    data_root, output = data_root.resolve(), output.resolve()
    if output.is_relative_to(data_root) or data_root.is_relative_to(output):
        raise ValueError("comparison_output_must_be_independent")
    output.mkdir(parents=True, exist_ok=False)
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=data_root))
    trials, ledger_sha = admission_v2.ledger_snapshot(settings)
    resolver = ArchivedCurveResolver(data_root, trusted_trials=trials)
    book_path = data_root / "assistant_remote/book.json"
    book = json.loads(book_path.read_text())
    peers, peer_identity = admission_v2.peer_snapshot(book)
    inputs = {
        str(book_path): admission_v2.file_sha(book_path),
        str(data_root / "trials/trials.jsonl"): ledger_sha,
    }
    for _, path, digest in resolver.curves.values():
        inputs[str(path)] = digest
    for matches in resolver.legacy_runs.values():
        for _, evidence in matches:
            inputs.update(evidence["files"])
    for candidate in book["candidates"]:
        if candidate.get("status") == "hung":
            inputs[candidate["source_path"]] = admission_v2.file_sha(candidate["source_path"])
    table, failures = [], []
    jobs = sorted((data_root / "research_intake/jobs").glob("*.json"))
    for path in jobs:
        inputs[str(path)] = admission_v2.file_sha(path)
        job = json.loads(path.read_text())
        for result in job.get("results", []):
            row = dict(
                job_id=job["job_id"],
                variant=result["variant"],
                strategy_id=result["strategy_id"],
                saved_job_status=job["status"],
                saved_result_status=result.get("status"),
                saved_v1_passed=None,
                saved_v1_n_trials=None,
                current_counterfactual_tier=None,
                family_members=None,
                legacy_members=None,
                counterfactual_recomputed=False,
                historical_v2_status="not_evaluated",
                capital_authorized=False,
                reason="historical_protocol_and_peer_snapshot_not_frozen",
            )
            record = {
                "schema": "historical_admission_comparison/v1",
                "row": row,
                "scope": "current_family_and_current_peers_counterfactual_only",
                "historical_family_snapshot_available": False,
                "historical_peer_snapshot_available": False,
                "current_peer_digest": peer_identity["digest"],
                "trial_ledger_sha256": ledger_sha,
                "consumer_qualification": "not_evaluated",
                "gate": None,
            }
            try:
                directory = data_root / "strategy_library" / result["strategy_id"]
                validation_path = (
                    directory / "validations" / result["validation"]["run_id"] / "validation.json"
                )
                validation = verify_validation_receipt(
                    validation_path,
                    expected_sha=result["validation_sha256"],
                    definition_digest=result["definition_digest"],
                    require_admission=False,
                )
                for name in (
                    "validation.json",
                    "platform-result.json",
                    "prices.parquet",
                    "qlib-replay.json",
                    "signal-analysis.json",
                ):
                    source = validation_path.parent / name
                    inputs[str(source)] = admission_v2.file_sha(source)
                payload = json.loads((validation_path.parent / "platform-result.json").read_text())
                if payload.get("evaluation_initial_cash") != 10000:
                    raise ValueError("original_initial_cash_not_proven_10000")
                row["saved_v1_passed"] = validation["status"] == "passed"
                row["saved_v1_n_trials"] = (
                    validation.get("gates", {}).get("dsr", {}).get("n_trials")
                )
                increment = None
                plan = next(p for p in job["plans"] if p["variant"] == result["variant"])
                try:
                    increment, increment_binding = admission_v2._increment_context(
                        settings,
                        job,
                        plan,
                        validation,
                        payload,
                    )
                    record["declared_increment"] = increment_binding
                except (ValueError, KeyError, OSError) as exc:
                    record["declared_increment"] = {"status": "not_evaluated", "reason": str(exc)}
                    row["reason"] += ";declared_increment_not_passed"
                gate = evaluate_gate_v2(
                    curve_rows=payload["curve"],
                    initial_cash=payload["evaluation_initial_cash"],
                    universe_digest=universe_digest(payload["profile"]["symbols"]),
                    definition_digest=result["definition_digest"],
                    benchmark_symbol=payload["profile"].get("benchmark_symbol"),
                    trials_rows=trials,
                    curve_resolver=resolver,
                    legacy_resolver=resolver.legacy,
                    hung_sleeves=peers,
                    increment_objective=increment,
                    v1_passed=row["saved_v1_passed"],
                )
                record["gate"] = gate
                row.update(
                    current_counterfactual_tier=gate["tier_recommendation"]["tier"],
                    family_members=len(gate["family"]["members"]),
                    legacy_members=sum(
                        "legacy_evidence" in member for member in gate["family"]["members"]
                    ),
                    counterfactual_recomputed=verify_verdict_v2(
                        gate,
                        trusted_trials=trials,
                        curve_resolver=resolver,
                        legacy_resolver=resolver.legacy,
                    ),
                )
                record["original_validation"] = {
                    "path": str(validation_path),
                    "sha256": result["validation_sha256"],
                }
                record["counterfactual_changed_from_saved_v1"] = row["saved_v1_passed"] != (
                    row["current_counterfactual_tier"] == "T2"
                )
            except (ValueError, OSError, KeyError, TypeError) as exc:
                row["reason"] = str(exc)
                failures.append(
                    {"job_id": job["job_id"], "variant": result["variant"], "reason": str(exc)}
                )
            record["digest"] = _hash(record)
            write(output / "sidecars" / (job["job_id"] + "-" + result["variant"] + ".json"), record)
            table.append(row)
    if any(admission_v2.file_sha(path) != digest for path, digest in inputs.items()):
        raise ValueError("readonly_inputs_changed_during_comparison")
    with (output / "historical-job-comparison.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]) if table else ["job_id"])
        writer.writeheader()
        writer.writerows(table)
    manifest = {
        "schema": "historical_admission_comparison_manifest/v1",
        "code": admission_v2.code_identity(),
        "script_sha256": admission_v2.file_sha(__file__),
        "input_files": inputs,
        "jobs": len(jobs),
        "evaluations": len(table),
        "unique_validations": len(
            {
                result.get("validation_sha256")
                for path in jobs
                for result in json.loads(path.read_text()).get("results", [])
                if result.get("validation_sha256")
            }
        ),
        "original_trials": len(trials),
        "failures": failures,
        "historical_authorization": "not_evaluated",
        "capital_authorized": False,
        "authoritative_source_switch": admission_v2.AUTHORITATIVE_ENABLED,
        "old_artifacts_modified": False,
        "backtests_run": 0,
        "new_trials": 0,
        "counts": dict(Counter(str(row["current_counterfactual_tier"]) for row in table)),
        "counterfactual_recomputed": sum(row["counterfactual_recomputed"] for row in table),
        "limitations": [
            "No original frozen v2 protocol or historical peer-set receipts.",
            "Original n_trials varies by job; current-family math cannot recreate that history.",
            "Current ledger and current peers are counterfactual context, not as-of history.",
            "Current DSR/health random calibration does not qualify this full consumer.",
            "No automatic switch or capital permission is produced.",
        ],
        "artifacts": {
            str(path.relative_to(output)): admission_v2.file_sha(path)
            for path in output.rglob("*")
            if path.is_file()
        },
    }
    write(output / "manifest.json", manifest)
    return {
        key: manifest[key]
        for key in ("jobs", "evaluations", "counterfactual_recomputed", "counts", "failures")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.data_root, args.output), sort_keys=True))
