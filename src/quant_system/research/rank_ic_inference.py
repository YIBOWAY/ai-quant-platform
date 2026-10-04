"""Separate, fixed secondary RankIC inference from saved wide-scorecard series.

This does not regenerate signals, labels, Pearson results, portfolios or cluster
standard errors. NaN positions stay on the archived signal-observation axis.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.factors.evaluation import newey_west_stats
from quant_system.research.factor_inference import _family, adjust_pvalues, digest, file_sha

PLAN_SCHEMA = "qs.rank_ic_inference_plan/v1"
REPORT_SCHEMA = "qs.rank_ic_inference/v1"
_ROOT = Path(__file__).resolve().parents[1]
METHOD = {
    "version": "secondary_directional_rank_ic_hac/v1",
    "endpoint_role": "secondary",
    "estimand": "mean_sessionwise_spearman_rank_ic_same_frozen_samples",
    "alternative": "declared_direction_mean_rank_ic_gt_zero",
    "direction_rule": "higher_is_better:+1;lower_is_better:-1;apply_once",
    "sequence_rule": "sort_original_signal_dates_preserve_every_nan_position_no_drop_or_fill",
    "hac_function": "quant_system.factors.evaluation.newey_west_stats",
    "lag_rule": "exact_archived_nw_lag_frozen_per_cell",
    "hac_horizon": "archived_overlap_lags_plus_one_in_signal_observation_units",
    "minimum_observations": "existing_default_max_60_3_times_lag_plus_one",
    "minimum_pairs": 30,
    "standard_error": "sqrt_positive_hac_lrv_over_finite_observations",
    "p_value": "normal_survival_direction_times_rank_hac_t_asymptotic",
    "holm_alpha": 0.05,
    "by_q": 0.05,
    "family_size": 81,
    "missing_p_policy": "null_in_results_one_only_inside_full_81_adjustment_no_rejection_claim",
    "pearson_endpoint_replaced": False,
    "choose_better_endpoint": False,
    "combined_162_family_error_control_claimed": False,
    "original_preregistration_claimed": False,
    "joint_cluster_se_claimed": False,
    "admission_authority": False,
    "funding_authority": False,
}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def rank_values(series):
    """Reject malformed data before the legacy HAC helper's permissive coercion."""
    _require(
        pd.api.types.is_numeric_dtype(series.dtype)
        and not pd.api.types.is_bool_dtype(series.dtype),
        "rank_ic_non_numeric_series",
    )
    values = series.to_numpy(dtype=float, na_value=np.nan)
    _require(not np.isinf(values).any(), "rank_ic_infinite_value")
    finite = values[np.isfinite(values)]
    _require((np.abs(finite) <= 1 + 1e-12).all(), "rank_ic_outside_correlation_range")
    return values


def _population(daily, family, window):
    _require(
        {"factor_id", "horizon", "signal_ts", "rank_ic", "price_basis"}.issubset(daily),
        "rank_ic_columns_missing",
    )
    daily = daily.copy()
    rank_values(daily.rank_ic)
    daily["signal_ts"] = pd.to_datetime(daily.signal_ts, utc=True, errors="raise")
    allowed = {(x["factor_id"], x["horizon"]) for x in family}
    _require(
        not daily.duplicated(["factor_id", "horizon", "signal_ts"]).any()
        and set(zip(daily.factor_id, daily.horizon, strict=True)).issubset(allowed)
        and daily.price_basis.eq("open_to_open").all()
        and daily.signal_ts.between(
            pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC")
        ).all(),
        "rank_ic_population_changed",
    )
    return daily


def _cell_identity(item, sample, factor):
    values = rank_values(sample.rank_ic)
    dates = [x.isoformat() for x in pd.to_datetime(sample.signal_ts, utc=True)]
    numbers = [None if np.isnan(x) else float(x) for x in values]
    _require(
        factor.get("direction") == item["direction"]
        and factor.get("direction_defaulted") is not True
        and set(factor["horizons"]) == {"1", "5", "21"},
        "rank_ic_factor_contract_changed",
    )
    block = factor["horizons"][str(item["horizon"])]
    stat, info = block["ic"], block["inference"]
    finite = values[np.isfinite(values)]
    mean = float(finite.mean()) if len(finite) else None
    archived = stat.get("rank_ic_mean")
    _require(
        (mean is None and archived is None)
        or (
            mean is not None
            and type(archived) in {int, float}
            and math.isfinite(archived)
            and math.isclose(mean, archived, abs_tol=1e-12, rel_tol=1e-12)
        ),
        "rank_ic_archived_mean_changed",
    )
    lag, overlap = stat.get("nw_lag"), info.get("overlap_lags")
    _require(
        type(lag) is int
        and type(overlap) is int
        and lag >= 0
        and overlap >= 0
        and info.get("lag_unit") == "signal_observations"
        and info.get("horizon_unit") == "trading_sessions"
        and info.get("signal_frequency") == item["frequency"]
        and (item["frequency"] != "daily" or overlap == item["horizon"] - 1),
        "rank_ic_original_lag_or_cadence_invalid",
    )
    return {
        **item,
        "sequence_rows": len(sample),
        "rank_observations": len(finite),
        "sequence_digest": digest({"signal_dates": dates, "rank_ic": numbers}),
        "missing_positions_digest": digest(np.isnan(values).tolist()),
        "archived_rank_ic_mean": archived,
        "nw_lag": lag,
        "overlap_lags": overlap,
        "lag_unit": info["lag_unit"],
        "horizon_unit": info["horizon_unit"],
    }


