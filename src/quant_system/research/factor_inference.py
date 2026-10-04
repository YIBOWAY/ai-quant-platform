"""Research-only multiplicity sidecars for an immutable 27 x 3 scorecard batch.

The archived ``ic.nw_t`` estimates the mean *Pearson* IC, not RankIC. This
module preserves that estimand, its signal-observation cadence and frozen
factor direction. It does not recompute factors, prices, portfolios or gates.
Holm is primary; BY is auxiliary. Their guarantees remain conditional on valid
individual p-values; the archived HAC normal approximation is asymptotic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PLAN_SCHEMA = "qs.factor_inference_plan/v1"
REPORT_SCHEMA = "qs.factor_inference/v1"
METHOD = {
    "version": "directional_pearson_hac_holm_by/v1",
    "estimand": "mean_of_daily_cross_sectional_pearson_ic_on_frozen_signal_observations",
    "null": "declared_direction_mean_pearson_ic_lte_zero",
    "alternative": "declared_direction_mean_pearson_ic_gt_zero",
    "raw_ic_orientation": "raw_factor_value_not_direction_adjusted",
    "direction_rule": "higher_is_better:+1;lower_is_better:-1;apply_once",
    "raw_p": "normal_survival(direction_sign * archived_pearson_ic_nw_t)",
    "p_value_validity": "asymptotic_HAC_normal_approximation_not_exact_finite_sample",
    "primary_adjustment": "holm",
    "familywise_alpha": 0.05,
    "secondary_adjustment": "benjamini_yekutieli",
    "secondary_fdr_q": 0.05,
    "method_selection": "fixed_primary_holm_secondary_by_no_pick_the_best",
    "missing_p_policy": (
        "retain_null_status;use_one_only_inside_full_81_adjustment;no_rejection_claim"
    ),
    "dependence_scope": "arbitrary_cross_hypothesis_dependence_if_individual_p_values_valid",
    "family_scope": "this_frozen_27_by_3_batch_only_not_all_historical_search",
    "horizons": [1, 5, 21],
    "factor_count": 27,
    "family_size": 81,
    "cluster": "not_evaluated_no_cluster_or_entity_influence_contract_in_archived_ic_daily",
    "historical_method_timing": (
        "retrospective_method_extension_not_original_preregistration_or_holdout"
    ),
    "funding_authority": False,
    "admission_authority": False,
}
REFERENCES = [
    "https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html",
    "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html",
    "https://sandwich.r-forge.r-project.org/reference/vcovCL.html",
]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _family(config: dict) -> list[dict]:
    objects = config["objects"]
    _require(
        len(objects) == len({o["factor_id"] for o in objects}) == 27
        and config["horizons"] == [1, 5, 21],
        "factor_inference_family_must_be_27_by_3",
    )
    result = []
    for item in objects:
        _require(
            item.get("direction") in {"higher_is_better", "lower_is_better"}
            and item.get("frequency") in {"daily", "month_end"},
            "factor_inference_direction_or_frequency_missing",
        )
        for horizon in config["horizons"]:
            result.append(
                {
                    "hypothesis_id": f"{item['factor_id']}:h{horizon}",
                    "factor_id": item["factor_id"],
                    "horizon": horizon,
                    "direction": item["direction"],
                    "frequency": item["frequency"],
                    "object_digest": digest(item),
                    "duplicate_group": item.get("duplicate_group"),
                }
            )
    return result


def freeze_plan(run_dir: Path, *, expected_output_manifest_sha256: str) -> dict:
    """Freeze all hypotheses and methods before deriving any new p-value."""
    from quant_system.factors.scorecard_service import _wide_payload

    run_dir = Path(run_dir).resolve()
    card = _wide_payload(run_dir, expected_output_manifest_sha256)
    config = json.loads((run_dir / "run-config.json").read_text())
    value = {
        "schema": PLAN_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "source_run_id": "wide-" + expected_output_manifest_sha256[:20],
        "source_run_dir": str(run_dir),
        "source_output_manifest_sha256": expected_output_manifest_sha256,
        "source_files": json.loads((run_dir / "output-digests.json").read_text()),
        "source_factor_manifest_digest": config["digest"],
        "source_provenance_digest": digest(card["provenance"]),
        "signal_window": config["signal_window"],
        "membership_mode": config["membership_mode"],
        "eligibility": config["eligibility"],
        "duplicate_policy": config["duplicate_policy"],
        "family": _family(config),
        "method": json.loads(json.dumps(METHOD)),
        "references": REFERENCES,
    }
    value["plan_digest"] = digest(value)
    return value


def adjust_pvalues(pvalues: list[float | None], *, method: str) -> list[float | None]:
    """Keep unknown cells in the full family, without manufacturing their p-values."""
    _require(bool(pvalues) and method in {"holm", "by"}, "factor_inference_adjustment_invalid")
    _require(
        all(
            p is None or (type(p) in {float, int} and math.isfinite(p) and 0 <= p <= 1)
            for p in pvalues
        ),
        "factor_inference_pvalue_invalid",
    )
    values = [1.0 if p is None else float(p) for p in pvalues]
    count = len(values)
    order = sorted(range(count), key=lambda i: (values[i], i))
    adjusted = [1.0] * count
    if method == "holm":
        cumulative = 0.0
        for rank, index in enumerate(order):
            cumulative = max(cumulative, (count - rank) * values[index])
            adjusted[index] = min(1.0, cumulative)
    else:
        harmonic = math.fsum(1 / rank for rank in range(1, count + 1))
        cumulative = 1.0
        for rank in range(count - 1, -1, -1):
            index = order[rank]
            cumulative = min(cumulative, values[index] * count * harmonic / (rank + 1))
            adjusted[index] = cumulative
    return [None if p is None else adjusted[i] for i, p in enumerate(pvalues)]


def _finite(value: Any) -> bool:
    return type(value) in {float, int} and math.isfinite(value)


def _cell(hypothesis: dict, factor: dict, sample: pd.DataFrame) -> dict:
    _require(
        factor.get("direction") == hypothesis["direction"]
        and factor.get("direction_defaulted") is not True
        and set(factor["horizons"]) == {"1", "5", "21"},
        "factor_inference_factor_contract_changed",
    )
    block = factor["horizons"][str(hypothesis["horizon"])]
    ic = block.get("ic") or {}
    inference = block.get("inference") or {}
    statistic, mean = ic.get("nw_t"), ic.get("ic_mean")
    n_obs = int(np.isfinite(sample.ic.to_numpy(dtype=float)).sum()) if len(sample) else 0
    if ic:
        _require(ic.get("n_days") == n_obs, "factor_inference_ic_sample_count_changed")
    if n_obs and _finite(mean):
        _require(
            math.isclose(float(sample.ic.mean()), mean, rel_tol=1e-12, abs_tol=1e-12),
            "factor_inference_ic_mean_changed",
        )
    sign = 1 if hypothesis["direction"] == "higher_is_better" else -1
    available = ic.get("status") == "ready" and _finite(statistic) and _finite(mean)
    reason = (
        None if available else ic.get("reason") or block.get("reason") or "pearson_hac_unavailable"
    )
    if available:
        lag, overlap = ic.get("nw_lag"), inference.get("overlap_lags")
        _require(
            type(lag) is int
            and type(overlap) is int
            and 0 <= overlap <= lag < n_obs
            and n_obs >= max(60, 3 * (lag + 1))
            and inference.get("lag_unit") == "signal_observations"
            and inference.get("horizon_unit") == "trading_sessions",
            "factor_inference_hac_contract_invalid",
        )
        _require(
            (hypothesis["frequency"] != "daily" or overlap == hypothesis["horizon"] - 1)
            and inference.get("signal_frequency") == hypothesis["frequency"],
            "factor_inference_cadence_changed",
        )
        _require(statistic * mean >= 0, "factor_inference_statistic_direction_changed")
    return {
        **hypothesis,
        "status": "evaluated" if available else "not_evaluated",
        "reason": reason,
        "n_observations": n_obs,
        "nw_lag": ic.get("nw_lag"),
        "overlap_lags": inference.get("overlap_lags"),
        "raw_pearson_ic_mean": mean if _finite(mean) else None,
        "directed_pearson_ic_mean": sign * mean if _finite(mean) else None,
        "raw_pearson_ic_hac_t": statistic if available else None,
        "directed_hac_statistic": sign * statistic if available else None,
        "raw_p": 0.5 * math.erfc(sign * statistic / math.sqrt(2)) if available else None,
        "sample_start": sample.signal_ts.min().isoformat() if len(sample) else None,
        "sample_end": sample.signal_ts.max().isoformat() if len(sample) else None,
        "direction_applied_once": True,
    }


def _cluster_status() -> dict:
    return {
        "status": "not_evaluated",
        "standard_error": None,
        "reason": "archived_session_ic_has_no_entity_contributions_or_frozen_cluster_contract",
        "existing_hac_is_cluster_robust": False,
        "required_observation_fields": [
            "factor_id",
            "horizon",
            "entity_id",
            "signal_ts",
            "entry_ts",
            "return_end_ts",
            "factor_value",
            "forward_return",
            "eligibility_mask",
        ],
        "required_design": [
            "preserve_mean_of_sessionwise_correlations_not_pooled_regression_estimand",
            "bind_original_entity_mapping_and_same_issuer_share_classes",
            "freeze_cluster_dimensions_and_enough_clusters_before_viewing_inference",
            "justify_between_cluster_independence_and_cross_boundary_horizon_overlap",
            "declare_finite_sample_correction_and_unavailable_conditions",
        ],
        "available_input_scope": (
            "prices_membership_identity_preserved_but_influence_panel_not_delivered"
        ),
        "rejected_substitutions": [
            "rename_existing_hac_as_cluster",
            "one_scalar_per_date_cluster_degenerates_to_basic_sandwich",
            "calendar_month_clusters_without_cross_cluster_dependence_justification",
        ],
    }


def derive_inference(plan: dict, *, run_dir: Path | None = None) -> dict:
    """Only new statistical transformations of saved metrics; never a factor rerun."""
    from quant_system.factors.scorecard_service import _wide_payload

    _require(
        plan.get("schema") == PLAN_SCHEMA
        and plan.get("plan_digest") == digest({k: v for k, v in plan.items() if k != "plan_digest"})
        and plan.get("method") == METHOD,
        "factor_inference_plan_changed",
    )
    run_dir = Path(run_dir or plan["source_run_dir"]).resolve()
    card = _wide_payload(run_dir, plan["source_output_manifest_sha256"])
    config = json.loads((run_dir / "run-config.json").read_text())
    _require(
        _family(config) == plan["family"]
        and config["digest"] == plan["source_factor_manifest_digest"]
        and config["signal_window"] == plan["signal_window"]
        and digest(card["provenance"]) == plan["source_provenance_digest"]
        and json.loads((run_dir / "output-digests.json").read_text()) == plan["source_files"],
        "factor_inference_source_identity_changed",
    )
    daily = pd.read_parquet(run_dir / "ic_daily.parquet")
    _require(
        {"factor_id", "horizon", "signal_ts", "ic", "price_basis"}.issubset(daily.columns),
        "factor_inference_ic_columns_missing",
    )
    daily = daily.copy()
    daily["signal_ts"] = pd.to_datetime(daily.signal_ts, utc=True, errors="raise")
    allowed = {(r["factor_id"], r["horizon"]) for r in plan["family"]}
    _require(
        not daily.duplicated(["factor_id", "horizon", "signal_ts"]).any()
        and set(zip(daily.factor_id, daily.horizon, strict=True)).issubset(allowed)
        and daily.price_basis.eq("open_to_open").all()
        and daily.signal_ts.between(
            pd.Timestamp(plan["signal_window"][0], tz="UTC"),
            pd.Timestamp(plan["signal_window"][1], tz="UTC"),
        ).all(),
        "factor_inference_ic_population_changed",
    )
    factors = {f["factor_id"]: f for f in card["factors"]}
    groups = {key: g.sort_values("signal_ts") for key, g in daily.groupby(["factor_id", "horizon"])}
    rows = [
        _cell(
            item,
            factors[item["factor_id"]],
            groups.get(
                (item["factor_id"], item["horizon"]),
                daily.iloc[:0],
            ),
        )
        for item in plan["family"]
    ]
    raw = [r["raw_p"] for r in rows]
    holm, by = (adjust_pvalues(raw, method=method) for method in ("holm", "by"))
    for row, first, second in zip(rows, holm, by, strict=True):
        row.update(
            holm_adjusted_p=first,
            by_adjusted_p=second,
            reject_primary=None if first is None else first <= METHOD["familywise_alpha"],
            reject_secondary=None if second is None else second <= METHOD["secondary_fdr_q"],
        )
    _require(
        all(file_sha(run_dir / name) == sha for name, sha in plan["source_files"].items()),
        "factor_inference_source_changed_during_read",
    )
    result = {
        "schema": REPORT_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "partial",
        "scope": "research_only_retrospective_inference_sidecar",
        "plan_digest": plan["plan_digest"],
        "method": METHOD,
        "family": plan["family"],
        "source": {
            k: plan[k]
            for k in (
                "source_run_id",
                "source_output_manifest_sha256",
                "source_files",
                "source_factor_manifest_digest",
                "source_provenance_digest",
                "signal_window",
            )
        },
        "implementation": {"module": "research/factor_inference.py", "sha256": file_sha(__file__)},
        "hypotheses": rows,
        "summary": {
            "family_size": len(rows),
            "evaluated": sum(r["status"] == "evaluated" for r in rows),
            "not_evaluated": sum(r["status"] == "not_evaluated" for r in rows),
            "primary_rejections": sum(r["reject_primary"] is True for r in rows),
            "secondary_rejections": sum(r["reject_secondary"] is True for r in rows),
            "missing_cells_retained_in_family": True,
        },
        "cluster_robust": _cluster_status(),
        "rank_ic_inference": {
            "status": "not_evaluated",
            "reason": "primary_endpoint_is_pearson_ic",
        },
        "industry_neutral": {"status": "not_evaluated", "reason": "outside_frozen_sidecar_scope"},
        "admission_authority": False,
        "funding_authority": False,
        "limitations": [
            "p_values_are_asymptotic_hac_approximations_not_finite_sample_certificates",
            "multiplicity_scope_excludes_undocumented_historical_search_and_parameter_trials",
            "retrospective_extension_not_new_out_of_sample_or_original_preregistration",
            "significant_pearson_prediction_does_not_prove_portfolio_alpha_or_paper_eligibility",
        ],
        "references": REFERENCES,
    }
    result["report_digest"] = digest(result)
    return result


def read_inference_sidecar(
    path: Path, *, expected_sha256: str, expected_source_output_sha256: str
) -> dict:
    """Require an externally pinned receipt hash, not a self-reported pass flag."""
    _require(file_sha(path) == expected_sha256, "factor_inference_receipt_changed")
    value = json.loads(Path(path).read_text())
    _require(
        value.get("schema") == REPORT_SCHEMA
        and value.get("method") == METHOD
        and value.get("report_digest")
        == digest({k: v for k, v in value.items() if k != "report_digest"})
        and value.get("source", {}).get("source_output_manifest_sha256")
        == expected_source_output_sha256
        and value.get("admission_authority") is False
        and value.get("funding_authority") is False
        and len(value.get("family", [])) == len(value.get("hypotheses", [])) == 81,
        "factor_inference_receipt_identity_invalid",
    )
    return value


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    _require(
        not args.out.resolve().is_relative_to(Path(plan["source_run_dir"]).resolve()),
        "factor_inference_output_must_be_outside_frozen_run",
    )
    report = derive_inference(plan)
    report["plan_file_sha256"] = file_sha(args.plan)
    report["report_digest"] = digest({k: v for k, v in report.items() if k != "report_digest"})
    _write_new(args.out, report)
    print(json.dumps({"output": str(args.out), "sha256": file_sha(args.out), **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
