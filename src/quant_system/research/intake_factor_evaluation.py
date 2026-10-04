"""Bind the existing factor scorecard to an intake's frozen paired evaluation.

This diagnostic adapter has no provider, queue, candidate or account writes. The
worker calls it before portfolio validation; GET projections only read receipts.
Factor statistics remain research evidence, never portfolio profit or authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_system.factors.evaluation import summarize_ic_series
from quant_system.factors.scorecard import build_factor_scorecard_bundle, current_source_digest
from quant_system.research.intake_evaluation import (
    compare_increment,
    digest,
    file_hash,
    validate_snapshot,
)

SCHEMA = "intake_factor_evaluation/v1"
# Wire fields of the existing HQA card, not a second hypothesis model. Platform
# must independently validate incoming JSON and cannot import the HQA package.
CARD_FIELDS = (
    "mechanism",
    "who_loses",
    "falsifiable_prediction",
    "required_fields",
    "test_protocol",
    "prior_evidence",
    "expressibility",
    "data_need_ids",
    "adaptation_diff",
)


def validate_hypothesis_card(value):
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value)
        != set(CARD_FIELDS)
        | {
            "schema_version",
            "hypothesis_digest",
        }
        or value.get("schema_version") != "hqa.hypothesis_card/v2"
    ):
        raise ValueError("intake_hypothesis_card_contract_invalid")
    normalized = {}
    for key in CARD_FIELDS:
        item = value[key]
        if key in {"required_fields", "data_need_ids"}:
            if (
                not isinstance(item, list)
                or (not item and key == "required_fields")
                or any(not isinstance(x, str) or not x.strip() for x in item)
                or len(set(item)) != len(item)
            ):
                raise ValueError("intake_hypothesis_card_fields_invalid")
            normalized[key] = list(item)
        else:
            if not isinstance(item, str) or not item.strip() or len(item) > 16000:
                raise ValueError("intake_hypothesis_card_fields_invalid")
            normalized[key] = item.strip()
    expected = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if value["hypothesis_digest"] != expected:
        raise ValueError("intake_hypothesis_card_digest_changed")
    return {"schema_version": "hqa.hypothesis_card/v2", **normalized, "hypothesis_digest": expected}


def _unsupported_fields(card):
    from quant_system.d34.qlib_expr import FIELDS

    return [name for name in card["required_fields"] if name.removeprefix("$") not in FIELDS]


def freeze_research_design(proposal, plans, *, before_evaluation=True):
    """Describe the actual frozen local test; do not infer a paper's missing method."""
    if not plans:
        card = validate_hypothesis_card(proposal.hypothesis_card)
        value = {
            "schema": "intake_research_design/v1",
            "frozen_before_evaluation": True,
            "materials_status": "waiting_data",
            "research_object": "unimplemented_source_method",
            "source_method_status": "hypothesis_card_received_not_independently_verified",
            "source_title": proposal.source_title,
            "hypothesis": proposal.hypothesis,
            "adaptation_note": proposal.adaptation_note,
            "source_urls": list(proposal.source_urls),
            "hypothesis_card": card,
            "local_factor": None,
            "portfolio": None,
            "inherited_defaults": [],
            "inherited_factor_weights": {},
            "data_needs": [
                {
                    "reason": "hypothesis_fields_outside_local_ohlcv_contract",
                    "fields": _unsupported_fields(card),
                    "data_need_ids": card["data_need_ids"],
                    "next_step": "provide_declared_fields_and_pit_contract_before_testing",
                }
            ],
        }
        value["design_digest"] = digest(value)
        return value
    primary = next(p for p in plans if p["activation_eligible"])
    payload = primary["payload"]
    spec = proposal.strategy_spec
    supplied = spec.model_fields_set if spec else set()
    weights = spec.factor_weights if spec else {}
    card = validate_hypothesis_card(proposal.hypothesis_card)
    fields = (
        "symbols",
        "benchmark_symbol",
        "rebalance",
        "top_n",
        "normalization",
        "selection",
        "max_weight_per_symbol",
        "target_gross_exposure",
        "min_order_value",
        "factor_weights",
    )
    value = {
        "schema": "intake_research_design/v1",
        "frozen_before_evaluation": before_evaluation,
        "source_method_status": "original_method_not_verified",
        "research_object": "local_ohlcv_factor_proxy",
        "source_urls": list(proposal.source_urls),
        "source_title": proposal.source_title,
        "hypothesis": proposal.hypothesis,
        "adaptation_note": proposal.adaptation_note,
        "hypothesis_card": card,
        "source_material_sha256": digest(
            {
                "title": proposal.source_title,
                "hypothesis": proposal.hypothesis,
                "adaptation_note": proposal.adaptation_note,
            }
        ),
        "local_factor": {
            "expression": proposal.expression,
            "direction": "higher_is_better",
            "required_fields": sorted(set(re.findall(r"\$([a-z]+)", proposal.expression))),
        },
        "portfolio": {
            **{k: payload[k] for k in fields if k != "factor_weights"},
            "factor_weights": {f["factor_id"]: f["weight"] for f in payload["factors"]},
            "commission_bps": payload["commission_bps"],
            "slippage_bps": payload["slippage_bps"],
            "start": primary["origin"]["start"],
            "end": primary["origin"]["end"],
        },
        "inherited_defaults": [
            k
            for k in fields
            if k not in supplied
            or getattr(spec, k, None) is None
            or (k == "factor_weights" and not weights)
        ],
        "inherited_factor_weights": {
            f["factor_id"]: f["weight"] for f in payload["factors"] if f["factor_id"] not in weights
        },
        "factor_horizons": [1, 5, 21],
        "stability_partition": "calendar_years_descriptive_not_unseen_holdout",
        "limitations": [
            "source_method_and_hypothesis_card_not_independently_verified",
            "default_protocol_is_local_comparison_not_paper_reproduction",
            "fixed_universe_not_point_in_time_membership",
            "factor_statistics_are_not_portfolio_returns_or_admission",
            "factor_multiplicity_and_industry_neutral_not_evaluated",
        ],
        "data_needs": [
            {
                "reason": "original_method_contract_not_supplied",
                "fields": [
                    "original_method",
                    "required_fields",
                    "adaptation_diff",
                    "test_protocol",
                ],
                "next_step": "attach_existing_hypothesis_card_and_source_data_requirements",
            }
        ],
    }
    if card:
        unavailable = _unsupported_fields(card)
        value["research_object"] = "local_ohlcv_implementation_original_method_unverified"
        value["source_method_status"] = "hypothesis_card_received_not_independently_verified"
        value["data_needs"] = (
            [
                {
                    "reason": "hypothesis_fields_outside_local_ohlcv_contract",
                    "fields": unavailable,
                    "data_need_ids": card["data_need_ids"],
                    "next_step": "provide_declared_fields_and_pit_contract_before_testing",
                }
            ]
            if unavailable
            else []
        )
        value["materials_status"] = "waiting_data" if unavailable else "ready_for_local_test"
    else:
        value["materials_status"] = "legacy_v1_local_formula_only_original_method_unknown"
    if any(p["origin"].get("replacement_target") for p in plans):
        value["inherited_defaults"] = []
        value["inherited_factor_weights"] = {}
        value["portfolio_source"] = "frozen_replacement_target"
    else:
        value["portfolio_source"] = "explicit_strategy_spec_with_listed_defaults"
    value["design_digest"] = digest(value)
    return value


