"""Artificial saved RankIC series exercise inference, never market-performance claims."""

import copy
import json
import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import false_discovery_control, norm

from quant_system.factors.evaluation import newey_west_stats
from quant_system.research import rank_ic_inference as subject
from tests.test_wide_scorecard_import import wide_run


def _json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))


def _reseal(run):
    _json(
        run / "output-digests.json",
        {p.name: subject.file_sha(p) for p in run.iterdir() if p.name != "output-digests.json"},
    )
    return subject.file_sha(run / "output-digests.json")


@pytest.fixture
def frozen(tmp_path):
    run, _ = wide_run(tmp_path)
    config = json.loads((run / "run-config.json").read_text())
    card = json.loads((run / "scorecard.json").read_text())
    rows = []
    for index, (obj, factor) in enumerate(zip(config["objects"], card["factors"], strict=True)):
        monthly = obj["frequency"] == "month_end"
        dates = pd.date_range(
            "2016-01-29" if monthly else "2016-01-04",
            periods=128 if monthly else 120,
            freq="BME" if monthly else "B",
            tz="UTC",
        )
        for horizon in [1, 5, 21]:
            overlap = (1 if horizon == 21 else 0) if monthly else horizon - 1
            lag = max(4, overlap)
            sign = 1 if obj["direction"] == "higher_is_better" else -1
            rank = sign * (
                0.025 + 0.2 * np.sin(np.arange(len(dates)) * 0.37 + index * 0.02 + horizon * 0.01)
            )
            if monthly and horizon == 21:
                rank[-1] = np.nan
            factor["horizons"][str(horizon)] = {
                "ic": {"rank_ic_mean": float(np.nanmean(rank)), "nw_lag": lag, "nw_t": 987.0},
                "inference": {
                    "overlap_lags": overlap,
                    "lag_unit": "signal_observations",
                    "horizon_unit": "trading_sessions",
                    "signal_frequency": obj["frequency"],
                },
            }
            rows.extend(
                {
                    "factor_id": obj["factor_id"],
                    "horizon": horizon,
                    "signal_ts": day,
                    "rank_ic": value,
                    "price_basis": "open_to_open",
                }
                for day, value in zip(dates, rank, strict=True)
            )
    pd.DataFrame(rows).to_parquet(run / "ic_daily.parquet", index=False)
    _json(run / "scorecard.json", card)
    old_plan, old_report = tmp_path / "pearson-plan.json", tmp_path / "pearson-report.json"
    _json(old_plan, {"scope": "artificial_unchanged_primary_fixture"})
    _json(old_report, {"scope": "artificial_unchanged_primary_fixture", "result": "untouched"})
    plan = subject.freeze_rank_plan(
        run,
        expected_bundle_sha=_reseal(run),
        pearson_plan_path=old_plan,
        pearson_report_path=old_report,
        expected_pearson_plan_sha=subject.file_sha(old_plan),
        expected_pearson_report_sha=subject.file_sha(old_report),
    )
    return run, plan


def _oracle(values, lag):
    good = np.isfinite(values)
    n = int(good.sum())
    mean = float(values[good].mean())
    centered = np.where(good, values - mean, 0.0)
    weighted = float(centered @ centered)
    for k in range(1, lag + 1):
        weighted += 2 * (1 - k / (lag + 1)) * float(centered[k:] @ centered[:-k])
    se = math.sqrt(weighted) / n
    return mean, se, mean / se


