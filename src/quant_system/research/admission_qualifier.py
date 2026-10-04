"""Fixed, recomputed qualifications; catalog JSON never supplies authority.

Registration stores a deterministic recipe and its observed result. Verification
reruns only the local fixed checks and compares the result; there is no signing
API, checked=True input, uploaded executable, or trusted self-reported pass.
This issuer cannot flip the admission switch or allocate funds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from quant_system.research.evaluation_service import _hash

SCHEMA = "admission_fixed_qualification_registration/v1"
ISSUER = "fixed_local_admission_qualifier/v1"
SCOPE = "new_explicit_static_us_daily_ohlcv_dsl_intake"
REQUIRED = {
    "review": {"bounded_behavior", "independent_holdout", "source_input_identity"},
    "data": {"provider_provenance", "calendar_coverage", "universe_identity", "usage_restrictions"},
    "consumer": {
        "legacy_path_unchanged",
        "full_gate_calibration",
        "new_funding_cas",
        "failure_zero_effects",
    },
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVIEW_BUNDLE = "2e35b01dcbc75c31725fc18d0bc0c76720ffad2e578b969ebe43ae517d35596c"
_REVIEW_RUN = "paired-run-4a267d44ce5e"
_REVIEW_SOURCES = {
    "src/quant_system/research/behavior_review.py": (
        "8745dad17a94a85df4b881480af3f65d140185240bf0072652ba076775bee604"
    ),
    "src/quant_system/research/exploration_sandbox.py": (
        "68cfcbebda1d4ab62106d7f2ea424855d453f7075dab650f2fd8c949efd16321"
    ),
    "scripts/exploration_sandbox_runner.py": (
        "d921abb4801a08b7ab729c8951d970b11dd73f5a8b470a5b8dcc6221c977e289"
    ),
    "src/quant_system/d34/qlib_expr.py": (
        "b2cbae76739b63dbc1519b64517d0fdfa70f9e135d13d4d5bd0bd379ed1669e1"
    ),
}
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
CONTROL_CONTEXT = {
    "ordered_symbols": CONTROL_SYMBOLS,
    "ordered_universe_digest": _hash(CONTROL_SYMBOLS),
    "benchmark_symbol": "SPY",
    "start": "2018-01-02",
    "end": "2026-09-08",
    "rebalance": "monthly",
    "top_n": 5,
    "execution_price": "next_open",
    "return_basis": "strategy_minus_benchmark_daily_arithmetic",
    "commission_bps": 1,
    "slippage_bps": 5,
    "target_gross_exposure": 1,
    "max_weight_per_symbol": 1,
    "selection": "top",
    "min_order_value": 0,
    "whole_share_orders": False,
}
CURRENT_DATASET = "futu24-current-20260920"
CURRENT_MANIFEST_SHA = "076d7b4790ba12b51e6a323647c13647c7f8e2095e1e16902e4085ebc54cdef9"
SEPTEMBER24_DATASET = "futu24-saved-intake-20260924"
SEPTEMBER24_MANIFEST_SHA = "85496a73ab4b7b01823af3447fa339802e886391ac0694934ae089cc106642c9"


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(
        Path(path).read_text(),
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )


def _registry(settings):
    return (
        Path(settings.data.data_dir).resolve() / "research_intake/admission_v2/qualifier_registry"
    )


def _unknown(reason, checks=None):
    return {
        "status": "not_evaluated",
        "reason": reason,
        "verified_checks": checks or [],
        "registration_digest": None,
        "issuer_id": ISSUER,
    }


def _check_failure(exc):
    retryable = isinstance(exc, (OSError, subprocess.TimeoutExpired)) and not isinstance(
        exc, FileNotFoundError
    )
    return {
        "checks": {},
        "reason": "qualification_fixed_check_timeout"
        if isinstance(exc, subprocess.TimeoutExpired)
        else str(exc),
        "error_type": type(exc).__name__,
        "retryable": retryable,
    }


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def require_supported_data_context(dataset, context):
    """A 24-stock control cannot silently qualify different execution semantics."""
    if dataset == "futu24-auto-window-v1":
        from quant_system.research.admission_window import window_context

        expected = window_context(context["end"])
        _require(
            all(context.get(key) == expected[key] for key in (*CONTROL_CONTEXT, "history_start")),
            "qualification_calibration_context_mismatch",
        )
    elif dataset == SEPTEMBER24_DATASET:
        _require(
            all(context.get(key) == value for key, value in
                {**CONTROL_CONTEXT, "end": "2026-09-24"}.items()),
            "qualification_calibration_context_mismatch",
        )
    elif dataset in {"futu-study-20260909-24", CURRENT_DATASET}:
        expected = (
            CONTROL_CONTEXT
            if dataset != CURRENT_DATASET
            else {**CONTROL_CONTEXT, "end": "2026-09-18"}
        )
        _require(
            all(context.get(key) == value for key, value in expected.items()),
            "qualification_calibration_context_mismatch",
        )


def _review_checks(evidence):
    """Recompute semantics on pinned independent raw receipts; execute no supplied code."""
    import pandas as pd

    from quant_system.research.behavior_review import (
        checked_scores,
        prepare_input,
        verify_translation,
    )
    from quant_system.research.exploration_sandbox import digest, records

    _require(set(evidence) == {"root"}, "qualification_recipe_invalid")
    root = Path(evidence["root"])
    frozen_path = root / "frozen_paired_holdout.json"
    _require(
        file_sha(frozen_path) == "51b6d5961a90dea4da38c285f24b42454e2798682819a44615378633c2db9fcd",
        "qualification_review_corpus_unrecognized",
    )
    frozen = _read(frozen_path)
    paths = ["frozen_paired_holdout.json"] + [
        f"{_REVIEW_RUN}/{case['id']}.json" for case in frozen["cases"]
    ]
    _require(
        _hash({p: file_sha(root / p) for p in paths}) == _REVIEW_BUNDLE,
        "qualification_review_bundle_changed",
    )
    repo = Path(__file__).resolve().parents[3]
    _require(
        all(file_sha(repo / p) == expected for p, expected in _REVIEW_SOURCES.items()),
        "qualification_review_source_version_changed",
    )
    raw_frame = pd.DataFrame(frozen["ohlcv"])
    for key in ("timestamp", "available_at"):
        raw_frame[key] = pd.to_datetime(raw_frame[key], utc=True)
    frame = prepare_input(raw_frame)
    input_digest = digest({"ohlcv": records(raw_frame), "context": frozen["context"]})
    counts = {"defects": 0, "historical_holdout_defects": 0, "correct": 0, "unsupported": 0}
    executions = 0
    for case in frozen["cases"]:
        report = _read(root / f"{_REVIEW_RUN}/{case['id']}.json")["report"]
        _require(
            hashlib.sha256(case["source"].encode()).hexdigest()
            == case["source_sha256"]
            == report["source_sha256"],
            "qualification_review_code_input_changed",
        )
        _require(
            report["input_digest"] == input_digest
            and report["review_digest"]
            == digest({k: v for k, v in report.items() if k != "review_digest"}),
            "qualification_review_code_input_changed",
        )
        if not case["supported"]:
            _require(report["status"] == "not_evaluated", "qualification_review_unsupported_passed")
            counts["unsupported"] += 1
            continue
        score_records = pd.DataFrame(report["scores"])[["symbol", "timestamp", "score"]].to_dict(
            "records"
        )
        scores = checked_scores({"status": "ok", "scores": score_records}, frame)
        actual = verify_translation(case["expression"], frame, scores)
        _require(
            actual == report["reference"]["comparisons"]["baseline"],
            "qualification_review_semantics_changed",
        )
        _require(
            actual["status"] == ("fail" if case["defective"] else "pass"),
            "qualification_review_misclassified",
        )
        counts["defects" if case["defective"] else "correct"] += 1
        if case["defective"] and case["id"] != "D16":
            counts["historical_holdout_defects"] += 1
        for run in report["executions"].values():
            isolation = run.get("isolation", {})
            _require(
                isolation.get("network_mode") == "none"
                and isolation.get("readonly_rootfs") is True
                and isolation.get("input_readonly") is True
                and isolation.get("pids_limit") == 32
                and isolation.get("user") == "65534:65534",
                "qualification_review_isolation_missing",
            )
            executions += 1
    _require(
        counts == {"defects": 32, "historical_holdout_defects": 31, "correct": 8, "unsupported": 3},
        "qualification_review_coverage_missing",
    )
    return {
        "checks": {key: {"status": "passed"} for key in REQUIRED["review"]},
        "evidence_digest": _REVIEW_BUNDLE,
        "counts": counts,
        "bound_execution_receipts": executions,
        "source_hashes": _REVIEW_SOURCES,
        "supported_context": {
            "contract": "declared_whitelist_daily_ohlcv_dsl",
            "historical_independent_holdout": True,
            "fresh_holdout_rerun": False,
            "current_version_known_corpus_replayed": True,
            "new_holdout_cases": 0,
            "arbitrary_python_qualified": False,
        },
        "reason": None,
    }


def inspect_data_binding(settings, validation_path):
    """Reconstruct consumer identity from owner-root originals, never caller claims."""
    from quant_system.execution.assistant_remote import load_book
    from quant_system.research import admission_v2 as admission
    from quant_system.research.external_intake import _load_job
    from quant_system.research.strategy_definition import StrategyDefinition, validate_definition
    from quant_system.research.validation_receipts import verify_validation_receipt

    path = Path(validation_path).resolve()
    _require(
        path.is_relative_to(Path(settings.data.data_dir).resolve() / "strategy_library")
        and path.name == "validation.json",
        "qualification_validation_outside_owner_root",
    )
    value = _read(path)
    source = path.parent.parent.parent / "definition.json"
    definition = validate_definition(_read(source))
    value = verify_validation_receipt(
        path,
        expected_sha=file_sha(path),
        definition_digest=definition.content_digest,
        require_admission=False,
    )
    evaluation = value["evaluation"]
    job = _load_job(settings, evaluation["job_id"])
    protocol = job["admission_protocol"]
    admission.verify_protocol(protocol)
    job, plan, job_digest = admission._job_context(
        settings, protocol, definition.content_digest, evaluation
    )
    planned_payload = dict(plan["payload"])
    history_start = planned_payload.pop("history_start", plan.get("history_start", "2015-01-01"))
    _require(
        "history_start" not in plan or plan["history_start"] == history_start,
        "qualification_plan_history_start_conflict",
    )
    planned = validate_definition(
        StrategyDefinition(history_start=history_start, **planned_payload)
    )
    _require(
        planned.model_dump(mode="json", exclude={"title"})
        == definition.model_dump(mode="json", exclude={"title"})
        and source.parent.name == plan["strategy_id"],
        "qualification_actual_definition_mismatch",
    )
    result = _read(path.parent / "platform-result.json")
    _require(
        result["profile"]["symbols"] == list(definition.symbols)
        and result["profile"]["benchmark_symbol"] == definition.benchmark_symbol,
        "qualification_result_universe_mismatch",
    )
    _require(
        file_sha(path.parent / "prices.parquet") == evaluation["prices_sha256"],
        "qualification_validation_prices_changed",
    )
    dates = [row["date"] for row in result["curve"]]
    _require(
        dates == sorted(set(dates)) and value["evaluation_calendar_digest"] == _hash(dates),
        "qualification_calendar_binding_changed",
    )
    _, ledger_sha = admission.ledger_snapshot(settings)
    _, peers = admission.peer_snapshot(load_book(settings), settings=settings)
    # Measured failed objectives retain input identity. Funding uses the
    # objective in this binding to refuse T2 independently of data qualification.
    _, increment = admission._increment_context(settings, job, plan, value, result)
    binding = {
        "job_id": protocol["job_id"],
        "proposal_digest": protocol["proposal_digest"],
        "definition_digest": definition.content_digest,
        "source_sha256": file_sha(source),
        "validation_path": str(path),
        "validation_sha256": file_sha(path),
        "prices_sha256": evaluation["prices_sha256"],
        "evaluation_id": evaluation.get("evaluation_id"),
        "curve_digest": _hash(result["curve"]),
        "calendar_digest": _hash(dates),
        "trial_ledger_sha256": ledger_sha,
        "peer_digest": peers["digest"],
        "owner_job_digest": job_digest,
        "activation_eligible": plan.get("activation_eligible") is True,
        "increment_binding": increment,
    }
    return {
        "binding": binding,
        "input_digest": _hash(binding),
        "definition": definition.model_dump(mode="json"),
        "evaluation": evaluation,
        "curve_dates": dates,
    }


def _approved_prices(evidence):
    """Two locally audited immutable datasets; hashes are source pins, not user claims."""
    import pandas as pd

    root = Path(evidence["source_root"])
    if evidence["dataset"] == "futu24-auto-window-v1":
        from quant_system.research.admission_window import read_window

        prices, manifest = read_window(
            root / "input-manifest.json", evidence["window_manifest_sha256"]
        )
        return prices, CONTROL_SYMBOLS, {
            "manifest_sha256": evidence["window_manifest_sha256"],
            "window_id": manifest["window_id"],
            "prices_sha256": manifest["source"]["prices_sha256"],
            "source": "verified_native_futu_validation_window",
            "immutable_job_digest": manifest["source"]["immutable_job_digest"],
            "supported_context": manifest["context"],
        }
    if evidence["dataset"] == SEPTEMBER24_DATASET:
        from quant_system.research.admission_dataset_20260924 import read_frozen_inputs

        prices, manifest = read_frozen_inputs(
            root / "input-manifest.json", SEPTEMBER24_MANIFEST_SHA
        )
        return prices, CONTROL_SYMBOLS, {
            "manifest_sha256": SEPTEMBER24_MANIFEST_SHA,
            "prices_sha256": manifest["artifacts"]["prices.parquet"]["sha256"],
            "source": "saved_futu_intake_capture_20260925_through_20260924",
            "source_job_sha256": manifest["source_job_sha256"],
        }
    if evidence["dataset"] == CURRENT_DATASET:
        manifest_path = root / "input-manifest.json"
        _require(
            file_sha(manifest_path) == CURRENT_MANIFEST_SHA,
            "qualification_current_manifest_changed",
        )
        manifest = _read(manifest_path)
        _require(
            manifest["schema"] == "phase2_current_static24_inputs/v1"
            and manifest["dataset"] == CURRENT_DATASET
            and manifest["ordered_symbols"] == CONTROL_SYMBOLS,
            "qualification_current_manifest_scope_changed",
        )
        _require(
            set(manifest["artifacts"])
            == {"prices.parquet", "source-audit.json", "builder-snapshot.py"}
            and {path.name for path in root.iterdir()}
            == {"input-manifest.json", *manifest["artifacts"]},
            "qualification_current_payload_closure",
        )
        for name, descriptor in manifest["artifacts"].items():
            path = root / name
            _require(
                descriptor["path"] == name
                and path.is_file()
                and not path.is_symlink()
                and file_sha(path) == descriptor["sha256"],
                "qualification_current_payload_changed",
            )
        for item in manifest["sources"]:
            _require(
                file_sha(item["path"]) == item["sha256"]
                and file_sha(item["metadata_path"]) == item["metadata_sha256"],
                "qualification_current_original_source_changed",
            )
        prices = pd.read_parquet(root / "prices.parquet")
        _require(
            len(prices) == manifest["price_rows"] == 73625,
            "qualification_current_row_count_changed",
        )
        return (
            prices,
            CONTROL_SYMBOLS,
            {
                "manifest_sha256": CURRENT_MANIFEST_SHA,
                "prices_sha256": manifest["artifacts"]["prices.parquet"]["sha256"],
                "source": "saved_futu_capture_20260920_current24",
            },
        )
    if evidence["dataset"] == "futu-study-20260909-24":
        index = root / "inputs.json"
        report = root / "saved-study-snapshot.json"
        _require(
            file_sha(index) == "4723c28f6c2834e5550e6f9cdabe88de9c48380a7f676d95910b664557f234d6"
            and file_sha(report)
            == "26f92cc99644f6fd813a7cc99ed32abc39a305991e24e1b841e5afea211828b7",
            "qualification_original_data_manifest_changed",
        )
        source = _read(report)["source"]
        path = Path(_read(index)["prices_path"])
        _require(
            file_sha(path)
            == source["prices_sha256"]
            == "670c5cb2117cc25d36decfe94fb1647dc6de0123bf8e4358b55547e6cefce002"
            and source["provider"] == "futu"
            and source["adjustment"] == "qfq",
            "qualification_original_provider_changed",
        )
        return (
            pd.read_parquet(path),
            CONTROL_SYMBOLS,
            {
                "prices_sha256": file_sha(path),
                "metadata_sha256": file_sha(report),
                "source": "saved_futu_capture_20260909",
            },
        )
    _require(
        evidence["dataset"] == "futu-exploration-20260920-4", "qualification_dataset_unsupported"
    )
    candidate_path = root / "frozen-candidate.json"
    _require(
        file_sha(candidate_path)
        == "c2c74bafe7c3e32599686064fc576fee3ec4ac2510b0a73d3003c036309f2229",
        "qualification_original_data_manifest_changed",
    )
    provenance = _read(candidate_path)["binding"]["data_provenance"]
    frames = []
    for item in provenance["files"]:
        path = Path(item["path"])
        metadata = path.with_suffix(".metadata.json")
        _require(
            file_sha(path) == item["sha256"] and file_sha(metadata) == item["metadata_sha256"],
            "qualification_original_provider_changed",
        )
        meta = _read(metadata)
        _require(
            meta["source"] == "futu"
            and meta["adjustment"] == "futu_qfq"
            and meta["symbol"] == item["symbol"]
            and meta["sha256"] == item["sha256"],
            "qualification_original_provider_changed",
        )
        frames.append(pd.read_parquet(path))
    return (
        pd.concat(frames, ignore_index=True),
        provenance["symbols"],
        {"manifest_sha256": file_sha(candidate_path), "source": "saved_futu_capture_20260920"},
    )


def _data_checks(settings, input_digest, evidence):
    import exchange_calendars
    import numpy as np
    import pandas as pd

    expected_keys = {"validation_path", "dataset", "source_root"}
    if evidence.get("dataset") == "futu24-auto-window-v1":
        expected_keys.add("window_manifest_sha256")
    _require(
        set(evidence) == expected_keys,
        "qualification_recipe_invalid",
    )
    facts = inspect_data_binding(settings, evidence["validation_path"])
    _require(facts["input_digest"] == input_digest, "qualification_owner_input_changed")
    definition, evaluation = facts["definition"], facts["evaluation"]
    original, supported_symbols, provenance = _approved_prices(evidence)
    _require(
        definition["symbols"] == supported_symbols and definition["benchmark_symbol"] == "SPY",
        "qualification_dataset_universe_unsupported",
    )
    symbols = list(dict.fromkeys([*supported_symbols, "SPY"]))
    prices = pd.read_parquet(Path(evidence["validation_path"]).parent / "prices.parquet")
    columns = [
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "provider",
        "interval",
        "event_ts",
        "knowledge_ts",
        "price_adjustment",
    ]
    start, end = (
        pd.Timestamp(definition["history_start"], tz="UTC"),
        pd.Timestamp(evaluation["end"], tz="UTC"),
    )
    for frame in (prices, original):
        _require(set(columns).issubset(frame), "qualification_price_columns_missing")
        for col in ("timestamp", "event_ts", "knowledge_ts"):
            frame[col] = pd.to_datetime(frame[col], utc=True)
    _require(
        set(prices.symbol) == set(symbols) and not prices.duplicated(["symbol", "timestamp"]).any(),
        "qualification_price_universe_or_duplicates",
    )
    expected = original[original.symbol.isin(symbols) & original.timestamp.between(start, end)]
    actual = prices.sort_values(["symbol", "timestamp"])[columns].reset_index(drop=True)
    expected = expected.sort_values(["symbol", "timestamp"])[columns].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError("qualification_prices_differ_from_approved_source") from exc
    numbers = prices[["open", "high", "low", "close", "volume"]].to_numpy(float)
    _require(
        np.isfinite(numbers).all() and (numbers[:, :4] > 0).all() and (numbers[:, 4] >= 0).all(),
        "qualification_price_values_invalid",
    )
    _require(
        set(prices.provider) == {"futu"}
        and set(prices.price_adjustment) == {"qfq"}
        and set(prices.interval) == {"1d"},
        "qualification_provider_mismatch",
    )
    calendar = exchange_calendars.get_calendar(
        "XNYS", start=f"{start.year - 1}-01-01", end=f"{end.year + 1}-12-31"
    )
    dates = pd.to_datetime(
        calendar.sessions_in_range(start.tz_localize(None), end.tz_localize(None)), utc=True
    )
    _require(
        all(
            pd.DatetimeIndex(part.timestamp.sort_values()).equals(dates)
            for _, part in prices.groupby("symbol")
        ),
        "qualification_session_gap",
    )
    evaluation_dates = (
        dates[dates >= pd.Timestamp(evaluation["start"], tz="UTC")].strftime("%Y-%m-%d").tolist()
    )
    _require(facts["curve_dates"] == evaluation_dates, "qualification_curve_calendar_mismatch")
    context = {
        "dataset": evidence["dataset"],
        "ordered_symbols": supported_symbols,
        "benchmark_symbol": "SPY",
        "universe_mode": "explicit_static",
        "history_start": definition["history_start"],
        "start": evaluation_dates[0],
        "end": evaluation_dates[-1],
        "rebalance": definition["rebalance"],
        "top_n": definition["top_n"],
        "ordered_universe_digest": _hash(supported_symbols),
        "execution_price": definition["execution_price"],
        "return_basis": "strategy_minus_benchmark_daily_arithmetic",
        "target_gross_exposure": definition["target_gross_exposure"],
        "max_weight_per_symbol": definition["max_weight_per_symbol"],
        "selection": definition["selection"],
        "min_order_value": definition["min_order_value"],
        "whole_share_orders": definition["whole_share_orders"],
        "commission_bps": definition["commission_bps"],
        "slippage_bps": definition["slippage_bps"],
        "historical_pit_verified": False,
        "corporate_action_vintage_verified": False,
        "broad_universe_qualified": False,
        "usage": "retrospective_fixed_input_research_only",
    }
    require_supported_data_context(evidence["dataset"], context)
    if evidence["dataset"] == "futu24-auto-window-v1":
        _require(
            all(context[key] == provenance["supported_context"][key]
                for key in (*CONTROL_CONTEXT, "history_start")),
            "qualification_window_context_mismatch",
        )
    return {
        "checks": {name: {"status": "passed"} for name in REQUIRED["data"]},
        "supported_context": context,
        "provenance": provenance,
        "input_digest": input_digest,
        "sessions_per_symbol": len(dates),
        "evaluation_sessions": len(evaluation_dates),
        "reason": None,
    }


def _evaluate(settings, *, kind, scope, code_digest, input_digest, evidence):
    from quant_system.research.admission_v2 import code_identity

    if kind not in REQUIRED or scope != SCOPE or code_digest != code_identity()["digest"]:
        raise ValueError("qualification_scope_or_code_mismatch")
    if kind == "data" and (not isinstance(input_digest, str) or not _SHA.fullmatch(input_digest)):
        raise ValueError("qualification_input_digest_required")
    if not isinstance(evidence, dict):
        raise ValueError("qualification_recipe_invalid")
    try:
        if kind == "review":
            result = _review_checks(evidence)
        elif kind == "consumer":
            from quant_system.research.admission_consumer_checks import verify_consumer_checks

            result = verify_consumer_checks(
                settings, code_digest=code_digest, scope=scope, evidence=evidence
            )
        else:
            result = _data_checks(settings, input_digest, evidence)
        _require(
            code_identity()["digest"] == code_digest, "qualification_code_changed_during_checks"
        )
        return result
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        return _check_failure(exc)
    except Exception as exc:
        result = _check_failure(exc)
        if not result["retryable"]:
            result["reason"] = "qualification_check_error:" + type(exc).__name__
        return result


def inspect_qualification(settings, *, kind, scope, evidence, input_digest=None):
    """Read-only fixed checks, without pretending that inspection is registration."""
    from quant_system.research.admission_v2 import code_identity

    code_digest = code_identity()["digest"]
    result = _evaluate(
        settings,
        kind=kind,
        scope=scope,
        code_digest=code_digest,
        input_digest=input_digest,
        evidence=evidence,
    )
    checked = sorted(
        name for name, row in result.get("checks", {}).items() if row.get("status") == "passed"
    )
    passed = REQUIRED[kind].issubset(checked)
    return {
        "status": "passed" if passed else "not_evaluated",
        "reason": None if passed else result.get("reason") or "qualification_checks_incomplete",
        "verified_checks": checked,
        "code_digest": code_digest,
        "input_digest": input_digest,
        "details": result,
        "registered": False,
    }


def verify_registered_qualification(
    settings, *, kind, scope, code_digest, input_digest, descriptor
):
    """Read-only verification: the only trust is local fixed check execution."""
    try:
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "path",
            "sha256",
            "registration_id",
        }:
            raise ValueError("qualification_descriptor_invalid")
        identity = descriptor["registration_id"]
        path = Path(descriptor["path"])
        if not isinstance(identity, str) or not _SHA.fullmatch(identity):
            raise ValueError("qualification_registration_invalid")
        if path.is_symlink() or path.resolve() != _registry(settings) / f"{identity}.json":
            raise ValueError("qualification_registration_outside_registry")
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise ValueError("qualification_registration_owner_invalid")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise ValueError("qualification_registration_changed")
        value = json.loads(raw)
        if _hash(value) != identity:
            raise ValueError("qualification_registration_identity_mismatch")
        expected_input = input_digest if kind == "data" else None
        if any(
            value.get(k) != v
            for k, v in {
                "schema": SCHEMA,
                "issuer_id": ISSUER,
                "kind": kind,
                "scope": scope,
                "code_digest": code_digest,
                "input_digest": expected_input,
            }.items()
        ):
            raise ValueError("qualification_scope_or_identity_mismatch")
        computed = _evaluate(
            settings,
            kind=kind,
            scope=scope,
            code_digest=code_digest,
            input_digest=expected_input,
            evidence=value["evidence"],
        )
        if value.get("verification_result") != computed:
            if computed.get("retryable") is True:
                return {
                    **_unknown(computed["reason"]),
                    "details": computed,
                    "retryable": True,
                    "error_type": computed.get("error_type"),
                }
            raise ValueError("qualification_recomputation_mismatch")
        checked = sorted(
            name
            for name, row in computed.get("checks", {}).items()
            if row.get("status") == "passed"
        )
        passed = REQUIRED[kind].issubset(checked)
        return {
            "status": "passed" if passed else "not_evaluated",
            "reason": None
            if passed
            else computed.get("reason") or "qualification_checks_incomplete",
            "verified_checks": checked,
            "registration_digest": identity,
            "issuer_id": ISSUER,
            "details": computed,
            "retryable": computed.get("retryable", False),
            "error_type": computed.get("error_type"),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _unknown(str(exc))


def register_qualification(settings, *, kind, scope, evidence, input_digest=None):
    """Explicit producer: callers choose inputs, never check outcomes or commands."""
    from quant_system.research.admission_v2 import code_identity

    code_digest = code_identity()["digest"]
    if kind != "data" and input_digest is not None:
        raise ValueError("qualification_static_kind_has_no_input_digest")
    result = _evaluate(
        settings,
        kind=kind,
        scope=scope,
        code_digest=code_digest,
        input_digest=input_digest,
        evidence=evidence,
    )
    value = {
        "schema": SCHEMA,
        "issuer_id": ISSUER,
        "kind": kind,
        "scope": scope,
        "code_digest": code_digest,
        "input_digest": input_digest,
        "evidence": evidence,
        "verification_result": result,
    }
    identity = _hash(value)
    directory = _registry(settings)
    _require(
        not directory.is_symlink()
        and directory.resolve().is_relative_to(Path(settings.data.data_dir).resolve()),
        "qualification_registry_path_invalid",
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{identity}.json"
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text() != raw:
            raise ValueError("qualification_registration_collision")
    else:
        with path.open("x") as handle:
            handle.write(raw)
        path.chmod(0o600)
    descriptor = {"path": str(path), "sha256": file_sha(path), "registration_id": identity}
    checked = sorted(
        name for name, row in result.get("checks", {}).items() if row.get("status") == "passed"
    )
    if not REQUIRED[kind].issubset(checked):
        # A failed fixed execution grants no authority. Preserve its original
        # error and retryability, instead of immediately running it twice and
        # turning a transient recovery into a permanent digest-mismatch error.
        return {
            "descriptor": descriptor,
            "verification": {
                "status": "not_evaluated",
                "reason": result.get("reason") or "qualification_checks_incomplete",
                "verified_checks": checked,
                "registration_digest": identity,
                "issuer_id": ISSUER,
                "details": result,
                "retryable": result.get("retryable", False),
                "error_type": result.get("error_type"),
            },
        }
    return {
        "descriptor": descriptor,
        "verification": verify_registered_qualification(
            settings,
            kind=kind,
            scope=scope,
            code_digest=code_digest,
            input_digest=input_digest,
            descriptor=descriptor,
        ),
    }
