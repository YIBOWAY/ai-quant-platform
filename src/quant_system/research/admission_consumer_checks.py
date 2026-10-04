"""Fixed, executable checks for the bounded Phase2 consumer qualification.

No caller-selected code/check list and no self-reported pass file is executed.
The control population is the exact 2026-09-20 batch of 500 saved BacktestEngine
monthly equal-weight Top5 paths. It is not a PIT-universe or arbitrary-DSL
qualification. Account tests use a new disposable PostgreSQL container only.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.active_returns import recompute_active_returns
from quant_system.research.gate_v2.control import clopper_pearson_upper, load_null_calibration_v2
from quant_system.research.gate_v2.correlation_v2 import raw_concentration_v2
from quant_system.research.gate_v2.family import ArchivedCurveResolver, project_family_v2
from quant_system.research.gate_v2.verdict import (
    GATE_V2_CONFIG,
    evaluate_gate_v2,
    grade_v2,
    tier_for_grade,
    verify_verdict_v2,
)
from quant_system.research.trials import universe_digest

ROOT = Path(__file__).resolve().parents[3]
INPUTS_SHA = "4723c28f6c2834e5550e6f9cdabe88de9c48380a7f676d95910b664557f234d6"
RECEIPTS_SHA = "23b064a8f02135a3fe07f28feb7fe1abd7615ffe279dc3d13ef4f65cbb60dc63"
PRICES_SHA = "670c5cb2117cc25d36decfe94fb1647dc6de0123bf8e4358b55547e6cefce002"
LEDGER_SHA = "cb4f3939bd350636037a2c83d49447c5c17209e5770f4d3d71390cc4827f5628"
PEER_DIGEST = "c72621584495a36ef6a379b877a62725e1d7c627646bec63321e7c4623dfeef5"
CONTROL_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "GOOGL",
    "META",
    "AVGO",
    "ORCL",
    "CRM",
    "LMT",
    "RTX",
    "NOC",
    "GD",
    "HII",
    "LHX",
    "BA",
    "UNH",
    "JNJ",
    "PFE",
    "MRK",
    "ABBV",
    "TMO",
    "MDT",
    "AMGN",
]
CONTEXT = {
    "ordered_symbols": CONTROL_SYMBOLS,
    "ordered_universe_digest": _hash(CONTROL_SYMBOLS),
    "universe_digest": universe_digest(CONTROL_SYMBOLS),
    "top_n": 5,
    "rebalance": "monthly",
    "weights": "equal_weight_0.2",
    "execution_price": "next_open",
    "commission_bps": 1,
    "slippage_bps": 5,
    "benchmark_symbol": "SPY",
    "start": "2018-01-02",
    "end": "2026-09-08",
    "return_basis": "strategy_minus_benchmark_daily_arithmetic",
    "membership": "static_frozen_24",
    "engine_initial_cash": 100000,
    "whole_share_orders": False,
    "min_order_value": 0,
    "target_gross_exposure": 1,
    "max_weight_per_symbol": 1,
    "selection": "top",
    "leverage": False,
    "upgrade_target": None,
}
CONTROL_VERSIONS = {
    "futu24-saved-intake-20260924": {
        "inputs_sha256": "36dce2680f85a87c220a33b0b8c8e59bb7d803c7021306d8c0aaab6c8f2917e2",
        "receipts_sha256": "2ca0a3639a5efbabd79bf083cb1437d5000e799710dec22359d45a2cb222168c",
        "prices_sha256": "0880dbd7b809ae12f4a725bd8c504ec9d8b2de7267114db2fca3b53586e6e704",
        "context": {**CONTEXT, "end": "2026-09-24"},
    },
    "futu24-original-20260920": {
        "inputs_sha256": INPUTS_SHA,
        "receipts_sha256": RECEIPTS_SHA,
        "prices_sha256": PRICES_SHA,
        "context": CONTEXT,
    },
    "futu24-current-20260920": {
        "inputs_sha256": "fd0e88c9b1487fa7ef3256bae61e324c54ec3bbf852fb219959262f529ffbdfa",
        "receipts_sha256": "16a42e42308c58419a8e8b66fda23d8d56a3236737a27c56cae130b26b6f3b3e",
        "prices_sha256": "54b654e8577ce982ed1ee232d6030cd545f811bedfc288b63c0a9cf8101de52d",
        "context": {**CONTEXT, "end": "2026-09-18"},
    },
}
FIXED_TESTS = (
    "tests/test_control_window_identity.py",
    "tests/test_qualification_dependency_closure.py",
    "tests/test_admission_current_population_stage.py",
    "tests/test_control_family_snapshot.py",
    "tests/test_legacy_family_originals.py",
    "tests/test_d34_qlib_turnover.py",
    "tests/test_capital_peer_holdings.py",
    "tests/test_peer_account_attribution.py",
    "tests/test_registered_capital_integration.py",
    "tests/test_registered_family_evidence.py",
    "tests/test_external_intake.py",
    "tests/test_admission_v2.py",
    "tests/test_admission_v2_consumers.py",
    "tests/test_admission_v2_postgres.py",
    "tests/test_admission_warm_preflight.py",
    "tests/test_intake_replacement.py",
    "tests/test_strategy_replacement.py",
    "tests/test_admission_replacement_integration.py",
    "tests/test_replacement_dsr_invariant.py",
    "tests/test_admission_qualification_flow.py",
    "tests/test_admission_activation.py",
    "tests/test_admission_consumer_checks.py",
    "tests/test_admission_increment_identity.py",
    "tests/test_admission_dataset_20260924.py",
    "tests/test_admission_window.py",
    "tests/test_admission_auto_window_flow.py",
    "tests/test_admission_window_activation.py",
    "tests/test_admission_window_routing.py",
    "tests/test_new_capital_consumer.py",
    "tests/test_capital_evidence.py",
    "tests/test_capital_peer_binding.py",
    "tests/test_gate_current_contract.py",
    "tests/test_current_consumer_qualification.py",
)
_TEST_CACHE = {}
_TEST_RUN_LOGS = {}
_CALIBRATION_CACHE = {}
CURRENT_CONTROL_RULE = "current-common-quality-control-v1"
# This reader accepts the 2026-10-03 pre-sampling design only. A new design
# requires an explicit rule/version change, never a self-resealed descriptor.
SEMANTIC_CALIBRATION_PLAN = {
    "contract": "1230158f975e8809c81da9bbe910fdde785d110248e43c3376aaa3f9ebaf97fd",
    "addendum": "9942ab7b5ae9e6350dd9b826d75160047ca00f72f06c13a3e652966ed56a340f",
}
_CURRENT_EVIDENCE_KEYS = {"current_control_rule", "validation_path", "semantic_calibration"}
_CONTROL_WORK = ContextVar("current_consumer_control_work", default=None)


@contextmanager
def collect_control_execution_trace():
    """Per-attempt work facts, outside repeatable qualification semantics."""
    rows = []
    token = _CONTROL_WORK.set(rows)
    try:
        yield rows
    finally:
        _CONTROL_WORK.reset(token)


def _population_evidence(evidence):
    return {key: value for key, value in evidence.items() if key not in _CURRENT_EVIDENCE_KEYS}


def _saved_turnover(payload):
    """Reconstruct proportional turnover from original fills, never invert a gate."""
    cash = payload.get("evaluation_initial_cash")
    _require(
        type(cash) in {int, float} and math.isfinite(cash) and cash > 0,
        "current_control_initial_cash_unavailable",
    )
    trades = payload.get("trades")
    _require(isinstance(trades, list), "current_control_cost_fills_unavailable")
    amounts = []
    for trade in trades:
        _require(trade.get("side") in {"buy", "sell"}, "current_control_fill_side_invalid")
        for field in ("quantity", "fill_price", "requested_price", "commission"):
            value = trade.get(field)
            _require(
                type(value) in {int, float} and math.isfinite(value) and value >= 0,
                "current_control_fill_value_invalid",
            )
        _require(
            trade["quantity"] > 0 and trade["requested_price"] > 0,
            "current_control_fill_value_invalid",
        )
        sign = 1 if trade["side"] == "buy" else -1
        gross = trade["quantity"] * trade["fill_price"]
        _require(
            abs(trade["fill_price"] - trade["requested_price"] * (1 + sign * 0.0005)) <= 1e-7
            and abs(trade["commission"] - gross * 0.0001) <= 1e-7,
            "current_control_cost_contract_mismatch",
        )
        amounts.append(gross)
    return math.fsum(amounts) / cash


def inspect_current_consumer_scope(settings, validation_path):
    """Cheap read-only prerequisite before PG or any 500-control work.

    A measured candidate refusal is not a qualification failure by itself.
    Missing family/peer/original evidence is. This never registers or funds.
    """
    from quant_system.execution.assistant_remote import (
        _book_path,
        _certify_cost_sensitivity,
        _current_exposure_candidates,
        load_book,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
    from quant_system.research.admission_v2 import code_identity, ledger_snapshot, peer_snapshot
    from quant_system.research.capital_evidence import (
        CurrentFamilyResolver,
        _Originals,
        current_peer_exposures,
        registered_population_integrity,
    )
    from quant_system.research.capital_quality import evaluate_new_capital_quality
    from quant_system.research.gate_v2.family import (
        _validate_curve,
        compatibility_contract_from_result,
    )
    from quant_system.research.strategy_definition import StrategyDefinition, validate_definition
    from quant_system.research.trials import performance_from_daily_returns

    result = {
        "schema": "current_common_quality_consumer_scope/v1",
        "status": "not_evaluated",
        "reason": None,
        "reasons": [],
        "controls_run": 0,
        "postgres": "not_run",
        "funding_authority": False,
        "code": code_identity(),
    }
    originals = _Originals(settings.data.data_dir)
    try:
        _require(validation_path is not None, "current_consumer_validation_required")
        path = originals.path(validation_path)
        _require(
            path.name == "validation.json"
            and path.is_relative_to(originals.root / "strategy_library"),
            "current_consumer_validation_outside_owner",
        )
        validation = originals.read(path)
        payload = originals.read(path.parent / "platform-result.json")
        definition = StrategyDefinition.model_validate(
            originals.read(path.parent.parent.parent / "definition.json")
        )
        _require(
            payload.get("definition") == definition.model_dump(mode="json")
            and payload.get("definition_digest")
            == validation.get("definition_digest")
            == definition.content_digest
            and payload.get("profile", {}).get("symbols") == list(definition.symbols),
            "current_consumer_definition_binding_mismatch",
        )
        contract = compatibility_contract_from_result(payload, definition=definition)
        rows, ledger_sha = ledger_snapshot(settings)
        result["registered_population"] = registered_population_integrity(
            settings.data.data_dir, rows, definition.symbols, contract,
            load_book(settings)["candidates"],
        )
        if not result["registered_population"]["complete"]:
            result["reasons"].append("current_registered_population_incomplete")
        originals.pin(originals.root / "trials/trials.jsonl")
        resolver = CurrentFamilyResolver(originals.root, trusted_trials=rows)
        family = project_family_v2(
            trials_rows=rows,
            universe_digest=universe_digest(definition.symbols),
            compatibility_contract=contract,
            curve_resolver=resolver,
            legacy_resolver=resolver.legacy,
        )
        for archived in resolver.resolved.values():
            for key in ("family_evidence", "legacy_evidence"):
                for source, expected in (archived.get(key) or {}).get("files", {}).items():
                    original = originals.pin(source)
                    _require(
                        originals.files[str(original)] == expected, "current_family_source_changed"
                    )
        result.update(
            family=family,
            return_contract=contract,
            trial_ledger_sha256=ledger_sha,
            definition_digest=definition.content_digest,
        )
        if family["excluded"] or family["evidence_state"] != "complete" or not family["trusted"]:
            result["reasons"].append("current_family_evidence_incomplete")
        _validate_curve(payload["curve"], active=True)
        active = recompute_active_returns(
            payload["curve"], initial_cash=payload["evaluation_initial_cash"]
        )
        result["window"] = {
            "start": active["start"],
            "end": active["end"],
            "calendar_digest": _hash(active["dates"]),
        }
        result["ordered_symbols"] = list(definition.symbols)
        for name, expected in validation.get("receipts", {}).get("files", {}).items():
            original = originals.pin(path.parent / name)
            _require(
                originals.files[str(original)] == expected, "current_validation_original_changed"
            )
        book_path = _book_path(settings)
        book_exists = book_path.is_file()
        if book_exists:
            originals.pin(book_path)
        candidates = load_book(settings)["candidates"]
        storage = PaperStrategySleeveStorage(originals.root / "api_runs")
        physical_sources = {}
        for row in candidates:
            if not isinstance(row, dict) or not (
                row.get("sleeve_id") or row.get("status") == "hung"
            ):
                continue
            sleeve_id = str(row.get("sleeve_id") or "")
            for source in (storage.sleeve_path(sleeve_id), storage.sleeve_lots_path(sleeve_id)):
                source = source.resolve()
                _require(source.is_relative_to(originals.root), "peer_source_outside_owner")
                physical_sources[str(source)] = source.exists()
                if source.exists():
                    originals.pin(source)
        result["physical_peer_sources"] = physical_sources
        account_exposures = {}
        physical = _current_exposure_candidates(
            settings, candidates, storage=storage, exposure_evidence=account_exposures,
        )
        result["account_exposures"] = account_exposures
        peers, _ = current_peer_exposures(settings, physical, originals=originals)
        # Numeric return arrays and admission identities have different digests.
        # Preserve both; stage review must bind the real financial peer identity.
        result["admission_peer_digest"] = peer_snapshot(
            {"candidates": candidates}, settings=settings
        )[1]["digest"]
        concentration = raw_concentration_v2(
            candidate_returns=active["equity_returns"],
            candidate_dates=active["dates"],
            hung_sleeves=peers,
            require_dates=True,
        )
        concentration.update(applicable=bool(peers), passed=concentration["raw_passed"])
        result.update(peers=peers, peer_digest=_hash(peers), concentration=concentration)
        if concentration.get("raw_unavailable_sleeves"):
            result["reasons"].append("current_peer_correlation_unmeasurable")
        turnover = _saved_turnover(payload)
        cost = _certify_cost_sensitivity(
            {
                "performance": {
                    **performance_from_daily_returns(active["equity_returns"]),
                    "turnover_period": turnover,
                }
            },
            cost_bps=6,
        )
        result["minimum_quality"] = evaluate_new_capital_quality(
            selected_returns=active["active_returns"],
            total_returns=active["equity_returns"],
            dates=active["dates"],
            return_contract=contract,
            family=family,
            concentration=concentration,
            cost=cost,
            config=GATE_V2_CONFIG,
        )
        # Historical definitions can describe a missing family, but cannot grant
        # a current-source qualification even when that family is complete.
        try:
            validate_definition(definition)
        except ValueError:
            result["reasons"].append("current_candidate_implementation_changed")
        _require(ledger_snapshot(settings)[1] == ledger_sha, "current_consumer_ledger_changed")
        _require(book_path.is_file() == book_exists, "current_consumer_book_changed")
        _require(
            all(Path(source).exists() == exists for source, exists in physical_sources.items()),
            "current_consumer_physical_peers_changed",
        )
        originals.verify()
        if not result["reasons"]:
            result["status"] = "ready_for_verification"
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result["reasons"].append(str(exc))
    result["reason"] = result["reasons"][0] if result["reasons"] else None
    result["input_files"] = dict(sorted(originals.files.items()))
    result["scope_digest"] = _hash(result)
    return result


def verify_semantic_calibration(descriptor):
    """Verify the additional F artifact; never substitute it for PG/real controls."""
    import importlib.util

    result = {
        "status": "not_evaluated",
        "reason": None,
        "input_files": {},
        "population": "synthetic_no_peer_semantics_only",
        "replaces_pg": False,
        "replaces_current_real_control": False,
    }
    files = result["input_files"]
    try:
        _require(
            isinstance(descriptor, dict) and set(descriptor) == {"summary", "contract", "addendum"},
            "semantic_calibration_descriptor_required",
        )
        documents = {}
        for name, reference in descriptor.items():
            _require(
                isinstance(reference, dict) and set(reference) == {"path", "sha256"},
                "semantic_calibration_descriptor_invalid",
            )
            path = Path(reference["path"]).resolve(strict=True)
            _require(
                path.is_file() and _sha(path) == reference["sha256"],
                "semantic_calibration_file_changed",
            )
            files[str(path)] = reference["sha256"]
            documents[name] = json.loads(path.read_text())
        summary, contract, addendum = (documents[k] for k in ("summary", "contract", "addendum"))
        _require(
            summary.get("schema") == "admission_semantics_synthetic_calibration_result/v1"
            and summary.get("status") == "passed",
            "semantic_calibration_not_passed",
        )
        _require(
            all(descriptor[name]["sha256"] == expected
                for name, expected in SEMANTIC_CALIBRATION_PLAN.items()),
            "semantic_calibration_frozen_contract_mismatch",
        )
        _require(
            contract.get("schema") == "admission_semantics_synthetic_calibration/v1"
            and contract.get("status") == addendum.get("status") == "frozen_before_sampling"
            and summary.get("scope") == contract.get("scope")
            and contract.get("source", {}).get("selected_function")
            == "quant_system.research.capital_quality.evaluate_new_capital_quality"
            and summary.get("explicit_non_claims") == contract.get("explicit_non_claims"),
            "semantic_calibration_scope_mismatch",
        )
        directory = Path(descriptor["summary"]["path"]).resolve().parent
        binding_path = directory / "binding.json"
        binding = json.loads(binding_path.read_text())
        files[str(binding_path)] = _sha(binding_path)
        for name in ("contract", "addendum"):
            _require(
                binding[name] == documents[name]
                and binding[name + "_sha256"]
                == descriptor[name]["sha256"]
                == summary[name + "_sha256"],
                "semantic_calibration_contract_changed",
            )
        _require(
            addendum["parent_contract_sha256"] == descriptor["contract"]["sha256"],
            "semantic_calibration_parent_changed",
        )
        # Only the fixed repository-owned verifier is imported, never a path
        # chosen by the artifact. Its module top level performs no sampling.
        script = ROOT / "scripts/calibrate_admission_semantics.py"
        spec = importlib.util.spec_from_file_location(
            "_fixed_semantic_calibration_verifier", script
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_contract(contract, addendum)
        saved = binding["source_identity"]
        _require(
            module.digest(saved) == binding["source_digest"] == summary["source_digest"],
            "semantic_calibration_source_binding_invalid",
        )
        current = module.source_identity()
        _require(
            {k: v for k, v in current.items() if k != "package_path"}
            == {k: v for k, v in saved.items() if k != "package_path"},
            "semantic_calibration_source_changed",
        )
        cells, verified = module.cells(), []
        for holdout in (False, True):
            cell_root = directory / ("holdout" if holdout else "main")
            for cell in cells:
                if holdout and not (cell["primary_null"] or cell["primary_positive"]):
                    continue
                checked = module.load_completed_cell(
                    cell,
                    holdout=holdout,
                    output=cell_root,
                    expected_source=binding["source_digest"],
                )
                verified.append(checked)
                for suffix in (".jsonl", ".summary.json"):
                    path = cell_root / f"cell-{cell['index']:03d}{suffix}"
                    files[str(path)] = _sha(path)
        _require(
            verified == summary.get("cells")
            and len(verified) == 327
            and sum(row["replicates"] for row in verified) == summary.get("quality_calls") == 163500
            and not summary.get("forbidden")
            and summary.get("failed_replicates") == 0
            and all(row["failed_replicates"] == 0 for row in verified)
            and all(row["primary_acceptance"] is not False for row in verified)
            and all(row["pure_beta_risk_adjusted_zero"] is not False for row in verified),
            "semantic_calibration_results_not_qualified",
        )
        expected_engine = [
            cell
            for cell in cells
            if (cell["n"] == 126 and cell["case"] in {"null", "pure_beta", "positive_ir2"})
            or cell["primary_positive"]
        ]
        engines = summary.get("engine_examples")
        _require(
            isinstance(engines, list)
            and len(engines) == len(expected_engine) == 57
            and summary.get("confirmed_completed_engine_invocations") == 228,
            "semantic_calibration_engine_count_invalid",
        )
        for cell, engine in zip(expected_engine, engines, strict=True):
            path = directory / "engine" / f"cell-{cell['index']:03d}"
            _require(
                engine.get("cell") == cell
                and engine.get("status") == "completed"
                and engine.get("engine_invocations") == 4
                and engine.get("source_digest") == binding["source_digest"]
                and json.loads((path / "summary.json").read_text()) == engine,
                "semantic_calibration_engine_binding_changed",
            )
            _require(
                engine.get("accounting_tolerance_usd") == 1e-7
                and engine.get("rtol") == 0
                and all(
                    type(engine.get(key)) in {int, float}
                    and math.isfinite(engine[key])
                    and 0 <= engine[key] <= 1e-7
                    for key in (
                        "max_nav_error_usd",
                        "max_gross_turnover_error_usd",
                        "max_commission_error_usd",
                    )
                ),
                "semantic_calibration_engine_tolerance_failed",
            )
            for name, key in (
                ("input.json", "inputs_sha256"),
                ("ARTIFICIAL-prices.parquet", "prices_sha256"),
                ("cost-replay.json.gz", "outputs_sha256"),
            ):
                _require(
                    _sha(path / name) == engine[key], "semantic_calibration_engine_file_changed"
                )
                files[str(path / name)] = engine[key]
            for name in ("attempt.json", "summary.json"):
                files[str(path / name)] = _sha(path / name)
        recoveries = []
        for path in sorted((directory / "interrupted-engine-attempts").glob("*/recovery.json")):
            recovery = json.loads(path.read_text())
            _require(
                recovery.get("source_digest") == binding["source_digest"],
                "semantic_calibration_recovery_source_changed",
            )
            files[str(path)] = _sha(path)
            for name, expected in recovery["files"].items():
                original = (path.parent / name).resolve()
                _require(
                    original.is_relative_to(path.parent.resolve()) and _sha(original) == expected,
                    "semantic_calibration_recovery_file_changed",
                )
                files[str(original)] = expected
            recoveries.append(recovery)
        _require(
            recoveries == summary.get("interrupted_engine_attempts", []),
            "semantic_calibration_recovery_changed",
        )
        _require(
            all(_sha(path) == value for path, value in files.items()),
            "semantic_calibration_changed_during_read",
        )
        _require(
            {k: v for k, v in module.source_identity().items() if k != "package_path"}
            == {k: v for k, v in saved.items() if k != "package_path"},
            "semantic_calibration_source_changed_during_read",
        )
        result.update(
            status="passed",
            source_digest=binding["source_digest"],
            quality_calls=163500,
            engine_examples=57,
            interrupted_engine_attempts=recoveries,
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError) as exc:
        result["status"] = "not_evaluated"
        result["reason"] = str(exc)
    result["evidence_digest"] = _hash(result)
    return result


def _sha(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, sort_keys=True, allow_nan=False)


def freeze_peer_snapshot(source_book, output):
    """Copy only necessary numerical/source identities, never objectives or chat bodies."""
    from quant_system.research.admission_v2 import peer_snapshot

    book = json.loads(Path(source_book).read_text())
    _, identity = peer_snapshot(book)
    _require(identity["digest"] == PEER_DIGEST, "control_peer_population_changed")
    fields = {
        "candidate_id",
        "status",
        "sleeve_id",
        "definition_digest",
        "source_path",
        "source_digest",
        "candidate_code_digest",
        "comparison_digest",
        "verification_receipt_digest",
        "performance",
    }
    snapshot = {
        "candidates": [
            {key: value for key, value in row.items() if key in fields}
            for row in book["candidates"]
            if row.get("status") == "hung"
        ]
    }
    _require(peer_snapshot(snapshot)[1] == identity, "control_peer_projection_changed")
    _write(Path(output), snapshot)
    return {
        "path": str(Path(output).resolve()),
        "sha256": _sha(output),
        "peer_digest": identity["digest"],
    }


def freeze_family_snapshot(random_root, source_data_root, output):
    """Pin original family files by read-only aliases, without copying large price files.

    New live trials/validations do not change this historical calibration population.
    Every target is an already-existing archive file, with its original hash recorded.
    No aliases lead to the mutable formal ledger or book.
    """
    root, source, output = (
        Path(random_root),
        Path(source_data_root).resolve(),
        Path(output).resolve(),
    )
    _require(
        not output.is_relative_to(source) and not output.is_relative_to(root.resolve()),
        "control_snapshot_must_be_separate",
    )
    rows_path = root / "families/source-trials.jsonl"
    _require(_sha(rows_path) == LEDGER_SHA, "control_original_trial_population_changed")
    rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line]
    resolver = ArchivedCurveResolver(source, trusted_trials=rows)
    selected = {}
    for row in rows:
        metadata = row.get("metadata", {})
        digest = metadata.get("equity_curve_digest")
        # Equal returns can belong to different frozen implementations. Match
        # the reader's definition identity instead of the last curve-key entry.
        original = next(
            (item for item in resolver.family_curves.get(digest, [])
             if item[0].get("definition_digest") == metadata.get("strategy_definition_digest")),
            None,
        )
        if original is not None:
            _, path, _ = original
            for name in (
                "platform-result.json",
                "prices.parquet",
                "validation.json",
                "qlib-replay.json",
            ):
                item = path.parent / name
                selected[item] = _sha(item)
        legacy = resolver.legacy(row)
        if legacy:
            selected.update(
                {Path(path): digest for path, digest in legacy["legacy_evidence"]["files"].items()}
            )
    output.mkdir(parents=True, exist_ok=False)
    links = {}
    for path, digest in selected.items():
        _require(path.is_relative_to(source), "control_archive_outside_source")
        alias = output / path.relative_to(source)
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.symlink_to(path)
        links[str(alias.relative_to(output))] = {"original_path": str(path), "sha256": digest}
    _write(
        output / "snapshot-provenance.json",
        {
            "schema": "fixed_family_source_aliases/v1",
            "original_ledger_sha256": LEDGER_SHA,
            "files": links,
        },
    )
    return {"data_root": str(output), "files": len(links), "purpose": "historical_calibration_only"}


def concentration_inputs(curve, initial_cash, peers):
    """Compute the same aligned residual diagnostic/null used by the consumer."""
    active = recompute_active_returns(curve, initial_cash=initial_cash)
    benchmark = [
        x - y for x, y in zip(active["equity_returns"], active["active_returns"], strict=True)
    ]
    if not peers:
        return benchmark, {"status": "not_applicable", "reason": "no_hung_peers", "null_p95": None}
    raw = raw_concentration_v2(
        candidate_returns=active["equity_returns"],
        candidate_dates=active["dates"],
        hung_sleeves=peers,
    )
    if raw["raw_unavailable_sleeves"] or not raw["raw_by_sleeve"]:
        return benchmark, {
            "status": "not_evaluated",
            "reason": "peer_overlap_unavailable",
            "null_p95": None,
        }
    reference = max(raw["raw_by_sleeve"], key=lambda row: row["correlation"])
    peer = next(row for row in peers if row["sleeve_id"] == reference["sleeve_id"])
    other = dict(zip(peer["dates"], peer["returns"], strict=True))
    indices = [i for i, date in enumerate(active["dates"]) if date in other]
    result = load_null_calibration_v2(
        left_returns=[active["equity_returns"][i] for i in indices],
        right_returns=[other[active["dates"][i]] for i in indices],
        benchmark_returns=[benchmark[i] for i in indices],
        block_length=GATE_V2_CONFIG["null_block_length"],
        seed=GATE_V2_CONFIG["null_seed"],
        n_resamples=2000,
    )
    return benchmark, {
        **result,
        "status": "evaluated" if result["null_p95"] is not None else "not_evaluated",
        "reference_sleeve_id": peer["sleeve_id"],
        "overlap_periods": len(indices),
    }


def _control_spec(evidence, *, execution_trace=None):
    version = evidence.get("control_version", "futu24-original-20260920")
    base_keys = {"random_root", "data_root", "peer_snapshot_path"}
    if version == "futu24-auto-window-v1":
        from quant_system.research.admission_window import verify_control_artifacts

        _require(
            set(evidence) == base_keys | {
                "control_version", "window_manifest", "window_manifest_sha256"
            },
            "consumer_evidence_schema_invalid",
        )
        return verify_control_artifacts(
            evidence["window_manifest"], evidence["window_manifest_sha256"],
            evidence["random_root"],
            execution_trace=execution_trace,
        )
    _require(version in CONTROL_VERSIONS, "control_version_unsupported")
    _require(
        set(evidence) <= base_keys | {"control_version"},
        "consumer_evidence_schema_invalid",
    )
    return CONTROL_VERSIONS[version]


def _load_context(evidence, *, execution_trace=None):
    from quant_system.research.admission_v2 import peer_snapshot

    root, data_root = Path(evidence["random_root"]).resolve(), Path(evidence["data_root"]).resolve()
    spec = _control_spec(evidence, execution_trace=execution_trace)
    _require(_sha(root / "inputs.json") == spec["inputs_sha256"], "control_inputs_not_frozen_batch")
    inputs = json.loads((root / "inputs.json").read_text())
    receipts = {
        f"variant-{i:04d}/receipt.json": _sha(root / f"variant-{i:04d}/receipt.json")
        for i in range(500)
    }
    _require(_hash(receipts) == spec["receipts_sha256"], "control_receipt_population_changed")
    prices_path = Path(inputs["prices_path"])
    _require(
        _sha(prices_path) == inputs["prices_sha256"] == spec["prices_sha256"],
        "control_prices_changed",
    )
    for name, digest in inputs["source_hashes"].items():
        if name.startswith("src/quant_system/backtest/"):
            _require(_sha(ROOT / name) == digest, "control_engine_source_changed")
    snapshots = json.loads((root / "saved-study-snapshot.json").read_text())
    profile = next(
        row for row in snapshots["results"] if row["profile"]["id"] == "stocks_momentum_12_2"
    )
    _require(_hash(profile) == inputs["profile_digest"], "control_reference_profile_changed")
    _require(profile["profile"]["peer_symbols"] == CONTROL_SYMBOLS, "control_universe_changed")
    _require(
        profile["curve"][0]["date"] == spec["context"]["start"]
        and profile["curve"][-1]["date"] == spec["context"]["end"],
        "control_effective_window_changed",
    )
    frame = pd.read_parquet(prices_path)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["date"] = frame.timestamp.dt.strftime("%Y-%m-%d")
    _require(
        set(frame.provider) == {"futu"} and set(frame.price_adjustment) == {"qfq"},
        "control_provider_changed",
    )
    frame = frame.set_index(["date", "symbol"], verify_integrity=True)
    ledger_path = root / "families/source-trials.jsonl"
    ledger_sha = _sha(ledger_path)
    rows = [json.loads(line) for line in ledger_path.read_text().splitlines() if line]
    _require(
        ledger_sha == LEDGER_SHA and len(rows) == 40, "control_original_trial_population_changed"
    )
    resolver = ArchivedCurveResolver(data_root, trusted_trials=rows)
    native, legacy = {}, {}
    file_hashes = {
        **spec.get("extra_file_hashes", {}),
        str(prices_path): spec["prices_sha256"],
        str(ledger_path): ledger_sha,
        str(root / "inputs.json"): spec["inputs_sha256"],
        str(root / "saved-study-snapshot.json"): _sha(root / "saved-study-snapshot.json"),
        **{str(root / k): v for k, v in receipts.items()},
    }
    # Cache hits verify every underlying file, not just the receipt population.
    for relative in receipts:
        receipt_path = root / relative
        receipt = json.loads(receipt_path.read_text())
        for name, digest in receipt["files"].items():
            path = receipt_path.parent / name
            _require(_sha(path) == digest, "control_variant_file_changed")
            file_hashes[str(path)] = digest
    for row in rows:
        native[row["trial_id"]], legacy[row["trial_id"]] = resolver(row), resolver.legacy(row)
    for _, path, digest in resolver.curves.values():
        file_hashes[str(path)] = digest
    for matches in resolver.legacy_runs.values():
        for _, item in matches:
            file_hashes.update(item["files"])
    # Immutable in-memory snapshot, byte-verified before AND after the complete run.
    trusted = {row["trial_id"]: row for row in rows}

    def native_resolver(row):
        return native.get(row["trial_id"]) if row == trusted.get(row["trial_id"]) else None

    def legacy_resolver(row):
        return legacy.get(row["trial_id"]) if row == trusted.get(row["trial_id"]) else None

    family = project_family_v2(
        trials_rows=rows,
        universe_digest=CONTEXT["universe_digest"],
        curve_resolver=native_resolver,
        legacy_resolver=legacy_resolver,
    )
    _require(family["trusted"] and family["n_trials"] == 39, "control_full_family_unavailable")
    book_path = Path(evidence["peer_snapshot_path"]).resolve()
    peers, peer_identity = peer_snapshot(json.loads(book_path.read_text()))
    _require(
        len(peers) == 2 and peer_identity["digest"] == PEER_DIGEST,
        "control_requires_two_frozen_real_peers",
    )
    file_hashes[str(book_path)] = _sha(book_path)
    for row in peer_identity["bindings"]:
        candidate = next(
            c
            for c in json.loads(book_path.read_text())["candidates"]
            if c["candidate_id"] == row["candidate_id"]
        )
        file_hashes[candidate["source_path"]] = row["source_sha256"]
    return (
        root,
        frame,
        profile,
        rows,
        native_resolver,
        legacy_resolver,
        peers,
        family,
        peer_identity,
        file_hashes,
    )


def _check_variant(root, index, frame, profile, file_hashes, *, dynamic_window=False):
    directory = root / f"variant-{index:04d}"
    receipt = json.loads((directory / "receipt.json").read_text())
    _require(
        receipt["index"] == index and receipt["status"] == "completed", "control_variant_incomplete"
    )
    for name, digest in receipt["files"].items():
        _require(_sha(directory / name) == digest, "control_variant_file_changed")
        file_hashes[str(directory / name)] = digest
    config = json.loads((directory / "config.json").read_text())
    _require(
        all(
            config.get(key) == CONTEXT[key]
            for key in (
                "commission_bps",
                "slippage_bps",
                "execution_price",
                "whole_share_orders",
                "min_order_value",
            )
        ),
        "control_execution_contract_changed",
    )
    _require(
        config["initial_cash"] == 100000 and config["max_weight_per_symbol"] is None,
        "control_cash_contract_changed",
    )
    schedule = json.loads((directory / "schedule.json").read_text())
    # Dynamic populations were reconstructed from the fixed RNG by _control_spec.
    expected_count = len(profile["signals"]) if dynamic_window else 105
    _require(len(schedule) == expected_count, "control_schedule_changed")
    spy_dates = list(frame.xs("SPY", level="symbol").index)
    for item, original in zip(schedule, profile["signals"], strict=True):
        _require(
            item["signal_date"] == original["signal_date"]
            and item["trade_date"] == original["trade_date"],
            "control_schedule_not_same_window",
        )
        position = spy_dates.index(item["signal_date"])
        _require(spy_dates[position + 1] == item["trade_date"], "control_not_next_session")
        _require(
            sorted(item["eligible_symbols"]) == sorted(CONTROL_SYMBOLS)
            and len(item["targets"]) == 5
            and all(value == 0.2 for value in item["targets"].values()),
            "control_top5_changed",
        )
    payload = json.loads((directory / "platform-result.json").read_text())
    curve = payload["curve"]
    _require(
        payload["evaluation_initial_cash"] == 100000 and _hash(curve) == receipt["curve_digest"],
        "control_curve_changed",
    )
    _require(
        [row["date"] for row in curve] == [row["date"] for row in profile["curve"]]
        and all(
            row["benchmark"] == ref["benchmark"]
            for row, ref in zip(curve, profile["curve"], strict=True)
        ),
        "control_benchmark_or_calendar_changed",
    )
    fills = pd.read_parquet(directory / "trade_blotter.parquet")
    dates = pd.to_datetime(fills.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    quotes = frame.reindex(pd.MultiIndex.from_arrays([dates, fills.symbol]))["open"].to_numpy()
    sign = np.where(fills.side.eq("buy"), 1.0, -1.0)
    expected = quotes * (1 + sign * 5e-4)
    _require(
        np.isfinite(quotes).all()
        and np.allclose(fills.requested_price, quotes, rtol=1e-12, atol=1e-12),
        "control_fill_not_saved_open",
    )
    _require(
        np.allclose(fills.fill_price, expected, rtol=1e-12, atol=1e-12)
        and np.allclose(
            fills.commission, fills.quantity * fills.fill_price * 1e-4, rtol=1e-10, atol=1e-10
        ),
        "control_costs_not_1_and_5bps",
    )
    equity = pd.read_parquet(directory / "equity_curve.parquet")
    positions = pd.read_parquet(directory / "positions.parquet")
    _require(
        equity.cash.min() >= -1e-7 and positions.quantity.min() >= -1e-10,
        "control_leverage_detected",
    )
    _require(
        np.allclose(equity.equity, [row["equity"] for row in curve], rtol=1e-12, atol=1e-8),
        "control_nav_not_engine_curve",
    )
    _require(
        np.allclose(equity.cash + equity.market_value, equity.equity, rtol=1e-12, atol=1e-8),
        "control_nav_accounting_mismatch",
    )
    return (
        receipt,
        payload,
        {
            "saved_files": len(receipt["files"]),
            "fills": len(fills),
            "minimum_cash": float(equity.cash.min()),
            "linear_bps_fractional_model": True,
        },
    )


def _run_historical_full_control(evidence, *, output=None, probe_one=False):
    from quant_system.research.admission_v2 import code_identity

    started = time.monotonic()
    code = code_identity()
    (root, frame, profile, rows, resolver, legacy, peers, family, peer_identity, files) = (
        _load_context(evidence)
    )
    version = evidence.get("control_version", "futu24-original-20260920")
    supported_context = _control_spec(evidence)["context"]
    records, failures = [], []
    count = 1 if probe_one else 500
    for index in range(count):
        try:
            if version == "futu24-auto-window-v1":
                receipt, payload, inputs = _check_variant(
                    root, index, frame, profile, files, dynamic_window=True
                )
            else:
                receipt, payload, inputs = _check_variant(root, index, frame, profile, files)
            benchmark, null = concentration_inputs(payload["curve"], 100000, peers)
            gate = evaluate_gate_v2(
                curve_rows=payload["curve"],
                initial_cash=100000,
                universe_digest=CONTEXT["universe_digest"],
                benchmark_symbol="SPY",
                definition_digest=receipt["definition_digest"],
                trials_rows=rows,
                curve_resolver=resolver,
                legacy_resolver=legacy,
                hung_sleeves=peers,
                benchmark_returns=benchmark,
                null_p95=null["null_p95"],
                config=GATE_V2_CONFIG,
            )
            verified = verify_verdict_v2(
                gate, trusted_trials=rows, curve_resolver=resolver, legacy_resolver=legacy
            )
            evaluable = bool(
                verified
                and gate["family"]["trusted"]
                and gate["dsr"]["path"] == "data_driven"
                and gate["dsr"].get("reason") is None
                and isinstance(gate["dsr"].get("value"), (int, float))
                and math.isfinite(gate["dsr"]["value"])
                and all(
                    isinstance(gate["health"][key].get("value"), (int, float))
                    and math.isfinite(gate["health"][key]["value"])
                    for key in ("psr_total", "max_drawdown", "annual_volatility")
                )
                and not gate["concentration"]["raw_unavailable_sleeves"]
                and null["status"] == "evaluated"
            )
            record = {
                "index": index,
                "status": "evaluated" if evaluable else "not_evaluated",
                "gate_passed": evaluable and gate["tier_recommendation"]["tier"] == "T2",
                "gate": gate,
                "input_verification": inputs,
                "residual_calibration": null,
                "qualification_status": "not_evaluated",
                "capital_authorized": False,
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            record = {
                "index": index,
                "status": "not_evaluated",
                "reason": str(exc),
                "gate_passed": False,
            }
            failures.append({"index": index, "reason": str(exc)})
        records.append(record)
        if output:
            _write(Path(output) / "variants" / f"{index:04d}.json", record)
        if index % 10 == 0 and output:
            print(
                json.dumps(
                    {
                        "completed": index + 1,
                        "total": count,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                    }
                ),
                flush=True,
            )
    _require(
        all(_sha(path) == digest for path, digest in files.items()),
        "control_inputs_changed_during_run",
    )
    _require(code_identity() == code, "control_source_changed_during_run")
    evaluated = sum(row["status"] == "evaluated" for row in records)
    passed = sum(row["gate_passed"] for row in records)
    upper = clopper_pearson_upper(k=passed, n=evaluated) if evaluated else None
    normalized = copy.deepcopy(records)
    for record in normalized:
        if "gate" in record:
            record["gate"].pop("computed_at", None)
            record["gate"].pop("envelope_digest", None)
    summary = {
        "schema": "frozen_full_gate_control/v1",
        "control_version": version,
        "supported_context": supported_context,
        "effective_calendar_digest": _hash([row["date"] for row in profile["curve"]]),
        "scope": "full_gate_v2_statistics_not_full_intake_authorization",
        "purpose": "historical_diagnostic_not_current_common_quality",
        "qualification_reason": "historical_control_rule_only",
        "n_controls": count,
        "statistically_evaluable": evaluated,
        "not_evaluated": count - evaluated,
        "gate_passes": passed,
        "false_pass_rate": passed / evaluated if evaluated else None,
        "clopper_pearson_upper": upper,
        "calibration_passed": count == evaluated == 500 and passed / 500 <= 0.05 and upper <= 0.05,
        "components": {
            name: sum(bool(row.get("gate", {}).get(name, {}).get("passed")) for row in records)
            for name in ("dsr", "health", "concentration")
        },
        "tiers": dict(
            Counter(
                row.get("gate", {}).get("tier_recommendation", {}).get("tier", "unknown")
                for row in records
            )
        ),
        "upgrade_path": "not_applicable_new_independent_sleeve_only",
        "family": family,
        "peer_identity": peer_identity,
        "input_files": files,
        "results_digest": _hash(normalized),
        "code": code,
        "config": GATE_V2_CONFIG,
        "qualification_status": "not_evaluated",
        "capital_authorized": False,
        "new_trials": 0,
        "backtests_run": None if version == "futu24-auto-window-v1" else 0,
        "failures": failures,
    }
    if output:
        _write(Path(output) / "manifest.json", summary)
    if not probe_one:
        key = _hash({"code": code["digest"], "files": files, "peers": peer_identity})
        _CALIBRATION_CACHE[key] = summary
    return summary


def _current_control_contract(root, profile, files):
    """Read the saved control's own semantics, without borrowing a candidate label.

    The registered profile producer uses a USD daily, zero-interest engine and
    a net buy-and-hold benchmark. Provider, adjustment, frequency, benchmark
    identity and fee rates must all be present in its authenticated originals.
    No StrategyDefinition is invented for these historical random controls.
    """
    from quant_system.research.gate_v2.family import COMPATIBILITY_SCHEMA, _compatibility_contract

    root = Path(root)
    config_path = root / "variant-0000/config.json"
    snapshot_path = root / "saved-study-snapshot.json"
    _require(
        all(str(path) in files and _sha(path) == files[str(path)]
            for path in (config_path, snapshot_path)),
        "current_control_contract_original_unbound",
    )
    config = json.loads(config_path.read_text())
    _require(
        profile in json.loads(snapshot_path.read_text())["results"],
        "current_control_profile_not_original",
    )
    _require(
        profile["frequency"] == "daily" and config["annualization_factor"] == 252,
        "current_control_frequency_contract_unsupported",
    )
    return _compatibility_contract({
        "schema": COMPATIBILITY_SCHEMA,
        "return_definition": "arithmetic_net_active",
        "benchmark": {"symbol": profile["profile"]["benchmark_symbol"],
                      "method": "net_buy_and_hold"},
        "frequency": profile["frequency"],
        "cost_definition": {"model": "proportional_bps",
                            "commission_bps": config["commission_bps"],
                            "slippage_bps": config["slippage_bps"], "cash_interest": 0.0},
        "market_data_contract": {"provider": profile["source"],
                                 "price_adjustment": profile["price_adjustment"],
                                 "currency": "USD", "bar": "1d"},
    })


def _require_control_compatibility(candidate, control):
    _require(candidate == control, "current_control_compatibility_mismatch")
    return control


def _control_window_identity(verified_record, control_version):
    """Carry AUTO identity only from its already verified spec/result."""
    if control_version != "futu24-auto-window-v1":
        return {}
    value = verified_record.get("window_id")
    _require(isinstance(value, str) and bool(value), "current_control_window_identity_missing")
    return {"window_id": value}


def run_full_control(evidence, *, output=None, probe_one=False, settings=None):
    """Versioned control decision; old populations are never new funding proof."""
    if evidence.get("current_control_rule") != CURRENT_CONTROL_RULE:
        result = _run_historical_full_control(evidence, output=output, probe_one=probe_one)
        return {
            **result,
            "qualification_status": "not_evaluated",
            "qualification_reason": "historical_control_rule_only",
            "purpose": "historical_diagnostic_not_current_common_quality",
        }
    from quant_system.execution.assistant_remote import _certify_cost_sensitivity
    from quant_system.research.admission_v2 import code_identity
    from quant_system.research.capital_quality import evaluate_new_capital_quality
    from quant_system.research.trials import performance_from_daily_returns

    current = inspect_current_consumer_scope(settings, evidence.get("validation_path"))
    if current["status"] != "ready_for_verification":
        return {
            "schema": "current_common_quality_control/v1",
            "qualification_status": "not_evaluated",
            "reason": current["reason"],
            "current_scope": current,
            "calibration_passed": False,
            "n_controls": 0,
            "statistically_evaluable": 0,
            "gate_passes": None,
            "false_pass_rate": None,
            "clopper_pearson_upper": None,
            "capital_authorized": False,
        }
    population = _population_evidence(evidence)
    execution_trace = {
        "confirmed_profile_engine_runs": 0,
        "confirmed_variant_engine_runs": 0,
        "failed_call_engine_count_unknown": False,
    }
    try:
        root, frame, profile, _, _, _, _, _, _, files = _load_context(
            population, execution_trace=execution_trace
        )
        spec = _control_spec(population, execution_trace=execution_trace)
    finally:
        work = _CONTROL_WORK.get()
        if work is not None:
            work.append(copy.deepcopy(execution_trace))
    _require(
        current["ordered_symbols"] == spec["context"]["ordered_symbols"]
        and current["window"]["start"] == spec["context"]["start"]
        and current["window"]["end"] == spec["context"]["end"],
        "current_control_window_or_universe_mismatch",
    )
    window_identity = _control_window_identity(spec, population.get("control_version"))
    control_contract = _require_control_compatibility(
        current["return_contract"], _current_control_contract(root, profile, files)
    )
    count, rows, failures = (1 if probe_one else 500), [], []
    for index in range(count):
        try:
            receipt, payload, verified = _check_variant(
                root,
                index,
                frame,
                profile,
                files,
                dynamic_window=population.get("control_version") == "futu24-auto-window-v1",
            )
            active = recompute_active_returns(payload["curve"], initial_cash=100000)
            _require(
                _hash(active["dates"]) == current["window"]["calendar_digest"],
                "current_control_calendar_mismatch",
            )
            fills = pd.read_parquet(root / f"variant-{index:04d}" / "trade_blotter.parquet")
            turnover = math.fsum((fills.quantity * fills.fill_price).tolist()) / 100000
            cost = _certify_cost_sensitivity(
                {
                    "performance": {
                        **performance_from_daily_returns(active["equity_returns"]),
                        "turnover_period": turnover,
                    }
                },
                cost_bps=6,
            )
            concentration = raw_concentration_v2(
                candidate_returns=active["equity_returns"],
                candidate_dates=active["dates"],
                hung_sleeves=current["peers"],
                require_dates=True,
            )
            concentration.update(
                applicable=bool(current["peers"]), passed=concentration["raw_passed"]
            )
            quality = evaluate_new_capital_quality(
                selected_returns=active["active_returns"],
                total_returns=active["equity_returns"],
                dates=active["dates"],
                return_contract=control_contract,
                family=current["family"],
                concentration=concentration,
                cost=cost,
                config=GATE_V2_CONFIG,
            )
            evaluable = (
                quality["dsr"].get("reason") is None
                and not concentration.get("raw_unavailable_sleeves")
                and not any(
                    reason in quality["reasons"]
                    for reason in (
                        "cost_evidence_invalid",
                        "return_contract_invalid",
                        "family_members_invalid",
                        "family_evidence_incomplete",
                        "correlation_unmeasured_blocked",
                    )
                )
            )
            record = {
                "index": index,
                "status": "evaluated" if evaluable else "not_evaluated",
                "gate_passed": bool(evaluable and quality["eligible"]),
                "minimum_quality": quality,
                "return_contract": control_contract,
                "input_verification": verified,
                "control_definition_digest": receipt["definition_digest"],
                "turnover_from_original_fills": turnover,
                "capital_authorized": False,
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            record = {
                "index": index,
                "status": "not_evaluated",
                "reason": str(exc),
                "gate_passed": False,
            }
            failures.append({"index": index, "reason": str(exc)})
        rows.append(record)
        if output:
            _write(Path(output) / "variants" / f"{index:04d}.json", record)
    _require(
        inspect_current_consumer_scope(settings, evidence["validation_path"]) == current,
        "current_control_scope_changed_during_run",
    )
    _require(
        all(_sha(path) == value for path, value in files.items()),
        "control_inputs_changed_during_run",
    )
    _require(code_identity() == current["code"], "control_source_changed_during_run")
    evaluated = sum(row["status"] == "evaluated" for row in rows)
    passed = sum(row["gate_passed"] for row in rows)
    upper = clopper_pearson_upper(k=passed, n=evaluated) if evaluated else None
    summary = {
        "schema": "current_common_quality_control/v1",
        "current_control_rule": CURRENT_CONTROL_RULE,
        "control_version": population.get("control_version", "futu24-original-20260920"),
        # Only the verified control spec supplies this identity. Stage review
        # compares it with the separately verified data-window provenance.
        **window_identity,
        "supported_context": spec["context"],
        "current_scope": current,
        "purpose": "same_frozen_engine_originals_rejudged_under_current_family_and_minimum_quality",
        "n_controls": count,
        "statistically_evaluable": evaluated,
        "not_evaluated": count - evaluated,
        "gate_passes": passed,
        "false_pass_rate": passed / evaluated if evaluated else None,
        "clopper_pearson_upper": upper,
        "calibration_passed": count == evaluated == 500 and passed / 500 <= 0.05 and upper <= 0.05,
        "components": {
            name: sum(
                bool(row.get("minimum_quality", {}).get(name, {}).get("passed")) for row in rows
            )
            for name in ("dsr", "health", "concentration", "cost")
        },
        "input_files": {**files, **current["input_files"]},
        "results_digest": _hash(rows),
        "family": current["family"],
        "peer_identity": {"digest": current["peer_digest"]},
        "failures": failures,
        "code": current["code"],
        "config": GATE_V2_CONFIG,
        "qualification_status": "not_evaluated",
        "capital_authorized": False,
        "new_trials": 0,
        "decision_only_backtests_run": 0,
        "engine_revalidation": execution_trace,
    }
    if output:
        _write(Path(output) / "manifest.json", summary)
    return summary


def _fixed_consumer_tests(code_digest, *, settings=None):
    hashes = {name: _sha(ROOT / name) for name in FIXED_TESTS}
    docker = shutil.which("docker")
    _require(bool(docker), "consumer_test_docker_missing")
    name = "phase2-qualification-pg-" + uuid4().hex[:12]

    def command(args, timeout=30):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)

    image_id = command([docker, "image", "inspect", "postgres:16-alpine", "--format", "{{.Id}}"])
    image_id = image_id.stdout.strip()
    key = _hash({"code": code_digest, "tests": hashes, "postgres_image": image_id})
    if key in _TEST_CACHE:
        return copy.deepcopy(_TEST_CACHE[key])

    container = None
    try:
        container = command(
            [
                docker,
                "run",
                "--rm",
                "--pull=never",
                "-d",
                "--name",
                name,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=admission_qualification_test",
                "-p",
                "127.0.0.1::5432",
                image_id,
            ]
        ).stdout.strip()
        port = command([docker, "port", name, "5432"]).stdout.strip().rsplit(":", 1)[1]
        for _ in range(100):
            ready = subprocess.run(
                [docker, "exec", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=3,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise ValueError("consumer_test_pg_unavailable")
        with tempfile.TemporaryDirectory(prefix="phase2-consumer-checks-") as temporary:
            report = Path(temporary) / "junit.xml"
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT / "src"),
                "QS_DATA_DIR": str(Path(temporary) / "data"),
                "QS_TEST_DATABASE_URL": f"postgresql://postgres@127.0.0.1:{port}/admission_qualification_test",
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-o",
                    "addopts=",
                    f"--junitxml={report}",
                    *FIXED_TESTS,
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
            )
            document = ET.parse(report).getroot()
            cases = sorted(
                (
                    case.attrib["classname"] + "::" + case.attrib["name"],
                    "failed"
                    if case.find("failure") is not None or case.find("error") is not None
                    else "skipped"
                    if case.find("skipped") is not None
                    else "passed",
                )
                for case in document.iter("testcase")
            )
            status = (
                completed.returncode == 0
                and len(cases) >= 80
                and all(state == "passed" for _, state in cases)
            )
            result = {
                "status": "passed" if status else "not_evaluated",
                "cases": [list(case) for case in cases],
                "test_source_hashes": hashes,
                "code_digest": code_digest,
                "postgres": "real_disposable_postgres_16",
                "postgres_image_digest": image_id,
                "production_database_used": False,
                "producer_capability": "sealed_in_consumer_tests",
            }
            # Preserve original bytes before TemporaryDirectory cleanup. These
            # are execution traces, not reconstructed XML or authority inputs.
            _TEST_RUN_LOGS[_hash(result)] = {
                "junit.xml": report.read_bytes(),
                "stdout.txt": completed.stdout.encode(),
                "stderr.txt": completed.stderr.encode(),
                "execution.json": json.dumps(
                    {
                        "exit_code": completed.returncode,
                        "code_digest": code_digest,
                        "test_source_hashes": hashes,
                        "postgres_image_digest": image_id,
                        "production_database_used": False,
                    },
                    sort_keys=True,
                ).encode(),
            }
            if settings is not None:
                # Persist while the original temporary XML still exists, even
                # if a later statistical replay or process shutdown fails.
                _persist_test_execution(settings, result)
    finally:
        if container:
            subprocess.run(
                [docker, "stop", container], capture_output=True, timeout=30, check=False
            )
    _TEST_CACHE[key] = result
    return copy.deepcopy(result)


def _persist_test_execution(settings, result):
    """Keep exact XML/log bytes while qualification's semantic identity is stable.

    Every cold verifier still executes tests. Its deterministic result points
    to the first byte-closed trace for those same code/tests/image/cases; later
    real executions are retained separately and never replace that first run.
    """
    from quant_system.research.external_intake import _private_directory

    semantic = _hash(result)
    raw = _TEST_RUN_LOGS.get(semantic)
    _require(raw is not None, "consumer_test_execution_bytes_missing")
    names = {"junit.xml", "stdout.txt", "stderr.txt", "execution.json"}
    _require(set(raw) == names, "consumer_test_execution_closure_invalid")
    root = (
        Path(settings.data.data_dir).resolve()
        / "research_intake/admission_v2/test-executions"
        / semantic
    )
    _private_directory(root)
    import hashlib

    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    run = root / "runs" / _hash(hashes)
    _private_directory(run)
    for name, value in raw.items():
        path = run / name
        if path.exists():
            _require(_sha(path) == hashes[name], "consumer_test_execution_changed")
        else:
            with path.open("xb") as handle:
                handle.write(value)
            path.chmod(0o600)
    manifest = root / "first-execution.json"
    if not manifest.exists():
        _write(
            manifest,
            {
                "schema": "fixed_consumer_test_execution/v1",
                "semantic_digest": semantic,
                "result": result,
                "files": {str(run / k): v for k, v in hashes.items()},
            },
        )
        manifest.chmod(0o600)
    saved = json.loads(manifest.read_text())
    files = saved.get("files", {})
    _require(
        isinstance(files, dict) and len(files) == 4 and {Path(p).name for p in files} == names,
        "consumer_test_execution_closure_invalid",
    )
    parents = {Path(p).parent for p in files}
    _require(len(parents) == 1, "consumer_test_execution_closure_invalid")
    original_run = parents.pop()
    _require(
        original_run.parent == root / "runs"
        and original_run.name == _hash({Path(p).name: s for p, s in files.items()})
        and not original_run.is_symlink()
        and all(not Path(p).is_symlink() for p in files)
        and {p.name for p in original_run.iterdir()} == names,
        "consumer_test_execution_closure_invalid",
    )
    _require(
        saved["semantic_digest"] == semantic
        and saved["result"] == result
        and all(_sha(p) == v for p, v in saved["files"].items()),
        "consumer_test_execution_changed",
    )
    return {"path": str(manifest), "sha256": _sha(manifest), "files": saved["files"]}


def verify_consumer_checks(settings, *, code_digest, scope, evidence):
    """Fixed verifier consumed by admission_qualifier; file claims are not evidence."""
    from quant_system.research.admission_v2 import SCOPE, code_identity

    names = (
        "legacy_path_unchanged",
        "full_gate_calibration",
        "new_funding_cas",
        "failure_zero_effects",
    )
    checks = {
        name: {"status": "not_evaluated", "reason": "consumer_verification_incomplete"}
        for name in names
    }
    result = {
        "checks": checks,
        "supported_context": CONTEXT,
        "supported_operations": ["new_independent"],
    }
    try:
        _require(
            scope == SCOPE and code_digest == code_identity()["digest"],
            "consumer_code_or_scope_mismatch",
        )
        current = inspect_current_consumer_scope(settings, evidence.get("validation_path"))
        result["current_scope"] = current
        if current["status"] != "ready_for_verification":
            result.update(reason=current["reason"], retryable=False)
            result["evidence_digest"] = _hash(result)
            return result
        if evidence.get("current_control_rule") != CURRENT_CONTROL_RULE:
            result.update(reason="current_control_contract_required", retryable=False)
            result["evidence_digest"] = _hash(result)
            return result
        semantic = verify_semantic_calibration(evidence.get("semantic_calibration"))
        result["semantic_calibration"] = semantic
        if semantic["status"] != "passed":
            result.update(reason=semantic["reason"], retryable=False)
            result["evidence_digest"] = _hash(result)
            return result
        population = _population_evidence(evidence)
        _require(
            set(population)
            in (
                {"random_root", "data_root", "peer_snapshot_path"},
                {"random_root", "data_root", "peer_snapshot_path", "control_version"},
                {
                    "random_root",
                    "data_root",
                    "peer_snapshot_path",
                    "control_version",
                    "window_manifest",
                    "window_manifest_sha256",
                },
            ),
            "consumer_evidence_schema_invalid",
        )
        version = evidence.get("control_version", "futu24-original-20260920")
        result["control_version"] = version
        # Infrastructure or genuine consumer test failures precede the costly
        # statistical replay. The strategy engine is never invoked here.
        tests = _fixed_consumer_tests(code_digest, settings=settings)
        result["tests"] = tests
        result["test_execution_evidence"] = _persist_test_execution(settings, tests)
        if tests["status"] != "passed":
            result["reason"] = "fixed_test_execution_failed"
            result["retryable"] = False
            result["evidence_digest"] = _hash(result)
            return result
        cache_key = _hash(
            {
                "code": code_digest,
                "current_scope": current["scope_digest"],
                "population": population,
                "semantic": semantic["evidence_digest"],
            }
        )
        if cache_key not in _CALIBRATION_CACHE:
            measured = run_full_control(evidence, settings=settings)
            _CALIBRATION_CACHE[cache_key] = {
                k: v for k, v in measured.items() if k != "engine_revalidation"
            }
        calibration = _CALIBRATION_CACHE[cache_key]
        _require(
            calibration.get("schema") == "current_common_quality_control/v1"
            and calibration.get("current_control_rule") == CURRENT_CONTROL_RULE,
            "current_control_result_required",
        )
        _require(
            calibration.get("current_scope") == current,
            "current_control_scope_changed_before_checks",
        )
        _require(
            all(_sha(path) == value for path, value in calibration["input_files"].items()),
            "current_control_original_changed",
        )
        result["supported_context"] = calibration["supported_context"]
        result["current_control_rule"] = CURRENT_CONTROL_RULE
        result.update(_control_window_identity(calibration, version))
        result["calibration_digest"] = _hash(calibration)
        # Preserve the fixed producer's actual aggregate, including the result
        # digest and every original variant's file binding. Capture timestamps
        # must never make cold re-verification differ from registration.
        result["calibration"] = {
            key: value
            for key, value in calibration.items()
            if key not in {"elapsed_seconds", "generated_at", "computed_at", "captured_at"}
        }
        result["variant_evidence_root"] = str(Path(evidence["random_root"]).resolve())
        result["variant_evidence_kind"] = "verified_original_engine_receipts"
        result["current_control_population"] = {
            "family_digest": calibration["family"]["family_digest"],
            "family_n_trials": calibration["family"]["n_trials"],
            "original_ledger_sha256": current["trial_ledger_sha256"],
            "peer_digest": calibration["peer_identity"]["digest"],
            "admission_peer_digest": current["admission_peer_digest"],
            "peer_windows": [
                {
                    "sleeve_id": peer["sleeve_id"],
                    "start": peer["dates"][0],
                    "end": peer["dates"][-1],
                    "periods": len(peer["dates"]),
                }
                for peer in current["peers"]
            ],
            "concentration_alignment": "actual_date_intersection_not_full_candidate_window",
            "control_version": version,
            "n_controls": calibration["n_controls"],
            "statistically_evaluable": calibration["statistically_evaluable"],
            "purpose": "fixed_real_price_controls_under_current_complete_family_and_strict_peers",
        }
        checks["full_gate_calibration"] = {
            "status": "passed" if calibration["calibration_passed"] else "not_evaluated",
            "reason": None
            if calibration["calibration_passed"]
            else "full_gate_control_not_qualified",
            "supported_context": result["supported_context"],
            "statistically_evaluable": calibration["statistically_evaluable"],
        }
        result["historical_family_39"] = {
            "purpose": "original_engine_population_provenance_only",
            "new_funding_qualification": False,
        }
        for name in ("legacy_path_unchanged", "new_funding_cas", "failure_zero_effects"):
            checks[name] = {
                "status": tests["status"],
                "reason": None if tests["status"] == "passed" else "fixed_test_execution_failed",
            }
        invariant = replacement_dsr_necessary_condition()
        dsr_upper = clopper_pearson_upper(
            k=calibration["components"]["dsr"], n=calibration["statistically_evaluable"]
        )
        result["replacement_null_bound"] = {
            "evidence_type": "derived_from_common_dsr_necessary_condition",
            "direct_replacement_control_runs": 0,
            "population": "same_fixed_500_candidates_and_benchmarks_only",
            "observed_passes_upper_bound": calibration["components"]["dsr"],
            "clopper_pearson_upper_bound": dsr_upper,
            "concentration_monotonicity_claimed": False,
            "invariant": invariant,
        }
        if (
            calibration["calibration_passed"]
            and tests["status"] == "passed"
            and invariant["status"] == "passed"
            and dsr_upper <= 0.05
        ):
            result["supported_operations"].append("replacement")
    except Exception as exc:
        result["error"] = str(exc)
        result["reason"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["retryable"] = (
            isinstance(exc, (subprocess.TimeoutExpired, subprocess.CalledProcessError))
            or isinstance(exc, OSError)
            and not isinstance(exc, FileNotFoundError)
            or str(exc) in {"consumer_test_pg_unavailable", "consumer_test_docker_missing"}
        )
    result["evidence_digest"] = _hash(result)
    return result


def replacement_dsr_necessary_condition():
    """Exhaust Boolean branches with failed DSR; never claims account experiments."""
    checks = []
    for raw_passed in (False, True):
        for applicable in (False, True):
            for accepted in (False, True):
                for trusted in (False, True):
                    grade = grade_v2(
                        dsr={"passed": False, "n_periods": 260, "path": "data_driven"},
                        health={"passed": True},
                        concentration={"applicable": applicable, "raw_passed": raw_passed},
                        upgrade={
                            "applicable": True,
                            "upgrade_accepted": accepted,
                            "accepted_evidence": "primary" if accepted else None,
                        },
                        family={"trusted": trusted},
                        config=GATE_V2_CONFIG,
                    )
                    checks.append(tier_for_grade(grade["grade"]) == "T0")
    return {
        "status": "passed" if all(checks) else "not_evaluated",
        "branches": len(checks),
        "rule": "DSR_false_implies_T0_independent_of_pair_or_target_concentration",
    }
