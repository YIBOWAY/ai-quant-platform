"""Read-only D34 experiment archives for compatible-family accounting.

This verifies the saved experiment, request and cost contract. It is not a
replacement for selected-candidate dual-engine or capital qualification.
Legacy scalar-only trials remain unknown; no benchmark series is fabricated.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from quant_system.d34.research_driver import validate_xnys_calendar
from quant_system.d34.research_request import digest_document
from quant_system.d34.worker import _research_request_digest
from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import performance_from_daily_returns, universe_digest


def _require(value, reason):
    if not value:
        raise ValueError("d34_family_" + reason)


def _document(row):
    value = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)
    return json.loads(json.dumps(value, allow_nan=False))


class D34FamilyEvidenceResolver:
    """Resolve only caller-owned immutable trial identities and canonical files."""

    def __init__(self, data_root: Path, *, trusted_trials: Sequence):
        self.root = Path(data_root).resolve()
        self.trials = {str(_document(row)["trial_id"]): _document(row) for row in trusted_trials}
        self.failures: dict[str, str] = {}

    def __call__(self, row):
        row = _document(row)
        identifier = str(row.get("trial_id"))
        if row.get("kind") != "d34_experiment":
            return None
        try:
            _require(self.trials.get(identifier) == row, "trial_not_trusted")
            result = self._resolve(row)
            self.failures.pop(identifier, None)
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            reason = str(exc)
            self.failures[identifier] = (
                reason if reason.startswith("d34_family_") else "d34_family_original_invalid"
            )
            return None

    def _read(self, path, files):
        path = Path(path).resolve(strict=True)
        _require(path.is_relative_to(self.root) and path.is_file(), "original_path_invalid")
        raw = path.read_bytes()
        value = json.loads(raw)
        _require(isinstance(value, dict), "original_invalid")
        files[str(path)] = hashlib.sha256(raw).hexdigest()
        return value

    @staticmethod
    def _sealed(value, key):
        expected = value.get(key)
        body = {k: v for k, v in value.items() if k != key}
        _require(expected == digest_document(body), "document_digest_mismatch")
        return expected

    @staticmethod
    def _reference_matches(value, expected, job):
        """Allow original container paths, but never another job's same basename."""
        if not isinstance(value, str):
            return False
        path = Path(value)
        if not path.is_absolute():
            return (expected.parent / path).resolve() == expected.resolve()
        if path == expected:
            return True
        parts = path.parts
        return (
            job.name in parts
            and parts[parts.index(job.name) + 1 :] == expected.relative_to(job).parts
        )

    def _resolve(self, row):
        files = {}
        metadata = row.get("metadata") or {}
        job_id, experiment = metadata.get("job_id"), metadata.get("experiment_id")
        _require(
            isinstance(job_id, str)
            and re.fullmatch(r"job-[A-Za-z0-9._:-]+", job_id)
            and isinstance(experiment, str)
            and re.fullmatch(r"[A-Za-z0-9._-]+", experiment)
            and metadata.get("run_id") == f"{job_id}:{experiment}",
            "trial_identity_missing",
        )
        job = self.root / "_runtime/d34/jobs" / job_id
        request = self._read(job / "research_request.json", files)
        _require(
            request.get("contract") == "hqa.d34_research_request/v2"
            and request.get("job_id") == job_id
            and "initial_cash" in request,
            "request_identity_mismatch",
        )
        request_digest = _research_request_digest(request)
        _require(request_digest == metadata.get("request_digest"), "request_digest_mismatch")
        dates = list(validate_xnys_calendar(request["calendar"]))
        symbols = request["universe"]
        _require(
            universe_digest(symbols) == row["universe_digest"]
            and sorted(symbols) == row["universe"],
            "universe_mismatch",
        )
        market_contract = self._snapshot_contract(request, files)
        initial = request["initial_cash"]
        _require(
            type(initial) in {int, float} and math.isfinite(initial) and initial > 0,
            "initial_cash_invalid",
        )
        batch_path = job / f"research/experiment-trials-{request_digest[:32]}.json"
        _require(batch_path.is_file(), "batch_missing")
        batch = self._read(batch_path, files)
        batch_digest = self._sealed(batch, "receipt_digest")
        _require(
            batch.get("contract") == "hqa.d34_experiment_trial_batch/v1"
            and batch.get("job_id") == job_id
            and batch.get("request_digest") == request_digest
            and batch.get("universe") == symbols
            and batch.get("universe_digest") == digest_document(symbols)
            and batch.get("return_dates") == dates
            and batch.get("calendar_digest") == digest_document(dates),
            "batch_identity_mismatch",
        )
        attempts, experiments = batch.get("attempts"), batch.get("experiments")
        _require(
            isinstance(attempts, list)
            and isinstance(experiments, list)
            and all(isinstance(item, dict) for item in [*attempts, *experiments]),
            "batch_counts_invalid",
        )
        successful = {a["experiment_id"] for a in attempts if a.get("status") == "succeeded"}
        ids = [a["experiment_id"] for a in attempts]
        expected_count = (
            1
            if request.get("formula")
            else request["max_iterations"] * request["experiments_per_iteration"]
        )
        _require(
            len(ids) == len(set(ids)) == batch.get("experiment_count") == expected_count
            and all(a.get("status") in {"succeeded", "failed"} for a in attempts)
            and len(experiments) == len(successful) == batch.get("successful_experiment_count")
            and {e["experiment_id"] for e in experiments} == successful,
            "batch_counts_invalid",
        )
        selected_rows = [e for e in experiments if e["experiment_id"] == experiment]
        _require(len(selected_rows) == 1, "experiment_missing")
        original = selected_rows[0]
        _require(original.get("subject") == row["subject"], "experiment_identity_mismatch")
        results = []
        for path in sorted((job / "research").glob("*/research_receipt.json")):
            document = self._read(path, files)
            if document.get("request_digest") == request_digest:
                results.append((path, document))
        _require(len(results) == 1, "research_result_missing_or_ambiguous")
        result_path, result = results[0]
        _require(
            result.get("contract") == "hqa.d34_research_result/v2"
            and result.get("job_id") == job_id
            and result.get("run_id") == request.get("run_id")
            and result.get("experiment_trials_digest") == batch_digest
            and result.get("experiment_trials_file_digest") == files[str(batch_path.resolve())]
            and self._reference_matches(result.get("experiment_trials_path"), batch_path, job)
            and result.get("experiment_count") == batch["experiment_count"]
            and result.get("successful_experiment_count") == batch["successful_experiment_count"],
            "research_result_binding_mismatch",
        )
        observation_path = result_path.parent / "experiments" / experiment / "receipt.json"
        observation = self._read(observation_path, files)
        _require(metadata.get("experiment_receipt_digest") is not None, "returns_binding_missing")
        _require(
            files[str(observation_path.resolve())] == original.get("experiment_receipt_digest")
            and metadata.get("experiment_receipt_digest", original.get("experiment_receipt_digest"))
            == original.get("experiment_receipt_digest")
            and observation.get("experiment_id") == experiment
            and observation.get("status") == "succeeded"
            and digest_document(observation.get("proposal")) == original.get("proposal_digest")
            and metadata.get("proposal_digest", original.get("proposal_digest"))
            == original.get("proposal_digest"),
            "experiment_original_mismatch",
        )
        values = original.get("daily_returns")
        _require(
            observation.get("returns_digest") is not None
            and observation.get("return_dates_digest") is not None,
            "returns_binding_missing",
        )
        _require(
            observation["returns_digest"] == digest_document({"values": values, "dates": dates})
            and observation["return_dates_digest"] == digest_document(dates),
            "returns_binding_mismatch",
        )
        _require(
            isinstance(values, list)
            and len(values) == len(dates)
            and all(type(v) in {int, float} and math.isfinite(v) and v >= -1 for v in values),
            "returns_invalid",
        )
        perf = performance_from_daily_returns(values)
        _require(
            row.get("n_periods") == len(dates)
            and row.get("window_start") == dates[0][:10]
            and row.get("window_end") == dates[-1][:10]
            and all(
                row.get(k) is not None
                and math.isclose(row[k], perf[k], rel_tol=1e-9, abs_tol=1e-12)
                for k in ("total_return",)
            ),
            "trial_returns_mismatch",
        )
        evaluation = original.get("evaluation_contract")
        if evaluation is not None:
            _require(isinstance(evaluation, dict), "evaluation_contract_invalid")
            _require(
                observation.get("evaluation_contract") == evaluation, "evaluation_contract_mismatch"
            )
            _require(
                evaluation.get("schema") == "hqa.d34_experiment_evaluation/v1"
                and evaluation.get("request_digest") == request_digest
                and evaluation.get("initial_cash") == initial
                and evaluation.get("return_definition") == "net_total_return"
                and evaluation.get("frequency") == "daily"
                and evaluation.get("snapshot_digest") == request.get("snapshot_digest")
                and evaluation.get("snapshot_id") == request.get("snapshot_id")
                and evaluation.get("snapshot_source") == "futu"
                and evaluation.get("universe_digest") == digest_document(symbols)
                and evaluation.get("calendar_digest") == digest_document(dates)
                and all(
                    re.fullmatch(
                        r"[0-9a-f]{64}", str(evaluation.get("implementation", {}).get(key, ""))
                    )
                    for key in ("producer_sha256", "runner_source_sha256")
                ),
                "evaluation_contract_invalid",
            )
            config = evaluation.get("qlib_config")
            _require(
                digest_document(config) == evaluation.get("qlib_config_digest"),
                "config_digest_mismatch",
            )
        else:
            config = self._selected_legacy_config(
                job, request, result_path, result, original, batch, dates, files
            )
        contract = self._contract(config, request)
        contract["market_data_contract"] = market_contract
        curve, nav = [], float(initial)
        for stamp, value in zip(dates, values, strict=True):
            nav *= 1 + value
            curve.append({"date": stamp[:10], "equity": nav})
        return {
            "curve": curve,
            "evaluation_initial_cash": initial,
            "family_contract": contract,
            "family_evidence": {
                "adapter": "d34_original_experiment/v1",
                "trial_digest": _hash(row),
                "curve_digest": _hash(curve),
                "files": files,
                "input_identity": {
                    "request_digest": request_digest,
                    "snapshot_digest": request["snapshot_digest"],
                    "batch_digest": batch_digest,
                    "experiment_id": experiment,
                },
                "selection_history": {
                    "job_id": job_id,
                    "all_attempt_ids": ids,
                    "selected_experiment": batch["selected_experiment"],
                },
            },
        }

    def _snapshot_contract(self, request, files):
        identifier = request.get("snapshot_id")
        _require(
            isinstance(identifier, str) and re.fullmatch(r"snapshot-[0-9a-f]{32}", identifier),
            "snapshot_identity_invalid",
        )
        root = self.root / "_runtime/d34/snapshots" / identifier
        manifest = self._read(root / "manifest.json", files)
        identity = {
            k: v
            for k, v in manifest.items()
            if k
            not in {
                "snapshot_id",
                "snapshot_digest",
                "observed_at",
                "provider_receipt",
                "parquet_file",
            }
        }
        digest = digest_document(identity)
        provider = manifest.get("provider_receipt") or {}
        codes = {symbol: f"US.{symbol}" for symbol in request["universe"]}
        _require(
            manifest.get("contract") == "hqa.market_data_snapshot/v1"
            and manifest.get("snapshot_id") == identifier == "snapshot-" + digest[:32]
            and manifest.get("snapshot_digest") == request.get("snapshot_digest") == digest
            and manifest.get("provider") == request.get("snapshot_source") == "futu"
            and manifest.get("universe") == request["universe"]
            and manifest.get("symbol_codes") == codes
            and manifest.get("calendar") == "XNYS"
            and manifest.get("timezone") == "America/New_York"
            and manifest.get("adjustment") == "qfq"
            and provider.get("symbols") == codes
            and provider.get("interval") == "1d"
            and digest_document(provider) == manifest.get("provider_receipt_digest"),
            "snapshot_contract_mismatch",
        )
        _require(manifest.get("parquet_file") == "ohlcv.parquet", "snapshot_path_invalid")
        path = (root / "ohlcv.parquet").resolve(strict=True)
        _require(path.is_relative_to(self.root) and path.is_file(), "snapshot_path_invalid")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _require(digest == manifest.get("parquet_digest"), "snapshot_file_changed")
        files[str(path)] = digest
        return {"provider": "futu", "price_adjustment": "qfq", "currency": "USD", "bar": "1d"}

    def _selected_legacy_config(
        self, job, request, result_path, result, original, batch, dates, files
    ):
        _require(
            original["experiment_id"]
            == result.get("selected_experiment")
            == batch.get("selected_experiment"),
            "experiment_cost_contract_missing",
        )
        path = result_path.parent / str(result.get("qlib_receipt_file"))
        qlib = self._read(path, files)
        digest = self._sealed(qlib, "receipt_digest")
        _require(
            qlib.get("contract") == "hqa.d34_engine_receipt/v1"
            and qlib.get("engine") == "qlib"
            and files[str(path.resolve())] == result.get("qlib_receipt_file_digest")
            and digest == result.get("qlib_receipt_digest")
            and qlib.get("job_id") == request["job_id"]
            and qlib.get("run_id") == request["run_id"]
            and qlib.get("selected_experiment") == original["experiment_id"]
            and qlib.get("daily_returns") == original["daily_returns"]
            and qlib.get("return_dates") == dates
            and qlib.get("snapshot_digest") == request["snapshot_digest"]
            and qlib.get("snapshot_id") == request["snapshot_id"]
            and qlib.get("universe_digest") == digest_document(request["universe"])
            and qlib.get("calendar_digest") == digest_document(dates),
            "selected_original_mismatch",
        )
        config = qlib.get("qlib_config")
        _require(isinstance(config, dict), "config_identity_mismatch")
        _require(
            digest_document(config)
            == qlib.get("qlib_config_digest")
            == result.get("qlib_config_digest"),
            "config_digest_mismatch",
        )
        manifest = self._read(job / "evidence_manifest.json", files)
        self._sealed(manifest, "manifest_digest")
        _require(
            manifest.get("contract") == "hqa.d34_research_evidence/v1"
            and manifest.get("job_id") == request["job_id"]
            and manifest.get("run_id") == request["run_id"]
            and manifest.get("research_request_digest") == digest_document(request)
            and (job / str(manifest.get("qlib_raw_receipt_path"))).resolve() == path.resolve()
            and manifest.get("qlib_raw_receipt_file_digest") == files[str(path.resolve())]
            and manifest.get("qlib_receipt_digest") == digest,
            "manifest_binding_mismatch",
        )
        cost = manifest.get("cost_model")
        _require(
            isinstance(cost, dict)
            and set(cost) == {"commission_bps", "slippage_bps"}
            and all(type(v) in {int, float} and math.isfinite(v) and v >= 0 for v in cost.values()),
            "cost_contract_missing",
        )
        exchange = config.get("exchange") or {}
        rate = sum(cost.values()) / 10000
        _require(
            math.isclose(exchange.get("open_cost", -1), rate, rel_tol=0, abs_tol=1e-15)
            and math.isclose(exchange.get("close_cost", -1), rate, rel_tol=0, abs_tol=1e-15),
            "cost_contract_mismatch",
        )
        return config

    @staticmethod
    def _contract(config, request):
        _require(
            isinstance(config, Mapping)
            and config.get("contract") == "hqa.d34_qlib_config/v1"
            and config.get("universe") == request["universe"]
            and config.get("start_time") == request["calendar"][0]
            and config.get("end_time") == request["calendar"][-1]
            and config.get("execution_timing") == "next_open",
            "config_identity_mismatch",
        )
        exchange = config.get("exchange") or {}
        rate = exchange.get("open_cost")
        _require(
            type(rate) in {int, float}
            and math.isfinite(rate)
            and rate >= 0
            and exchange.get("close_cost") == rate
            and exchange.get("deal_price") == "$open"
            and exchange.get("min_cost") == 0,
            "cost_contract_unsupported",
        )
        _require(request.get("snapshot_source") == "futu", "source_contract_missing")
        return {
            "schema": "research_family_compatibility/v1",
            "return_definition": "net_total_return",
            "benchmark": {"symbol": None, "method": "none"},
            "frequency": "daily",
            "cost_definition": {
                "model": "qlib_combined_bps",
                "one_way_bps": float(Decimal(str(rate)) * 10000),
                "min_cost": 0,
                "cash_interest": 0.0,
            },
            "market_data_contract": {
                "provider": "futu",
                "price_adjustment": "qfq",
                "currency": "USD",
                "bar": "1d",
            },
        }
