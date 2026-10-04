"""Re-run the fixed 500 random Top5 controls on the separately frozen current panel.

Only repository-owned fixed functions are imported. No payload script, provider,
model, formal ledger, account or intake is invoked. The original 09-08 controls
are never extended or overwritten. All new engine outputs and failures remain.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.research.admission_qualifier import CONTROL_SYMBOLS
from quant_system.research.evaluation_service import _hash
from quant_system.research.profile_backtests import run_profile
from quant_system.research.trials import ResearchTrial, TrialsLedger

ROOT = Path(__file__).resolve().parents[1]
CONTROL_VERSION = "futu24-current-20260920"
FAMILY_LEDGER_SHA = "cb4f3939bd350636037a2c83d49447c5c17209e5770f4d3d71390cc4827f5628"
SEED, N_VARIANTS = 20260920, 500


@lru_cache
def _repo_script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location("phase2_fixed_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engine_driver():
    return _repo_script("recompute_phase2_evidence.py")


def run_controls(manifest_path, expected_sha, family_ledger, output, *, probe_one=False):
    inputs = _repo_script("prepare_current_phase2_inputs.py")
    driver = engine_driver()
    manifest_path, family_ledger, output = (
        Path(manifest_path).resolve(),
        Path(family_ledger).resolve(),
        Path(output).resolve(),
    )
    if output.is_relative_to(manifest_path.parent) or manifest_path.parent.is_relative_to(output):
        raise ValueError("control_output_must_be_separate_from_inputs")
    prices, manifest = inputs.read_frozen_inputs(manifest_path, expected_sha)
    from quant_system.research.admission_dataset_20260924 import DATASET as SEPTEMBER24

    control_version = SEPTEMBER24 if manifest["dataset"] == SEPTEMBER24 else CONTROL_VERSION
    if driver.sha256(family_ledger) != FAMILY_LEDGER_SHA:
        raise ValueError("frozen_control_family_changed")
    profile = run_profile(
        prices,
        "stocks_momentum_12_2",
        start=manifest["requested_start"],
        end=manifest["requested_end"],
    )
    if profile["status"] != "available":
        raise ValueError("current_control_profile_unavailable:" + str(profile.get("reason")))
    if (
        profile["profile"]["peer_symbols"] != CONTROL_SYMBOLS
        or profile["start"] != manifest["effective_start"]
        or profile["end"] != manifest["effective_end"]
    ):
        raise ValueError("current_control_profile_scope_changed")
    count = 1 if probe_one else N_VARIANTS
    output.mkdir(parents=True, exist_ok=False)
    (output / "families").mkdir()
    (output / "families/source-trials.jsonl").write_bytes(family_ledger.read_bytes())
    document = {
        "scope": "fresh_fixed_control_context_not_a_formal_study",
        "results": [profile],
        "source": {
            "provider": "futu",
            "adjustment": "qfq",
            "prices_sha256": manifest["artifacts"]["prices.parquet"]["sha256"],
        },
    }
    driver.write_json(output / "saved-study-snapshot.json", document)
    source_paths = [
        ROOT / "scripts/recompute_phase2_evidence.py",
        Path(__file__),
        *[
            ROOT / "src/quant_system" / name
            for name in (
                "backtest/engine.py",
                "backtest/broker.py",
                "backtest/models.py",
                "backtest/order_generation.py",
                "backtest/portfolio.py",
                "research/profile_backtests.py",
                "research/reference_backtests.py",
                "research/active_metrics.py",
            )
        ],
    ]
    identity = {
        "control_version": control_version,
        "seed": SEED,
        "n_variants": count,
        "generator": "numpy.random.Generator(PCG64), sequential choices",
        "prices_path": str(manifest_path.parent / "prices.parquet"),
        "prices_sha256": manifest["artifacts"]["prices.parquet"]["sha256"],
        "approved_input_manifest": str(manifest_path),
        "approved_input_manifest_sha256": expected_sha,
        "latest_path": str(output / "saved-study-snapshot.json"),
        "latest_sha256": driver.sha256(output / "saved-study-snapshot.json"),
        "profile_digest": _hash(profile),
        "script_sha256": driver.sha256(__file__),
        "engine_driver_sha256": driver.sha256(ROOT / "scripts/recompute_phase2_evidence.py"),
        "source_hashes": {
            str(path.relative_to(ROOT)): driver.sha256(path) for path in source_paths
        },
        "requested_window": {
            "start": manifest["requested_start"],
            "end": manifest["requested_end"],
        },
        "effective_window": {"start": profile["start"], "end": profile["end"]},
        "family_ledger_sha256": FAMILY_LEDGER_SHA,
        "probe_only": probe_one,
        "initial_cash": 100000,
        "capital_authorized": False,
        "formal_trial_writes": False,
        "historical_pit_verified": False,
    }
    driver.write_json(output / "inputs.json", identity)
    (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    frame = driver._prepare_prices(prices)
    frame = frame[
        frame.symbol.isin(CONTROL_SYMBOLS)
        & frame.timestamp.between(
            pd.Timestamp(profile["start"], tz="UTC"), pd.Timestamp(profile["end"], tz="UTC")
        )
    ]
    ledger = TrialsLedger(output / "research_index")
    reference_returns = pd.Series([row["equity"] for row in profile["curve"]]).pct_change(
        fill_method=None
    )
    reference_returns.iloc[0] = profile["curve"][0]["equity"] / 100000 - 1
    ledger.append(
        ResearchTrial.record(
            kind="strategy_replication",
            subject="fixed_control_context_reference",
            universe=CONTROL_SYMBOLS,
            daily_returns=reference_returns.tolist(),
            window_start=profile["start"],
            window_end=profile["end"],
            source="futu_saved_prices",
            metadata={
                "run_id": "control-context-" + _hash(identity),
                "scope_tag": "random_control_calibration",
                "canonical_family_member": False,
                "new_hypothesis": False,
                "role": "fixed_reference_recompute",
            },
        )
    )
    rng = np.random.default_rng(SEED)
    failures, receipts = [], []
    started = time.monotonic()
    for index in range(count):
        schedule, records = driver.random_schedule(rng, profile)
        try:
            receipt = driver.run_variant(index, frame, schedule, records, profile, output, identity)
            ledger.append(ResearchTrial.model_validate(receipt["trial"]))
        except Exception as exc:
            receipt = {
                "index": index,
                "status": "failed",
                "error_type": type(exc).__name__,
                "reason": str(exc),
            }
            driver.write_json(output / f"variant-{index:04d}-failure.json", receipt)
            ledger.append(
                ResearchTrial.skipped(
                    kind="platform_backtest",
                    subject=f"current-control-{index:04d}",
                    universe=CONTROL_SYMBOLS,
                    reason=str(exc),
                    source="phase2_random_control",
                    metadata={
                        "run_id": f"current-control-failed-{expected_sha}-{index}",
                        "scope_tag": "random_control_calibration",
                        "canonical_family_member": False,
                    },
                )
            )
            failures.append(receipt)
        driver.append_index(output / "research-index.jsonl", receipt)
        receipts.append(receipt)
        if index % 25 == 0 or index == count - 1 or receipt["status"] == "failed":
            print(
                json.dumps(
                    {"completed": index + 1, "planned": count, "failures": len(failures)},
                    sort_keys=True,
                ),
                flush=True,
            )
    inputs.read_frozen_inputs(manifest_path, expected_sha)
    if any(
        driver.sha256(path) != identity["source_hashes"][str(path.relative_to(ROOT))]
        for path in source_paths
    ):
        raise ValueError("control_code_changed_during_execution")
    summary = {
        "schema": "phase2_current_control_engine/v1",
        "control_version": control_version,
        "status": "partial" if failures else "completed",
        "n_variants": count,
        "successful": count - len(failures),
        "failures": failures,
        "elapsed_seconds": time.monotonic() - started,
        "probe_only": probe_one,
        "full_gate_evaluated": False,
        "capital_authorized": False,
        "formal_trial_writes": False,
        "local_trial_records": count + 1,
        "extra_reference_logical_attempts": 1,
        "effective_window": identity["effective_window"],
        "source_prices_sha256": identity["prices_sha256"],
    }
    driver.write_json(output / "summary.json", summary)
    files = {
        str(path.relative_to(output)): driver.sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    driver.write_json(output / "artifact-manifest.json", {"files": files})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expect-sha", required=True)
    parser.add_argument("--family-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-one", action="store_true")
    args = parser.parse_args(argv)
    result = run_controls(
        args.manifest, args.expect_sha, args.family_ledger, args.output, probe_one=args.probe_one
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