def _identity(job):
    evaluation = job.get("evaluation") or {}
    return {
        "job_id": job.get("job_id"),
        "proposal_sha256": job.get("payload_sha256"),
        "plans_sha256": job.get("plans_sha256"),
        "evaluation_id": evaluation.get("evaluation_id"),
        "prices_sha256": evaluation.get("prices_sha256"),
        "definition_digests": {p["variant"]: p["definition_digest"] for p in job.get("plans", [])},
        "design_digest": (job.get("research_design") or {}).get("design_digest"),
    }


def _write_json(path, value):
    from quant_system.research.external_intake import _write

    _write(path, value)


def validate_research_design(job):
    design = job.get("research_design")
    if design and design.get("design_digest") != digest(
        {k: v for k, v in design.items() if k != "design_digest"}
    ):
        raise ValueError("intake_research_design_changed")


def _read_receipt(settings, job):
    validate_research_design(job)
    validate_snapshot(settings, job["evaluation"])
    ref = job["factor_evaluation"]
    allowed = (settings.data.data_dir / "research_intake" / "evaluations").resolve()
    path = Path(ref["path"])
    if not path.is_absolute() or not path.resolve().is_relative_to(allowed):
        raise ValueError("intake_factor_evaluation_path_invalid")
    if file_hash(path) != ref["sha256"]:
        raise ValueError("intake_factor_evaluation_receipt_changed")
    receipt = json.loads(path.read_text())
    if receipt["identity"] != _identity(job):
        raise ValueError("intake_factor_evaluation_identity_changed")
    if (
        receipt.get("schema") != SCHEMA
        or receipt.get("scope") != "research_only"
        or receipt.get("admission_authority") is not False
    ):
        raise ValueError("intake_factor_evaluation_contract_invalid")
    summary = receipt.get("summary") or {}
    if summary.get("status") not in {"ready", "partial", "unavailable", "not_evaluated"}:
        raise ValueError("intake_factor_evaluation_status_invalid")
    if summary.get("status") == "not_evaluated" and summary.get("horizons"):
        raise ValueError("intake_factor_evaluation_unmeasured_metrics")
    if summary.get("factor_id") != job["formula_factor_id"]:
        raise ValueError("intake_factor_evaluation_identity_changed")
    if summary.get("status") in {"ready", "partial", "unavailable"}:
        required = {
            "scorecard.json",
            "factor_values.parquet",
            "ic_daily.parquet",
            "quantile_daily.parquet",
            "long_short_daily.parquet",
            "correlation_daily.parquet",
            "audit.parquet",
        }
        if set(receipt.get("artifacts", {})) != required:
            raise ValueError("intake_factor_evaluation_artifacts_incomplete")
    for name, expected in receipt.get("artifacts", {}).items():
        if Path(name).name != name or file_hash(path.parent / name) != expected:
            raise ValueError("intake_factor_evaluation_artifact_changed")
    if summary.get("status") in {"ready", "partial", "unavailable"}:
        card = json.loads((path.parent / "scorecard.json").read_text())
        factors = card.get("factors") or []
        if (
            len(factors) != 1
            or factors[0].get("factor_id") != job["formula_factor_id"]
            or summary.get("horizons") != factors[0].get("horizons")
            or summary.get("direction") != factors[0].get("direction")
            or summary.get("status") != card.get("status")
            or {k: v for k, v in (summary.get("redundancy") or {}).items() if k != "scope"}
            != factors[0].get("correlation")
        ):
            raise ValueError("intake_factor_evaluation_summary_changed")
    return receipt


