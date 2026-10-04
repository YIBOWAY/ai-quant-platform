"""Registered-factor originals -> existing trial ledger and generic family curve.

The writer is called only by a newly completed registered verification. The
reader and census are read-only; neither repairs old jobs nor grants capital.
The selected statistical object is Platform net total return, with no benchmark.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd

from quant_system.d34.engine_comparison import ComparisonPolicy, compare_engine_receipts
from quant_system.d34.registered_verification import RegisteredVerificationError, _engine_receipt
from quant_system.d34.research_driver import validate_xnys_calendar
from quant_system.d34.research_request import digest_document
from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import ResearchTrial, TrialsLedger, universe_digest

INTENT = "registered-trial-intent.json"
CURVE = "registered-family-curve.json"
SCHEMA = "registered_trial_commit/v1"
ATTEMPT_INPUT = "registered-attempt-input.json"
PRODUCER_IDENTITY = "registered-producer-identity.json"


def registered_producer_sources():
    """Reuse the central source closure; disk bytes are not process-load proof."""
    from quant_system.research.admission_v2 import code_identity

    return code_identity()


def _require(value, reason):
    if not value:
        raise ValueError("registered_family_" + reason)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    from quant_system.d34.registered_verification import _read_json

    return _read_json(Path(path))


def _write_new(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, sort_keys=True, allow_nan=False, separators=(",", ":"))
        handle.write("\n")


def _document(row):
    return row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)


def _verified_job_universe(value, job_id):
    """Only a valid canonical job identity may exclude another universe."""
    identity = {
        key: value[key]
        for key in (
            "contract",
            "factor_id",
            "factor_identity_digest",
            "source_digest",
            "universe",
            "market_session",
        )
    }
    _require(
        identity["contract"] == "hqa.registered_factor_evidence/v1"
        and isinstance(identity["universe"], list)
        and identity["universe"]
        and all(isinstance(x, str) and x for x in identity["universe"])
        and job_id == "job-registered-" + digest_document(identity)[:32],
        "job_identity_invalid",
    )
    return identity["universe"]


def _verified_manifest_universe(data_root, path):
    scope = _originals(data_root, path.parent, scope_only=True)
    _require(scope["manifest"]["job_id"] == path.parent.name, "job_identity_invalid")
    return scope["manifest"]["universe"]


def _evaluation_input_identity(manifest, raw):
    """Unknown execution configuration is never equivalent to a later result."""
    config = raw["platform"].get("config")
    fields = {
        "initial_cash",
        "commission_bps",
        "slippage_bps",
        "min_order_value",
        "whole_share_orders",
        "execution_price",
    }
    if (
        not isinstance(config, dict)
        or set(config) != fields
        or type(config["whole_share_orders"]) is not bool
        or config["execution_price"] != "next_open"
        or any(
            type(config[k]) not in (int, float) or not math.isfinite(config[k]) or config[k] < 0
            for k in fields - {"whole_share_orders", "execution_price"}
        )
        or config["initial_cash"] <= 0
        or raw["qlib"]["target_weights_digest"] != raw["platform"]["target_weights_digest"]
    ):
        return None
    return {
        "snapshot_digest": manifest["snapshot_digest"],
        "snapshot_file_digest": manifest["snapshot_file_digest"],
        "targets_digest": raw["platform"]["target_weights_digest"],
        "calendar_digest": manifest["calendar_digest"],
        "universe_digest": raw["platform"]["universe_digest"],
        "execution_config": config,
    }


def _originals(data_root, root, *, scope_only=False):
    """Reconstruct numerical inputs from saved files, not book summary fields."""
    data_root, root = Path(data_root).resolve(), Path(root).resolve(strict=True)
    _require(root.is_relative_to(data_root / "_runtime/d34/jobs"), "job_outside_owner")
    files = {}

    def pin(relative, expected=None):
        path = (root / relative).resolve(strict=True)
        _require(path.is_relative_to(root) and path.is_file(), "original_outside_job")
        digest = _sha(path)
        _require(expected is None or digest == expected, "original_changed")
        files[str(path.relative_to(root))] = digest
        return path

    manifest_path = pin("manifest.json")
    manifest = _read(manifest_path)
    _require(
        manifest.get("contract") == "hqa.registered_factor_evidence/v1"
        and manifest.get("manifest_digest")
        == digest_document({k: v for k, v in manifest.items() if k != "manifest_digest"}),
        "manifest_invalid",
    )
    _verified_job_universe(manifest, manifest["job_id"])
    refs = {}
    for name in (
        "source",
        "snapshot",
        "qlib_receipt",
        "qlib_bound",
        "platform_receipt",
        "platform_bound",
    ):
        refs[name] = pin(manifest[name + "_path"], manifest[name + "_file_digest"])
    _require(files[manifest["source_path"]] == manifest["source_digest"], "source_mismatch")
    if (root / ATTEMPT_INPUT).is_file():
        attempt = _read(pin(ATTEMPT_INPUT))
        _require(
            _verified_job_universe(attempt, manifest["job_id"]) == manifest["universe"],
            "attempt_universe_mismatch",
        )
    producer = None
    if not scope_only and (root / PRODUCER_IDENTITY).is_file():
        producer = _read(pin(PRODUCER_IDENTITY))
        sources = producer.get("producer_sources") or {}
        _require(
            producer.get("schema") == "registered_producer_identity/v1"
            and producer.get("source_binding_kind") == "disk_files_and_execution_config"
            and producer.get("loaded_process_attested") is False
            and sources.get("digest") == _hash(sources.get("files"))
            and producer.get("post_execution_sources_unchanged") is True,
            "producer_identity_invalid",
        )
    request_path = pin("request.json")
    request = _read(request_path)
    _require(
        all(
            request.get(key) == manifest[key]
            for key in (
                "job_id",
                "run_id",
                "factor_id",
                "source_digest",
                "snapshot_digest",
                "universe",
                "calendar",
            )
        ),
        "request_mismatch",
    )
    calendar = list(validate_xnys_calendar(manifest["calendar"]))
    _require(digest_document(calendar) == manifest["calendar_digest"], "calendar_mismatch")
    snapshot = pd.read_parquet(refs["snapshot"])
    _require(
        set(snapshot["provider"]) == {"futu"}
        and set(snapshot["price_adjustment"]) == {"qfq"}
        and set(snapshot["symbol"]) == set(manifest["universe"]),
        "snapshot_contract_invalid",
    )
    interval = snapshot["interval"] if "interval" in snapshot else snapshot["bar"]
    _require(set(interval) == {"1d"}, "snapshot_frequency_invalid")
    actual_calendar = [
        stamp.isoformat()
        for stamp in sorted(pd.to_datetime(snapshot["timestamp"], utc=True).unique())
    ]
    _require(actual_calendar == calendar, "snapshot_calendar_mismatch")
    engines, raw = {}, {}
    for name in ("qlib", "platform"):
        raw[name] = _read(refs[name + "_receipt"])
        try:
            engines[name] = _engine_receipt(
                refs[name + "_receipt"],
                engine=name,
                job_id=manifest["job_id"],
                run_id=manifest["run_id"],
                **(
                    {
                        "factor_id": manifest["factor_id"],
                        "source_digest": manifest["source_digest"],
                        "qlib_expression": manifest["qlib_expression"],
                    }
                    if name == "qlib"
                    else {}
                ),
            )
        except RegisteredVerificationError as exc:
            raise ValueError("registered_family_" + exc.code) from exc
        bound = _read(refs[name + "_bound"])
        _require(
            bound.get("contract") == "hqa.d34_bound_engine_receipt/v2"
            and bound.get("receipt_digest")
            == digest_document({k: v for k, v in bound.items() if k != "receipt_digest"})
            and bound.get("job_id") == manifest["job_id"]
            and bound.get("run_id") == manifest["run_id"]
            and bound.get("engine") == name,
            "bound_receipt_invalid",
        )
        _require(
            pin(bound["raw_receipt_path"], bound["raw_receipt_file_digest"])
            == refs[name + "_receipt"],
            "bound_receipt_wrong_original",
        )
        expected = {
            key: raw[name][key]
            for key in (
                "engine",
                "snapshot_digest",
                "universe_digest",
                "calendar_digest",
                "target_weights_digest",
                "daily_returns",
                "return_dates",
                "terminal_nav",
                "terminal_weights",
                "receipt_digest",
            )
        }
        _require(bound.get("engine_receipt") == expected, "bound_receipt_content_changed")
        _require(
            raw[name]["receipt_digest"] == manifest[name + "_receipt_digest"]
            and list(engines[name].return_dates) == calendar
            and engines[name].universe_digest == digest_document(manifest["universe"])
            and engines[name].calendar_digest == manifest["calendar_digest"]
            and engines[name].snapshot_digest == manifest["snapshot_digest"],
            "engine_identity_mismatch",
        )
    compared = compare_engine_receipts(
        qlib=engines["qlib"], platform=engines["platform"], policy=ComparisonPolicy.initial()
    )
    pin(
        str(refs["qlib_receipt"].parent.relative_to(root) / "target_weights.parquet"),
        engines["qlib"].target_weights_digest,
    )
    _require(
        compared.comparison_digest == manifest["comparison_digest"]
        and manifest["comparison"]["accepted"] is compared.accepted,
        "dual_engine_comparison_mismatch",
    )
    input_identity = _evaluation_input_identity(manifest, raw)
    if scope_only:
        return {"manifest": manifest, "files": files, "evaluation_input_identity": input_identity}
    platform = raw["platform"]
    config = platform.get("config")
    _require(
        config
        == {
            "initial_cash": 100000.0,
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "min_order_value": 0.0,
            "whole_share_orders": False,
            "execution_price": "next_open",
        }
        and manifest["cost_model"] == {"commission_bps": 1.0, "slippage_bps": 5.0},
        "platform_cost_contract_unproven",
    )
    if producer is not None:
        _require(producer.get("execution_config") == config, "producer_execution_config_changed")
    outputs = platform.get("output_digests")
    _require(
        isinstance(outputs, dict)
        and {
            "equity_curve.parquet",
            "trade_blotter.parquet",
            "orders.parquet",
            "positions.parquet",
            "attribution.parquet",
        }
        <= set(outputs),
        "platform_outputs_missing",
    )
    output_paths = {
        name: pin(str(refs["platform_receipt"].parent.relative_to(root) / name), digest)
        for name, digest in outputs.items()
    }
    values, dates = list(engines["platform"].daily_returns), [day[:10] for day in calendar]
    _require(
        all(
            type(value) in (int, float) and math.isfinite(value) and value > -1 for value in values
        ),
        "returns_invalid",
    )
    equity = pd.read_parquet(output_paths["equity_curve.parquet"])
    _require(
        pd.to_datetime(equity.timestamp, utc=True).dt.strftime("%Y-%m-%d").tolist() == dates,
        "equity_calendar_mismatch",
    )
    # Platform's historical receipt uses pct_change().fillna(0), so its first
    # element can omit an actual first-day fee. Keep that original untouched;
    # the newly declared net-total object starts at actual initial cash.
    nav, curve, net_values = 100000.0, [], []
    for index, (value, day, actual) in enumerate(zip(values, dates, equity.equity, strict=True)):
        _require(math.isfinite(actual) and actual > 0, "equity_values_invalid")
        if index or value != 0.0:
            _require(abs(actual - nav * (1 + value)) <= 1e-7, "equity_returns_mismatch")
        net_values.append(actual / nav - 1)
        nav = float(actual)
        curve.append({"date": day, "equity": nav})
    _require(
        abs(nav / 100000.0 - engines["platform"].terminal_nav) <= 1e-12, "terminal_nav_mismatch"
    )
    fills = pd.read_parquet(output_paths["trade_blotter.parquet"])
    gross = []
    for fill in fills.to_dict("records"):
        _require(fill["side"] in {"buy", "sell"}, "fill_side_invalid")
        quantity, price, requested, commission = (
            fill[key] for key in ("quantity", "fill_price", "requested_price", "commission")
        )
        _require(
            all(
                type(x) in (int, float) and math.isfinite(x)
                for x in (quantity, price, requested, commission)
            )
            and quantity > 0
            and price > 0
            and requested > 0,
            "fill_values_invalid",
        )
        expected = requested * (1 + (1 if fill["side"] == "buy" else -1) * 0.0005)
        _require(
            abs(price - expected) <= 1e-10 and abs(commission - quantity * price * 0.0001) <= 1e-7,
            "fill_cost_mismatch",
        )
        gross.append(quantity * price)
    turnover = math.fsum(gross) / 100000.0
    _require(
        type(manifest["turnover_period"]) in (int, float)
        and abs(turnover - manifest["turnover_period"]) <= 1e-9
        and abs(turnover - platform["metrics"]["turnover"]) <= 1e-9,
        "turnover_mismatch",
    )
    contract = {
        "schema": "research_family_compatibility/v1",
        "return_definition": "net_total_return",
        "benchmark": {"symbol": None, "method": "none"},
        "frequency": "daily",
        "cost_definition": {
            "model": "proportional_bps",
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "cash_interest": 0.0,
        },
        "market_data_contract": {
            "provider": "futu",
            "price_adjustment": "qfq",
            "currency": "USD",
            "bar": "1d",
        },
    }
    return {
        "manifest": manifest,
        "files": files,
        "selected": net_values,
        "total": net_values,
        "raw_receipt_returns": values,
        "return_reconstruction": {
            "method": "initial_cash_then_original_equity/v1",
            "initial_cash": 100000.0,
            "first_raw_return": values[0],
            "first_net_return": net_values[0],
            "accounting_atol_usd": 1e-7,
            "rtol": 0,
        },
        "dates": dates,
        "curve": curve,
        "contract": contract,
        "turnover": turnover,
        "comparison_accepted": compared.accepted,
        "evaluation_input_identity": input_identity,
        "producer_sources": producer["producer_sources"] if producer else None,
        "producer_execution_config": producer["execution_config"] if producer else None,
        "producer_boundary_receipts": producer.get("boundary_receipts") if producer else None,
        "loaded_process_attested": False,
        "selected_engine": "platform",
        "exposure_engine": "platform",
        "exposure_returns": net_values,
        "exposure_dates": dates,
    }


def prepare_registered_trial(data_root, staging_root, final_root):
    """Freeze a new result's curve and append intent before its atomic publish."""
    data_root, staging_root, final_root = map(Path, (data_root, staging_root, final_root))
    result = _originals(data_root, staging_root)
    manifest = result["manifest"]
    _require(
        final_root.resolve() == data_root.resolve() / "_runtime/d34/jobs" / manifest["job_id"],
        "final_root_mismatch",
    )
    base_metadata = {
        "run_id": manifest["run_id"],
        "registered_job_id": manifest["job_id"],
        "registered_manifest_sha256": result["files"]["manifest.json"],
        "registered_manifest_digest": manifest["manifest_digest"],
        "selected_engine": "platform",
        "return_definition": "net_total_return",
        "returns_digest": _hash({"values": result["selected"], "dates": result["dates"]}),
        "raw_receipt_returns_digest": _hash(result["raw_receipt_returns"]),
        "return_reconstruction": result["return_reconstruction"],
        "registered_producer_digest": _hash(result["producer_sources"]),
        "equity_curve_digest": _hash(result["curve"]),
        "family_contract_digest": _hash(result["contract"]),
    }
    row = ResearchTrial.record(
        kind="platform_backtest",
        subject=manifest["factor_id"],
        universe=manifest["universe"],
        daily_returns=result["selected"],
        window_start=result["dates"][0],
        window_end=result["dates"][-1],
        source="registered_factor_verification",
        metadata=base_metadata,
    )
    identity = {
        key: getattr(row, key)
        for key in ("kind", "subject", "universe_digest", "window_start", "window_end", "n_periods")
    }
    payload = {
        "schema": "research_family_curve/v1",
        "trial_identity": identity,
        "run_id": manifest["run_id"],
        "evaluation_initial_cash": 100000.0,
        "family_contract": result["contract"],
        "curve": result["curve"],
        "input_identity": {
            "job_id": manifest["job_id"],
            "manifest_digest": manifest["manifest_digest"],
            "source_digest": manifest["source_digest"],
            "snapshot_digest": manifest["snapshot_digest"],
            "returns_digest": base_metadata["returns_digest"],
        },
        "source_files": {
            str((final_root / name).relative_to(data_root)): digest
            for name, digest in result["files"].items()
        },
    }
    _write_new(staging_root / CURVE, payload)
    row.metadata.update(
        family_evidence_path=str((final_root / CURVE).relative_to(data_root)),
        family_evidence_sha256=_sha(staging_root / CURVE),
    )
    _write_new(
        staging_root / INTENT,
        {
            "schema": SCHEMA,
            "trial": row.model_dump(mode="json"),
            "curve_sha256": _sha(staging_root / CURVE),
        },
    )
    return row.model_dump(mode="json")


