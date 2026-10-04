"""Trusted local verification for the finite public_price_pilot/v1 contract.

Only the installed repository's fixed pilot functions run. Package Python is
hashed, never imported or executed. No provider, queue, trial or account writes.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.factors import evaluation
from quant_system.research import wide_universe

METHODS = ("Mom12m", "STreversal", "generic_monthly_realized_volatility")
FILES = {
    "frozen-config.json",
    "future-labels.csv",
    "future-labels.parquet",
    "input-audit.json",
    "input-manifest-snapshot.json",
    "monthly-coverage.csv",
    "monthly-statistics.csv",
    "research-index.jsonl",
    "script-snapshot.py",
    "signals.csv",
    "signals.parquet",
    "summary.json",
}
SHA = re.compile(r"[0-9a-f]{64}")


def file_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def read_json(path):
    return json.loads(
        Path(path).read_bytes(),
        object_pairs_hook=_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )


def _trusted_pilot():
    source = Path(__file__).resolve().parents[3] / "scripts/phase2_public_price_pilot.py"
    spec = importlib.util.spec_from_file_location("_trusted_public_pilot", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trusted_source_identity() -> tuple[dict, dict]:
    pilot = _trusted_pilot()
    resolved = Path(pilot.__file__).resolve()
    try:
        # Repository-relative on purpose: script_sha256 below already binds the
        # content, so binding the checkout directory too would make identical
        # evidence digest differently under every other clone.
        script_path = resolved.relative_to(Path(__file__).resolve().parents[3]).as_posix()
    except ValueError:
        script_path = str(resolved)
    return (
        {
            "script_path": script_path,
            "script_sha256": file_digest(pilot.__file__),
            "loader_sha256": file_digest(wide_universe.__file__),
            "statistics_sha256": file_digest(evaluation.__file__),
            "verifier_sha256": file_digest(__file__),
            "pandas_version": pd.__version__,
        },
        dict(pilot.CONFIG),
    )


def inspect_public_pilot(bundle: str | Path, *, expected_manifest_sha256: str) -> dict:
    root = Path(bundle).resolve()
    if (
        not SHA.fullmatch(expected_manifest_sha256)
        or file_digest(root / "artifact-manifest.json") != expected_manifest_sha256
    ):
        raise ValueError("pilot_manifest_digest_mismatch")
    manifest = read_json(root / "artifact-manifest.json")
    if set(manifest) != FILES or {p.name for p in root.iterdir()} != FILES | {
        "artifact-manifest.json"
    }:
        raise ValueError("pilot_file_closure")
    for name, checksum in manifest.items():
        file = root / name
        if (
            file.is_symlink()
            or not file.is_file()
            or not isinstance(checksum, str)
            or not SHA.fullmatch(checksum)
        ):
            raise ValueError("pilot_invalid_file")
        if file_digest(file) != checksum:
            raise ValueError("pilot_file_digest_mismatch:" + name)
    local, supported = trusted_source_identity()
    frozen = read_json(root / "frozen-config.json")
    for key in ("script_sha256", "loader_sha256", "statistics_sha256", "pandas_version"):
        if frozen.get(key) != local[key]:
            raise ValueError("trusted_source_version_mismatch:" + key)
    if manifest["script-snapshot.py"] != local["script_sha256"]:
        raise ValueError("trusted_source_version_mismatch:script_snapshot")
    if any(frozen.get(k) != v for k, v in supported.items()):
        raise ValueError("unsupported_public_pilot_definition")
    if set(frozen) != set(supported) | {
        "script_sha256",
        "loader_sha256",
        "statistics_sha256",
        "pandas_version",
        "input_manifest_sha256",
    }:
        raise ValueError("unsupported_public_pilot_config_fields")
    if frozen.get("input_manifest_sha256") != manifest["input-manifest-snapshot.json"]:
        raise ValueError("pilot_input_manifest_digest_mismatch")
    return {
        "schema_version": "qs.public_pilot_inspection/v1",
        "source_code_executed": False,
        "manifest_sha256": expected_manifest_sha256,
        "input_manifest_sha256": frozen["input_manifest_sha256"],
        "config_sha256": manifest["frozen-config.json"],
        "trusted_sources": local,
        "files": manifest,
        "config": frozen,
    }


def recompute_monthly_statistics(signals: pd.DataFrame, labels: pd.DataFrame):
    """Re-form groups before joining separately supplied future labels."""
    if "forward_return" in signals or "value" in labels or "factor" in labels:
        raise ValueError("signal_label_separation")
    keys = ["month", "entity_id", "symbol"]
    if (
        set(signals.factor) != set(METHODS)
        or signals.duplicated(keys + ["factor"]).any()
        or labels.duplicated(keys).any()
    ):
        raise ValueError("pilot_duplicate_or_unsupported_series")
    for frame, column in ((signals, "value"), (labels, "forward_return")):
        values = pd.to_numeric(frame[column], errors="raise")
        if np.isinf(values).any():
            raise ValueError("pilot_nonfinite_values")
    known_dates = labels.dropna(subset=["entry_date", "exit_date"])
    if (
        (known_dates.entry_date <= known_dates.signal_date)
        | (known_dates.exit_date <= known_dates.entry_date)
    ).any():
        raise ValueError("pilot_nonfuture_label_dates")
    pilot = _trusted_pilot()
    rows = []
    for (month, method), group in signals.groupby(["month", "factor"], sort=True):
        formed = pilot.assign_quintiles(group.drop(columns=["quintile"], errors="ignore"))
        joined = formed.merge(
            labels[keys + ["forward_return"]], on=keys, how="left", validate="one_to_one"
        )
        rows.append({"month": month, "factor": method, **pilot.month_statistics(joined)})
    monthly = pd.DataFrame(rows)
    calendar = pd.period_range(
        pilot.CONFIG["start_month"], pilot.CONFIG["end_month"], freq="M"
    ).astype(str)
    if set(monthly.month) - set(calendar):
        raise ValueError("pilot_month_outside_frozen_window")
    results = []
    for method in METHODS:
        series = monthly[monthly.factor == method].set_index("month").reindex(calendar)
        item = {
            "factor": method,
            "calendar_months": len(calendar),
            "source_scope": "independent_public_price_method",
        }
        for metric in ("rank_ic", "q5_q1"):
            values = series[metric]
            lag = evaluation.newey_west_lag_rule(len(calendar), horizon=1)
            item[metric] = {
                "mean": float(values.mean()) if values.notna().any() else None,
                "observed_months": int(values.notna().sum()),
                "newey_west": evaluation.newey_west_stats(
                    values, lag=lag, horizon=1, min_observations=60
                ),
            }
        item["coverage"] = {
            "mother_rows": int(series.mother_count.sum()),
            "signal_rows": int(series.signal_count.sum()),
            "paired_rows": int(series.paired_count.sum()),
            "signal_fraction": float(series.signal_count.sum() / series.mother_count.sum()),
            "paired_fraction": float(series.paired_count.sum() / series.mother_count.sum()),
        }
        results.append(item)
    return monthly, results


def _verify_descriptors(value, seen: dict[str, str]) -> None:
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            path, expected = Path(value["path"]), value["sha256"]
            if (
                not path.is_absolute()
                or not isinstance(expected, str)
                or not SHA.fullmatch(expected)
            ):
                raise ValueError("pilot_input_descriptor_invalid")
            actual = file_digest(path)
            if actual != expected:
                raise ValueError("pilot_input_file_digest_mismatch")
            if str(path) in seen:
                return
            seen[str(path)] = actual
            if path.suffix == ".json":
                _verify_descriptors(read_json(path), seen)
        for child in value.values():
            _verify_descriptors(child, seen)
    elif isinstance(value, list):
        for child in value:
            _verify_descriptors(child, seen)


def verify_public_pilot(bundle: str | Path, *, expected_manifest_sha256: str) -> dict:
    """Recompute the exact fixed study from original input prices in a temp directory."""
    root = Path(bundle).resolve()
    bound = inspect_public_pilot(root, expected_manifest_sha256=expected_manifest_sha256)
    inputs = read_json(root / "input-manifest-snapshot.json")
    checked_inputs = {}
    _verify_descriptors(inputs, checked_inputs)
    pilot = _trusted_pilot()
    mismatches = []
    with tempfile.TemporaryDirectory(prefix="public-pilot-verification-") as temporary:
        reproduced = Path(temporary)
        with contextlib.redirect_stdout(io.StringIO()):
            pilot.run(root / "input-manifest-snapshot.json", reproduced)
        # These independent artifacts include signal values and bucket membership;
        # reading only the claimed summary can never pass this verification.
        for name in ("signals.parquet", "future-labels.parquet"):
            try:
                pd.testing.assert_frame_equal(
                    pd.read_parquet(root / name),
                    pd.read_parquet(reproduced / name),
                    check_dtype=False,
                    rtol=1e-12,
                    atol=1e-12,
                )
            except AssertionError:
                mismatches.append(name)
        for name in (
            "signals.csv",
            "future-labels.csv",
            "monthly-statistics.csv",
            "monthly-coverage.csv",
        ):
            try:
                pd.testing.assert_frame_equal(
                    pd.read_csv(root / name),
                    pd.read_csv(reproduced / name),
                    check_dtype=False,
                    rtol=1e-12,
                    atol=1e-12,
                )
            except AssertionError:
                mismatches.append(name)
        for name in ("summary.json", "frozen-config.json", "input-audit.json"):
            if read_json(root / name) != read_json(reproduced / name):
                mismatches.append(name)
        if (root / "research-index.jsonl").read_bytes() != (
            reproduced / "research-index.jsonl"
        ).read_bytes():
            mismatches.append("research-index.jsonl")
        actual_signals = pd.read_parquet(reproduced / "signals.parquet")
        actual_labels = pd.read_parquet(reproduced / "future-labels.parquet")
        input_limitations = read_json(reproduced / "summary.json")["input_limitations"]
        monthly, results = recompute_monthly_statistics(actual_signals, actual_labels)
        try:
            pd.testing.assert_frame_equal(
                monthly,
                pd.read_csv(root / "monthly-statistics.csv"),
                check_dtype=False,
                rtol=1e-12,
                atol=1e-12,
            )
        except AssertionError:
            mismatches.append("independent_monthly_statistics")
    # Bind the bytes actually used and reject concurrent source/input changes.
    if trusted_source_identity()[0] != bound["trusted_sources"]:
        raise ValueError("trusted_sources_changed_during_verification")
    for path, checksum in checked_inputs.items():
        if file_digest(path) != checksum:
            raise ValueError("pilot_input_changed_during_verification")
    inspect_public_pilot(root, expected_manifest_sha256=expected_manifest_sha256)
    for result in results:
        result.update(
            status="failed" if mismatches else "verified",
            definition_digest=digest(
                {"method": result["factor"], "config_sha256": bound["config_sha256"]}
            ),
            input_digest=bound["input_manifest_sha256"],
            completed_attempts=1,
            attempt_scope="same_definition_engineering_replay_not_a_new_trial",
        )
    receipt = {
        "schema_version": "qs.public_pilot_local_evidence/v1",
        "status": "failed" if mismatches else "verified",
        "supported_scope": "public_price_pilot/v1_fixed_three_methods",
        "methods": results,
        "bundle_manifest_sha256": expected_manifest_sha256,
        "config_sha256": bound["config_sha256"],
        "input_manifest_sha256": bound["input_manifest_sha256"],
        "trusted_sources": bound["trusted_sources"],
        "verified_input_files": len(checked_inputs),
        "mismatched_artifacts": sorted(set(mismatches)),
        "source_code_executed": False,
        "local_trusted_functions_executed": True,
        "original_osap_completed": False,
        "admission_authority": False,
        "capital_authority": False,
        "jobs_submitted": 0,
        "input_limitations": input_limitations,
        "contract_limitations": pilot.CONFIG["limitations"],
        "monthly_statistics": monthly.where(pd.notna(monthly), None).to_dict("records"),
    }
    # Pandas float columns retain NaN after where(None); JSON normalizes those to
    # null without changing the measured statistics.
    receipt["monthly_statistics"] = json.loads(
        monthly.to_json(orient="records", double_precision=15)
    )
    receipt["evidence_digest"] = digest(receipt)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_public_pilot(
            args.bundle, expected_manifest_sha256=args.expected_manifest_sha256
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {
            "schema_version": "qs.public_pilot_local_evidence/v1",
            "status": "not_evaluated",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "admission_authority": False,
            "capital_authority": False,
            "source_code_executed": False,
            "jobs_submitted": 0,
        }
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