def _factor_frames(prices, definition, factor_id, start, end):
    # Reuse the exact strategy calendar and whitelist evaluator. In particular,
    # missing sessions do not compress a rolling window or become filled prices.
    from quant_system.d34.qlib_expr import compile_qlib_expr
    from quant_system.research.profile_backtests import _date, _formula_scores
    from quant_system.research.strategy_runtime import _prepare_context

    context = _prepare_context(prices, definition, _date(end))
    component = next(f for f in definition.factors if f.factor_id == factor_id)
    values = _formula_scores(
        context["frame"],
        context["sessions"],
        {"peer_symbols": list(definition.symbols), "eligibility_window": component.lookback},
        compile_qlib_expr(component.expression),
    )
    values = values.loc[values.index >= _date(start)]
    factor = values.rename_axis(index="signal_ts", columns="symbol").stack(future_stack=True)
    factor = factor.rename("value").reset_index().assign(factor_id=factor_id)
    # Spearman redundancy uses the exact normalized/weighted baseline components
    # on the complete common intersection. It is not the return-correlation gate.
    peers = context["components"].drop(columns=[factor_id], errors="ignore")
    peers = peers.loc[peers.index.get_level_values("timestamp") >= _date(start)]
    peers = peers.rename_axis(columns="factor_id").stack(future_stack=True)
    peers = peers.rename("value").reset_index().rename(columns={"timestamp": "signal_ts"})
    return factor, peers, context["frame"], component


