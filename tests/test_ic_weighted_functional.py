"""Fixed artificial oracles only; no market or Monte Carlo coverage evidence."""

import math

import numpy as np
import pandas as pd
import pytest

from quant_system.research import ic_weighted_functional as method

EPSILONS = (1e-4, 1e-5, 1e-6)
DERIVATIVE_ATOL, DERIVATIVE_RTOL = 1e-7, 1e-5


def artificial_panel(*, hole=True):
    dates = pd.bdate_range("2024-01-02", periods=8, tz="UTC")
    x = [-2.0, -0.4, 0.8, 2.3]
    y = [2.0, 0.2, 1.2, -0.8]
    slope = [0.6, 0.1, -0.2, 0.4]
    rows = []
    for t, date in enumerate(dates):
        for i in range(4):
            eligible = not (hole and t == 2) and not (t == 1 and i == 3)
            rows.append(
                {
                    "symbol": f"S{i}",
                    "entity_id": f"G{i}",
                    "signal_ts": date,
                    "entry_ts": date + pd.Timedelta(days=1),
                    "return_end_ts": date + pd.Timedelta(days=6),
                    "value": x[i] + t * 0.15,
                    "forward_return": (y[i] + t * slope[i]) / 20 if eligible else np.nan,
                    "eligible": eligible,
                    "factor_id": "ARTIFICIAL",
                    "horizon": 5,
                }
            )
    return pd.DataFrame(rows), dates


def reference_mean(frame, dates, entity_counts=None, date_counts=None):
    """Independent integer replication + pandas Pearson; no production helpers."""
    results = []
    for date in dates:
        selected = frame[(frame.signal_ts == date) & frame.eligible]
        if selected.empty:
            continue
        if entity_counts is not None:
            selected = selected.loc[selected.index.repeat(selected.entity_id.map(entity_counts))]
        count = 1 if date_counts is None else date_counts[date.isoformat()]
        value = selected.value.corr(selected.forward_return, method="pearson")
        results.extend([value] * count)
    return math.fsum(results) / len(results)


def assert_diagnostic(result):
    assert result["method_role"] == "candidate_method_diagnostic"
    assert result["joint_cluster_se"] is None
    assert result["joint_cluster_status"] == "not_evaluated"
    assert result["significance_computed"] is False
    assert result["admission_authority"] is result["funding_authority"] is False


def test_uniform_weights_match_independent_pearson_date_average_without_pooled_weighting():
    frame, dates = artificial_panel()
    before = frame.copy(deep=True)
    panel = method.prepare_panel(frame, signal_calendar=dates)
    result = method.weighted_ic(panel)
    assert_diagnostic(result)
    assert result["mean_ic"] == pytest.approx(reference_mean(frame, dates), abs=1e-12)
    clean = frame[frame.eligible]
    assert abs(result["mean_ic"] - clean.value.corr(clean.forward_return)) > 1e-3
    assert result["calendar_slots"] == 8 and result["effective_dates"] == 7
    assert result["daily"][2] == {"signal_ts": dates[2].isoformat(), "ic": None, "n_original": 0}
    assert result["daily"][1]["n_original"] == 3
    pd.testing.assert_frame_equal(frame, before)
    with pytest.raises(ValueError):
        panel.x[0] = 42.0


def test_nonuniform_weights_match_literal_entity_and_date_replication():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    ew = {"G0": 1, "G1": 3, "G2": 2, "G3": 1}
    tw = {day.isoformat(): 1 + i % 3 for i, day in enumerate(dates)}
    result = method.weighted_ic(panel, entity_weights=ew, date_weights=tw)
    assert result["mean_ic"] == pytest.approx(reference_mean(frame, dates, ew, tw), abs=1e-12)


