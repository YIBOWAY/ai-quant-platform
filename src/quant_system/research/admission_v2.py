"""Versioned intake admission evidence and new-allocation checks.

Old jobs/candidates without this protocol never enter this module. Parallel
receipts do not replace legacy authority. An authoritative receipt requires
scope/code/input-bound independent qualifications and a separate closed-by-
default source switch; neither a tier label nor a self-consistent gate record
alone is funding authority. All pricing, account mutations and scheduling stay
in their existing owners.

Supported scope: new, owner-stored explicit static-universe US daily OHLCV DSL
intake; one independent sleeve, or a same-snapshot augmented formula retaining
its declared objective and paired CI. T0 is a record, T1 is shadow evidence,
neither creates an ALLOCATED sleeve. T2 alone can request the existing $10,000
transaction after current owner evidence and locked peer/family CAS checks.
Same-sleeve replacement additionally requires the fixed journaled lifecycle,
paired same-input baseline and zero new capital. Owner-only recipes may invoke
fixed local qualification programs outside financial locks. Historical
authorization reconstruction and arbitrary Python proofs remain unsupported.
Independent scope/code/input-bound qualifications are late-bound after the
validation UUID and curves exist; refreshed sidecars never overwrite old ones
or replay the backtest. The legacy source constant stays OFF; a fixed bounded
activation review and process-local warm proof are required for state-based
authority. That state cannot qualify arbitrary future datasets or windows.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path

from quant_system.research.capital_evidence import CurrentFamilyResolver
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import (
    FAMILY_RULE_VERSION,
    compatibility_contract_from_result,
)
from quant_system.research.gate_v2.verdict import (
    GATE_V2_CONFIG,
    evaluate_gate_v2,
    gate_v2_sources,
    verify_verdict_v2,
)
from quant_system.research.trials import universe_digest
from quant_system.research.validation_receipts import verify_validation_receipt

PROTOCOL_VERSION = "intake_admission/v2"
RECEIPT_SCHEMA = "intake_admission_receipt/v1"
QUALIFICATION_SCHEMA = "intake_admission_qualification/v1"
AUTHORITATIVE_ENABLED = False
_WARM_QUALIFICATIONS = {}
_WARM_MAX_AGE_SECONDS = 120
_CANDIDATE_PREFIX = "strategy-v2-"
SCOPE = "new_explicit_static_us_daily_ohlcv_dsl_intake"
_ROOT = Path(__file__).resolve().parents[1]
_REQUIRED_QUALIFICATIONS = {
    "review": {"bounded_behavior", "independent_holdout", "source_input_identity"},
    "data": {"provider_provenance", "calendar_coverage", "universe_identity", "usage_restrictions"},
    "consumer": {
        "legacy_path_unchanged",
        "full_gate_calibration",
        "new_funding_cas",
        "failure_zero_effects",
    },
}


class AdmissionV2Error(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise AdmissionV2Error(code)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_identity():
    from quant_system.research.strategy_definition import _COMMON_SOURCES

    files = {"admission_v2.py": file_sha(__file__), **gate_v2_sources()}
    for name in (
        *_COMMON_SOURCES,
        "research/active_metrics.py",
        "research/validation_receipts.py",
        "research/intake_evaluation.py",
        "research/intake_factor_evaluation.py",
        "research/fingerprint_grading.py",
        "research/trials.py",
        "factors/evaluation.py",
        "d34/qlib_expr.py",
        "research/external_intake.py",
        "research/strategy_library.py",
        "execution/assistant_remote.py",
        "execution/account.py",
        "execution/account_repository_factory.py",
        "execution/account_repository.py",
        "execution/account_postgres_repository.py",
        "execution/account_storage.py",
        "execution/account_dual_write_repository.py",
        "execution/paper_strategy_sleeves.py",
        "execution/paper_strategy_sleeve_storage.py",
    ):
        files[name] = file_sha(_ROOT / name)
    for name in (
        "research/admission_qualifier.py",
        "research/admission_dataset_20260924.py",
        "research/admission_window.py",
        "research/admission_consumer_checks.py",
        "research/admission_qualification_flow.py",
        "research/admission_activation.py",
        "research/capital_quality.py",
        "research/capital_evidence.py",
        "research/legacy_family_evidence.py",
        "research/d34_family_evidence.py",
        "research/registered_family_evidence.py",
        "d34/registered_verification.py",
        "d34/rdagent_qlib_runtime.py",
        "d34/worker.py",
        "d34/research_driver.py",
        "d34/research_cli.py",
        "d34/docker_runtime.py",
        "d34/platform_replay.py",
        "research/cost_replay.py",
        "execution/strategy_replacement.py",
        "d34/paper_cycle.py",
    ):
        producer = _ROOT / name
        files[name] = file_sha(producer) if producer.is_file() else None
    files["repository/docker/d34/container_entrypoint.py"] = file_sha(
        _ROOT.parents[1] / "docker/d34/container_entrypoint.py"
    )
    files["repository/scripts/calibrate_admission_semantics.py"] = file_sha(
        _ROOT.parents[1] / "scripts/calibrate_admission_semantics.py"
    )
    return {"files": files, "digest": _hash(files)}


def qualification_refs(settings, input_digest):
    """An optional owner-only index, never initialized by a reader."""
    path = Path(settings.data.data_dir) / "research_intake/admission_v2/qualifications.json"
    if not path.exists():
        return {}
    _require(
        not path.is_symlink()
        and path.stat().st_uid == os.getuid()
        and path.stat().st_mode & 0o077 == 0,
        "admission_v2_qualification_index_owner_invalid",
    )
    value = json.loads(path.read_text())
    _require(
        isinstance(value, dict)
        and value.get("schema") == "admission_qualification_index/v1"
        and isinstance(value.get("entries"), dict),
        "admission_v2_qualification_index_invalid",
    )
    refs = value["entries"].get(input_digest, {})
    _require(
        isinstance(refs, dict) and set(refs) <= set(_REQUIRED_QUALIFICATIONS),
        "admission_v2_qualification_index_invalid",
    )
    return refs


def _intent(protocol):
    intent = protocol.get("intent", {"kind": "new_independent"})
    _require(isinstance(intent, dict), "admission_v2_intent_invalid")
    if intent.get("kind") == "new_independent":
        _require(set(intent) == {"kind"}, "admission_v2_intent_invalid")
    else:
        target = intent.get("target")
        _require(
            intent.get("kind") == "replacement"
            and set(intent) == {"kind", "target"}
            and isinstance(target, dict)
            and set(target)
            == {
                "candidate_id",
                "sleeve_id",
                "definition_digest",
                "config_id",
                "config_version",
            },
            "admission_v2_intent_invalid",
        )
        _require(
            all(
                isinstance(target[key], str) and target[key]
                for key in (
                    "candidate_id",
                    "sleeve_id",
                    "definition_digest",
                    "config_id",
                )
            )
            and type(target["config_version"]) is int
            and target["config_version"] >= 1,
            "admission_v2_target_identity_invalid",
        )
    return intent


def freeze_protocol(
    job_id: str, proposal_digest: str, *, mode="parallel", intent=None, activation=None
):
    _require(mode in {"parallel", "authoritative"}, "admission_v2_mode_invalid")
    value = {
        "version": PROTOCOL_VERSION,
        "mode": mode,
        "scope": SCOPE,
        "job_id": job_id,
        "proposal_digest": proposal_digest,
        "intent": copy.deepcopy(intent or {"kind": "new_independent"}),
        "config": copy.deepcopy(GATE_V2_CONFIG),
        "code": code_identity(),
        "qualification_source": "owner_input_bound_catalog/v1",
        "qualification_requirements": {
            key: sorted(value) for key, value in _REQUIRED_QUALIFICATIONS.items()
        },
    }
    if activation is not None:
        from quant_system.research.admission_activation import validate_binding

        validate_binding(activation)
        _require(mode == "authoritative", "admission_v2_activation_requires_authoritative")
        value["activation"] = copy.deepcopy(activation)
    _intent(value)
    value["protocol_digest"] = _hash(value)
    return value


def verify_protocol(
    protocol,
    *,
    job_id=None,
    proposal_digest=None,
    current_code=True,
    current_config=True,
):
    _require(isinstance(protocol, dict), "admission_v2_protocol_required")
    _intent(protocol)
    if "activation" in protocol:
        from quant_system.research.admission_activation import validate_binding

        validate_binding(protocol["activation"], current_scope=current_code)
        _require(
            protocol.get("mode") == "authoritative"
            and protocol["activation"]["code_digest"] == protocol.get("code", {}).get("digest"),
            "admission_v2_activation_protocol_mismatch",
        )
    _require(
        protocol.get("version") == PROTOCOL_VERSION
        and protocol.get("scope") == SCOPE
        and protocol.get("mode") in {"parallel", "authoritative"},
        "admission_v2_protocol_unsupported",
    )
    _require(
        protocol.get("protocol_digest")
        == _hash({k: v for k, v in protocol.items() if k != "protocol_digest"}),
        "admission_v2_protocol_digest_mismatch",
    )
    _require(job_id is None or protocol.get("job_id") == job_id, "admission_v2_job_mismatch")
    _require(
        proposal_digest is None or protocol.get("proposal_digest") == proposal_digest,
        "admission_v2_proposal_mismatch",
    )
    _require(
        protocol.get("qualification_source") == "owner_input_bound_catalog/v1"
        and protocol.get("qualification_requirements")
        == {key: sorted(value) for key, value in _REQUIRED_QUALIFICATIONS.items()},
        "admission_v2_qualification_contract_changed",
    )
    if current_config:
        _require(protocol.get("config") == GATE_V2_CONFIG, "admission_v2_config_changed")
    if current_code:
        _require(protocol.get("code") == code_identity(), "admission_v2_code_changed")


def ledger_snapshot(settings):
    import fcntl

    path = Path(settings.data.data_dir) / "trials/trials.jsonl"
    _require(path.is_file(), "admission_v2_trial_ledger_missing")
    with path.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        raw = handle.read()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    _require(
        len({row["trial_id"] for row in rows}) == len(rows), "admission_v2_trial_ledger_duplicate"
    )
    return rows, hashlib.sha256(raw).hexdigest()


def _job_context(settings, protocol, definition_digest, evaluation):
    from quant_system.research.external_intake import _load_job
    from quant_system.research.intake_evaluation import validate_snapshot

    job = _load_job(settings, protocol["job_id"])
    requested_target = job["proposal"].get("upgrade_target")
    intent = _intent(protocol)
    _require(
        (requested_target is not None) == (intent["kind"] == "replacement"),
        "admission_v2_intent_proposal_mismatch",
    )
    if requested_target is not None:
        _require(
            requested_target.get("candidate_id") == intent["target"]["candidate_id"],
            "admission_v2_intent_proposal_mismatch",
        )
    _require(
        job.get("admission_protocol") == protocol
        and job.get("evaluation") == evaluation
        and evaluation.get("plans_sha256") == job["plans_sha256"],
        "admission_v2_owner_job_binding_mismatch",
    )
    validate_snapshot(settings, evaluation)
    plans = [plan for plan in job["plans"] if plan["definition_digest"] == definition_digest]
    _require(len(plans) == 1, "admission_v2_owner_definition_missing")
    return (
        job,
        plans[0],
        _hash(
            {
                key: job[key]
                for key in (
                    "job_id",
                    "payload_sha256",
                    "plans_sha256",
                    "admission_protocol",
                    "evaluation",
                )
            }
        ),
    )


def _increment_context(settings, job, plan, validation, result):
    """Bind a measured comparison independently of whether its objective passed.

    A failed declared improvement is a known rejection, not an unknown input.
    Identity callers and full gate statistics need both measured outcomes;
    validated tier and every funding consumer still enforce the objective.
    """
    if plan["variant"] != "augmented":
        return None, None
    from quant_system.research.intake_evaluation import compare_increment
    from quant_system.research.strategy_definition import StrategyDefinition, validate_definition
    from quant_system.research.strategy_library import _returns

    baseline = next((row for row in job.get("results", []) if row["variant"] == "baseline"), None)
    _require(baseline is not None, "admission_v2_baseline_missing")
    baseline_plan = next(row for row in job["plans"] if row["variant"] == "baseline")
    directory = Path(settings.data.data_dir) / "strategy_library" / baseline_plan["strategy_id"]
    path = directory / "validations" / baseline["validation"]["run_id"] / "validation.json"
    first = verify_validation_receipt(
        path,
        expected_sha=baseline["validation_sha256"],
        definition_digest=baseline_plan["definition_digest"],
        require_admission=False,
    )
    _require(
        first.get("evaluation") == validation.get("evaluation"),
        "admission_v2_baseline_input_mismatch",
    )
    expected_prices = (validation.get("evaluation") or {}).get("prices_sha256")
    _require(
        expected_prices is not None and file_sha(path.parent / "prices.parquet") == expected_prices,
        "admission_v2_baseline_price_identity_mismatch",
    )
    original_definition = validate_definition(
        json.loads((directory / "definition.json").read_text())
    )
    planned_definition = validate_definition(
        StrategyDefinition(
            history_start=baseline_plan.get("history_start", "2015-01-01"),
            **baseline_plan["payload"],
        )
    )
    _require(
        original_definition.model_dump(mode="json", exclude={"title"})
        == planned_definition.model_dump(mode="json", exclude={"title"})
        and original_definition.content_digest == baseline_plan["definition_digest"],
        "admission_v2_baseline_definition_mismatch",
    )
    original_result = json.loads((path.parent / "platform-result.json").read_text())
    _require(
        original_result.get("profile", {}).get("symbols")
        == list(original_definition.symbols)
        == result.get("profile", {}).get("symbols")
        and original_result.get("profile", {}).get("benchmark_symbol")
        == original_definition.benchmark_symbol
        == result.get("profile", {}).get("benchmark_symbol"),
        "admission_v2_baseline_profile_mismatch",
    )
    _require(
        original_result.get("source") == original_definition.provider
        and original_result.get("price_adjustment") == original_definition.price_adjustment
        and original_result.get("evaluation_initial_cash")
        == result.get("evaluation_initial_cash")
        == 10000
        and original_result.get("costs", {}).get("commission_bps")
        == original_definition.commission_bps
        and original_result.get("costs", {}).get("slippage_bps")
        == original_definition.slippage_bps,
        "admission_v2_baseline_execution_mismatch",
    )
    values, dates = _returns(result)
    old_values, old_dates = _returns(original_result)
    _require(
        dates == old_dates and first.get("evaluation_calendar_digest") == _hash(old_dates),
        "admission_v2_baseline_calendar_mismatch",
    )
    pair = [
        {
            "variant": variant,
            "evaluation": raw["evaluation"],
            "validation": raw,
            "evaluation_calendar_digest": raw["evaluation_calendar_digest"],
        }
        for variant, raw in (("baseline", first), ("augmented", validation))
    ]
    objective = compare_increment({"proposal": job["proposal"], "results": pair})
    _require(
        objective.get("comparable") is True and objective.get("status") in {"passed", "failed"},
        "admission_v2_declared_increment_unmeasured",
    )
    return {"baseline": old_values, "augmented": values}, {
        "baseline_validation_sha256": baseline["validation_sha256"],
        "baseline_definition_digest": baseline_plan["definition_digest"],
        "baseline_semantics_digest": _hash(original_definition.model_dump(
            mode="json", exclude={"title", "content_digest", "source_fingerprints"}
        )),
        "objective": objective,
    }


def _replacement_state(settings, protocol, book, supplied=None):
    """Resolve actual owner state, including a coordinator-authenticated PAUSED preimage."""
    try:
        from quant_system.execution import strategy_replacement as lifecycle
        from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
    except ImportError as exc:
        raise AdmissionV2Error("admission_v2_replacement_lifecycle_unavailable") from exc
    expected = _intent(protocol)["target"]
    _require(
        lifecycle.SCHEMA == "same_contract_strategy_replacement/v1"
        and protocol["code"]["files"].get("execution/strategy_replacement.py")
        == file_sha(lifecycle.__file__),
        "admission_v2_replacement_lifecycle_unverified",
    )
    storage = PaperStrategySleeveStorage(Path(settings.data.data_dir) / "api_runs")
    physical = storage.load_sleeve(expected["sleeve_id"])
    pending = physical.metadata.get(lifecycle.MARKER)
    if pending:
        state = lifecycle.inspect_replacement_recovery_target(settings, replacement_id=pending)
    else:
        resolved = lifecycle.inspect_replacement_target(
            settings,
            candidate_id=expected["candidate_id"],
            sleeve_id=expected["sleeve_id"],
        )
        _require(
            resolved["replacement_target"] == expected, "admission_v2_replacement_target_changed"
        )
        canonical = lifecycle.assistant_remote.load_book(settings)
        _require(
            peer_snapshot(canonical)[1] == peer_snapshot(book)[1],
            "admission_v2_replacement_peer_snapshot_changed",
        )
        target = next(
            (
                row
                for row in canonical["candidates"]
                if row.get("candidate_id") == expected["candidate_id"]
            ),
            None,
        )
        _require(target is not None, "admission_v2_replacement_target_changed")
        state = {
            "target_candidate": target,
            "target_sleeve": physical,
            "target_config": storage.load_frozen_strategy_config(
                expected["config_id"], version=expected["config_version"]
            ),
            "book": book,
        }
    old, sleeve, config = (
        state[key] for key in ("target_candidate", "target_sleeve", "target_config")
    )
    actual = {
        "candidate_id": old["candidate_id"],
        "sleeve_id": sleeve.sleeve_id,
        "definition_digest": old.get("definition_digest"),
        "config_id": config.strategy_config_id,
        "config_version": config.version,
    }
    _require(
        actual == expected and peer_snapshot(state["book"])[1] == peer_snapshot(book)[1],
        "admission_v2_replacement_target_changed",
    )
    if supplied is not None:
        _require(
            supplied["target_candidate"] == old
            and supplied["target_sleeve"].model_dump(mode="json") == sleeve.model_dump(mode="json")
            and supplied["target_config"].model_dump(mode="json") == config.model_dump(mode="json"),
            "admission_v2_replacement_callback_identity_mismatch",
        )
        if "new_candidate" in state:
            _require(
                state["new_candidate"] == supplied["new_candidate"],
                "admission_v2_replacement_callback_identity_mismatch",
            )
    definition = config.strategy_definition
    return {
        "schema": lifecycle.SCHEMA,
        "target": actual,
        "source_sha256": old["source_digest"],
        "definition_semantics_digest": _hash({
            key: value for key, value in definition.items()
            if key not in {"title", "content_digest", "source_fingerprints"}
        }),
        "source_fingerprints": copy.deepcopy(definition["source_fingerprints"]),
    }


def _require_replacement_baseline(job, increment_binding, replacement):
    """A current replay must prove the complete recipe of its authenticated old target."""
    _require(increment_binding is not None, "admission_v2_replacement_baseline_mismatch")
    _require(
        increment_binding["baseline_semantics_digest"]
        == replacement["definition_semantics_digest"],
        "admission_v2_replacement_baseline_semantics_changed",
    )
    if (
        increment_binding["baseline_definition_digest"]
        == replacement["target"]["definition_digest"]
    ):
        return  # The unchanged sealed recipe already supplies the exact identity.
    expected = {
        "original_definition_digest": replacement["target"]["definition_digest"],
        "original_source_sha256": replacement["source_sha256"],
        "original_source_fingerprints": replacement["source_fingerprints"],
        "current_baseline_digest": increment_binding["baseline_definition_digest"],
        "historical_validation_reused": False,
    }
    for variant in ("baseline", "augmented"):
        plan = next(row for row in job["plans"] if row["variant"] == variant)
        origin = plan.get("origin") or {}
        _require(
            origin.get("replacement_target") == replacement["target"]
            and origin.get("baseline_revalidation") == expected,
            "admission_v2_replacement_baseline_origin_mismatch",
        )


def peer_snapshot(book, *, settings=None):
    _require(
        isinstance(book, dict) and isinstance(book.get("candidates"), list),
        "admission_v2_peer_book_missing",
    )
    candidates = book["candidates"]
    authenticated = {}
    original_files = {}
    if settings is not None:
        from quant_system.execution.assistant_remote import _current_exposure_candidates
        from quant_system.research.capital_evidence import current_peer_exposures

        candidates = _current_exposure_candidates(settings, candidates)
        exposures, original_files = current_peer_exposures(settings, candidates)
        authenticated = {row["sleeve_id"]: row for row in exposures}
    peers, bindings = [], []
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") != "hung":
            continue
        performance = candidate.get("performance") or {}
        dates, values = (
            performance.get("return_dates") or [],
            performance.get("daily_returns") or [],
        )
        source = Path(str(candidate.get("source_path") or ""))
        source_sha = candidate.get("source_digest") or candidate.get("candidate_code_digest")
        _require(
            candidate.get("candidate_id")
            and candidate.get("sleeve_id")
            and len(dates) >= 20
            and len(dates) == len(values)
            and dates == sorted(set(dates))
            and all(isinstance(x, (float, int)) and math.isfinite(x) for x in values),
            "admission_v2_peer_returns_missing",
        )
        _require(
            source.is_file()
            and file_sha(source) == source_sha
            and len(str(candidate.get("comparison_digest") or "")) == 64,
            "admission_v2_peer_source_unverified",
        )
        peers.append(
            authenticated.get(candidate["sleeve_id"]) or {
                "sleeve_id": candidate["sleeve_id"],
                "definition_digest": candidate.get("definition_digest"),
                "dates": dates,
                "returns": values,
            }
        )
        bindings.append(
            {
                "candidate_id": candidate["candidate_id"],
                "sleeve_id": candidate["sleeve_id"],
                "source_sha256": source_sha,
                "comparison_digest": candidate["comparison_digest"],
                "verification_receipt_digest": candidate.get("verification_receipt_digest"),
                "performance_digest": _hash(performance),
            }
        )
    bindings.sort(key=lambda row: row["sleeve_id"])
    _require(
        len({row["sleeve_id"] for row in bindings}) == len(bindings), "admission_v2_peer_duplicate"
    )
    identity = {"bindings": bindings, "digest": _hash(bindings)}
    if settings is not None:
        identity["original_files"] = original_files
        identity["digest"] = _hash({"bindings": bindings, "original_files": original_files})
    return peers, identity


def qualification_input_context(bindings):
    """Execution scope reconstructed from bound original files, not qualifier claims."""
    run = Path(bindings["validation_path"]).parent
    definition = json.loads((run.parent.parent / "definition.json").read_text())
    curve = json.loads((run / "platform-result.json").read_text())["curve"]
    return {
        "ordered_symbols": definition["symbols"],
        "ordered_universe_digest": _hash(definition["symbols"]),
        "benchmark_symbol": definition["benchmark_symbol"],
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "return_basis": "strategy_minus_benchmark_daily_arithmetic",
        **{
            key: definition[key]
            for key in (
                "rebalance",
                "top_n",
                "execution_price",
                "commission_bps",
                "slippage_bps",
                "target_gross_exposure",
                "max_weight_per_symbol",
                "selection",
                "min_order_value",
                "whole_share_orders",
            )
        },
    }


def _warm_key(settings, protocol, bindings, refs):
    return _hash(
        {
            "owner_root": str(Path(settings.data.data_dir).resolve()),
            "protocol": protocol,
            "input": bindings,
            "refs": refs,
        }
    )


def _warm_qualifications(settings, protocol, bindings, refs):
    cached = _WARM_QUALIFICATIONS.get(_warm_key(settings, protocol, bindings, refs))
    _require(
        cached is not None
        and cached["pid"] == os.getpid()
        and 0 <= time.monotonic() - cached["at"] <= _WARM_MAX_AGE_SECONDS,
        "admission_v2_qualification_preflight_required",
    )
    # Registration bytes and caller-frozen refs are rechecked without invoking
    # the expensive producer. Only successful local execution fills this cache.
    _require(
        all(file_sha(ref["path"]) == ref["sha256"] for ref in refs.values()),
        "admission_v2_qualification_changed",
    )
    _require(isinstance(cached.get("dependency_files"), dict),
             "admission_v2_qualification_preflight_required")
    try:
        _require(
            all(file_sha(path) == expected
                for path, expected in cached["dependency_files"].items()),
            "qualification_dependency_changed",
        )
    except OSError as exc:
        raise AdmissionV2Error("qualification_dependency_changed") from exc
    return copy.deepcopy(cached["outcomes"])


def _qualification_dependency_files(outcomes):
    """The warm path skips producers, never the hashes of their evidence."""
    from quant_system.research.admission_consumer_checks import CURRENT_CONTROL_RULE

    details = outcomes["consumer"]["registration"].get("details", {})
    files = {}
    maps = [(details.get(name) or {}).get("input_files", {})
            for name in ("calibration", "semantic_calibration")]
    execution = details.get("test_execution_evidence") or {}
    maps.append(execution.get("files", {}))
    if details.get("current_control_rule") == CURRENT_CONTROL_RULE:
        _require(all(isinstance(mapping, dict) and mapping for mapping in maps),
                 "qualification_dependency_missing")
    for mapping in maps:
        _require(isinstance(mapping, dict), "qualification_dependency_missing")
        for path, expected in mapping.items():
            _require(isinstance(path, str) and isinstance(expected, str)
                     and (path not in files or files[path] == expected),
                     "qualification_dependency_conflict")
            files[path] = expected
    if execution:
        _require(isinstance(execution.get("path"), str)
                 and isinstance(execution.get("sha256"), str),
                 "qualification_dependency_missing")
        path, expected = execution["path"], execution["sha256"]
        _require(path not in files or files[path] == expected, "qualification_dependency_conflict")
        files[path] = expected
    return files


def _qualifications(settings, protocol, bindings, refs, *, allow_execution=True):
    if not allow_execution:
        return _warm_qualifications(settings, protocol, bindings, refs)
    expected = {
        "scope": SCOPE,
        "code_digest": protocol["code"]["digest"],
        "input_digest": _hash(bindings),
    }
    outcomes = {}
    for kind, checks in _REQUIRED_QUALIFICATIONS.items():
        descriptor = refs.get(kind)
        try:
            _require(isinstance(descriptor, dict), "qualification_missing")
            # Catalog entries are references, never assertions of independence.
            # Only this fixed local producer can authenticate execution-backed
            # registrations; absent capability is explicitly not_evaluated.
            from quant_system.research.admission_qualifier import verify_registered_qualification

            verified = verify_registered_qualification(
                settings,
                kind=kind,
                descriptor=descriptor,
                **expected,
            )
            _require(
                isinstance(verified, dict)
                and verified.get("status") == "passed"
                and checks <= set(verified.get("verified_checks") or [])
                and verified.get("registration_digest")
                and verified.get("issuer_id"),
                str(verified.get("reason") or "qualification_execution_not_verified")
                if isinstance(verified, dict)
                else "qualification_execution_not_verified",
            )
            outcomes[kind] = {
                "status": "passed",
                "descriptor": descriptor,
                "bindings": expected,
                "registration": verified,
            }
        except ImportError:
            outcomes[kind] = {
                "status": "not_evaluated",
                "reason": "qualification_producer_unavailable",
            }
        except (OSError, KeyError, TypeError, ValueError) as exc:
            outcomes[kind] = {"status": "not_evaluated", "reason": str(exc)}
        except Exception as exc:  # A producer fault never promotes an unverified result.
            outcomes[kind] = {
                "status": "not_evaluated",
                "reason": f"qualification_producer_error:{type(exc).__name__}",
            }
    if all(outcomes[kind]["status"] == "passed" for kind in ("data", "consumer")):
        try:
            actual = qualification_input_context(bindings)
            for kind in ("data", "consumer"):
                scope = (
                    outcomes[kind]["registration"].get("details", {}).get("supported_context", {})
                )
                _require(
                    all(scope.get(key) == value for key, value in actual.items()),
                    "qualification_calibration_context_mismatch",
                )
            operations = (
                outcomes["consumer"]["registration"]
                .get("details", {})
                .get("supported_operations", [])
            )
            _require(
                _intent(protocol)["kind"] in operations, "qualification_operation_not_supported"
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            outcomes["consumer"] = {"status": "not_evaluated", "reason": str(exc)}
    if all(row["status"] == "passed" for row in outcomes.values()):
        try:
            dependencies = _qualification_dependency_files(outcomes)
            _require(all(file_sha(path) == value for path, value in dependencies.items()),
                     "qualification_dependency_changed")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            outcomes["consumer"] = {"status": "not_evaluated", "reason": str(exc)}
            return outcomes
        if len(_WARM_QUALIFICATIONS) >= 128:
            _WARM_QUALIFICATIONS.pop(next(iter(_WARM_QUALIFICATIONS)))
        _WARM_QUALIFICATIONS[_warm_key(settings, protocol, bindings, refs)] = {
            "pid": os.getpid(),
            "at": time.monotonic(),
            "outcomes": copy.deepcopy(outcomes),
            "dependency_files": dependencies,
        }
    return outcomes


def evaluate_validation(
    settings,
    *,
    protocol,
    validation_path,
    expected_validation_sha,
    definition_digest,
    source_sha256,
    evaluation,
    book,
    upgrade_target=None,
    _qualification_execution=True,
    _replacement_objects=None,
):
    """Evaluate complete available evidence; unavailable parts remain named, unfunded."""
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "protocol": copy.deepcopy(protocol),
        "status": "not_evaluated",
        "validated_tier": "T0",
        "capital_authorized": False,
        "mode": protocol.get("mode"),
        "reasons": [],
        "gate": None,
        "source_binding": {
            "job_id": protocol.get("job_id"),
            "proposal_digest": protocol.get("proposal_digest"),
            "definition_digest": definition_digest,
            "source_sha256": source_sha256,
            "validation_path": str(Path(validation_path).resolve()),
            "validation_sha256": expected_validation_sha,
        },
        "qualifications": {},
        "legacy_unchanged": True,
    }
    try:
        verify_protocol(protocol)
        _require(upgrade_target is None, "admission_v2_replacement_lifecycle_unverified")
        validation_path = Path(validation_path).resolve()
        _require(
            validation_path.is_relative_to(
                Path(settings.data.data_dir).resolve() / "strategy_library"
            ),
            "admission_v2_validation_outside_owner_root",
        )
        validation = verify_validation_receipt(
            validation_path,
            expected_sha=expected_validation_sha,
            definition_digest=definition_digest,
            require_admission=False,
        )
        _require(
            validation.get("comparison", {}).get("accepted") is True,
            "admission_v2_dual_engine_missing",
        )
        _require(
            validation.get("signal_analysis", {}).get("status") in {"available", "not_applicable"},
            "admission_v2_signal_review_missing",
        )
        _require(
            validation.get("gates", {}).get("cost", {}).get("passed") is True,
            "admission_v2_cost_not_passed",
        )
        result = json.loads((validation_path.parent / "platform-result.json").read_text())
        job, plan, job_digest = _job_context(settings, protocol, definition_digest, evaluation)
        _require(
            validation_path.parent.parent.parent.name == plan["strategy_id"],
            "admission_v2_owner_definition_path_mismatch",
        )
        from quant_system.research.strategy_definition import (
            StrategyDefinition,
            validate_definition,
        )

        source_path = validation_path.parent.parent.parent / "definition.json"
        _require(file_sha(source_path) == source_sha256, "admission_v2_source_sha_mismatch")
        definition = validate_definition(json.loads(source_path.read_text()))
        planned = validate_definition(
            StrategyDefinition(
                history_start=plan.get("history_start", "2015-01-01"),
                **plan["payload"],
            )
        )
        _require(
            definition.content_digest == definition_digest == planned.content_digest
            and definition.model_dump(mode="json", exclude={"title"})
            == planned.model_dump(mode="json", exclude={"title"}),
            "admission_v2_actual_definition_mismatch",
        )
        _require(
            result.get("profile", {}).get("symbols") == list(definition.symbols)
            and result.get("profile", {}).get("benchmark_symbol") == definition.benchmark_symbol,
            "admission_v2_result_profile_mismatch",
        )
        _require(
            result.get("source") == "futu"
            and result.get("price_adjustment") == "qfq"
            and result.get("costs", {}).get("commission_bps") == 1
            and result.get("costs", {}).get("slippage_bps") == 5,
            "admission_v2_price_or_cost_scope_unsupported",
        )
        _require(
            result.get("evaluation_initial_cash") == 10000,
            "admission_v2_initial_cash_unproven",
        )
        _require(
            evaluation
            and evaluation.get("job_id") == protocol["job_id"]
            and validation.get("evaluation") == evaluation
            and file_sha(validation_path.parent / "prices.parquet")
            == evaluation.get("prices_sha256"),
            "admission_v2_evaluation_identity_missing",
        )
        curve = result["curve"]
        dates = [row["date"] for row in curve]
        _require(
            dates == sorted(set(dates))
            and validation.get("evaluation_calendar_digest") == _hash(dates),
            "admission_v2_calendar_identity_missing",
        )
        rows, ledger_sha = ledger_snapshot(settings)
        from quant_system.research.capital_evidence import registered_population_integrity

        return_contract = compatibility_contract_from_result(result, definition=definition)
        receipt["registered_population"] = registered_population_integrity(
            settings.data.data_dir, rows, definition.symbols, return_contract, book["candidates"],
        )
        _require(receipt["registered_population"]["complete"],
                 "current_registered_population_incomplete")
        increment, increment_binding = _increment_context(settings, job, plan, validation, result)
        resolver = CurrentFamilyResolver(Path(settings.data.data_dir), trusted_trials=rows)
        peers, peer_identity = peer_snapshot(book, settings=settings)
        gate_peers = copy.deepcopy(peers)
        selected_target = None
        if _intent(protocol)["kind"] == "replacement" and plan["activation_eligible"]:
            replacement = _replacement_state(settings, protocol, book, _replacement_objects)
            _require(increment is not None, "admission_v2_replacement_baseline_mismatch")
            _require_replacement_baseline(job, increment_binding, replacement)
            target = replacement["target"]
            selected_target = {
                "sleeve_id": target["sleeve_id"],
                "definition_digest": target["definition_digest"],
            }
            matched = [row for row in gate_peers if row["sleeve_id"] == target["sleeve_id"]]
            _require(len(matched) == 1, "admission_v2_replacement_target_changed")
            matched[0].update(returns=increment["baseline"], dates=dates)
            receipt["replacement"] = {
                **replacement,
                "baseline_validation_sha256": increment_binding["baseline_validation_sha256"],
                "capital_delta_usd": 0,
            }
        binding = {
            "job_id": protocol["job_id"],
            "proposal_digest": protocol["proposal_digest"],
            "definition_digest": definition_digest,
            "source_sha256": source_sha256,
            "validation_path": str(validation_path),
            "validation_sha256": expected_validation_sha,
            "prices_sha256": evaluation["prices_sha256"],
            "evaluation_id": evaluation.get("evaluation_id"),
            "curve_digest": _hash(curve),
            "calendar_digest": _hash(dates),
            "trial_ledger_sha256": ledger_sha,
            "peer_digest": peer_identity["digest"],
            "owner_job_digest": job_digest,
            "activation_eligible": plan.get("activation_eligible") is True,
            "increment_binding": increment_binding,
        }
        receipt["source_binding"], receipt["peers"] = binding, peer_identity
        if "activation" in protocol:
            from quant_system.research.admission_activation import require_context

            require_context(
                protocol["activation"], qualification_input_context(binding), source_binding=binding
            )
        from quant_system.research.admission_consumer_checks import concentration_inputs

        benchmark_returns, residual_calibration = concentration_inputs(
            curve,
            result["evaluation_initial_cash"],
            [
                row
                for row in gate_peers
                if selected_target is None or row["sleeve_id"] != selected_target["sleeve_id"]
            ],
        )
        receipt["residual_calibration"] = residual_calibration
        gate = evaluate_gate_v2(
            curve_rows=curve,
            initial_cash=result["evaluation_initial_cash"],
            universe_digest=universe_digest(result["profile"]["symbols"]),
            definition_digest=definition_digest,
            benchmark_symbol=result["profile"].get("benchmark_symbol"),
            trials_rows=rows,
            curve_resolver=resolver,
            legacy_resolver=resolver.legacy,
            hung_sleeves=gate_peers,
            v1_passed=validation.get("status") == "passed",
            config=protocol["config"],
            increment_objective=increment,
            benchmark_returns=benchmark_returns,
            null_p95=residual_calibration["null_p95"],
            upgrade_target=selected_target,
            compatibility_contract=return_contract,
        )
        _require(
            verify_verdict_v2(
                gate, trusted_trials=rows, curve_resolver=resolver, legacy_resolver=resolver.legacy
            ),
            "admission_v2_recomputation_failed",
        )
        receipt["gate"] = gate
        from quant_system.research.capital_quality import evaluate_new_capital_quality

        receipt["minimum_quality"] = evaluate_new_capital_quality(
            selected_returns=gate["inputs"]["active_returns"],
            total_returns=gate["inputs"]["equity_returns"],
            dates=gate["inputs"]["dates"], return_contract=gate["family"]["compatibility_contract"],
            family=gate["family"], concentration=gate["concentration"],
            cost=validation["gates"]["cost"], config=protocol["config"],
        )
        receipt["qualification_refs"] = qualification_refs(settings, _hash(binding))
        receipt["qualifications"] = _qualifications(
            settings,
            protocol,
            binding,
            receipt["qualification_refs"],
            allow_execution=_qualification_execution,
        )
        missing = [
            f"qualification_{kind}:{row.get('reason')}"
            for kind, row in receipt["qualifications"].items()
            if row["status"] != "passed"
        ]
        increment_rejected = (
            increment_binding is not None
            and increment_binding["objective"]["passed"] is not True
        )
        if missing:
            receipt["reasons"] = missing
        else:
            receipt["validated_tier"] = (
                "T0" if increment_rejected else gate["tier_recommendation"]["tier"]
            )
            if (receipt["validated_tier"] == "T2"
                    and receipt["minimum_quality"]["eligible"] is not True):
                receipt["validated_tier"] = "T0"
            receipt["status"] = {"T0": "recorded", "T1": "shadow", "T2": "passed"}[
                receipt["validated_tier"]
            ]
            receipt["reasons"] = list(gate["grade"]["reasons"])
            if not receipt["minimum_quality"]["eligible"]:
                receipt["reasons"].extend(
                    "minimum_quality:" + reason
                    for reason in receipt["minimum_quality"]["reasons"]
                )
        if increment_rejected:
            receipt["reasons"].insert(0, "admission_v2_declared_increment_not_passed")
        receipt["authority_status"] = (
            "source_disabled"
            if not authority_configured(settings)
            else "parallel_only"
            if protocol["mode"] == "parallel"
            else "eligible_to_recheck"
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        receipt["reasons"] = [str(exc)]
    receipt["receipt_digest"] = _hash(receipt)
    return receipt


def _semantic_digest(receipt):
    value = copy.deepcopy(receipt)
    value.pop("receipt_digest", None)
    value.pop("authority_status", None)
    if isinstance(value.get("gate"), dict):
        value["gate"].pop("computed_at", None)
        value["gate"].pop("envelope_digest", None)
    return _hash(value)


def write_receipt(run_dir, receipt):
    identity = _semantic_digest(receipt)
    path = Path(run_dir) / f"admission-v2-{identity[:24]}.json"
    if path.exists():
        receipt = json.loads(path.read_text())
        _require(_semantic_digest(receipt) == identity, "admission_v2_receipt_already_frozen")
    else:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
    intent = _intent(receipt["protocol"])
    return {
        "path": str(path.resolve()),
        "sha256": file_sha(path),
        "protocol_digest": receipt["protocol"]["protocol_digest"],
        "mode": receipt["mode"],
        "status": receipt["status"],
        "validated_tier": receipt["validated_tier"],
        "reasons": receipt["reasons"],
        "capital_authorized": False,
        "intent_kind": intent["kind"],
        **(
            {"target_sleeve_id": intent["target"]["sleeve_id"]}
            if intent["kind"] == "replacement"
            else {}
        ),
    }


def read_bound_receipt(
    settings, descriptor, *, definition_digest, validation_sha256, source_sha256
):
    _require(isinstance(descriptor, dict), "admission_v2_receipt_required")
    path = Path(descriptor.get("path", "")).resolve()
    _require(
        path.is_relative_to(Path(settings.data.data_dir).resolve() / "strategy_library")
        and path.is_file()
        and file_sha(path) == descriptor.get("sha256"),
        "admission_v2_receipt_file_changed",
    )
    receipt = json.loads(path.read_text())
    _require(
        receipt.get("schema") == RECEIPT_SCHEMA
        and receipt.get("receipt_digest")
        == _hash({k: v for k, v in receipt.items() if k != "receipt_digest"}),
        "admission_v2_receipt_digest_mismatch",
    )
    verify_protocol(receipt.get("protocol"), current_code=False, current_config=False)
    from quant_system.research.external_intake import _job_path, _load_job

    owner_path = _job_path(settings, receipt["protocol"]["job_id"])
    _require(owner_path.is_file(), "admission_v2_original_job_required")
    owner = _load_job(settings, receipt["protocol"]["job_id"])
    _require(
        owner.get("admission_protocol") == receipt["protocol"],
        "admission_v2_original_protocol_mismatch",
    )
    binding = receipt.get("source_binding") or {}
    _require(
        binding.get("definition_digest") == definition_digest
        and binding.get("validation_sha256") == validation_sha256
        and binding.get("source_sha256") == source_sha256,
        "admission_v2_candidate_binding_mismatch",
    )
    validation_path = path.parent / "validation.json"
    _require(
        Path(binding.get("validation_path", "")).resolve() == validation_path,
        "admission_v2_validation_path_mismatch",
    )
    verify_validation_receipt(
        validation_path,
        expected_sha=validation_sha256,
        definition_digest=definition_digest,
        require_admission=False,
    )
    _require(
        receipt["protocol"]["protocol_digest"] == descriptor.get("protocol_digest"),
        "admission_v2_protocol_binding_mismatch",
    )
    _require(
        descriptor.get("mode") == receipt["protocol"]["mode"] == receipt.get("mode")
        and descriptor.get("status") == receipt.get("status")
        and descriptor.get("validated_tier") == receipt.get("validated_tier"),
        "admission_v2_descriptor_mismatch",
    )
    intent = _intent(receipt["protocol"])
    if "intent_kind" not in descriptor:
        _require(
            "intent" not in receipt["protocol"] and receipt["mode"] == "parallel",
            "admission_v2_descriptor_intent_missing",
        )
    else:
        _require(
            descriptor["intent_kind"] == intent["kind"]
            and descriptor.get("target_sleeve_id")
            == (intent["target"]["sleeve_id"] if intent["kind"] == "replacement" else None),
            "admission_v2_descriptor_intent_mismatch",
        )
    return receipt


def candidate_id(validation_sha, descriptor):
    return (
        _CANDIDATE_PREFIX
        + _hash({"validation": validation_sha, "admission": descriptor["sha256"]})[:24]
    )


def candidate_uses_protocol(candidate):
    return "admission_v2" in candidate or str(candidate.get("candidate_id", "")).startswith(
        _CANDIDATE_PREFIX
    )


def require_protocol_lineage(settings, candidate):
    """Recover protocol identity from the owner job, not a caller-chosen candidate ID."""
    if candidate.get("source") != "strategy_definition":
        return
    source = Path(candidate.get("source_path") or "").resolve()
    expected = candidate.get("verification_receipt_digest")
    for path in (source.parent / "validations").glob("*/validation.json"):
        if file_sha(path) != expected:
            continue
        raw = json.loads(path.read_text())
        marker = raw.get("admission_protocol_digest")
        evaluation = raw.get("evaluation") or {}
        job_id = evaluation.get("job_id")
        from quant_system.research.external_intake import _job_path, _load_job

        job_path = _job_path(settings, job_id) if job_id else None
        owner_record = json.loads(job_path.read_text()) if job_path and job_path.is_file() else {}
        owner_tagged = "admission_protocol" in owner_record or any(
            plan.get("origin", {}).get("admission_protocol_digest")
            for plan in owner_record.get("plans", [])
        )
        if not marker and not candidate_uses_protocol(candidate) and not owner_tagged:
            return  # Old jobs are not retroactively subjected to new admission gates.
        _require(bool(job_id), "admission_v2_original_job_required")
        job = _load_job(settings, job_id)
        _require(
            job.get("evaluation") == evaluation
            and job["plans_sha256"] == evaluation.get("plans_sha256"),
            "admission_v2_owner_job_binding_mismatch",
        )
        protocol = job.get("admission_protocol")
        descriptor = candidate.get("admission_v2") or {}
        _require(
            protocol is not None
            and candidate_uses_protocol(candidate)
            and descriptor.get("protocol_digest") == protocol["protocol_digest"]
            and (marker is None or marker == protocol["protocol_digest"]),
            "admission_v2_original_protocol_required",
        )
        return


def candidate_receipt(settings, candidate):
    require_protocol_lineage(settings, candidate)
    descriptor = candidate.get("admission_v2")
    _require(isinstance(descriptor, dict), "admission_v2_candidate_receipt_required")
    _require(
        candidate.get("candidate_id")
        == candidate_id(candidate.get("verification_receipt_digest"), descriptor),
        "admission_v2_candidate_identity_mismatch",
    )
    receipt = read_bound_receipt(
        settings,
        descriptor,
        definition_digest=candidate.get("definition_digest"),
        validation_sha256=candidate.get("verification_receipt_digest"),
        source_sha256=candidate.get("source_digest") or candidate.get("candidate_code_digest"),
    )
    source = Path(candidate.get("source_path") or "").resolve()
    run = Path(descriptor["path"]).parent
    _require(
        source == run.parent.parent / "definition.json"
        and source.is_file()
        and file_sha(source) == receipt["source_binding"]["source_sha256"],
        "admission_v2_candidate_source_mismatch",
    )
    from quant_system.research.strategy_library import _returns

    result = json.loads((run / "platform-result.json").read_text())
    returns, dates = _returns(result)
    performance = candidate.get("performance") or {}
    observed = performance.get("daily_returns") or []
    _require(
        dates == performance.get("return_dates")
        and len(observed) == len(returns)
        and all(
            math.isfinite(x) and abs(x - y) <= 1e-12 for x, y in zip(observed, returns, strict=True)
        ),
        "admission_v2_candidate_performance_mismatch",
    )
    return receipt


def candidate_validation(settings, candidate, *, expected_admission_sha=None):
    """Preserve the base receipt contract; authority mode has a separate admission."""
    receipt = candidate_receipt(settings, candidate)
    _require(
        expected_admission_sha is None
        or candidate["admission_v2"]["sha256"] == expected_admission_sha,
        "admission_v2_activation_receipt_changed",
    )
    return verify_validation_receipt(
        receipt["source_binding"]["validation_path"],
        expected_sha=candidate["verification_receipt_digest"],
        definition_digest=candidate["definition_digest"],
        comparison_digest=candidate.get("comparison_digest"),
        require_admission=receipt["mode"] != "authoritative",
    ), receipt


def verify_for_new_capital(
    settings, descriptor, *, definition_digest, validation_sha256, source_sha256, book
):
    return _verify_current_decision(
        settings,
        descriptor,
        definition_digest=definition_digest,
        validation_sha256=validation_sha256,
        source_sha256=source_sha256,
        book=book,
        require_authority=True,
    )


def authority_configured(settings):
    """Cheap source-bound state check, never a qualification or money authorization.

    Money and replacement authority need the module-level source switch and the
    bound activation state together; an activation file alone is not a switch.
    """
    from quant_system.research.admission_activation import configured

    return AUTHORITATIVE_ENABLED and configured(settings)


def verify_for_publication(
    settings, descriptor, *, definition_digest, validation_sha256, source_sha256, book
):
    """A verified new authoritative candidate needs a full tier, but cannot fund."""
    return _verify_current_decision(
        settings,
        descriptor,
        definition_digest=definition_digest,
        validation_sha256=validation_sha256,
        source_sha256=source_sha256,
        book=book,
        require_authority=False,
        purpose="publication",
    )


def verify_locked_new_capital(settings, descriptor, **bindings):
    """Never invokes qualification programs; cold state is a typed refusal."""
    return _verify_current_decision(
        settings,
        descriptor,
        **bindings,
        require_authority=True,
        allow_execution=False,
    )


def project_new_capital_eligibility(
    settings, descriptor, *, definition_digest, validation_sha256, source_sha256
):
    """Read-only money projection; never executes a qualification producer.

    A cold process cannot run the locked preflight, so this only rechecks the
    saved authoritative decision against the registered refs, the current
    code/scope identity and the bound activation state. Actual enabling still
    runs the full locked preflight.
    """
    receipt = read_bound_receipt(
        settings,
        descriptor,
        definition_digest=definition_digest,
        validation_sha256=validation_sha256,
        source_sha256=source_sha256,
    )
    verify_protocol(receipt["protocol"])
    _require(
        receipt["protocol"]["mode"] == "authoritative",
        "admission_v2_parallel_has_no_capital_authority",
    )
    _require(authority_configured(settings), "admission_v2_authority_disabled")
    _require(
        receipt.get("status") == "passed" and receipt.get("validated_tier") == "T2",
        "admission_v2_unfunded_tier",
    )
    _require(
        receipt.get("gate", {}).get("family", {}).get("rule_version") == FAMILY_RULE_VERSION
        and receipt.get("minimum_quality", {}).get("eligible") is True,
        "admission_v2_minimum_quality_required",
    )
    increment = receipt["source_binding"].get("increment_binding")
    _require(
        increment is None or increment.get("objective", {}).get("passed") is True,
        "admission_v2_declared_increment_not_passed",
    )
    _require(
        receipt.get("gate", {}).get("dsr", {}).get("passed") is True,
        "admission_v2_common_dsr_required",
    )
    _require(
        receipt["source_binding"].get("activation_eligible") is True,
        "admission_v2_reference_plan_unfunded",
    )
    refs = qualification_refs(settings, _hash(receipt["source_binding"]))
    _require(refs == receipt.get("qualification_refs"), "admission_v2_qualification_changed")
    _require(
        all(file_sha(ref["path"]) == ref["sha256"] for ref in refs.values()),
        "admission_v2_qualification_changed",
    )
    expected = {
        "scope": SCOPE,
        "code_digest": receipt["protocol"]["code"]["digest"],
        "input_digest": _hash(receipt["source_binding"]),
    }
    rows = receipt.get("qualifications") or {}
    _require(
        set(rows) == set(_REQUIRED_QUALIFICATIONS),
        "admission_v2_qualification_changed",
    )
    refused = [
        str(row.get("reason") or "qualification_not_evaluated")
        for row in rows.values()
        if row.get("status") != "passed" or row.get("bindings") != expected
    ]
    _require(not refused, refused[0] if refused else "admission_v2_qualification_changed")
    _require(
        all(
            isinstance((row.get("registration") or {}).get("registration_digest"), str)
            and bool(row["registration"]["registration_digest"])
            for row in rows.values()
        ),
        "admission_v2_qualification_changed",
    )
    if "activation" in receipt["protocol"]:
        from quant_system.research.admission_activation import require_context

        require_context(
            receipt["protocol"]["activation"],
            qualification_input_context(receipt["source_binding"]),
            source_binding=receipt["source_binding"],
        )
    return receipt


def verify_locked_publication(settings, descriptor, **bindings):
    return _verify_current_decision(
        settings,
        descriptor,
        **bindings,
        require_authority=False,
        allow_execution=False,
        purpose="publication",
    )


def _verify_current_decision(
    settings,
    descriptor,
    *,
    definition_digest,
    validation_sha256,
    source_sha256,
    book,
    require_authority,
    allow_execution=True,
    purpose="new_capital",
    replacement_objects=None,
):
    receipt = read_bound_receipt(
        settings,
        descriptor,
        definition_digest=definition_digest,
        validation_sha256=validation_sha256,
        source_sha256=source_sha256,
    )
    verify_protocol(receipt["protocol"])
    _require(
        _intent(receipt["protocol"])["kind"] != "replacement"
        or purpose in {"publication", "replacement"},
        "admission_v2_replacement_requires_lifecycle",
    )
    _require(
        receipt["protocol"]["mode"] == "authoritative",
        "admission_v2_parallel_has_no_capital_authority",
    )
    if require_authority:
        _require(authority_configured(settings), "admission_v2_authority_disabled")
        if "activation" in receipt["protocol"]:
            # A protocol that froze an activation binding must still prove that
            # binding at every money decision, whichever source switch is on.
            from quant_system.research.admission_activation import verify_for_funding

            verify_for_funding(
                settings,
                receipt["protocol"],
                qualification_input_context(receipt["source_binding"]),
                allow_execution=allow_execution,
                source_binding=receipt["source_binding"],
            )
    _require(
        receipt.get("status") == "passed" and receipt.get("validated_tier") == "T2",
        "admission_v2_unfunded_tier",
    )
    increment = receipt["source_binding"].get("increment_binding")
    _require(
        increment is None or increment.get("objective", {}).get("passed") is True,
        "admission_v2_declared_increment_not_passed",
    )
    _require(
        receipt.get("gate", {}).get("dsr", {}).get("passed") is True,
        "admission_v2_common_dsr_required",
    )
    _require(
        receipt["source_binding"].get("activation_eligible") is True,
        "admission_v2_reference_plan_unfunded",
    )
    current_refs = qualification_refs(settings, _hash(receipt["source_binding"]))
    _require(
        current_refs == receipt.get("qualification_refs"), "admission_v2_qualification_changed"
    )
    if not allow_execution:
        _warm_qualifications(settings, receipt["protocol"], receipt["source_binding"], current_refs)
    rows, ledger_sha = ledger_snapshot(settings)
    _require(
        ledger_sha == receipt["source_binding"]["trial_ledger_sha256"],
        "admission_v2_family_changed",
    )
    _, peers = peer_snapshot(book, settings=settings)
    _require(
        peers["digest"] == receipt["source_binding"]["peer_digest"], "admission_v2_peers_changed"
    )
    _require(
        all(
            row["status"] == "passed"
            for row in _qualifications(
                settings,
                receipt["protocol"],
                receipt["source_binding"],
                current_refs,
                allow_execution=allow_execution,
            ).values()
        ),
        "admission_v2_qualification_changed",
    )
    resolver = CurrentFamilyResolver(Path(settings.data.data_dir), trusted_trials=rows)
    _require(
        verify_verdict_v2(
            receipt["gate"],
            trusted_trials=rows,
            curve_resolver=resolver,
            legacy_resolver=resolver.legacy,
        ),
        "admission_v2_gate_recomputation_failed",
    )
    _require(
        receipt["gate"]["tier_recommendation"]
        == {"tier": "T2", "tier_source": "program_rule", "allocated_cash": 10000.0},
        "admission_v2_tier_or_budget_mismatch",
    )
    validation = json.loads(Path(receipt["source_binding"]["validation_path"]).read_text())
    fresh = evaluate_validation(
        settings,
        protocol=receipt["protocol"],
        validation_path=receipt["source_binding"]["validation_path"],
        expected_validation_sha=validation_sha256,
        definition_digest=definition_digest,
        source_sha256=source_sha256,
        evaluation=validation.get("evaluation"),
        book=book,
        _qualification_execution=allow_execution,
        _replacement_objects=replacement_objects,
    )
    _require(
        _semantic_digest(fresh) == _semantic_digest(receipt),
        "admission_v2_saved_decision_not_reproducible",
    )
    return receipt


def _verify_replacement(
    settings,
    *,
    new_candidate,
    target_candidate,
    target_sleeve,
    target_config,
    book,
    allow_execution,
):
    candidate_receipt(settings, new_candidate)
    objects = {
        "new_candidate": new_candidate,
        "target_candidate": target_candidate,
        "target_sleeve": target_sleeve,
        "target_config": target_config,
    }
    receipt = read_bound_receipt(
        settings,
        new_candidate["admission_v2"],
        definition_digest=new_candidate["definition_digest"],
        validation_sha256=new_candidate["verification_receipt_digest"],
        source_sha256=new_candidate["source_digest"],
    )
    _require(
        _intent(receipt["protocol"])["kind"] == "replacement",
        "admission_v2_explicit_replacement_required",
    )
    state = _replacement_state(settings, receipt["protocol"], book, objects)
    _require(
        new_candidate.get("status") == "verified"
        and not new_candidate.get("sleeve_id")
        and any(row == new_candidate for row in book["candidates"]),
        "admission_v2_replacement_candidate_not_current",
    )
    verified = _verify_current_decision(
        settings,
        new_candidate["admission_v2"],
        definition_digest=new_candidate["definition_digest"],
        validation_sha256=new_candidate["verification_receipt_digest"],
        source_sha256=new_candidate["source_digest"],
        book=book,
        require_authority=True,
        purpose="replacement",
        allow_execution=allow_execution,
        replacement_objects=objects,
    )
    _require(
        verified.get("replacement", {}).get("target") == state["target"],
        "admission_v2_replacement_target_changed",
    )
    return {**verified, "capital_delta_usd": 0, "replacement_target": state["target"]}


def prepare_replacement_preflight(settings, **objects):
    """Fixed coordinator hook; producer work is allowed only before financial locks."""
    return _verify_replacement(settings, **objects, allow_execution=True)


def verify_for_replacement(settings, **objects):
    """Fixed locked coordinator hook; a saved JSON cannot supply its warm proof."""
    return _verify_replacement(settings, **objects, allow_execution=False)