def ensure_factor_evaluation(settings, job):
    """Write one immutable diagnostic for this input; resume only matching bytes."""
    prices_path = validate_snapshot(settings, job["evaluation"])
    source_digest = digest(
        {
            "scorecard": current_source_digest(),
            "adapter": file_hash(__file__),
        }
    )
    if job.get("factor_evaluation"):
        receipt = _read_receipt(settings, job)
        if receipt["source_digest"] != source_digest:
            raise ValueError("intake_factor_evaluation_source_changed")
        return job["factor_evaluation"]
    validate_research_design(job)
    directory = prices_path.parent / "factor-evaluation"
    directory.mkdir(mode=0o700, exist_ok=True)
    receipt_path = directory / "receipt.json"
    identity = _identity(job)
    receipt = {
        "schema": SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "source_digest": source_digest,
        "scope": "research_only",
        "admission_authority": False,
        "artifacts": {},
    }
    if receipt_path.exists():
        ref = {"path": str(receipt_path), "sha256": file_hash(receipt_path)}
        restored = _read_receipt(settings, {**job, "factor_evaluation": ref})
        if restored["source_digest"] != source_digest:
            raise ValueError("intake_factor_evaluation_source_changed")
        ref["summary"] = restored["summary"]
        return ref
    try:
        from quant_system.research.strategy_definition import (
            StrategyDefinition,
            validate_definition,
        )

        primary = next(p for p in job["plans"] if p["activation_eligible"])
        definition = validate_definition(
            StrategyDefinition(
                history_start=primary.get("history_start", "2015-01-01"),
                **primary["payload"],
            )
        )
        if definition.content_digest != primary["definition_digest"]:
            raise ValueError("intake_factor_definition_mismatch")
        factor, peers, frame, component = _factor_frames(
            pd.read_parquet(prices_path),
            definition,
            job["formula_factor_id"],
            job["evaluation"]["start"],
            job["evaluation"]["end"],
        )
        card, artifacts = build_factor_scorecard_bundle(
            factor_results=factor,
            ohlcv=frame,
            factor_metadata=[{"factor_id": component.factor_id, "direction": component.direction}],
            benchmark_symbol=definition.benchmark_symbol,
            library_factor_results=peers,
            horizons=(1, 5, 21),
        )
        entry = card["factors"][0]
        daily = artifacts["ic_daily"]
        years = []
        for (horizon, year), group in daily.groupby(
            [
                "horizon",
                pd.to_datetime(daily.signal_ts, utc=True).dt.year,
            ]
        ):
            years.append(
                {
                    "horizon": int(horizon),
                    "year": int(year),
                    **summarize_ic_series(group, horizon=int(horizon)),
                }
            )
        _write_json(directory / "scorecard.json", card)
        receipt["artifacts"]["scorecard.json"] = file_hash(directory / "scorecard.json")
        for name, data in {**artifacts, "factor_values": factor}.items():
            path = directory / (name + ".parquet")
            data.to_parquet(path, index=False)
            path.chmod(0o600)
            receipt["artifacts"][path.name] = file_hash(path)
        observed_years = {y["year"] for y in years if y["n_days"] > 0}
        summary = {
            "status": card["status"],
            "reason": None,
            "factor_id": component.factor_id,
            "lookback": component.lookback,
            "direction": component.direction,
            "horizons": entry["horizons"],
            "redundancy": {**entry["correlation"], "scope": "declared_baseline_components_only"},
            "stability": {
                "status": "ready" if len(observed_years) >= 2 else "not_evaluated",
                "reason": None if len(observed_years) >= 2 else "multiple_years_with_ic_required",
                "partition": "calendar_years_descriptive_not_unseen_holdout",
                "by_year": years,
            },
            "performance_scope": "factor_prediction_and_group_labels_not_portfolio_profit",
            "next_step": "read_paired_portfolio_increment_and_existing_admission",
        }
    except (ValueError, KeyError, StopIteration) as exc:
        summary = {
            "status": "not_evaluated",
            "reason": str(exc).split(":", 1)[0] or type(exc).__name__,
            "factor_id": job["formula_factor_id"],
            "horizons": {},
            "stability": {"status": "not_evaluated"},
            "redundancy": {"status": "not_evaluated"},
            "next_step": "resolve_exact_input_or_implementation_without_proxy_substitution",
        }
    receipt["summary"] = summary
    _write_json(receipt_path, receipt)
    return {"path": str(receipt_path), "sha256": file_hash(receipt_path), "summary": summary}


