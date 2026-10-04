#!/usr/bin/env python3
"""Offline wide-universe input audit and scorecards; never fetch or trade."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_system.factors.evaluation import prepare_evaluation_frames
from quant_system.factors.scorecard import build_factor_scorecard_bundle
from quant_system.research.wide_factor_set import (
    REGISTRY_OBJECTS,
    build_wide_factor_values,
    frozen_factor_manifest,
)
from quant_system.research.wide_universe import build_fetch_plan, file_digest, load_wide_universe


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def run_scorecard(input_manifest: Path, factor_manifest: Path, output: Path, *, mode: str) -> dict:
    """Persist one immutable research result, with no provider or account side effects."""
    if output.exists():
        raise FileExistsError(output)
    frozen = frozen_factor_manifest()
    if json.loads(factor_manifest.read_text()) != frozen:
        raise ValueError("frozen_factor_manifest_mismatch")
    inputs = load_wide_universe(input_manifest, mode=mode)
    if mode == "formal" and inputs.manifest["signal_window"] != frozen["signal_window"]:
        raise ValueError("formal_signal_window_mismatch")
    if not inputs.ohlcv.empty:
        observed_days = pd.DatetimeIndex(inputs.ohlcv.timestamp.unique()).sort_values()
        expected_days = inputs.calendar[
            (inputs.calendar >= observed_days.min()) & (inputs.calendar <= observed_days.max())
        ]
        if len(expected_days.difference(observed_days)):
            # The reused engine labels on union-observed dates. Reject a whole-
            # market missing session rather than shifting all labels one day.
            raise ValueError("scorecard_global_session_gap")
    peers = build_wide_factor_values(
        inputs.ohlcv,
        inputs.membership,
        calendar=inputs.calendar,
        factor_ids=[row[0] for row in REGISTRY_OBJECTS],
    )[["symbol", "signal_ts", "factor_id", "value"]]
    scorecard = {
        "schema_version": "factor_scorecard_v1",
        "status": "unavailable",
        "factors": [],
        "provenance": {},
    }
    artifact_parts: dict[str, list[pd.DataFrame]] = {}
    bundle_provenance = {}
    statuses = []
    coverage = []
    for item in frozen["objects"]:
        factor_id = item["factor_id"]
        # The engine expands three horizon frames. Bound memory to one object,
        # rather than materializing 27 x the full daily panel simultaneously.
        values = build_wide_factor_values(
            inputs.ohlcv, inputs.membership, calendar=inputs.calendar, factor_ids=[factor_id]
        )
        prepared = {}
        if len(values):
            bundle, artifacts = build_factor_scorecard_bundle(
                factor_results=values,
                ohlcv=inputs.ohlcv,
                factor_metadata=[item],
                benchmark_symbol=frozen["benchmark"],
                horizons=frozen["horizons"],
                quantiles=frozen["quantiles"],
                library_factor_results=peers,
            )
            for key in ("methodology", "generated_at", "stale"):
                scorecard.setdefault(key, bundle[key])
            scorecard["factors"].extend(bundle["factors"])
            bundle_provenance[factor_id] = bundle["provenance"]
            statuses.append(bundle["status"])
            for name, frame in artifacts.items():
                if not frame.empty:
                    artifact_parts.setdefault(name, []).append(frame)
            prepared = prepare_evaluation_frames(
                values, inputs.ohlcv, horizons=frozen["horizons"], price_basis="open_to_open"
            )
        else:
            statuses.append("unavailable")
            scorecard["factors"].append(
                {
                    "factor_id": factor_id,
                    "direction": item["direction"],
                    "direction_defaulted": False,
                    "status": "unavailable",
                    "reason": "no_eligible_factor_values",
                    "horizons": {
                        str(h): {"status": "not_evaluated", "reason": "no_eligible_factor_values"}
                        for h in frozen["horizons"]
                    },
                }
            )
        signals = values[values.factor_id == factor_id]
        expected = inputs.membership
        if item["frequency"] == "month_end":
            last_days = (
                pd.Series(inputs.calendar, index=inputs.calendar)
                .groupby(inputs.calendar.strftime("%Y-%m"))
                .last()
            )
            expected = expected[expected.signal_ts.isin(last_days)]
        details = {
            "factor_id": factor_id,
            "expected_member_signal_rows": len(expected),
            "eligible_factor_rows": len(signals),
            "warmup_or_missing_input_rows": len(expected) - len(signals),
            "horizons": {},
        }
        for horizon, frame in prepared.items():
            part = frame[frame.factor_id == factor_id]
            valid = part[part.exclusion_reason.isna()]
            tail = part.return_end_ts.isna()
            details["horizons"][str(horizon)] = {
                "valid_rows": len(valid),
                "valid_signal_days": valid.signal_ts.nunique(),
                "label_tail_insufficient": int(tail.sum()),
                "excluded_by_reason": {
                    str(k): int(v) for k, v in part.exclusion_reason.dropna().value_counts().items()
                },
                "first_valid_signal": valid.signal_ts.min().isoformat() if len(valid) else None,
                "last_valid_signal": valid.signal_ts.max().isoformat() if len(valid) else None,
            }
        coverage.append(details)
    if bundle_provenance:
        common = next(iter(bundle_provenance.values()))
        if any(x["prices_sha256"] != common["prices_sha256"] for x in bundle_provenance.values()):
            raise ValueError("price_digest_changed_between_objects")
        scorecard["provenance"] = {
            **{key: value for key, value in common.items() if key != "input_digest"},
            "input_digest_scope": "ordered_individual_engine_bundles",
            "factor_bundle_provenance": bundle_provenance,
            "input_digest": hashlib.sha256(
                json.dumps(bundle_provenance, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    scorecard["status"] = (
        "ready"
        if all(x == "ready" for x in statuses)
        else ("unavailable" if all(x == "unavailable" for x in statuses) else "partial")
    )
    scorecard["factors"].sort(key=lambda row: row["factor_id"])
    scorecard["data_acceptance"] = inputs.report
    scorecard["wide_run"] = {
        "factor_manifest_digest": frozen["digest"],
        "factor_manifest_file_sha256": file_digest(factor_manifest),
        "input_manifest_sha256": file_digest(input_manifest),
        "mode": mode,
        "admission_authority": False,
        "signal_window": inputs.manifest["signal_window"],
    }
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "scorecard.json", scorecard)
    _write_json(output / "run-config.json", frozen)
    _write_json(output / "input-manifest.json", inputs.manifest)
    _write_json(output / "skip-registry.json", inputs.report)
    _write_json(output / "factor-coverage.json", {"factors": coverage})
    for name in ("ic_daily", "quantile_daily", "long_short_daily", "correlation_daily", "audit"):
        parts = artifact_parts.get(name, [])
        frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if not len(frame.columns):
            frame = pd.DataFrame({"unavailable": pd.Series(dtype="str")})
        frame.to_parquet(output / f"{name}.parquet", index=False)
    _write_json(
        output / "output-digests.json", {p.name: file_digest(p) for p in sorted(output.iterdir())}
    )
    return scorecard


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-plan", action="store_true")
    parser.add_argument("--freeze-factors", action="store_true")
    parser.add_argument("--audit-only", "--dry-run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--factor-manifest", type=Path)
    parser.add_argument("--mode", choices=["diagnostic", "formal"], default="diagnostic")
    parser.add_argument("--membership", type=Path)
    parser.add_argument("--prices", type=Path, action="append")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.fetch_plan:
        if not args.membership or not args.prices:
            parser.error("fetch plan requires --membership and --prices")
        plan = build_fetch_plan(args.membership, args.prices)
        args.out.mkdir(parents=True, exist_ok=False)
        _write_json(args.out / "fetch-plan.json", plan)
        pd.DataFrame(plan["requests"]).to_csv(args.out / "fetch-plan.csv", index=False)
        print(
            json.dumps(
                {
                    "output": str(args.out),
                    "members": plan["member_symbol_count"],
                    "missing_files": plan["missing_file_count"],
                }
            )
        )
    elif args.freeze_factors:
        args.out.mkdir(parents=True, exist_ok=False)
        frozen = frozen_factor_manifest()
        _write_json(args.out / "factor-manifest.json", frozen)
        print(json.dumps({"output": str(args.out), "factor_manifest_digest": frozen["digest"]}))
    elif args.audit_only:
        if not args.manifest:
            parser.error("input audit requires --manifest")
        inputs = load_wide_universe(args.manifest, mode=args.mode)
        args.out.mkdir(parents=True, exist_ok=False)
        _write_json(args.out / "input-report.json", inputs.report)
        _write_json(args.out / "input-manifest.json", inputs.manifest)
        print(json.dumps({"output": str(args.out), "formal_ready": inputs.report["formal_ready"]}))
    else:
        if not args.manifest or not args.factor_manifest:
            parser.error("scorecard requires --manifest and --factor-manifest")
        result = run_scorecard(args.manifest, args.factor_manifest, args.out, mode=args.mode)
        print(
            json.dumps(
                {
                    "output": str(args.out),
                    "objects": len(result["factors"]),
                    "formal_ready": result["data_acceptance"]["formal_ready"],
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
