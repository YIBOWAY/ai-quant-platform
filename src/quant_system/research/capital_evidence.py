"""Read-only original-evidence adapters for the shared new-capital quality report.

This never installs qualifications, writes trials or changes an account. Financial
consumers retain their current-state locks, peer lineage and authority checks.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path

from quant_system.research.evaluation_service import _hash


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


class CurrentFamilyResolver:
    """Compose the existing archive adapters for every current family consumer."""

    def __init__(self, data_root, *, trusted_trials):
        from quant_system.research.d34_family_evidence import D34FamilyEvidenceResolver

        self.data_root, self.trusted_trials = data_root, trusted_trials
        self._archived = None
        self.d34 = D34FamilyEvidenceResolver(data_root, trusted_trials=trusted_trials)
        self.resolved = {}

    @property
    def archived(self):
        # A candidate with missing/stale originals fails before a full archive
        # scan. This is per-read lazy work, never a cache across funding calls.
        from quant_system.research.gate_v2.family import ArchivedCurveResolver

        if self._archived is None:
            self._archived = ArchivedCurveResolver(
                self.data_root, trusted_trials=self.trusted_trials,
            )
        return self._archived

    def __call__(self, row):
        row = row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        payload = self.d34(row) if row.get("kind") == "d34_experiment" else self.archived(row)
        if payload is not None:
            self.resolved[row["trial_id"]] = payload
        return payload

    def legacy(self, row):
        from quant_system.research.legacy_family_evidence import recover_legacy_family_contract

        row = row.model_dump(mode="json") if hasattr(row, "model_dump") else row
        payload = self.archived.legacy(row)
        if payload is not None:
            payload = recover_legacy_family_contract(self.data_root, row, payload)
            self.resolved[row["trial_id"]] = payload
        return payload


class _Originals:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = {}

    def path(self, path):
        path = Path(path).resolve(strict=True)
        _require(path.is_relative_to(self.root) and path.is_file(), "original_outside_owner_root")
        return path

    def pin(self, path):
        path = self.path(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        previous = self.files.setdefault(str(path), digest)
        _require(previous == digest, "original_changed_during_read")
        return path

    def read(self, path):
        from quant_system.execution.assistant_remote import _strict_json_mapping

        path = self.pin(path)
        value = _strict_json_mapping(path)
        _require(isinstance(value, dict), "original_document_invalid")
        return value

    def verify(self):
        for path, expected in self.files.items():
            _require(
                hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected,
                "original_changed_during_read",
            )


def _book_performance(candidate, values, dates):
    performance = candidate.get("performance") or {}
    _require(
        performance.get("daily_returns") == values and performance.get("return_dates") == dates,
        "candidate_original_performance_mismatch",
    )


def _definition_candidate(candidate, originals):
    from quant_system.research.gate_v2.active_returns import recompute_active_returns
    from quant_system.research.gate_v2.family import (
        _validate_curve,
        compatibility_contract_from_result,
    )
    from quant_system.research.strategy_definition import validate_definition
    from quant_system.research.validation_receipts import verify_candidate_validation

    source = originals.pin(candidate["source_path"])
    _require(
        source.is_relative_to(originals.root / "strategy_library")
        and source.name == "definition.json",
        "candidate_definition_path_invalid",
    )
    _require(
        originals.files[str(source)] == candidate.get("source_digest"),
        "candidate_source_digest_mismatch",
    )
    definition = validate_definition(originals.read(source))
    _require(
        definition.content_digest == candidate.get("definition_digest")
        and list(definition.symbols) == candidate.get("universe"),
        "candidate_definition_mismatch",
    )
    validation = verify_candidate_validation(
        source,
        expected_sha=candidate.get("verification_receipt_digest"),
        definition_digest=definition.content_digest,
        comparison_digest=candidate.get("comparison_digest"),
    )
    matches = [
        path
        for path in (source.parent / "validations").glob("validation-*/validation.json")
        if hashlib.sha256(path.read_bytes()).hexdigest()
        == candidate.get("verification_receipt_digest")
    ]
    _require(len(matches) == 1, "candidate_validation_ambiguous")
    path = originals.pin(matches[0])
    for name, digest in validation["receipts"]["files"].items():
        original = originals.pin(path.parent / name)
        _require(originals.files[str(original)] == digest, "candidate_validation_input_changed")
    payload = originals.read(path.parent / "platform-result.json")
    _require(
        payload.get("definition") == definition.model_dump(mode="json")
        and payload.get("profile", {}).get("symbols") == list(definition.symbols),
        "candidate_result_definition_mismatch",
    )
    contract = compatibility_contract_from_result(payload, definition=definition)
    _validate_curve(payload["curve"], active=True)
    active = recompute_active_returns(
        payload["curve"], initial_cash=payload["evaluation_initial_cash"]
    )
    _require(
        active.get("reason") is None and len(active["dates"]) == len(payload["curve"]),
        "candidate_curve_incomplete",
    )
    _book_performance(candidate, active["equity_returns"], active["dates"])
    return {
        "selected": active["active_returns"],
        "total": active["equity_returns"],
        "dates": active["dates"],
        "contract": contract,
        "turnover": payload.get("metrics", {}).get("turnover"),
        "selected_engine": "platform",
        "exposure_engine": "platform",
        "exposure_returns": active["equity_returns"],
        "exposure_dates": active["dates"],
    }


def _d34_candidate(candidate, originals, rows, resolver, *, exposure_only=False):
    from quant_system.d34.engine_comparison import (
        ComparisonPolicy,
        EngineReceipt,
        compare_engine_receipts,
    )
    from quant_system.d34.research_request import digest_document
    from quant_system.execution.assistant_remote import CandidateEvidenceRef, _bound_engine_receipt
    from quant_system.research.gate_v2.family import _family_returns

    ref = CandidateEvidenceRef(**candidate["evidence_ref"]).validated()
    _require(
        re.fullmatch(r"job-[A-Za-z0-9._:-]+", ref["job_id"]) is not None, "candidate_job_id_invalid"
    )
    job = originals.root / "_runtime/d34/jobs" / ref["job_id"]
    manifest = originals.read(job / "evidence_manifest.json")
    _require(
        manifest.get("manifest_digest")
        == ref["manifest_digest"]
        == digest_document({k: v for k, v in manifest.items() if k != "manifest_digest"})
        and manifest.get("contract") == "hqa.d34_research_evidence/v1"
        and manifest.get("job_id") == ref["job_id"]
        and manifest.get("run_id") == ref["run_id"],
        "candidate_manifest_mismatch",
    )
    request = originals.read(job / "research_request.json")
    _require(
        manifest.get("research_request_digest") == digest_document(request)
        and request.get("job_id") == ref["job_id"]
        and request.get("run_id") == ref["run_id"]
        and request.get("universe") == candidate.get("universe"),
        "candidate_request_mismatch",
    )
    source = originals.pin(candidate["source_path"])
    _require(
        source == originals.path(job / manifest["candidate_code_path"])
        and source.is_relative_to(job / "research")
        and originals.files[str(source)]
        == candidate.get("source_digest")
        == manifest.get("candidate_code_digest"),
        "candidate_source_digest_mismatch",
    )
    _require(
        manifest.get("cost_model") == {"commission_bps": 1.0, "slippage_bps": 5.0},
        "candidate_platform_cost_scope_unsupported",
    )
    engines = {}
    for engine in ("qlib", "platform"):
        path = originals.pin(job / manifest[engine + "_receipt_path"])
        _require(
            originals.files[str(path)] == manifest[engine + "_receipt_file_digest"],
            "candidate_bound_receipt_changed",
        )
        bound = _bound_engine_receipt(
            path,
            job_root=job,
            job_id=ref["job_id"],
            run_id=ref["run_id"],
            resource_envelope_id=request["resource_envelope_id"],
            engine=engine,
        )
        raw = originals.pin(bound["raw_receipt_path"])
        _require(
            raw == originals.path(job / manifest[engine + "_raw_receipt_path"])
            and originals.files[str(raw)] == manifest[engine + "_raw_receipt_file_digest"]
            and bound["raw_receipt_digest"]
            == ref[engine + "_raw_receipt_digest"]
            == manifest[engine + "_receipt_digest"],
            "candidate_engine_original_mismatch",
        )
        engines[engine] = bound
    comparison = compare_engine_receipts(
        qlib=EngineReceipt(**engines["qlib"]["engine_receipt"]),
        platform=EngineReceipt(**engines["platform"]["engine_receipt"]),
        policy=ComparisonPolicy.initial(),
    )
    _require(
        comparison.accepted
        and comparison.comparison_digest
        == manifest.get("comparison_digest")
        == candidate.get("comparison_digest"),
        "candidate_dual_engine_rejected",
    )
    if exposure_only:
        platform = engines["platform"]["engine_receipt"]
        return platform["daily_returns"], [day[:10] for day in platform["return_dates"]]
    qlib = engines["qlib"]["raw_document"]
    _require(
        qlib.get("candidate_code_digest") == candidate.get("source_digest")
        and qlib.get("factor_id") == candidate.get("factor_id"),
        "candidate_qlib_source_mismatch",
    )
    matches = [
        row
        for row in rows
        if row.get("kind") == "d34_experiment"
        and row.get("metadata", {}).get("job_id") == ref["job_id"]
        and row.get("metadata", {}).get("experiment_id") == qlib.get("selected_experiment")
    ]
    _require(len(matches) == 1, "candidate_selected_trial_missing_or_ambiguous")
    payload = resolver(matches[0])
    _require(payload is not None, "candidate_selected_trial_original_unavailable")
    _require(
        payload["family_evidence"]["selection_history"]["selected_experiment"]
        == qlib.get("selected_experiment"),
        "candidate_selected_trial_mismatch",
    )
    for path, digest in payload["family_evidence"]["files"].items():
        original = originals.pin(path)
        _require(originals.files[str(original)] == digest, "candidate_selected_input_changed")
    batches = [
        path
        for path in payload["family_evidence"]["files"]
        if Path(path).name.startswith("experiment-trials-")
    ]
    _require(len(batches) == 1, "candidate_selected_batch_ambiguous")
    batch = originals.read(batches[0])
    experiment = next(
        row for row in batch["experiments"] if row["experiment_id"] == qlib["selected_experiment"]
    )
    _require(
        experiment["daily_returns"] == qlib["daily_returns"]
        and batch["return_dates"] == qlib["return_dates"],
        "candidate_selected_returns_mismatch",
    )
    evaluation = experiment.get("evaluation_contract")
    if evaluation is not None:
        _require(
            evaluation["qlib_config"] == qlib.get("qlib_config")
            and evaluation["qlib_config_digest"] == qlib.get("qlib_config_digest"),
            "candidate_selected_cost_contract_mismatch",
        )
    # The resolver proves the Qlib experiment and its combined-rate economics.
    # Keep that selected object distinct from the Platform exposure comparator.
    values = _family_returns(payload, payload["family_contract"])
    original_values = engines["qlib"]["engine_receipt"]["daily_returns"]
    _require(
        len(values["equity_returns"]) == len(original_values), "candidate_trial_curve_mismatch"
    )
    platform = engines["platform"]["engine_receipt"]
    exposure_dates = [day[:10] for day in platform["return_dates"]]
    _book_performance(candidate, platform["daily_returns"], exposure_dates)
    return {
        "selected": original_values,
        "total": original_values,
        "dates": [day[:10] for day in qlib["return_dates"]],
        "contract": payload["family_contract"],
        "turnover": engines["qlib"]["turnover_period"],
        "selected_engine": "qlib",
        "exposure_engine": "platform",
        "exposure_returns": platform["daily_returns"],
        "exposure_dates": exposure_dates,
    }


def _registered_candidate(candidate, originals, rows, *, historical=False):
    import inspect

    from quant_system.execution.assistant_remote import CandidateEvidenceRef
    from quant_system.factors.registry import build_factor_registry
    from quant_system.research.registered_family_evidence import (
        read_registered_exposure,
        read_registered_trial,
    )

    _require(isinstance(candidate.get("evidence_ref"), dict),
             "candidate_registered_evidence_required")
    ref = CandidateEvidenceRef(**candidate["evidence_ref"]).validated()
    _require(re.fullmatch(r"job-registered-[A-Za-z0-9._:-]+", ref["job_id"]) is not None,
             "candidate_registered_job_invalid")
    job = originals.root / "_runtime/d34/jobs" / ref["job_id"]
    selected = (
        read_registered_exposure(originals.root, job) if historical
        else read_registered_trial(originals.root, job, rows)
    )
    manifest = selected["manifest"]
    _require(
        selected["comparison_accepted"] is True
        and manifest["manifest_digest"] == ref["manifest_digest"]
        == candidate.get("verification_receipt_digest")
        and manifest["run_id"] == ref["run_id"]
        and manifest["source_digest"] == candidate.get("source_digest")
        and manifest["factor_id"] == candidate.get("factor_id")
        and manifest["universe"] == candidate.get("universe")
        and manifest["comparison_digest"] == candidate.get("comparison_digest")
        and manifest["qlib_receipt_digest"] == ref["qlib_raw_receipt_digest"]
        and manifest["platform_receipt_digest"] == ref["platform_raw_receipt_digest"],
        "candidate_registered_identity_mismatch",
    )
    if not historical:
        from quant_system.research.registered_family_evidence import registered_producer_sources

        _require(selected.get("producer_sources") == registered_producer_sources(),
                 "candidate_registered_producer_changed_or_unproven")
        factor = build_factor_registry(purpose="paper").create(candidate["factor_id"])
        source = Path(inspect.getsourcefile(type(factor)) or "").resolve(strict=True)
        _require(source == Path(candidate["source_path"]).resolve(strict=True)
                 and hashlib.sha256(source.read_bytes()).hexdigest() == manifest["source_digest"],
                 "candidate_registered_current_source_mismatch")
    for path, expected in selected["source_files"].items():
        actual = originals.pin(path)
        _require(originals.files[str(actual)] == expected, "candidate_registered_original_changed")
    # The historical book/comparison used the original pct_change array. The
    # decision object includes the first session's actual price movement/fees.
    _book_performance(candidate, selected["raw_receipt_returns"], selected["dates"])
    return selected


def registered_population_integrity(data_root, rows, universe, contract, candidates=()):
    """Additional census of real evaluations; never invent or append ledger rows."""
    from quant_system.research.registered_family_evidence import census_registered_trials
    from quant_system.research.trials import universe_digest

    census = census_registered_trials(data_root, rows)
    entries = list(census["entries"])
    found = {item.get("job_id") for item in entries}
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("source") != "registered_factor":
            continue
        job = (candidate.get("evidence_ref") or {}).get("job_id")
        if job not in found:
            entries.append({"status": "unknown", "job_id": job,
                            "candidate_id": candidate.get("candidate_id"),
                            "universe_digest": universe_digest(candidate.get("universe") or []),
                            "universe_verified": False, "contract": None,
                            "reason": "registered_candidate_job_missing"})
    target = universe_digest(universe)
    gaps, outside, input_files = [], [], {}
    for entry in entries:
        for path_key, sha_key in (("manifest_path", "manifest_sha256"),
                                  ("failure_receipt_path", "failure_receipt_sha256")):
            if entry.get(path_key) and entry.get(sha_key):
                input_files[entry[path_key]] = entry[sha_key]
        if entry["status"] in {"recorded", "no_real_evaluation", "recovered_evaluation"}:
            continue
        proven = entry.get("universe_verified") is True
        if proven and entry.get("universe_digest") != target:
            outside.append({**entry, "exclusion": "universe_mismatch"})
        elif (proven and entry.get("contract_verified") is True
              and entry.get("contract") is not None and entry["contract"] != contract):
            outside.append({**entry, "exclusion": "incompatible_return_contract"})
        else:
            gaps.append(entry)
    result = {"schema": "current_registered_population_integrity/v1", "complete": not gaps,
              "gaps": gaps, "out_of_scope": outside, "input_files": input_files,
              "new_trials": 0, "writes": 0}
    result["digest"] = _hash(result)
    return result


def historical_peer_exposure(candidate, originals):
    """Authenticate an existing exposure without recertifying its old qualification."""
    from quant_system.research.fingerprint_grading import frozen_definition_identity
    from quant_system.research.strategy_library import _returns

    if candidate.get("source") == "registered_factor":
        selected = _registered_candidate(candidate, originals, [], historical=True)
        return {"sleeve_id": candidate["sleeve_id"], "returns": selected["exposure_returns"],
                "dates": selected["exposure_dates"], "definition_digest": None}
    source = originals.pin(candidate["source_path"])
    _require(originals.files[str(source)] == candidate.get("source_digest"),
             "peer_source_digest_mismatch")
    if candidate.get("source") == "strategy_definition":
        definition = frozen_definition_identity(originals.read(source))
        _require(definition.content_digest == candidate.get("definition_digest")
                 and list(definition.symbols) == candidate.get("universe"),
                 "peer_definition_mismatch")
        paths = [path for path in (source.parent / "validations").glob("*/validation.json")
                 if hashlib.sha256(path.read_bytes()).hexdigest()
                 == candidate.get("verification_receipt_digest")]
        _require(len(paths) == 1, "peer_validation_missing_or_ambiguous")
        validation = originals.read(paths[0])
        _require(validation.get("definition_digest") == definition.content_digest
                 and validation.get("status") == "passed"
                 and validation.get("comparison", {}).get("accepted") is True
                 and validation["comparison"].get("comparison_digest")
                 == candidate.get("comparison_digest"), "peer_validation_mismatch")
        files = validation.get("receipts", {}).get("files", {})
        _require(set(files) == {"prices.parquet", "platform-result.json", "qlib-replay.json",
                                "signal-analysis.json"}, "peer_validation_bindings_missing")
        for name, expected in files.items():
            path = originals.pin(paths[0].parent / name)
            _require(originals.files[str(path)] == expected, "peer_original_changed")
        result = originals.read(paths[0].parent / "platform-result.json")
        _require(result.get("definition_digest") == definition.content_digest
                 and result.get("definition") == definition.model_dump(mode="json"),
                 "peer_result_definition_mismatch")
        values, dates = _returns(result)
    elif candidate.get("source") == "d34_artifact":
        if candidate.get("evidence_ref"):
            values, dates = _d34_candidate(candidate, originals, [], None, exposure_only=True)
        else:
            values, dates = _legacy_d34_peer(candidate, originals, source)
    else:
        raise ValueError("peer_original_adapter_unavailable")
    _book_performance(candidate, values, dates)
    return {"sleeve_id": candidate["sleeve_id"], "returns": values, "dates": dates,
            "definition_digest": candidate.get("definition_digest")}


def _legacy_d34_peer(candidate, originals, source):
    """Old cycle/dual-engine originals can prove exposure, never fresh funding."""
    from quant_system.d34.engine_comparison import (
        ComparisonPolicy,
        EngineReceipt,
        compare_engine_receipts,
    )
    from quant_system.d34.research_request import digest_document

    job = source.parents[2]
    _require(job.parent == originals.root / "_runtime/d34/jobs", "peer_job_path_invalid")
    cycle = originals.read(job / "cycle_receipt.json")
    request = originals.read(job / "research_request.json")
    _require(cycle.get("job_id") == job.name == request.get("job_id")
             and cycle.get("candidate_code_digest") == candidate.get("source_digest")
             and cycle.get("comparison_digest") == candidate.get("comparison_digest")
             and request.get("universe") == candidate.get("universe")
             and cycle.get("comparison_accepted") is True, "peer_cycle_identity_mismatch")
    engines = {}
    for engine in ("qlib", "platform"):
        matches = []
        paths = ([source.parent / "qlib_receipt.json"] if engine == "qlib"
                 else (job / "platform-replay").glob("*/receipt.json"))
        for path in paths:
            document = originals.read(path)
            expected = document.get("receipt_digest")
            if expected != cycle.get(engine + "_receipt_digest"):
                continue
            _require(expected == digest_document({k: v for k, v in document.items()
                                                   if k != "receipt_digest"}),
                     "peer_engine_receipt_changed")
            matches.append(document)
        _require(len(matches) == 1, "peer_engine_original_missing_or_ambiguous")
        document = matches[0]
        engines[engine] = EngineReceipt(**{key: document[key] for key in
                                          EngineReceipt.__dataclass_fields__})
    comparison = compare_engine_receipts(qlib=engines["qlib"], platform=engines["platform"],
                                         policy=ComparisonPolicy.initial())
    _require(comparison.accepted and comparison.comparison_digest == candidate["comparison_digest"],
             "peer_dual_engine_mismatch")
    return (list(engines["platform"].daily_returns),
            [day[:10] for day in engines["platform"].return_dates])


def current_peer_exposures(settings, candidates, *, originals=None):
    own_originals = originals is None
    originals = originals or _Originals(settings.data.data_dir)
    peers = [historical_peer_exposure(peer, originals) for peer in candidates
             if isinstance(peer, dict) and peer.get("status") == "hung"]
    _require(len({row["sleeve_id"] for row in peers}) == len(peers), "peer_duplicate_sleeve")
    if own_originals:
        originals.verify()
    return peers, dict(originals.files)


def current_candidate_quality(settings, candidate, candidates):
    """Project current minimum quality from original files; never authorizes money."""
    from quant_system.execution.assistant_remote import _certify_cost_sensitivity
    from quant_system.research.admission_v2 import ledger_snapshot
    from quant_system.research.capital_quality import evaluate_new_capital_quality
    from quant_system.research.gate_v2.correlation_v2 import raw_concentration_v2
    from quant_system.research.gate_v2.family import project_family_v2
    from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG
    from quant_system.research.trials import performance_from_daily_returns, universe_digest

    originals = _Originals(settings.data.data_dir)
    binding = {"adapter": "current_candidate_originals/v1", "funding_authority": False}
    try:
        ledger = originals.root / "trials/trials.jsonl"
        rows, ledger_sha = ledger_snapshot(settings) if ledger.is_file() else ([], None)
        binding.update(
            trial_ledger_sha256=ledger_sha, trial_ledger_state="present" if ledger_sha else "absent"
        )
        resolver = CurrentFamilyResolver(originals.root, trusted_trials=rows)

        source = candidate.get("source")
        if source == "strategy_definition":
            selected = _definition_candidate(candidate, originals)
        elif source == "d34_artifact":
            selected = _d34_candidate(candidate, originals, rows, resolver)
        elif source == "registered_factor":
            selected = _registered_candidate(candidate, originals, rows)
        else:
            raise ValueError("candidate_source_adapter_unavailable")
        population = registered_population_integrity(
            originals.root, rows, candidate["universe"], selected["contract"], candidates,
        )
        binding["registered_population"] = population
        for path, expected in population["input_files"].items():
            actual = originals.pin(path)
            _require(originals.files[str(actual)] == expected, "registered_population_changed")
        _require(population["complete"], "current_registered_population_incomplete")
        family = project_family_v2(
            trials_rows=rows,
            universe_digest=universe_digest(candidate["universe"]),
            compatibility_contract=selected["contract"],
            curve_resolver=resolver,
            legacy_resolver=resolver.legacy,
        )
        for payload in resolver.resolved.values():
            for evidence_key in ("family_evidence", "legacy_evidence"):
                for path, digest in (payload.get(evidence_key) or {}).get("files", {}).items():
                    original = originals.pin(path)
                    _require(originals.files[str(original)] == digest, "family_input_changed")
        peers, _ = current_peer_exposures(settings, [peer for peer in candidates
            if peer.get("candidate_id") != candidate.get("candidate_id")], originals=originals)
        concentration = raw_concentration_v2(
            candidate_returns=selected["exposure_returns"],
            candidate_dates=selected["exposure_dates"],
            hung_sleeves=peers,
            require_dates=True,
        )
        concentration.update(applicable=bool(peers), passed=concentration["raw_passed"])
        performance = performance_from_daily_returns(selected["total"])
        performance.update(
            daily_returns=selected["total"],
            return_dates=selected["dates"],
            turnover_period=selected["turnover"],
        )
        cost = _certify_cost_sensitivity({"performance": performance}, cost_bps=6.0)
        result = evaluate_new_capital_quality(
            selected_returns=selected["selected"],
            total_returns=selected["total"],
            dates=selected["dates"],
            return_contract=selected["contract"],
            family=family,
            concentration=concentration,
            cost=cost,
            config=GATE_V2_CONFIG,
        )
        current_sha = ledger_snapshot(settings)[1] if ledger.is_file() else None
        _require(current_sha == ledger_sha, "candidate_family_changed_during_read")
        _require(registered_population_integrity(
            originals.root, rows, candidate["universe"], selected["contract"], candidates,
        )["digest"] == population["digest"], "registered_population_changed_during_read")
        originals.verify()
        binding.update(
            candidate_digest=_hash(candidate),
            peer_digest=_hash(peers),
            selected_engine=selected["selected_engine"],
            exposure_engine=selected["exposure_engine"],
            selected_returns_digest=_hash(selected["selected"]),
            selected_dates_digest=_hash(selected["dates"]),
            exposure_returns_digest=_hash(selected["exposure_returns"]),
            exposure_dates_digest=_hash(selected["exposure_dates"]),
            family_digest=family["family_digest"],
        )
        result["family"] = family
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        result = {
            "schema": "new_paper_capital_minimum_quality/v1",
            "eligible": False,
            "tier": "T0",
            "reasons": ["quality_evidence_unavailable"],
            "evidence_reason": str(exc),
            "funding_authority": False,
        }
    from quant_system.d34 import engine_comparison
    from quant_system.execution import assistant_remote
    from quant_system.research import (
        capital_quality,
        d34_family_evidence,
        registered_family_evidence,
        strategy_definition,
        trials,
        validation_receipts,
    )
    from quant_system.research.gate_v2 import (
        active_returns,
        correlation_v2,
        dsr_v2,
        health_v2,
        verdict,
    )
    from quant_system.research.gate_v2 import family as family_module

    binding["source_sha256"] = {
        module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (
            capital_quality,
            d34_family_evidence,
            registered_family_evidence,
            validation_receipts,
            family_module,
            engine_comparison,
            assistant_remote,
            strategy_definition,
            trials,
            active_returns,
            correlation_v2,
            dsr_v2,
            health_v2,
            verdict,
        )
    }
    binding["source_sha256"][__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    binding["files"] = dict(sorted(originals.files.items()))
    result["evidence_binding"] = copy.deepcopy(binding)
    return result