def test_rank_hac_keeps_nan_positions_and_matches_centered_product_oracle():
    values = 0.025 + 0.2 * np.sin(np.arange(180) * 0.23)
    values[[5, 16, 44, 51, 99, 105]] = np.nan
    cell = {"direction": "higher_is_better", "nw_lag": 7, "overlap_lags": 4}
    row = subject.infer_cell(cell, pd.DataFrame({"rank_ic": values}))
    mean, se, t = _oracle(values, 7)
    assert row["status"] == "evaluated"
    assert row["raw_rank_ic_mean"] == pytest.approx(mean)
    assert row["hac_standard_error"] == pytest.approx(se, rel=1e-13)
    assert row["raw_rank_ic_hac_t"] == pytest.approx(t, rel=1e-13)
    assert row["raw_p"] == pytest.approx(norm.sf(t), abs=1e-15)
    compressed = newey_west_stats(values[np.isfinite(values)], lag=7, horizon=5)
    assert not math.isclose(compressed["t_stat"], t, rel_tol=1e-4)
    assert row["hac"]["pair_counts"]["1"] == int(
        (np.isfinite(values[1:]) & np.isfinite(values[:-1])).sum()
    )


def test_declared_lower_direction_applies_once_without_reversing_raw_series():
    values = 0.08 + 0.1 * np.sin(np.arange(120) * 0.7)
    row = subject.infer_cell(
        {"direction": "lower_is_better", "nw_lag": 4, "overlap_lags": 0},
        pd.DataFrame({"rank_ic": values}),
    )
    assert row["raw_rank_ic_hac_t"] > 0
    assert row["directed_rank_ic_hac_t"] == -row["raw_rank_ic_hac_t"]
    assert row["directed_rank_ic_mean"] == -row["raw_rank_ic_mean"]
    assert row["raw_p"] > 0.99


def test_frozen_81_secondary_endpoint_does_not_copy_pearson_t_or_modify_sources(frozen):
    run, plan = frozen
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    result = subject.derive_rank_inference(plan)
    assert result["summary"]["family_size"] == 81
    assert result["summary"]["evaluated"] == 81
    assert result["endpoint_role"] == "secondary" and result["pearson_endpoint_replaced"] is False
    assert result["combined_162_family_error_control_claimed"] is False
    assert result["joint_cluster_se"]["status"] == "not_evaluated"
    assert result["admission_authority"] is result["funding_authority"] is False
    assert all(x["raw_rank_ic_hac_t"] != 987 for x in result["hypotheses"])
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
    for cell in result["hypotheses"]:
        if cell["frequency"] == "month_end":
            assert cell["nw_lag"] == 4
            assert cell["overlap_lags"] == (1 if cell["horizon"] == 21 else 0)
            assert cell["hac_horizon_in_signal_observations"] == (2 if cell["horizon"] == 21 else 1)
            assert cell["rank_observations"] == (127 if cell["horizon"] == 21 else 128)
    raw = [x["raw_p"] for x in result["hypotheses"]]
    assert [x["by_adjusted_p"] for x in result["hypotheses"]] == pytest.approx(
        false_discovery_control(raw, method="by"),
        abs=1e-15,
    )


@pytest.mark.parametrize(
    "series",
    [
        pd.Series(["0.1", "bad"]),
        pd.Series([True, False]),
        pd.Series([0.1, float("inf")]),
        pd.Series([0.1, 1.1]),
    ],
)
def test_invalid_numeric_values_are_not_silently_coerced_to_missing(series):
    with pytest.raises(ValueError, match="rank_ic_"):
        subject.rank_values(series)


def test_statistical_failure_remains_null_in_full_81_correction(frozen):
    run, old = frozen
    frame = pd.read_parquet(run / "ic_daily.parquet")
    cell = old["family"][0]
    selected = frame.factor_id.eq(cell["factor_id"]) & frame.horizon.eq(cell["horizon"])
    frame.loc[selected, "rank_ic"] = 0.0
    frame.to_parquet(run / "ic_daily.parquet", index=False)
    card = json.loads((run / "scorecard.json").read_text())
    card["factors"][0]["horizons"]["1"]["ic"]["rank_ic_mean"] = 0.0
    _json(run / "scorecard.json", card)
    p = old["pearson_preserved"]
    plan = subject.freeze_rank_plan(
        run,
        expected_bundle_sha=_reseal(run),
        pearson_plan_path=p["plan_path"],
        pearson_report_path=p["report_path"],
        expected_pearson_plan_sha=p["plan_sha256"],
        expected_pearson_report_sha=p["report_sha256"],
    )
    with pytest.warns(UserWarning, match="long-run variance"):
        result = subject.derive_rank_inference(plan)
    failed = result["hypotheses"][0]
    assert failed["status"] == "not_evaluated" and failed["reason"] == "nonpositive_lrv"
    assert failed["raw_p"] is failed["hac_standard_error"] is failed["holm_adjusted_p"] is None
    assert failed["holm_reject_secondary_endpoint"] is None
    assert result["summary"]["family_size"] == 81 and result["summary"]["not_evaluated"] == 1
    raw = [1.0 if x["raw_p"] is None else x["raw_p"] for x in result["hypotheses"]]
    expected = false_discovery_control(raw, method="by")
    assert result["hypotheses"][1]["by_adjusted_p"] == pytest.approx(expected[1])


