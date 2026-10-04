"""Deterministic, research-only stock panels and reconciliation with archived ICs.

No statistical standard error, admission, provider or account operation lives
here. The CLI binds the original source tree before importing its pure loader,
factor and label functions. This module supplies joins and reconciliation only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

PANEL_COLUMNS = [
    "factor_id",
    "horizon",
    "symbol",
    "entity_id",
    "signal_ts",
    "entry_ts",
    "return_end_ts",
    "value",
    "forward_return",
    "exclusion_reason",
    "eligible",
    "price_basis",
]
PLAN_SCHEMA = "qs.factor_contribution_rebuild_plan/v1"
ARCHIVE_COMMIT = "55f8369f4a63870a0da07432e84303660c6e7829"
IC_ATOL = 1e-12
IC_RTOL = 1e-10


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def write_new_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def verify_files(plan, *, inputs=True):
    """Verify both original bytes and source files; no refresh or reconstruction."""
    for name, expected in plan["archive_source_files"].items():
        require(
            file_sha(Path(plan["archive_root"]) / name) == expected,
            "contribution_archived_source_changed",
        )
    source = Path(plan["source_run_dir"])
    require(
        file_sha(source / "output-digests.json") == plan["source_output_manifest_sha256"],
        "contribution_original_manifest_changed",
    )
    for name, expected in plan["source_files"].items():
        require(
            Path(name).name == name and file_sha(source / name) == expected,
            "contribution_original_artifact_changed",
        )
    if inputs:
        for name, expected in plan["referenced_input_files"].items():
            require(file_sha(name) == expected, "contribution_frozen_input_changed")


def validate_plan(plan):
    require(
        plan.get("schema") == PLAN_SCHEMA
        and plan.get("plan_digest")
        == digest({k: v for k, v in plan.items() if k != "plan_digest"}),
        "contribution_plan_changed",
    )
    require(plan["archive_commit"] == ARCHIVE_COMMIT, "contribution_wrong_archive_commit")
    require(plan["panel_columns"] == PANEL_COLUMNS, "contribution_panel_contract_changed")
    require(
        plan["comparison"]
        == {
            "ic_atol": IC_ATOL,
            "ic_rtol": IC_RTOL,
            "counts_dates_entities_exclusions": "exact",
            "missingness": "exact",
        },
        "contribution_comparison_contract_changed",
    )
    require(
        plan.get("admission_authority") is False and plan.get("funding_authority") is False,
        "contribution_research_only_required",
    )
    config = json.loads((Path(plan["source_run_dir"]) / "run-config.json").read_text())
    expected = [
        {
            "factor_id": obj["factor_id"],
            "horizon": horizon,
            "direction": obj["direction"],
            "frequency": obj["frequency"],
            "object_digest": digest(obj),
        }
        for obj in config["objects"]
        for horizon in config["horizons"]
    ]
    require(
        len(expected) == 81
        and len(config["objects"]) == 27
        and config["horizons"] == [1, 5, 21]
        and plan["tasks"] == expected
        and plan["pilot_task"] == expected[0]
        and config["digest"] == plan["source_factor_manifest_digest"],
        "contribution_frozen_family_changed",
    )


def assert_module_origins(modules, archive_root):
    root = (Path(archive_root) / "src").resolve()
    require(
        all(Path(module.__file__).resolve().is_relative_to(root) for module in modules),
        "contribution_wrong_import_source",
    )


def _dates(frame, column):
    return pd.to_datetime(frame[column], utc=True, errors="raise")


def preserve_original_join(values, prepared, membership, observed_mask, *, factor_id, horizon):
    """Preserve values excluded by the original observed-bar inner join explicitly.

    Recursive indicators can retain a finite value on a missing-bar session.
    Those values were never members of the original IC sample; no new filtering
    rule is introduced here. Any other dropped or invented row is an error.
    """
    keys = ["symbol", "signal_ts"]
    raw = values[["symbol", "signal_ts", "factor_id", "value"]].copy()
    raw["signal_ts"] = _dates(raw, "signal_ts")
    require(
        raw.factor_id.eq(factor_id).all() and not raw.duplicated(keys).any(),
        "contribution_duplicate_raw_value",
    )
    selected = prepared[["symbol", "signal_ts", "factor_id", "value"]].copy()
    selected["signal_ts"] = _dates(selected, "signal_ts")
    require(
        selected.factor_id.eq(factor_id).all() and not selected.duplicated(keys).any(),
        "contribution_duplicate_prepared_value",
    )
    joined = raw.merge(
        selected[keys + ["value"]],
        on=keys,
        how="outer",
        indicator=True,
        suffixes=("", "_prepared"),
        validate="one_to_one",
    )
    require(not joined._merge.eq("right_only").any(), "contribution_invented_evaluation_row")
    matched = joined._merge.eq("both")
    require(
        np.array_equal(
            joined.loc[matched, "value"].to_numpy(),
            joined.loc[matched, "value_prepared"].to_numpy(),
        ),
        "contribution_raw_value_changed",
    )
    observed = observed_mask.stack(future_stack=True).reindex(
        pd.MultiIndex.from_frame(joined[["signal_ts", "symbol"]])
    )
    require(observed.notna().all(), "contribution_signal_outside_original_observed_grid")
    require(
        np.array_equal(matched.to_numpy(), observed.to_numpy(dtype=bool)),
        "contribution_unknown_inner_join_drop",
    )
    unmatched = joined.loc[~matched, ["symbol", "signal_ts", "factor_id", "value"]].copy()
    identities = membership[["symbol", "signal_ts", "entity_id"]].copy()
    identities["signal_ts"] = _dates(identities, "signal_ts")
    require(not identities.duplicated(keys).any(), "contribution_ambiguous_membership")
    unmatched = unmatched.merge(identities, on=keys, how="left", validate="one_to_one")
    require(
        unmatched.entity_id.notna().all()
        and not unmatched.duplicated(["entity_id", "signal_ts"]).any(),
        "contribution_unmatched_entity_binding_invalid",
    )
    unmatched["horizon"] = horizon
    unmatched["eligible"] = False
    unmatched["exclusion_reason"] = "original_loaded_signal_bar_not_observed"
    require(len(prepared) + len(unmatched) == len(raw), "contribution_join_partition_incomplete")
    audit = {
        "original_factor_value_rows": len(raw),
        "matched_rows": len(prepared),
        "unmatched_rows": len(unmatched),
        "partition_complete": True,
        "unmatched_reason": "original_loaded_signal_bar_not_observed",
        "original_ic_sample_unchanged": True,
    }
    return unmatched.sort_values(["signal_ts", "symbol"], ignore_index=True), audit


def build_panel(prepared, membership, *, factor_id, horizon, label_calendar):
    required = {
        "factor_id",
        "symbol",
        "signal_ts",
        "entry_ts",
        "return_end_ts",
        "value",
        "forward_return",
        "exclusion_reason",
        "price_basis",
        "horizon",
    }
    require(required.issubset(prepared.columns), "contribution_prepared_columns_missing")
    panel = prepared[list(required)].copy()
    require(
        panel.factor_id.eq(factor_id).all()
        and panel.horizon.eq(horizon).all()
        and panel.price_basis.eq("open_to_open").all(),
        "contribution_factor_label_mismatch",
    )
    panel["signal_ts"] = _dates(panel, "signal_ts")
    require(not panel.duplicated(["symbol", "signal_ts"]).any(), "contribution_duplicate_signal")
    identities = membership[["symbol", "signal_ts", "entity_id"]].copy()
    identities["signal_ts"] = _dates(identities, "signal_ts")
    require(
        not identities.duplicated(["symbol", "signal_ts"]).any(),
        "contribution_ambiguous_membership",
    )
    panel = panel.merge(identities, on=["symbol", "signal_ts"], how="left", validate="one_to_one")
    require(
        panel.entity_id.notna().all() and panel.entity_id.astype(str).str.strip().ne("").all(),
        "contribution_entity_binding_missing",
    )
    require(
        not panel.duplicated(["entity_id", "signal_ts"]).any(),
        "contribution_duplicate_entity_signal",
    )
    calendar = pd.DatetimeIndex(pd.to_datetime(label_calendar, utc=True))
    require(
        calendar.is_monotonic_increasing and not calendar.has_duplicates,
        "contribution_label_calendar_invalid",
    )
    positions = calendar.get_indexer(panel.signal_ts)
    require((positions >= 0).all(), "contribution_signal_date_outside_calendar")
    for column, offset in (("entry_ts", 1), ("return_end_ts", horizon + 1)):
        panel[column] = _dates(panel, column)
        expected = np.full(len(panel), np.iinfo(np.int64).min, dtype="int64")
        valid = positions + offset < len(calendar)
        expected[valid] = calendar.asi8[positions[valid] + offset]
        require(
            np.array_equal(panel[column].array.asi8, expected),
            "contribution_entry_exit_binding_changed",
        )
    values = pd.to_numeric(panel.value, errors="raise").to_numpy(dtype=float)
    returns = pd.to_numeric(panel.forward_return, errors="raise").to_numpy(dtype=float)
    require(np.isfinite(values).all(), "contribution_factor_value_nonfinite")
    eligible = np.isfinite(values) & np.isfinite(returns)
    require(
        np.array_equal(eligible, panel.exclusion_reason.isna().to_numpy()),
        "contribution_exclusion_binding_changed",
    )
    panel["value"], panel["forward_return"], panel["eligible"] = values, returns, eligible
    return panel[PANEL_COLUMNS].sort_values(["signal_ts", "symbol"], ignore_index=True)


def daily_correlations(panel):
    """Vectorized reproduction of the original per-session Pearson and RankIC."""
    calendar = pd.DatetimeIndex(panel.signal_ts.unique()).sort_values()
    clean = panel.loc[panel.eligible, ["signal_ts", "value", "forward_return"]].copy()
    groups = clean.groupby("signal_ts", sort=True)
    result = pd.DataFrame(index=calendar)
    result.index.name = "signal_ts"
    result["n"] = groups.size().reindex(calendar, fill_value=0).astype("int64")
    varying = (groups[["value", "forward_return"]].nunique() >= 2).all(axis=1)
    for rank, name in ((False, "ic"), (True, "rank_ic")):
        values = (
            groups[["value", "forward_return"]].rank(method="average")
            if rank
            else clean[["value", "forward_return"]]
        )
        centered = values - values.groupby(clean.signal_ts).transform("mean")
        numerator = (centered.value * centered.forward_return).groupby(clean.signal_ts).sum()
        variance = (centered * centered).groupby(clean.signal_ts).sum()
        correlation = numerator / np.sqrt(variance.value * variance.forward_return)
        result[name] = correlation.where(varying).reindex(calendar)
    return result.reset_index()


def reconcile_panel(panel, expected_daily, expected_coverage):
    require(
        not panel.duplicated(["factor_id", "horizon", "symbol", "signal_ts"]).any(),
        "contribution_duplicate_signal",
    )
    actual = daily_correlations(panel)
    expected = expected_daily[["signal_ts", "n", "ic", "rank_ic"]].copy()
    expected["signal_ts"] = _dates(expected, "signal_ts")
    expected = expected.sort_values("signal_ts", ignore_index=True)
    require(not expected.signal_ts.duplicated().any(), "contribution_reference_duplicate_day")
    require(
        len(actual) == len(expected) and actual.signal_ts.equals(expected.signal_ts),
        "contribution_reference_calendar_mismatch",
    )
    require(np.array_equal(actual.n, expected.n), "contribution_reference_sample_count_mismatch")
    maxima = {}
    for column in ("ic", "rank_ic"):
        left, right = (frame[column].to_numpy(dtype=float) for frame in (actual, expected))
        require(
            np.array_equal(np.isnan(left), np.isnan(right)),
            "contribution_reference_missingness_mismatch",
        )
        require(
            np.allclose(left, right, atol=IC_ATOL, rtol=IC_RTOL, equal_nan=True),
            "contribution_reference_correlation_mismatch",
        )
        mask = np.isfinite(left) & np.isfinite(right)
        maxima[column] = float(np.max(np.abs(left[mask] - right[mask]))) if mask.any() else None
    observed = {
        "valid_rows": int(panel.eligible.sum()),
        "valid_signal_days": int(panel.loc[panel.eligible, "signal_ts"].nunique()),
        "label_tail_insufficient": int(panel.return_end_ts.isna().sum()),
        "excluded_by_reason": {
            str(k): int(v) for k, v in panel.exclusion_reason.dropna().value_counts().items()
        },
        "first_valid_signal": panel.loc[panel.eligible, "signal_ts"].min().isoformat()
        if panel.eligible.any()
        else None,
        "last_valid_signal": panel.loc[panel.eligible, "signal_ts"].max().isoformat()
        if panel.eligible.any()
        else None,
    }
    require(observed == expected_coverage, "contribution_reference_coverage_mismatch")
    return actual, {
        "status": "matched_original",
        "rows": len(panel),
        "signal_days": len(actual),
        "symbols": int(panel.symbol.nunique()),
        "entities": int(panel.entity_id.nunique()),
        "max_abs_pearson_difference": maxima["ic"],
        "max_abs_rankic_difference": maxima["rank_ic"],
        "coverage": observed,
        "duplicate_signal_rows": 0,
        "duplicate_entity_signal_rows": 0,
        "raw_factor_direction_retained": True,
    }


def reconcile_factor_values(values, membership, calendar, *, item, expected):
    require(
        values.factor_id.eq(item["factor_id"]).all()
        and not values.duplicated(["symbol", "signal_ts"]).any(),
        "contribution_factor_identity_changed",
    )
    if item["frequency"] == "month_end":
        ends = pd.Series(calendar, index=calendar).groupby(calendar.strftime("%Y-%m")).last()
        count = int(membership.signal_ts.isin(ends).sum())
    else:
        count = len(membership)
    require(
        count == expected["expected_member_signal_rows"]
        and len(values) == expected["eligible_factor_rows"]
        and count - len(values) == expected["warmup_or_missing_input_rows"],
        "contribution_reference_factor_coverage_mismatch",
    )