@pytest.mark.parametrize("epsilon", EPSILONS)
def test_entity_and_date_derivatives_match_centered_finite_difference_at_frozen_scales(epsilon):
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    analytic = method.analytic_contributions(panel)
    assert_diagnostic(analytic)
    for key, derivative in analytic["entity_derivatives"].items():
        plus, minus = dict.fromkeys(panel.entities, 1.0), dict.fromkeys(panel.entities, 1.0)
        plus[key] += epsilon
        minus[key] -= epsilon
        numeric = (
            method.weighted_ic(panel, entity_weights=plus)["mean_ic"]
            - method.weighted_ic(panel, entity_weights=minus)["mean_ic"]
        ) / (2 * epsilon)
        assert math.isclose(derivative, numeric, abs_tol=DERIVATIVE_ATOL, rel_tol=DERIVATIVE_RTOL)
    for key, derivative in analytic["date_derivatives"].items():
        plus, minus = dict.fromkeys(panel.dates, 1.0), dict.fromkeys(panel.dates, 1.0)
        plus[key] += epsilon
        minus[key] -= epsilon
        numeric = (
            method.weighted_ic(panel, date_weights=plus)["mean_ic"]
            - method.weighted_ic(panel, date_weights=minus)["mean_ic"]
        ) / (2 * epsilon)
        assert math.isclose(derivative, numeric, abs_tol=DERIVATIVE_ATOL, rel_tol=DERIVATIVE_RTOL)


def test_zero_date_sum_of_pearson_if_does_not_erase_actual_time_sensitivity():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    result = method.analytic_contributions(panel)
    sums = [value for value in result["psi_sums_by_original_date"] if value is not None]
    assert max(abs(x) for x in sums) < 1e-11
    wrong_date_meat = sum(x * x for x in sums)
    assert wrong_date_meat < 1e-20
    assert sum(x * x for x in result["date_derivatives"].values()) > 1e-4
    assert abs(sum(result["entity_derivatives"].values())) < 1e-11
    assert abs(sum(result["date_derivatives"].values())) < 1e-11
    assert result["joint_cluster_se"] is None  # The diagnostic is never a joint variance.


def test_duplicated_share_classes_share_history_weights_without_extra_cluster_information():
    frame, dates = artificial_panel()
    duplicate = frame.copy()
    duplicate["symbol"] += "_CLASS_B"
    expanded = pd.concat([frame, duplicate], ignore_index=True)
    first = method.prepare_panel(frame, signal_calendar=dates)
    second = method.prepare_panel(expanded, signal_calendar=dates)
    assert first.entities == second.entities  # Caller explicitly supplied issuer grouping.
    one = method.draw_resample_weights(first, seed=71, block_length=3)
    two = method.draw_resample_weights(second, seed=71, block_length=3)
    for key in ("entity_weights", "date_weights", "entity_draw_indices", "date_draw_indices"):
        assert one[key] == two[key]
    assert method.weighted_ic(first)["mean_ic"] == pytest.approx(
        method.weighted_ic(second)["mean_ic"], abs=1e-12
    )
    assert method.analytic_contributions(first)["entity_derivatives"] == pytest.approx(
        method.analytic_contributions(second)["entity_derivatives"], abs=1e-12
    )
    assert method.weighted_ic(
        first, entity_weights=one["entity_weights"], date_weights=one["date_weights"]
    )["mean_ic"] == pytest.approx(
        method.weighted_ic(
            second, entity_weights=two["entity_weights"], date_weights=two["date_weights"]
        )["mean_ic"],
        abs=1e-12,
    )


def test_shared_circular_blocks_keep_missing_date_slots_and_do_not_shuffle_each_security():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    draw = method.draw_resample_weights(panel, seed=71, block_length=3)
    assert_diagnostic(draw)
    assert draw["time_draw_shared_by_all_entities"] is True
    assert len(draw["date_draw_indices"]) == len(dates)
    assert set(draw["date_weights"]) == set(panel.dates)
    assert sum(draw["date_weights"].values()) == len(dates)
    assert sum(draw["entity_weights"].values()) == len(panel.entities)
    for start in range(0, len(dates), 3):
        block = draw["date_draw_indices"][start : start + 3]
        assert all(
            (right - left) % len(dates) == 1
            for left, right in zip(block[:-1], block[1:], strict=True)
        )
    whole = method.draw_resample_weights(panel, seed=4, block_length=8, resample_entities=False)
    assert whole["date_weights"][dates[2].isoformat()] == 1
    assert len(whole["date_weights"]) == 8  # Compression would incorrectly have seven slots.


