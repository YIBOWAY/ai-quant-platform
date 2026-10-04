"""Artificial frozen batches for inference mathematics; no market-profit claims."""

from __future__ import annotations

import copy
import itertools
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import false_discovery_control, norm

from quant_system.factors.evaluation import newey_west_lag_rule, newey_west_stats
from quant_system.research import factor_inference as inference
from tests.test_wide_scorecard_import import wide_run


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False))


def _reseal(run):
    manifest = {
        p.name: inference.file_sha(p)
        for p in sorted(run.iterdir())
        if p.name != "output-digests.json"
    }
    _write(run / "output-digests.json", manifest)
    return inference.file_sha(run / "output-digests.json")


@pytest.fixture
def frozen(tmp_path):
    run, _ = wide_run(tmp_path)
    config = json.loads((run / "run-config.json").read_text())
    card = json.loads((run / "scorecard.json").read_text())
    observations = []
    for obj, factor in zip(config["objects"], card["factors"], strict=True):
        sign = 1 if obj["direction"] == "higher_is_better" else -1
        values = sign * (0.005 + 0.02 * np.sin(np.arange(90) * 0.7))
        monthly = obj["frequency"] == "month_end"
        dates = pd.date_range(
            "2016-01-31" if monthly else "2016-01-04",
            periods=90,
            freq="ME" if monthly else "B",
            tz="UTC",
        )
        for horizon in (1, 5, 21):
            overlap = (1 if horizon == 21 else 0) if monthly else horizon - 1
            lag = newey_west_lag_rule(90, horizon=overlap + 1)
            stat = newey_west_stats(values, lag=lag, horizon=overlap + 1)
            factor["horizons"][str(horizon)] = {
                "ic": {
                    "status": "ready",
                    "reason": None,
                    "ic_mean": float(values.mean()),
                    "rank_ic_mean": 0.99,
                    "nw_t": stat["t_stat"],
                    "nw_lag": lag,
                    "n_days": 90,
                },
                "inference": {
                    "overlap_lags": overlap,
                    "signal_frequency": obj["frequency"],
                    "lag_unit": "signal_observations",
                    "horizon_unit": "trading_sessions",
                },
            }
            observations.extend(
                {
                    "factor_id": obj["factor_id"],
                    "horizon": horizon,
                    "signal_ts": day,
                    "ic": value,
                    "rank_ic": 0.99,
                    "price_basis": "open_to_open",
                    "n": 20,
                }
                for day, value in zip(dates, values, strict=True)
            )
    pd.DataFrame(observations).to_parquet(run / "ic_daily.parquet", index=False)
    _write(run / "scorecard.json", card)
    sha = _reseal(run)
    return run, inference.freeze_plan(run, expected_output_manifest_sha256=sha)


def _closed_bonferroni(pvalues):
    # Independent closed-testing calculation, deliberately not sorted Holm code.
    result = []
    indices = range(len(pvalues))
    for selected in indices:
        local_tests = []
        for size in range(1, len(pvalues) + 1):
            for subset in itertools.combinations(indices, size):
                if selected in subset:
                    local_tests.append(min(1.0, size * min(pvalues[i] for i in subset)))
        result.append(max(local_tests))
    return result


def test_holm_matches_closed_bonferroni_for_unsorted_ties_and_extremes():
    for raw in ([0.04, 0.001, 0.01, 0.03, 0.03], [1.0, 0.0, 0.1, 0.1, 0.99]):
        assert inference.adjust_pvalues(list(raw), method="holm") == pytest.approx(
            _closed_bonferroni(raw),
            abs=1e-15,
        )


def test_by_matches_existing_scipy_independent_implementation():
    raw = [0.04, 0.001, 0.01, 0.03, 0.03, 0.0, 1.0]
    assert inference.adjust_pvalues(raw, method="by") == pytest.approx(
        false_discovery_control(raw, method="by"),
        abs=1e-15,
    )


def test_unknown_cells_remain_in_denominator_without_becoming_p_one_results():
    raw = [0.03, None, None]
    assert inference.adjust_pvalues(raw, method="holm") == [0.09, None, None]
    adjusted = inference.adjust_pvalues(raw, method="by")
    assert adjusted[0] == pytest.approx(false_discovery_control([0.03, 1, 1], method="by")[0])
    assert adjusted[1:] == [None, None]
    assert inference.adjust_pvalues([None] * 81, method="holm") == [None] * 81


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True, "0.1"])
def test_invalid_p_values_are_rejected(value):
    with pytest.raises(ValueError, match="pvalue_invalid"):
        inference.adjust_pvalues([value], method="holm")


def test_full_family_retains_directions_duplicates_monthly_cadence_and_immutable_inputs(frozen):
    run, plan = frozen
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    result = inference.derive_inference(plan)
    assert result["summary"]["family_size"] == result["summary"]["evaluated"] == 81
    assert len({row["factor_id"] for row in result["hypotheses"]}) == 27
    assert sum(row["frequency"] == "month_end" for row in result["hypotheses"]) == 9
    assert any(row["duplicate_group"] is not None for row in result["hypotheses"])
    assert result["admission_authority"] is result["funding_authority"] is False
    assert result["cluster_robust"]["status"] == "not_evaluated"
    assert result["cluster_robust"]["standard_error"] is None
    assert result["cluster_robust"]["existing_hac_is_cluster_robust"] is False
    assert result["rank_ic_inference"]["status"] == "not_evaluated"
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
    for row in result["hypotheses"]:
        assert row["raw_p"] == pytest.approx(norm.sf(row["directed_hac_statistic"]), abs=1e-15)
        if row["direction"] == "lower_is_better":
            assert row["raw_pearson_ic_mean"] < 0 < row["directed_pearson_ic_mean"]
            assert row["directed_hac_statistic"] == -row["raw_pearson_ic_hac_t"]
        if row["frequency"] == "month_end" and row["horizon"] == 21:
            assert row["overlap_lags"] == 1
            assert row["nw_lag"] < 20