def _intent_original(data_root, root):
    data_root, root = Path(data_root).resolve(), Path(root).resolve(strict=True)
    intent = _read(root / INTENT)
    _require(intent.get("schema") == SCHEMA, "intent_invalid")
    row = ResearchTrial.model_validate(intent["trial"])
    result = _originals(data_root, root)
    manifest = result["manifest"]
    if row.metadata.get("registered_producer_digest") is not None:
        _require(
            result["producer_sources"] is not None
            and row.metadata["registered_producer_digest"] == _hash(result["producer_sources"]),
            "producer_identity_not_trial_bound",
        )
    else:
        # A producer file added beside an older row cannot retroactively bind it.
        result["producer_sources"] = None
        result["producer_execution_config"] = None
        result["producer_boundary_receipts"] = None
    reconstructed = ResearchTrial.record(
        kind="platform_backtest",
        subject=manifest["factor_id"],
        universe=manifest["universe"],
        daily_returns=result["selected"],
        window_start=result["dates"][0],
        window_end=result["dates"][-1],
        source="registered_factor_verification",
        metadata=row.metadata,
    )
    _require(
        row.model_dump(mode="json", exclude={"ts"})
        == reconstructed.model_dump(mode="json", exclude={"ts"}),
        "trial_original_mismatch",
    )
    _require(
        root.name == manifest["job_id"]
        and row.metadata.get("registered_job_id") == manifest["job_id"]
        and row.metadata.get("run_id") == manifest["run_id"]
        and row.metadata.get("registered_manifest_sha256") == result["files"]["manifest.json"]
        and row.metadata.get("registered_manifest_digest") == manifest["manifest_digest"]
        and row.metadata.get("returns_digest")
        == _hash({"values": result["selected"], "dates": result["dates"]})
        and row.metadata.get("equity_curve_digest") == _hash(result["curve"])
        and row.metadata.get("family_contract_digest") == _hash(result["contract"])
        and row.universe_digest == universe_digest(manifest["universe"])
        and row.metadata.get("family_evidence_path") == str((root / CURVE).relative_to(data_root))
        and row.metadata.get("family_evidence_sha256")
        == intent["curve_sha256"]
        == _sha(root / CURVE),
        "intent_original_mismatch",
    )
    payload = _read(root / CURVE)
    _require(
        payload["curve"] == result["curve"] and payload["family_contract"] == result["contract"],
        "curve_original_mismatch",
    )
    result.update(
        row=row.model_dump(mode="json"),
        payload=payload,
        source_files={str(root / name): value for name, value in result["files"].items()},
    )
    result["source_files"].update(
        {str(root / INTENT): _sha(root / INTENT), str(root / CURVE): _sha(root / CURVE)}
    )
    return result