def test_resampling_uses_frozen_labels_without_reconstructing_future_returns():
    frame, dates = artificial_panel()
    before = frame.copy(deep=True)
    panel = method.prepare_panel(frame, signal_calendar=dates)
    draw = method.draw_resample_weights(panel, seed=71, block_length=3)
    observed = method.weighted_ic(
        panel, entity_weights=draw["entity_weights"], date_weights=draw["date_weights"]
    )
    assert observed["mean_ic"] == pytest.approx(
        reference_mean(frame, dates, draw["entity_weights"], draw["date_weights"]), abs=1e-12
    )
    changed_times = frame.copy()
    changed_times["entry_ts"] += pd.Timedelta(days=10)
    changed_times["return_end_ts"] += pd.Timedelta(days=10)
    second = method.prepare_panel(changed_times, signal_calendar=dates)
    assert panel.input_digest != second.input_digest
    unchanged_labels = method.weighted_ic(
        second, entity_weights=draw["entity_weights"], date_weights=draw["date_weights"]
    )
    assert unchanged_labels["mean_ic"] == pytest.approx(observed["mean_ic"], abs=1e-12)
    assert draw["labels_reconstructed"] is False
    pd.testing.assert_frame_equal(frame, before)


def test_weighting_cannot_silently_drop_an_originally_valid_date():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    ew = {entity: float(entity == "G0") for entity in panel.entities}
    with pytest.raises(method.ICInputError, match="weighted_sample_too_small"):
        method.weighted_ic(panel, entity_weights=ew)
    only_hole = {day: float(day == dates[2].isoformat()) for day in panel.dates}
    with pytest.raises(method.ICInputError, match="no_weighted_effective_dates"):
        method.weighted_ic(panel, date_weights=only_hole)


def test_zero_date_weight_cannot_hide_a_new_entity_weight_degeneracy():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    ew = {"G0": 1.0, "G1": 0.0, "G2": 0.0, "G3": 1.0}
    tw = dict.fromkeys(panel.dates, 1.0)
    tw[dates[1].isoformat()] = 0.0  # G3 was already absent here in the original mask.
    with pytest.raises(method.ICInputError, match="weighted_sample_too_small"):
        method.weighted_ic(panel, entity_weights=ew, date_weights=tw)


def test_successful_single_draw_remains_diagnostic_without_variance_or_significance():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    result = method.resample_ic(panel, seed=71, block_length=3, resample_entities=False)
    assert_diagnostic(result)
    assert_diagnostic(result["draw"])
    assert_diagnostic(result["result"])
    assert result["evaluation_status"] == "evaluated" and result["attempted_draws"] == 1


def test_degenerate_single_draw_is_retained_without_retry_or_fabricated_result():
    frame, dates = artificial_panel(hole=False)
    frame = frame[frame.entity_id.isin(["G0", "G1"])]
    panel = method.prepare_panel(frame, signal_calendar=dates)
    result = method.resample_ic(panel, seed=0, block_length=2, resample_time=False)
    assert_diagnostic(result)
    assert result["draw"]["entity_draw_indices"] == [1, 1]
    assert result["evaluation_status"] == "rejected"
    assert result["reason"] == "ic_weighted_sample_too_small"
    assert result["attempted_draws"] == 1 and "result" not in result


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "eligible_nan",
        "infinite",
        "zero_scale",
        "single_pair",
        "all_missing",
        "label_time",
        "two_factors",
    ],
)
def test_invalid_original_data_are_rejected_without_filling_or_date_selection(mutation):
    frame, dates = artificial_panel()
    if mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif mutation == "eligible_nan":
        frame.loc[0, "forward_return"] = np.nan
    elif mutation == "infinite":
        frame.loc[0, "value"] = np.inf
    elif mutation == "zero_scale":
        frame.loc[frame.signal_ts == dates[0], "value"] = 1.0
    elif mutation == "single_pair":
        frame.loc[(frame.signal_ts == dates[0]) & (frame.symbol != "S0"), "eligible"] = False
    elif mutation == "all_missing":
        frame["eligible"] = False
    elif mutation == "label_time":
        frame.loc[0, "entry_ts"] = frame.loc[0, "signal_ts"]
    else:
        frame.loc[0, "factor_id"] = "ANOTHER"
    with pytest.raises(method.ICInputError):
        method.prepare_panel(frame, signal_calendar=dates)