@pytest.mark.parametrize(
    "field",
    ["direction", "nw_lag", "overlap_lags", "missing_positions_digest", "remove_cell", "endpoint"],
)
def test_rehashed_plan_cannot_change_frozen_direction_lag_missing_axis_or_secondary_role(
    frozen, field
):
    _, plan = frozen
    plan = copy.deepcopy(plan)
    if field == "remove_cell":
        plan["family"].pop()
    elif field == "endpoint":
        plan["method"]["endpoint_role"] = "primary"
    elif field == "direction":
        plan["family"][0]["direction"] = "lower_is_better"
    elif field == "missing_positions_digest":
        plan["family"][0][field] = "a" * 64
    else:
        plan["family"][0][field] += 1
    plan["plan_digest"] = subject.digest({k: v for k, v in plan.items() if k != "plan_digest"})
    with pytest.raises(ValueError, match="rank_ic_"):
        subject.derive_rank_inference(plan)


@pytest.mark.parametrize("target", ["ic_daily.parquet", "scorecard.json", "pearson"])
def test_changed_original_or_primary_reference_is_rejected(frozen, target):
    run, plan = frozen
    from pathlib import Path

    path = Path(plan["pearson_preserved"]["report_path"]) if target == "pearson" else run / target
    path.write_bytes(b"changed artificial fixture")
    with pytest.raises(ValueError):
        subject.derive_rank_inference(plan)


def test_bound_read_and_non_overwriting_cli(frozen, tmp_path):
    _, plan = frozen
    pp = tmp_path / "rank-plan.json"
    _json(pp, plan)
    output = tmp_path / "rank-report.json"
    assert subject.main(["--plan", str(pp), "--out", str(output)]) == 0
    report = subject.read_rank_sidecar(
        output,
        expected_sha256=subject.file_sha(output),
        expected_bundle_sha=plan["source_output_manifest_sha256"],
    )
    assert report["endpoint_role"] == "secondary"
    with pytest.raises(FileExistsError):
        subject.main(["--plan", str(pp), "--out", str(output)])
    with pytest.raises(ValueError, match="identity_invalid"):
        subject.read_rank_sidecar(
            output, expected_sha256=subject.file_sha(output), expected_bundle_sha="0" * 64
        )
    with pytest.raises(ValueError, match="outside_frozen_run"):
        subject.main(["--plan", str(pp), "--out", str(tmp_path / "frozen/rank-report.json")])


def test_missing_required_overlap_pairs_do_not_turn_into_a_compressed_time_test():
    values = 0.05 + 0.1 * np.sin(np.arange(140) * 0.4)
    values[1::2] = np.nan
    row = subject.infer_cell(
        {"direction": "higher_is_better", "nw_lag": 4, "overlap_lags": 4},
        pd.DataFrame({"rank_ic": values}),
    )
    assert row["hac"]["n_obs"] == 70
    assert row["status"] == "not_evaluated"
    assert row["reason"] == "insufficient_pairs_at_required_lag"
    assert row["hac"]["pair_counts"]["1"] == 0
    assert row["raw_p"] is row["hac_standard_error"] is None
    assert newey_west_stats(values[np.isfinite(values)], lag=4, horizon=5)["t_stat"] is not None