def commit_registered_trial(data_root, root):
    """Append exactly the frozen intent; old jobs lacking intent are never repaired."""
    result = _intent_original(data_root, root)
    row = ResearchTrial.model_validate(result["row"])
    TrialsLedger(Path(data_root) / "trials").append(row)
    return row.model_dump(mode="json")


def read_registered_trial(data_root, root, trusted_trials):
    """Return selected/exposure inputs only when the actual ledger binds this row."""
    result = _intent_original(data_root, root)
    rows = [_document(row) for row in trusted_trials]
    _require(result["row"] in rows, "trial_not_in_current_ledger")
    return result


def read_registered_exposure(data_root, root):
    """Read historical exposure originals, never a fallback for new capital.

    Callers must explicitly select their historical-peer branch. No intent,
    ledger or current-source qualification is created or required here.
    """
    root = Path(root).resolve(strict=True)
    result = _originals(data_root, root)
    _require(root.name == result["manifest"]["job_id"], "historical_job_identity_mismatch")
    result.update(
        purpose="historical_registered_exposure_only",
        funding_authority=False,
        source_files={str(root / name): digest for name, digest in result["files"].items()},
    )
    return result


def census_registered_trials(data_root, trusted_trials):
    """Read-only census: legacy unrecorded jobs are evidence gaps, never backfilled."""
    data_root = Path(data_root).resolve()
    rows, findings = [_document(row) for row in trusted_trials], []
    for job_root in sorted((data_root / "_runtime/d34/jobs").glob("job-registered-*")):
        path = job_root / "manifest.json"
        item = {
            "job_root": str(job_root),
            "manifest_path": str(path),
            "manifest_sha256": _sha(path) if path.is_file() else None,
            "status": "unknown",
            "universe_digest": None,
            "universe_verified": False,
            "contract": None,
            "contract_verified": False,
        }
        try:
            manifest = _read(path)
            symbols = _verified_manifest_universe(data_root, path)
            item.update(
                job_id=manifest.get("job_id"),
                universe=symbols,
                universe_digest=universe_digest(symbols),
                universe_verified=True,
            )
            result = _originals(data_root, path.parent)
            item["contract"] = result["contract"]
            item["contract_verified"] = True
            item["producer_digest"] = (
                _hash(result["producer_sources"]) if result["producer_sources"] else None
            )
            item["evaluation_input_identity"] = result["evaluation_input_identity"]
            if not (path.parent / INTENT).exists():
                item.update(
                    status="unrecorded_real_evaluation",
                    reason="registered_family_legacy_trial_missing",
                )
            else:
                item["status"] = "unrecorded_real_evaluation"
                read_registered_trial(data_root, path.parent, rows)
                item.update(status="recorded", reason=None)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OverflowError,
            RegisteredVerificationError,
        ) as exc:
            item["reason"] = str(exc)
        findings.append(item)
    for directory in sorted((data_root / "_runtime/d34/jobs/registered-failures").glob("*/*")):
        path = directory / "failure-receipt.json"
        item = {
            "job_root": str(directory),
            "manifest_path": None,
            "status": "unknown",
            "universe_digest": None,
            "universe_verified": False,
            "contract": None,
            "contract_verified": False,
            "failure_receipt_path": str(path),
            "failure_receipt_sha256": _sha(path) if path.is_file() else None,
        }
        try:
            failure = _read(path)
            job = directory.parent.name
            symbols = _verified_job_universe(_read(directory / ATTEMPT_INPUT), job)
            _require(
                failure["job_id"] == job and failure["universe"] == symbols,
                "failure_identity_invalid",
            )
            item["job_id"] = job
            physical = {
                str(p.relative_to(directory)): _sha(p)
                for p in directory.rglob("*")
                if p.is_file() and p != path
            }
            _require(physical == failure["files"], "failure_originals_changed")
            stage = failure["stage"]
            attempted = stage in {
                "platform_evaluation",
                "dual_engine_comparison",
                "family_recording",
            }
            _require(
                stage
                in {
                    "snapshot",
                    "qlib_provider",
                    "qlib_evaluation",
                    "platform_evaluation",
                    "dual_engine_comparison",
                    "family_recording",
                },
                "failure_stage_unknown",
            )
            present = any(
                name.startswith("platform-replay/") and name.endswith("/receipt.json")
                for name in physical
            )
            _require(
                failure["platform_evaluation_attempted"] is attempted
                and failure["platform_receipt_present"] is present
                and (
                    attempted or not any(name.startswith("platform-replay/") for name in physical)
                ),
                "failure_stage_artifact_conflict",
            )
            failed_input = None
            if attempted:
                scope = _originals(data_root, directory, scope_only=True)
                _require(
                    scope["manifest"]["universe"] == symbols and scope["manifest"]["job_id"] == job,
                    "failure_original_scope_mismatch",
                )
                item.update(
                    universe=symbols,
                    universe_digest=universe_digest(symbols),
                    universe_verified=True,
                )
                failed_input = scope["evaluation_input_identity"]
                item["evaluation_input_identity"] = failed_input
            producer_path = directory / PRODUCER_IDENTITY
            attempt_producer = (
                _read(producer_path).get("producer_sources") if producer_path.is_file() else None
            )
            recovered = any(
                row.get("job_id") == job
                and row["status"] == "recorded"
                and attempt_producer is not None
                and row.get("producer_digest") == _hash(attempt_producer)
                and failed_input is not None
                and row.get("evaluation_input_identity") == failed_input
                for row in findings
            )
            item.update(
                status="recovered_evaluation"
                if recovered
                else "unknown"
                if attempted
                else "no_real_evaluation",
                reason=failure["reason"],
                stage=stage,
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            item["reason"] = str(exc)
        findings.append(item)
    return {"schema": "registered_family_census/v1", "entries": findings, "writes": 0}


def preserve_registered_failure(
    data_root, staging_root, *, job_id, run_id, universe, stage, reason
):
    """Preserve a new attempt without manufacturing returns or a statistical trial."""
    data_root, staging_root = Path(data_root).resolve(), Path(staging_root).resolve()
    if not staging_root.exists():
        return None
    _require(staging_root.is_relative_to(data_root / "_runtime/d34/jobs"), "failure_outside_owner")
    paths = sorted(staging_root.glob("platform-replay/**/receipt.json"))
    document = {
        "schema": "registered_attempt_failure/v1",
        "job_id": job_id,
        "run_id": run_id,
        "universe": list(universe),
        "stage": stage,
        "reason": reason,
        "platform_receipt_present": bool(paths),
        "platform_evaluation_attempted": stage
        in {"platform_evaluation", "dual_engine_comparison", "family_recording"},
        "statistical_trial_created": False,
        "files": {
            str(path.relative_to(staging_root)): _sha(path)
            for path in staging_root.rglob("*")
            if path.is_file()
        },
    }
    _write_new(staging_root / "failure-receipt.json", document)
    final = (
        data_root / "_runtime/d34/jobs/registered-failures" / job_id / staging_root.name.lstrip(".")
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staging_root, final)
    return final