def _disposition(job, factor_summary, increment):
    design = job.get("research_design") or {}
    primary = next((r for r in job.get("results", []) if r.get("variant") != "baseline"), {})
    blockers = (primary.get("validation") or {}).get("blockers") or []
    if (
        design.get("materials_status") == "waiting_data"
        or factor_summary.get("status") == "not_evaluated"
    ):
        action, reason = "build_data", factor_summary.get("reason") or "declared_fields_unavailable"
    elif increment.get("status") == "failed":
        action, reason = "archive_hypothesis", increment["reason"]
    elif blockers:
        action, reason = "archive_hypothesis", "existing_admission_rejected_fixed_local_combination"
    else:
        action, reason = "continue_research", "review_existing_evidence_before_any_new_protocol"
    return {
        "action": action,
        "reason": reason,
        "scope": "this_frozen_local_factor_and_portfolio_hypothesis_only",
        "basis": {"increment_status": increment.get("status"), "admission_blockers": blockers},
        "direction_conclusion": "not_evaluated_without_family_convergence_and_budget_evidence",
        "original_paper_conclusion": "not_evaluated",
        "resubmission_authorized": False,
        "next_step": "retain_failure_and_fixed_direction_window_no_renaming_or_reversal_retry",
    }


def evaluation_chain(job, *, include_material=False):
    """A pure projection: missing historic factor work never becomes a pass."""
    ref = job.get("factor_evaluation") or {}
    variants = []
    for result in job.get("results", []):
        validation = result.get("validation") or {}
        variants.append(
            {
                "variant": result.get("variant"),
                "definition_digest": result.get("definition_digest"),
                "status": result.get("status"),
                "validation_run_id": validation.get("run_id"),
                "validation_sha256": result.get("validation_sha256"),
                "blockers": validation.get("blockers", []),
                "admission_v2": result.get("admission_v2"),
                "reason": result.get("evidence_error"),
            }
        )
    design = job.get("research_design")
    if design and not include_material:
        design = {
            k: v
            for k, v in design.items()
            if k
            not in {
                "source_title",
                "hypothesis",
                "adaptation_note",
                "hypothesis_card",
            }
        }
    factor_summary = ref.get("summary") or {
        "status": "not_evaluated",
        "reason": "factor_scorecard_not_recorded_for_this_input",
        "next_step": "evaluate_same_frozen_input_without_rewriting_historical_admission",
    }
    increment = compare_increment(
        {
            **job,
            "results": [r for r in job.get("results", []) if r.get("variant")],
        }
    )
    return {
        "schema": "intake_evaluation_chain/v1",
        "identity": _identity(job),
        "research_design": design,
        "factor_evaluation": factor_summary,
        "factor_receipt_sha256": ref.get("sha256"),
        "portfolio_increment": increment,
        "disposition": _disposition(job, factor_summary, increment),
        "admission": {
            "mode": (job.get("admission_protocol") or {}).get("mode"),
            "variants": variants,
            "factor_scorecard_grants_authority": False,
        },
    }