def _inputs(run_dir, expected_bundle_sha):
    from quant_system.factors.scorecard_service import _wide_payload

    run_dir = Path(run_dir).resolve()
    card = _wide_payload(run_dir, expected_bundle_sha)
    config = json.loads((run_dir / "run-config.json").read_text())
    family = _family(config)
    daily = _population(
        pd.read_parquet(run_dir / "ic_daily.parquet"), family, config["signal_window"]
    )
    groups = {k: g.sort_values("signal_ts") for k, g in daily.groupby(["factor_id", "horizon"])}
    factors = {x["factor_id"]: x for x in card["factors"]}
    cells = [
        _cell_identity(
            item,
            groups.get((item["factor_id"], item["horizon"]), daily.iloc[:0]),
            factors[item["factor_id"]],
        )
        for item in family
    ]
    return run_dir, config, daily, groups, cells


def freeze_rank_plan(
    run_dir,
    *,
    expected_bundle_sha,
    pearson_plan_path,
    pearson_report_path,
    expected_pearson_plan_sha,
    expected_pearson_report_sha,
):
    from quant_system.research.admission_v2 import code_identity

    run_dir, config, _, _, cells = _inputs(run_dir, expected_bundle_sha)
    _require(
        file_sha(pearson_plan_path) == expected_pearson_plan_sha
        and file_sha(pearson_report_path) == expected_pearson_report_sha,
        "rank_ic_pearson_reference_changed",
    )
    plan = {
        "schema": PLAN_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "source_run_dir": str(run_dir),
        "source_run_id": "wide-" + expected_bundle_sha[:20],
        "source_output_manifest_sha256": expected_bundle_sha,
        "source_files": json.loads((run_dir / "output-digests.json").read_text()),
        "factor_manifest_digest": config["digest"],
        "signal_window": config["signal_window"],
        "family": cells,
        "method": json.loads(json.dumps(METHOD)),
        "bound_code": {
            name: file_sha(_ROOT / name)
            for name in (
                "factors/evaluation.py",
                "research/factor_inference.py",
            )
        },
        "pearson_preserved": {
            "plan_path": str(Path(pearson_plan_path).resolve()),
            "plan_sha256": expected_pearson_plan_sha,
            "report_path": str(Path(pearson_report_path).resolve()),
            "report_sha256": expected_pearson_report_sha,
        },
        "owner_admission_code_digest": code_identity()["digest"],
        "scope": "secondary_rank_ic_only_no_new_factor_or_portfolio_experiment",
        "failure_policy": (
            "retain_all_81_statistical_failures_and_reasons;reject_changed_input_identity"
        ),
    }
    plan["plan_digest"] = digest(plan)
    return plan


def _verify_bound_sources(plan):
    from quant_system.research.admission_v2 import code_identity

    _require(
        set(plan["bound_code"]) == {"factors/evaluation.py", "research/factor_inference.py"},
        "rank_ic_statistical_code_binding_incomplete",
    )
    _require(
        all(file_sha(_ROOT / name) == expected for name, expected in plan["bound_code"].items()),
        "rank_ic_bound_statistical_code_changed",
    )
    original = plan["pearson_preserved"]
    _require(
        file_sha(original["plan_path"]) == original["plan_sha256"]
        and file_sha(original["report_path"]) == original["report_sha256"],
        "rank_ic_pearson_reference_changed",
    )
    _require(
        code_identity()["digest"] == plan["owner_admission_code_digest"],
        "rank_ic_owner_qualification_code_changed",
    )


def infer_cell(cell, sample):
    values = rank_values(sample.rank_ic)
    direction = 1 if cell["direction"] == "higher_is_better" else -1
    stats = newey_west_stats(values, lag=cell["nw_lag"], horizon=cell["overlap_lags"] + 1)
    # JSON object keys are strings. Normalize before sealing: numeric sorting of
    # lags 1..20 differs from string sorting after a persisted JSON round trip.
    stats["pair_counts"] = {str(key): count for key, count in stats["pair_counts"].items()}
    statistic = stats["t_stat"]
    available = statistic is not None
    mean = float(np.nanmean(values)) if np.isfinite(values).any() else None
    return {
        **cell,
        "status": "evaluated" if available else "not_evaluated",
        "reason": stats["reason"],
        "endpoint_role": "secondary",
        "raw_rank_ic_mean": mean,
        "directed_rank_ic_mean": None if mean is None else direction * mean,
        "hac_standard_error": math.sqrt(stats["lrv"] / stats["n_obs"]) if available else None,
        "raw_rank_ic_hac_t": statistic,
        "directed_rank_ic_hac_t": None if statistic is None else direction * statistic,
        "raw_p": None
        if statistic is None
        else 0.5 * math.erfc(direction * statistic / math.sqrt(2)),
        "hac": stats,
        "direction_applied_once": True,
        "hac_horizon_in_signal_observations": cell["overlap_lags"] + 1,
    }