@pytest.mark.parametrize("bad", [-1.0, float("inf"), float("nan"), True])
def test_invalid_weight_is_rejected(bad):
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    weights = dict.fromkeys(panel.entities, 1.0)
    weights[panel.entities[0]] = bad
    with pytest.raises(method.ICInputError, match="weights_invalid"):
        method.weighted_ic(panel, entity_weights=weights)


def test_dates_keys_and_zero_weights_are_not_silently_fixed():
    frame, dates = artificial_panel()
    with pytest.raises(method.ICInputError, match="calendar_invalid"):
        method.prepare_panel(frame, signal_calendar=dates[::-1])
    panel = method.prepare_panel(frame, signal_calendar=dates)
    with pytest.raises(method.ICInputError, match="weight_keys_mismatch"):
        method.weighted_ic(panel, entity_weights={"G0": 1.0})
    with pytest.raises(method.ICInputError, match="weight_total_invalid"):
        method.weighted_ic(panel, entity_weights=dict.fromkeys(panel.entities, 0.0))


def test_affine_invariance_sign_flip_and_row_permutation_preserve_the_contract():
    frame, dates = artificial_panel()
    original = method.prepare_panel(frame, signal_calendar=dates)
    baseline = method.weighted_ic(original)["mean_ic"]
    changed = frame.copy()
    # Arbitrary common date shifts cancel; they do not create a joint-dependence oracle.
    changed["value"] = 7 * changed.value + changed.signal_ts.map(
        {d: i * 100 for i, d in enumerate(dates)}
    )
    changed["forward_return"] = 2 * changed.forward_return + 10
    assert method.weighted_ic(method.prepare_panel(changed, signal_calendar=dates))[
        "mean_ic"
    ] == pytest.approx(baseline, abs=1e-12)
    changed["value"] *= -1
    assert method.weighted_ic(method.prepare_panel(changed, signal_calendar=dates))[
        "mean_ic"
    ] == pytest.approx(-baseline, abs=1e-12)
    shuffled = frame.sample(frac=1, random_state=3)
    assert (
        method.prepare_panel(shuffled, signal_calendar=dates).input_digest == original.input_digest
    )
    assert method.draw_resample_weights(
        original, seed=123, block_length=3
    ) == method.draw_resample_weights(original, seed=123, block_length=3)


def test_time_blocks_are_stable_across_entity_populations_and_toggles():
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    with_entities = method.draw_resample_weights(panel, seed=9, block_length=3)
    without_entities = method.draw_resample_weights(
        panel, seed=9, block_length=3, resample_entities=False
    )
    assert (
        without_entities["block_start_indices"] == with_entities["block_start_indices"]
        and without_entities["date_draw_indices"] == with_entities["date_draw_indices"]
    )
    trimmed = frame[frame["symbol"] != "S3"]
    smaller = method.prepare_panel(trimmed, signal_calendar=dates)
    shrunk = method.draw_resample_weights(smaller, seed=9, block_length=3)
    assert shrunk["date_draw_indices"] == with_entities["date_draw_indices"]


def test_rejected_draw_is_counted_for_later_aggregation(monkeypatch):
    frame, dates = artificial_panel()
    panel = method.prepare_panel(frame, signal_calendar=dates)
    alive = next(
        (
            method.resample_ic(panel, seed=seed, block_length=3)
            for seed in range(50)
            if method.resample_ic(panel, seed=seed, block_length=3)["evaluation_status"]
            == "evaluated"
        ),
        None,
    )
    assert alive is not None and alive["rejected_draws"] == 0
    dead = {
        "entity_weights": {entity: 0 for entity in panel.entities},
        "date_weights": {str(d): 1 for d in panel.dates},
    }
    monkeypatch.setattr(method, "draw_resample_weights", lambda *a, **k: dead)
    rejected = method.resample_ic(panel, seed=3, block_length=3)
    assert rejected["evaluation_status"] == "rejected" and rejected["rejected_draws"] == 1
