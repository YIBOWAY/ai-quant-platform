"""Freeze verified exploration material for the existing intake schema.

This is a read-only bridge, not an admission decision or queue producer. Its
required engineering checks must all pass. Formal data quality, net replay,
dual-engine validation and financial admission remain not_evaluated; a frozen
payload confers no right to allocate capital. Local hashes bind contents and
versions, not an external signature or proof of historical market-data truth.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_system.d34 import qlib_expr
from quant_system.research import behavior_review, exploration_sandbox
from quant_system.research.exploration_sandbox import digest
from quant_system.research.external_intake import Proposal, strict_json

SCHEMA = "exploration_intake_material/v1"
_MATERIAL_KEYS = {
    "source_urls",
    "source_title",
    "published_at",
    "retrieved_at",
    "hypothesis",
    "adaptation_note",
}


class ExplorationAdmissionError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise ExplorationAdmissionError(reason)


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_digest(document, field):
    _require(
        document.get(field) == digest({k: v for k, v in document.items() if k != field}),
        field + "_mismatch",
    )


def _isolation(run, *, source_sha, runner_sha, adapter_sha):
    _require(
        run.get("source_sha256") == source_sha
        and run.get("runner_sha256") == runner_sha
        and run.get("adapter_sha256") == adapter_sha,
        "execution_source_version_mismatch",
    )
    _require(str(run.get("image_id", "")).startswith("sha256:"), "image_identity_missing")
    iso = run.get("isolation") or {}
    _require(
        iso.get("network_mode") == "none"
        and iso.get("readonly_rootfs") is True
        and iso.get("input_readonly") is True
        and iso.get("memory_bytes") == 512 * 1024 * 1024
        and iso.get("pids_limit") == 32
        and iso.get("nano_cpus") == 1_000_000_000
        and iso.get("user") == "65534:65534"
        and "ALL" in iso.get("cap_drop", [])
        and "no-new-privileges" in iso.get("security_opt", [])
        and iso.get("bind_destinations") == ["/input", "/runner.py"],
        "isolation_evidence_incomplete",
    )


def prepare_exploration_candidate(
    run_dir: Path, *, source_material: dict, ordered_symbols: list[str], data_provenance: dict
) -> dict:
    """Verify a local run bundle and return an unsubmitted, frozen Proposal envelope."""
    run_dir = Path(run_dir).resolve()
    receipt = json.loads((run_dir / "receipt.json").read_text())
    inputs = json.loads((run_dir / "input.json").read_text())
    source_sha = _file_sha(run_dir / "factor.py")
    review = receipt.get("behavior") or {}
    _check_digest(receipt, "receipt_digest")
    _check_digest(review, "review_digest")
    _require(
        receipt.get("schema") == "research_exploration/v1"
        and receipt.get("status") == "research_candidate"
        and receipt.get("scope") == "research_only",
        "research_candidate_required",
    )
    _require(
        receipt.get("promotion_authorized") is False and receipt.get("switch_authorized") is False,
        "exploration_cannot_grant_authority",
    )
    _require(
        review.get("version") == behavior_review.VERSION
        and review.get("probe_sha256") == _file_sha(behavior_review.__file__),
        "review_version_mismatch",
    )
    _require(
        review.get("source_sha256") == source_sha and review.get("input_digest") == digest(inputs),
        "source_or_input_digest_mismatch",
    )
    _require(review.get("status") == "pass", "behavior_not_passed")
    probes = review.get("probes") or []
    required = {
        "output_contract",
        "determinism",
        "future_perturbation",
        "prefix_truncation",
        "available_at_visibility",
        "membership_change",
        "missing_market_data",
        "fault_propagation",
    }
    _require(
        required.issubset({p.get("probe") for p in probes})
        and all(p.get("status") == "pass" for p in probes),
        "probe_missing_or_not_passed",
    )
    reference = review.get("reference") or {}
    comparisons = reference.get("comparisons") or {}
    _require(
        reference.get("status") == "pass"
        and comparisons
        and all(
            r.get("status") == "pass"
            and all(r.get(k) is True for k in ("scores_equal", "rankings_equal", "holdings_equal"))
            for r in comparisons.values()
        ),
        "reference_not_passed",
    )
    expression = review.get("expected_expression")
    compiled = qlib_expr.compile_qlib_expr(expression)
    _require(
        reference.get("contract_digest")
        == digest(
            {
                "expected_expression": expression,
                "comparator_version": behavior_review.VERSION,
                "top_k": 2,
            }
        ),
        "reference_digest_mismatch",
    )
    compiler_sha = _file_sha(qlib_expr.__file__)
    _require(
        all(r.get("compiler_sha256") == compiler_sha for r in comparisons.values()),
        "compiler_version_mismatch",
    )
    frame = behavior_review.prepare_input(pd.DataFrame(inputs["ohlcv"]))
    n_dates = frame.timestamp.nunique()
    _require(
        sum(p.get("probe") == "prefix_truncation" for p in probes)
        == (n_dates - 1 if n_dates <= 32 else 4),
        "prefix_coverage_missing",
    )
    raw_scores = review.get("scores") or []
    _require(
        all(set(row) == {"symbol", "timestamp", "score"} for row in raw_scores),
        "score_schema_mismatch",
    )
    # JSON objects have no column order; the producer writes sorted object keys.
    ordered_scores = pd.DataFrame(raw_scores)[["symbol", "timestamp", "score"]].to_dict("records")
    scores = behavior_review.checked_scores({"status": "ok", "scores": ordered_scores}, frame)
    recomputed = behavior_review.verify_translation(expression, frame, scores)
    _require(
        recomputed.get("status") == "pass" and comparisons.get("baseline") == recomputed,
        "baseline_reference_recomputation_failed",
    )
    translation = receipt.get("translation") or {}
    _require(translation == recomputed, "final_translation_not_bound_to_scores")
    _require(receipt.get("batch_vs_causal_equal") is True, "causal_scores_not_equal")
    runner_sha = _file_sha(
        Path(exploration_sandbox.__file__).resolve().parents[3]
        / "scripts/exploration_sandbox_runner.py"
    )
    adapter_sha = _file_sha(exploration_sandbox.__file__)
    executions = review.get("executions") or {}
    _require(
        set(executions) - {"malformed"} == set(comparisons), "execution_reference_set_mismatch"
    )
    for name, run in executions.items():
        _isolation(run, source_sha=source_sha, runner_sha=runner_sha, adapter_sha=adapter_sha)
        _require(
            run.get("status") == "ok"
            or (name == "malformed" and run.get("reason") == "factor_exception"),
            "probe_execution_not_evaluated",
        )
    baseline_input = digest(
        {"ohlcv": exploration_sandbox.records(frame), "context": inputs["context"]}
    )
    _require(
        all(
            executions.get(name, {}).get("input_digest") == baseline_input
            for name in ("baseline", "repeat")
        ),
        "baseline_execution_input_mismatch",
    )
    causal = receipt.get("causal_execution") or {}
    _require(causal.get("status") == "pass", "causal_execution_not_passed")
    runs = causal.get("executions") or []
    dates = {stamp.isoformat() for stamp in frame.timestamp.unique()}
    _require(
        len(runs) == len(dates) and {run.get("as_of") for run in runs} == dates,
        "causal_date_coverage_missing",
    )
    for run in runs:
        _isolation(run, source_sha=source_sha, runner_sha=runner_sha, adapter_sha=adapter_sha)
        _require(
            run.get("status") == "ok" and run.get("scope") == "physically_clipped_asof_input",
            "causal_execution_not_evaluated",
        )
        cutoff = pd.Timestamp(run["as_of"])
        visible = frame[(frame.timestamp <= cutoff) & (frame.available_at <= cutoff)]
        context = dict(inputs["context"])
        if "observations" in context:
            context["observations"] = [
                row
                for row in context["observations"]
                if pd.Timestamp(row["available_at"]) <= cutoff
            ]
        _require(
            run.get("input_digest")
            == digest({"ohlcv": exploration_sandbox.records(visible), "context": context}),
            "asof_execution_input_mismatch",
        )
    _require(
        receipt.get("scorecard_digest") == _file_sha(run_dir / "scorecard.json"),
        "scorecard_digest_mismatch",
    )
    _require(receipt.get("cost_reference", {}).get("status") != "fail", "known_cost_failure")
    _require(set(source_material) == _MATERIAL_KEYS, "source_material_schema_mismatch")
    _require(
        isinstance(ordered_symbols, list)
        and len(ordered_symbols) == len(set(ordered_symbols))
        and set(ordered_symbols) == set(frame.symbol),
        "ordered_universe_mismatch",
    )
    _require(
        isinstance(data_provenance, dict) and bool(data_provenance), "data_provenance_required"
    )
    binding = {
        "code_sha256": source_sha,
        "input_digest": review["input_digest"],
        "reference_digest": reference["contract_digest"],
        "review_digest": review["review_digest"],
        "run_receipt_digest": receipt["receipt_digest"],
        "scorecard_sha256": receipt["scorecard_digest"],
        "compiler_sha256": compiler_sha,
        "behavior_version": behavior_review.VERSION,
        "probe_sha256": review["probe_sha256"],
        "runner_sha256": runner_sha,
        "sandbox_adapter_sha256": adapter_sha,
        "data_provenance": data_provenance,
        "bridge_sha256": _file_sha(__file__),
    }
    raw_proposal = {
        **source_material,
        "schema_version": 1,
        "proposal_id": "local-explore-" + digest(binding)[:24],
        "expression": compiled.qlib,
        "baseline_factor_ids": [],
        "strategy_spec": {
            "symbols": ordered_symbols,
            "benchmark_symbol": "SPY",
            "rebalance": "daily",
            "top_n": 2,
            "normalization": "rank",
            "selection": "top",
            "max_weight_per_symbol": 1.0,
            "target_gross_exposure": 1.0,
            "min_order_value": 0.0,
            "factor_weights": {},
        },
    }
    # The existing strict parser, Pydantic schema and whitelist compiler are the
    # actual intake validation seam. submit(), _plans(), policies and queues are not called.
    proposal = Proposal.model_validate(strict_json(json.dumps(raw_proposal, allow_nan=False)))
    verified_compilation = qlib_expr.compile_qlib_expr(proposal.expression)
    _require(verified_compilation.qlib == compiled.qlib, "intake_compilation_mismatch")
    candidate = {
        "schema": SCHEMA,
        "status": "frozen_research_material",
        "binding": binding,
        "proposal": proposal.model_dump(mode="json"),
        "proposal_digest": digest(proposal.model_dump(mode="json")),
        "intake_schema_validation": {
            "status": "pass",
            "schema": "external_intake.Proposal",
            "schema_source_sha256": _file_sha(Path(__file__).with_name("external_intake.py")),
            "compiler": "compile_qlib_expr",
        },
        "admission_status": "not_evaluated",
        "queue_submitted": False,
        "capital_authorized": False,
        "formal_checks_required": [
            "full_historical_data_quality_and_PIT",
            "dual_engine_net_replay",
            "DSR_and_trial_family",
            "costs_and_correlation",
            "owner_policy",
        ],
        "scope": "format_validated_research_material_only",
    }
    candidate["candidate_digest"] = digest(candidate)
    return candidate