def verified_evaluation_chain(settings, job, *, include_material=False):
    """One read path for the local page, CLI and cloud reconciliation."""
    from quant_system.research.evaluation_service import _view
    from quant_system.research.strategy_library_cli import _validation
    from quant_system.research.validation_receipts import verify_validation_receipt

    verified_results, issues = [], []
    for stored in job.get("results", []):
        result = dict(stored)
        cached = result.get("validation") or {}
        if cached:
            try:
                strategy_id, run_id = result.get("strategy_id", ""), cached.get("run_id", "")
                if not re.fullmatch(r"strategy-[0-9a-f]{24}", strategy_id) or not re.fullmatch(
                    r"validation-[0-9a-f]{32}", run_id
                ):
                    raise ValueError("intake_validation_path_invalid")
                directory = settings.data.data_dir / "strategy_library" / strategy_id
                path = directory / "validations" / run_id / "validation.json"
                raw = verify_validation_receipt(
                    path,
                    expected_sha=result.get("validation_sha256"),
                    definition_digest=result.get("definition_digest"),
                    require_admission=False,
                )
                if (
                    _validation(_view(raw)) != cached
                    or not job.get("evaluation")
                    or raw.get("evaluation") != job["evaluation"]
                    or result.get("evaluation") != job["evaluation"]
                    or raw.get("receipts", {}).get("files", {}).get("prices.parquet")
                    != job["evaluation"]["prices_sha256"]
                ):
                    raise ValueError("intake_validation_cache_or_input_changed")
                validate_snapshot(settings, job["evaluation"])
                if result.get("admission_v2"):
                    from quant_system.research.admission_v2 import read_bound_receipt

                    read_bound_receipt(
                        settings,
                        result["admission_v2"],
                        definition_digest=result["definition_digest"],
                        validation_sha256=result["validation_sha256"],
                        source_sha256=file_hash(directory / "definition.json"),
                    )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                reason = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "intake_validation_artifact_missing"
                )
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason):
                    reason = "intake_validation_receipt_unverifiable"
                result.update(
                    validation=None,
                    status="not_evaluated",
                    evidence_error=reason,
                    admission_v2={"status": "not_evaluated", "reasons": [reason]},
                )
                issues.append({"variant": result.get("variant"), "reason": reason})
        verified_results.append(result)
    verified_job = {**job, "results": verified_results}
    value = evaluation_chain(verified_job, include_material=include_material)
    if issues:
        value["evidence_issues"] = issues
    if job.get("factor_evaluation"):
        try:
            receipt = _read_receipt(settings, job)
            value["factor_evaluation"] = receipt["summary"]
        except (OSError, ValueError, KeyError, TypeError):
            value["factor_evaluation"] = {
                "status": "not_evaluated",
                "reason": "factor_receipt_integrity_failed",
                "next_step": "restore_exact_archived_receipt_before_using_metrics",
            }
        value["disposition"] = _disposition(
            verified_job,
            value["factor_evaluation"],
            value["portfolio_increment"],
        )
    return value


def research_evidence_for_strategy(settings, strategy_id):
    """Read the latest matching intake; no refresh or source/account mutation."""
    from quant_system.research.external_intake import _load_job, root

    matches, invalid = [], []
    for path in (root(settings) / "jobs").glob("*.json"):
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict) or not any(
                isinstance(p, dict) and p.get("strategy_id") == strategy_id
                for p in raw.get("plans", [])
            ):
                continue
        except (OSError, ValueError, TypeError):
            continue
        try:
            job = _load_job(settings, path.stem)
            plans = [p for p in job["plans"] if p["strategy_id"] == strategy_id]
            matches.append((job, plans[0]))
        except (OSError, ValueError, KeyError, TypeError):
            invalid.append(path.stem)
    if not matches:
        return (
            None
            if not invalid
            else {
                "status": "not_evaluated",
                "reason": "intake_record_integrity_failed",
                "integrity_warnings": invalid,
            }
        )
    job, plan = max(matches, key=lambda item: (item[0]["created_at"], item[0]["job_id"]))
    value = verified_evaluation_chain(settings, job, include_material=True)
    if invalid:
        value["integrity_warnings"] = invalid
    return {
        **value,
        "job_id": job["job_id"],
        "variant": plan["variant"],
        "definition_digest": plan["definition_digest"],
    }