def test_adverse_strong_ic_cannot_become_positive_evidence_via_absolute_t(frozen):
    run, plan = frozen
    card = json.loads((run / "scorecard.json").read_text())
    factor = card["factors"][0]
    samples = pd.read_parquet(run / "ic_daily.parquet")
    selected = samples[(samples.factor_id == factor["factor_id"]) & samples.horizon.eq(1)].copy()
    selected["ic"] *= -1
    factor["horizons"]["1"]["ic"].update(ic_mean=float(selected.ic.mean()), nw_t=-8.0)
    hypothesis = plan["family"][0]
    assert hypothesis["direction"] == "higher_is_better"
    row = inference._cell(hypothesis, factor, selected)
    assert row["raw_p"] > 0.999999
    assert row["directed_pearson_ic_mean"] < 0
    # The unrelated RankIC value is 0.99 throughout; it never supplies the test statistic.
    assert row["raw_pearson_ic_hac_t"] == -8.0


def test_missing_saved_hac_retains_unknown_cell_without_shrinking_family(frozen):
    run, _ = frozen
    card = json.loads((run / "scorecard.json").read_text())
    card["factors"][0]["horizons"]["1"]["ic"].update(nw_t=None, reason="not_evaluated_fixture")
    _write(run / "scorecard.json", card)
    plan = inference.freeze_plan(run, expected_output_manifest_sha256=_reseal(run))
    result = inference.derive_inference(plan)
    row = result["hypotheses"][0]
    assert result["summary"]["family_size"] == 81
    assert result["summary"]["evaluated"] == 80
    assert row["status"] == "not_evaluated"
    assert row["raw_p"] is row["holm_adjusted_p"] is row["reject_primary"] is None


@pytest.mark.parametrize("tamper", ["remove_cell", "direction", "horizon", "alpha", "window"])
def test_resealed_plan_cannot_change_family_method_or_window(frozen, tamper):
    _, plan = frozen
    changed = copy.deepcopy(plan)
    if tamper == "remove_cell":
        changed["family"].pop()
    elif tamper == "direction":
        changed["family"][0]["direction"] = "lower_is_better"
    elif tamper == "horizon":
        changed["family"][0]["horizon"] = 10
    elif tamper == "alpha":
        changed["method"]["familywise_alpha"] = 0.5
    else:
        changed["signal_window"][0] = "2020-01-01"
    changed["plan_digest"] = inference.digest(
        {k: v for k, v in changed.items() if k != "plan_digest"}
    )
    with pytest.raises(ValueError, match="factor_inference"):
        inference.derive_inference(changed)


@pytest.mark.parametrize(
    "tamper", ["card", "daily", "remove_factor", "missing_horizon", "duplicate_row"]
)
def test_changed_inputs_or_incomplete_source_are_rejected(frozen, tamper):
    run, plan = frozen
    if tamper == "daily":
        (run / "ic_daily.parquet").write_bytes(b"changed artificial fixture")
    else:
        card = json.loads((run / "scorecard.json").read_text())
        if tamper == "card":
            card["factors"][0]["horizons"]["1"]["ic"]["nw_t"] = 999
            _write(run / "scorecard.json", card)
        elif tamper == "remove_factor":
            card["factors"].pop()
            _write(run / "scorecard.json", card)
            _reseal(run)
            plan["source_output_manifest_sha256"] = inference.file_sha(run / "output-digests.json")
        elif tamper == "missing_horizon":
            card["factors"][0]["horizons"].pop("21")
            _write(run / "scorecard.json", card)
            plan = inference.freeze_plan(run, expected_output_manifest_sha256=_reseal(run))
        else:
            frame = pd.read_parquet(run / "ic_daily.parquet")
            pd.concat([frame, frame.iloc[:1]]).to_parquet(run / "ic_daily.parquet", index=False)
            plan = inference.freeze_plan(run, expected_output_manifest_sha256=_reseal(run))
    with pytest.raises(ValueError):
        inference.derive_inference(plan)


def test_bound_sidecar_read_and_non_overwriting_write(frozen, tmp_path):
    _, plan = frozen
    report = inference.derive_inference(plan)
    path = tmp_path / "sidecar.json"
    inference._write_new(path, report)
    assert (
        inference.read_inference_sidecar(
            path,
            expected_sha256=inference.file_sha(path),
            expected_source_output_sha256=plan["source_output_manifest_sha256"],
        )["plan_digest"]
        == plan["plan_digest"]
    )
    with pytest.raises(FileExistsError):
        inference._write_new(path, report)
    with pytest.raises(ValueError, match="identity_invalid"):
        inference.read_inference_sidecar(
            path, expected_sha256=inference.file_sha(path), expected_source_output_sha256="0" * 64
        )
    path.write_text("{}")
    with pytest.raises(ValueError, match="receipt_changed"):
        inference.read_inference_sidecar(
            path,
            expected_sha256="a" * 64,
            expected_source_output_sha256=plan["source_output_manifest_sha256"],
        )


def test_cli_cannot_add_sidecar_inside_original_frozen_bundle(frozen, tmp_path):
    run, plan = frozen
    plan_path = tmp_path / "plan.json"
    inference._write_new(plan_path, plan)
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    with pytest.raises(ValueError, match="output_must_be_outside_frozen_run"):
        inference.main(["--plan", str(plan_path), "--out", str(run / "new-sidecar.json")])
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