def derive_rank_inference(plan):
    _require(
        plan.get("schema") == PLAN_SCHEMA
        and plan.get("method") == METHOD
        and plan.get("plan_digest")
        == digest({k: v for k, v in plan.items() if k != "plan_digest"}),
        "rank_ic_plan_changed",
    )
    implementation_sha = file_sha(__file__)
    _verify_bound_sources(plan)
    run, config, daily, groups, cells = _inputs(
        plan["source_run_dir"], plan["source_output_manifest_sha256"]
    )
    _require(
        cells == plan["family"]
        and len(cells) == 81
        and config["digest"] == plan["factor_manifest_digest"]
        and config["signal_window"] == plan["signal_window"]
        and json.loads((run / "output-digests.json").read_text()) == plan["source_files"],
        "rank_ic_frozen_cell_identity_changed",
    )
    rows = [
        infer_cell(cell, groups.get((cell["factor_id"], cell["horizon"]), daily.iloc[:0]))
        for cell in cells
    ]
    raw = [x["raw_p"] for x in rows]
    holm, by = (adjust_pvalues(raw, method=method) for method in ("holm", "by"))
    for row, first, second in zip(rows, holm, by, strict=True):
        row.update(
            holm_adjusted_p=first,
            by_adjusted_p=second,
            holm_reject_secondary_endpoint=None if first is None else first <= METHOD["holm_alpha"],
            by_reject_secondary_endpoint=None if second is None else second <= METHOD["by_q"],
        )
    _require(
        all(file_sha(run / name) == sha for name, sha in plan["source_files"].items())
        and file_sha(__file__) == implementation_sha,
        "rank_ic_sources_changed_during_read",
    )
    _verify_bound_sources(plan)
    failed = sum(x["status"] == "not_evaluated" for x in rows)
    result = {
        "schema": REPORT_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "partial" if failed else "completed",
        "endpoint_role": "secondary",
        "scope": plan["scope"],
        "plan_digest": plan["plan_digest"],
        "method": METHOD,
        "source": {
            k: plan[k]
            for k in (
                "source_run_id",
                "source_output_manifest_sha256",
                "source_files",
                "factor_manifest_digest",
                "signal_window",
                "bound_code",
                "owner_admission_code_digest",
            )
        },
        "pearson_preserved": plan["pearson_preserved"],
        "family": plan["family"],
        "hypotheses": rows,
        "implementation": {"module": "research/rank_ic_inference.py", "sha256": implementation_sha},
        "summary": {
            "family_size": 81,
            "evaluated": 81 - failed,
            "not_evaluated": failed,
            "holm_rejections": sum(x["holm_reject_secondary_endpoint"] is True for x in rows),
            "by_rejections": sum(x["by_reject_secondary_endpoint"] is True for x in rows),
            "missing_cells_retained_in_denominator": True,
        },
        "joint_cluster_se": {
            "status": "not_evaluated",
            "reason": "HAC_is_not_joint_entity_time_cluster",
        },
        "pearson_endpoint_replaced": False,
        "combined_162_family_error_control_claimed": False,
        "admission_authority": False,
        "funding_authority": False,
        "limitations": [
            "secondary_endpoint_retrospective_extension_not_original_preregistration_or_new_holdout",
            "no_selection_between_Pearson_and_RankIC_and_no_combined_162_family_claim",
            "individual_p_values_are_asymptotic_HAC_normal_approximations",
            "prediction_statistics_do_not_establish_portfolio_alpha_or_admission",
        ],
    }
    result["report_digest"] = digest(result)
    return result


def read_rank_sidecar(path, *, expected_sha256, expected_bundle_sha):
    _require(file_sha(path) == expected_sha256, "rank_ic_receipt_changed")
    value = json.loads(Path(path).read_text())
    _require(
        value.get("schema") == REPORT_SCHEMA
        and value.get("method") == METHOD
        and value.get("report_digest")
        == digest({k: v for k, v in value.items() if k != "report_digest"})
        and value.get("source", {}).get("source_output_manifest_sha256") == expected_bundle_sha
        and value.get("endpoint_role") == "secondary"
        and value.get("pearson_endpoint_replaced") is False
        and value.get("combined_162_family_error_control_claimed") is False
        and value.get("admission_authority") is False
        and value.get("funding_authority") is False
        and len(value.get("family", [])) == len(value.get("hypotheses", [])) == 81,
        "rank_ic_receipt_identity_invalid",
    )
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())
    _require(
        not args.out.resolve().is_relative_to(Path(plan["source_run_dir"]).resolve()),
        "rank_ic_output_must_be_outside_frozen_run",
    )
    result = derive_rank_inference(plan)
    result["plan_file_sha256"] = file_sha(args.plan)
    result["report_digest"] = digest({k: v for k, v in result.items() if k != "report_digest"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.out), "sha256": file_sha(args.out), **result["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
