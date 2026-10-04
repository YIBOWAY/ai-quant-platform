#!/usr/bin/env python3
"""Rebuild immutable original-v4 panels; do not rerun scorecards or compute SEs."""

from __future__ import annotations

import argparse
import gc
import importlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa

OWNER = Path(__file__).resolve().parents[1]
HELPER = OWNER / "src/quant_system/research/factor_contributions.py"
spec = importlib.util.spec_from_file_location("contribution_builder", HELPER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def _core_identity(plan):
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(plan["owner_root"]) / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    value = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import json; from quant_system.research.admission_v2 import code_identity; "
            "print(json.dumps(code_identity()))",
        ],
        cwd=plan["owner_root"],
        env=env,
        text=True,
    )
    builder.require(
        json.loads(value) == plan["owner_admission_code"],
        "contribution_owner_runtime_identity_changed",
    )


def _archive_modules(plan):
    archive = Path(plan["archive_root"])
    head = subprocess.check_output(
        ["git", "-C", str(archive), "rev-parse", "HEAD"], text=True
    ).strip()
    builder.require(head == plan["archive_commit"], "contribution_wrong_archive_commit")
    dirty = subprocess.check_output(
        [
            "git",
            "-C",
            str(archive),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        text=True,
    ).strip()
    builder.require(not dirty, "contribution_archive_dirty")
    sys.path.insert(0, str(archive / "src"))
    names = [
        "quant_system.research.wide_universe",
        "quant_system.research.wide_factor_set",
        "quant_system.factors.evaluation",
    ]
    modules = [importlib.import_module(name) for name in names]
    builder.assert_module_origins(
        [
            value
            for name, value in sys.modules.items()
            if name.startswith("quant_system") and getattr(value, "__file__", None)
        ],
        archive,
    )
    return modules


def _peak_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _key(task):
    return task["factor_id"] + "-h" + str(task["horizon"])


def _read_completed(out, plan, implementation):
    rows = {}
    reuse = plan.get("reuse_verified_partitions") or {}
    for source in (reuse.get("generator_snapshot") or {}).values():
        builder.require(
            builder.file_sha(source["path"]) == source["sha256"],
            "contribution_reused_generator_snapshot_changed",
        )
    tasks = {_key(task): task for task in plan["tasks"]}
    for path in (out / "receipts").glob("*.json"):
        row = json.loads(path.read_text())
        key = _key(row["task"])
        approved = (reuse.get("receipts") or {}).get(key)
        own = row["plan_digest"] == plan["plan_digest"] and row["implementation"] == implementation
        historical = (
            approved
            and builder.file_sha(path) == approved["receipt_sha256"]
            and (
                row["plan_digest"] == approved["plan_digest"]
                and row["implementation"] == approved["implementation"]
            )
        )
        builder.require(
            (own or historical)
            and row["task"] == tasks.get(key)
            and row["status"] == "matched_original"
            and builder.file_sha(out / row["panel"]["path"]) == row["panel"]["sha256"]
            and builder.file_sha(out / row["daily"]["path"]) == row["daily"]["sha256"],
            "contribution_resume_binding_changed",
        )
        if row.get("unmatched"):
            builder.require(
                builder.file_sha(out / row["unmatched"]["path"]) == row["unmatched"]["sha256"],
                "contribution_unmatched_output_changed",
            )
        rows[key] = row
    return rows


def _write_index(out, plan, completed):
    rows = [completed[_key(t)] for t in plan["tasks"] if _key(t) in completed]
    value = {
        "schema": "qs.factor_contribution_index/v1",
        "plan_digest": plan["plan_digest"],
        "source_output_manifest_sha256": plan["source_output_manifest_sha256"],
        "scope": plan["scope"],
        "panel_columns": plan["panel_columns"],
        "identity_semantics": plan["identity_semantics"],
        "planned_partitions": len(plan["tasks"]),
        "completed_partitions": len(rows),
        "status": "completed" if len(rows) == len(plan["tasks"]) else "partial",
        "row_count": sum(r["rows"] for r in rows),
        "original_value_label_rows": sum(
            (r.get("join_audit") or {}).get("original_factor_value_rows", r["rows"]) for r in rows
        ),
        "unmatched_raw_signal_rows": sum(
            (r.get("join_audit") or {}).get("unmatched_rows", 0) for r in rows
        ),
        "reuse_policy": "v1_receipts_keep_original_plan_and_generator_identity",
        "partitions": rows,
        "cluster_standard_error": None,
        "cluster_status": "not_evaluated",
        "admission_authority": False,
        "funding_authority": False,
    }
    value["index_digest"] = builder.digest(value)
    temporary = out / "index.next.json"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(out / "index.json")


def run(plan_path, mode):
    started = time.monotonic()
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    plan = json.loads(Path(plan_path).read_text())
    builder.validate_plan(plan)
    out = Path(plan["output_root"]).resolve()
    builder.require(
        not out.is_relative_to(Path(plan["source_run_dir"]).resolve())
        and not out.is_relative_to(Path(plan["archive_root"]).resolve()),
        "contribution_output_must_be_separate",
    )
    out.mkdir(parents=True, exist_ok=True)
    import fcntl

    with (out / "builder.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        implementation = {
            "script_sha256": builder.file_sha(__file__),
            "helper_sha256": builder.file_sha(HELPER),
        }
        completed = _read_completed(out, plan, implementation)
        targets = (
            [plan["pilot_task"]]
            if mode == "pilot"
            else [plan["correction_probe_task"]]
            if mode == "correction-pilot"
            else plan["tasks"]
        )
        if mode == "remaining":
            builder.require(_key(plan["pilot_task"]) in completed, "contribution_pilot_required")
            if plan.get("correction_probe_task"):
                builder.require(
                    _key(plan["correction_probe_task"]) in completed
                    and (out / "correction-pilot-verification.json").is_file(),
                    "contribution_correction_probe_required",
                )
        targets = [t for t in targets if _key(t) not in completed]
        if not targets:
            print(json.dumps({"status": "already_completed", "mode": mode}))
            return
        current = None
        try:
            _core_identity(plan)
            builder.verify_files(plan)
            loader, factors, evaluation = _archive_modules(plan)
            config = json.loads((Path(plan["source_run_dir"]) / "run-config.json").read_text())
            builder.require(
                factors.frozen_factor_manifest() == config,
                "contribution_archived_factor_manifest_mismatch",
            )
            original = Path(plan["source_run_dir"])
            load_start = time.monotonic()
            inputs = loader.load_wide_universe(original / "input-manifest.json", mode="formal")
            load_seconds = time.monotonic() - load_start
            expected_acceptance = json.loads((original / "skip-registry.json").read_text())
            builder.require(
                inputs.report == expected_acceptance, "contribution_loader_acceptance_changed"
            )
            archived_daily = pd.read_parquet(original / "ic_daily.parquet")
            coverage = {
                r["factor_id"]: r
                for r in json.loads((original / "factor-coverage.json").read_text())["factors"]
            }
            price_frame = evaluation.build_price_frame(inputs.ohlcv, price_basis="open_to_open")
            expected_calendar = inputs.calendar[
                (inputs.calendar >= price_frame.calendar.min())
                & (inputs.calendar <= price_frame.calendar.max())
            ]
            builder.require(
                price_frame.calendar.equals(expected_calendar), "contribution_global_calendar_gap"
            )
            context = {
                "schema": "qs.factor_contribution_context/v1",
                "plan_digest": plan["plan_digest"],
                "implementation": implementation,
                "archive_commit": plan["archive_commit"],
                "loaded_price_rows": len(inputs.ohlcv),
                "loaded_membership_rows": len(inputs.membership),
                "label_calendar_digest": builder.digest(
                    [d.isoformat() for d in price_frame.calendar]
                ),
                "loaded_input_report_digest": builder.digest(inputs.report),
                "identity_scope": inputs.report.get("identity_scope"),
                "source_limits": inputs.manifest["usage_restrictions"],
            }
            context_path = out / "context.json"
            if context_path.exists():
                builder.require(
                    json.loads(context_path.read_text()) == context, "contribution_context_changed"
                )
            else:
                builder.write_new_json(context_path, context)
            print(
                json.dumps(
                    {
                        "event": "inputs_loaded",
                        "rows": len(inputs.ohlcv),
                        "load_seconds": load_seconds,
                        "peak_rss_bytes": _peak_bytes(),
                    }
                ),
                flush=True,
            )
            values = None
            previous_factor = None
            for task in targets:
                current = task
                identifier, horizon = task["factor_id"], task["horizon"]
                partition_start = time.monotonic()
                factor_seconds = 0.0
                if identifier != previous_factor:
                    del values
                    gc.collect()
                    factor_start = time.monotonic()
                    values = factors.build_wide_factor_values(
                        inputs.ohlcv,
                        inputs.membership,
                        calendar=inputs.calendar,
                        factor_ids=[identifier],
                    )
                    builder.reconcile_factor_values(
                        values,
                        inputs.membership,
                        inputs.calendar,
                        item=task,
                        expected=coverage[identifier],
                    )
                    factor_seconds = time.monotonic() - factor_start
                    previous_factor = identifier
                prepared = evaluation.prepare_evaluation_frames(
                    values,
                    inputs.ohlcv,
                    horizons=(horizon,),
                    price_basis="open_to_open",
                    price_frame=price_frame,
                )[horizon]
                unmatched, join_audit = builder.preserve_original_join(
                    values,
                    prepared,
                    inputs.membership,
                    price_frame.observed_mask,
                    factor_id=identifier,
                    horizon=horizon,
                )
                panel = builder.build_panel(
                    prepared,
                    inputs.membership,
                    factor_id=identifier,
                    horizon=horizon,
                    label_calendar=price_frame.calendar,
                )
                del prepared
                reference = archived_daily[
                    archived_daily.factor_id.eq(identifier) & archived_daily.horizon.eq(horizon)
                ]
                daily, reconciliation = builder.reconcile_panel(
                    panel,
                    reference,
                    coverage[identifier]["horizons"][str(horizon)],
                )
                directory = out / "panels" / identifier
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"h{horizon}.parquet"
                daily_path = directory / f"h{horizon}-daily.parquet"
                unmatched_path = directory / f"h{horizon}-unmatched.parquet"
                builder.require(
                    not path.exists() and not daily_path.exists() and not unmatched_path.exists(),
                    "contribution_unregistered_output_exists",
                )
                for name in ["factor_id", "symbol", "entity_id", "exclusion_reason", "price_basis"]:
                    panel[name] = panel[name].astype("category")
                panel.to_parquet(path, index=False, compression="zstd", row_group_size=65536)
                daily.to_parquet(daily_path, index=False, compression="zstd")
                unmatched.to_parquet(unmatched_path, index=False, compression="zstd")
                receipt = {
                    **reconciliation,
                    "join_audit": join_audit,
                    "task": task,
                    "plan_digest": plan["plan_digest"],
                    "implementation": implementation,
                    "created_at": datetime.now(UTC).isoformat(),
                    "panel": {
                        "path": str(path.relative_to(out)),
                        "sha256": builder.file_sha(path),
                        "bytes": path.stat().st_size,
                    },
                    "daily": {
                        "path": str(daily_path.relative_to(out)),
                        "sha256": builder.file_sha(daily_path),
                    },
                    "unmatched": {
                        "path": str(unmatched_path.relative_to(out)),
                        "sha256": builder.file_sha(unmatched_path),
                        "rows": len(unmatched),
                        "bytes": unmatched_path.stat().st_size,
                    },
                    "factor_seconds": factor_seconds,
                    "partition_seconds": time.monotonic() - partition_start,
                    "process_peak_rss_bytes": _peak_bytes(),
                    "load_seconds": load_seconds,
                    "process_elapsed_seconds": time.monotonic() - started,
                    "cluster_statistics_computed": False,
                }
                builder.write_new_json(out / "receipts" / (_key(task) + ".json"), receipt)
                completed[_key(task)] = receipt
                _write_index(out, plan, completed)
                print(
                    json.dumps(
                        {
                            "event": "partition_completed",
                            "factor_id": identifier,
                            "horizon": horizon,
                            "rows": len(panel),
                            "seconds": receipt["partition_seconds"],
                            "peak_rss_bytes": _peak_bytes(),
                            "file_bytes": path.stat().st_size,
                            "ic_max_abs": receipt["max_abs_pearson_difference"],
                            "rankic_max_abs": receipt["max_abs_rankic_difference"],
                            "unmatched_rows": len(unmatched),
                        }
                    ),
                    flush=True,
                )
                del panel, daily, unmatched
                gc.collect()
            builder.verify_files(plan)
            _core_identity(plan)
            builder.require(
                implementation
                == {
                    "script_sha256": builder.file_sha(__file__),
                    "helper_sha256": builder.file_sha(HELPER),
                },
                "contribution_generator_changed_during_run",
            )
            builder.write_new_json(
                out / f"{mode}-verification.json",
                {
                    "status": "verified",
                    "plan_digest": plan["plan_digest"],
                    "all_source_files_unchanged": True,
                    "all_frozen_inputs_unchanged": True,
                    "owner_admission_code_unchanged": True,
                    "implementation": implementation,
                    "elapsed_seconds": time.monotonic() - started,
                    "peak_rss_bytes": _peak_bytes(),
                    "completed_partitions": len(completed),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            builder.write_new_json(
                out / "failures" / f"{time.time_ns()}.json",
                {
                    "status": "failed",
                    "task": current,
                    "plan_digest": plan["plan_digest"],
                    "implementation": implementation,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "elapsed_seconds": time.monotonic() - started,
                    "peak_rss_bytes": _peak_bytes(),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--mode", choices=["pilot", "correction-pilot", "remaining"], required=True)
    args = parser.parse_args()
    run(args.plan, args.mode)


if __name__ == "__main__":
    main()
