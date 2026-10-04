"""Concentration (raw block, residual diagnostic), null p95 calibration, increment."""

from __future__ import annotations

import numpy as np
import pytest

from quant_system.research import gate_v2 as g
from tests.gate_v2_fixtures import active_series_from, curve_rows


def _series(rng: np.random.Generator, n: int, beta: float, common: np.ndarray, vol: float = 0.01):
    return [float(value) for value in beta * common + rng.normal(0.0, vol, n)]


def test_null_p95_calibrates_iid_pairs_to_a_usable_line() -> None:
    rng = np.random.default_rng(20260918)
    n = 126
    calibration = g.residual_null_p95(
        left_returns=_series(rng, n, 0.0, np.zeros(n)),
        right_returns=_series(rng, n, 0.0, np.zeros(n)),
        benchmark_returns=_series(rng, n, 0.0, np.zeros(n)),
        block_length=21,
        n_resamples=1000,
        seed=1,
    )
    p95 = calibration["null_p95"]
    assert p95 is not None and p95 < 0.25
    exceed = 0
    total = 200
    for _ in range(total):
        result = g.residual_correlation_v2(
            left_returns=_series(rng, n, 0.0, np.zeros(n)),
            right_returns=_series(rng, n, 0.0, np.zeros(n)),
            benchmark_returns=_series(rng, n, 0.0, np.zeros(n)),
            null_p95=p95,
        )
        if result["residual_corr"] is not None and result["residual_corr"] > p95:
            exceed += 1
    assert exceed / total <= 0.10  # i.i.d. false-report rate stays at the line


def test_a_planted_shared_factor_exceeds_the_null_line() -> None:
    rng = np.random.default_rng(7)
    n = 252
    common = rng.normal(0.0, 0.01, n)
    benchmark = [float(value) for value in rng.normal(0.0, 0.005, n)]
    left = _series(rng, n, 1.0, common)
    right = _series(rng, n, 1.0, common)
    calibration = g.residual_null_p95(
        left_returns=left,
        right_returns=right,
        benchmark_returns=benchmark,
        block_length=21,
        n_resamples=1000,
        seed=3,
    )
    result = g.residual_correlation_v2(
        left_returns=left,
        right_returns=right,
        benchmark_returns=benchmark,
        null_p95=calibration["null_p95"],
    )
    assert result["residual_corr"] > calibration["null_p95"]
    assert result["passed"] is False
    assert result["authority"] == "diagnostic_only"


def test_missing_benchmark_names_the_residual_dependency() -> None:
    result = g.residual_correlation_v2(
        left_returns=[0.01] * 60, right_returns=[0.01] * 60, benchmark_returns=None, null_p95=0.1
    )
    assert result == {
        "schema_version": g.CORR_V2_SCHEMA_VERSION,
        "residual_corr": None,
        "null_p95": 0.1,
        "passed": None,
        "reason": "benchmark_required_for_residual",
        "authority": "diagnostic_only",
    }


def test_raw_concentration_blocks_a_duplicate_sleeve() -> None:
    rng = np.random.default_rng(11)
    n = 200
    candidate = [float(value) for value in rng.normal(0.0, 0.01, n)]
    duplicate = [
        value * 1.0 + float(noise)
        for value, noise in zip(candidate, rng.normal(0, 0.0001, n), strict=True)
    ]
    active = active_series_from(candidate)
    blocked = g.concentration_v2(
        active=active,
        hung_sleeves=[{"sleeve_id": "s1", "returns": duplicate, "dates": None}],
        config=g.GATE_V2_CONFIG,
    )
    assert blocked["applicable"] is True
    assert blocked["raw_max"] > g.CORRELATION_MAX_V2
    assert blocked["raw_passed"] is False
    assert blocked["passed"] is False


def test_raw_concentration_passes_for_an_independent_sleeve() -> None:
    rng = np.random.default_rng(12)
    n = 400
    active = active_series_from([float(value) for value in rng.normal(0.0, 0.01, n)])
    independent = [float(value) for value in rng.normal(0.0, 0.01, n)]
    result = g.concentration_v2(
        active=active,
        hung_sleeves=[{"sleeve_id": "s1", "returns": independent, "dates": None}],
        config=g.GATE_V2_CONFIG,
    )
    assert result["raw_max"] < g.CORRELATION_MAX_V2
    assert result["passed"] is True


@pytest.mark.parametrize("raw_duplicate", [True, False])
def test_concentration_uses_raw_returns_when_active_returns_disagree(raw_duplicate) -> None:
    rng = np.random.default_rng(20260920)
    n = 252
    sleeve = rng.normal(0.0, 0.01, n)
    independent = rng.normal(0.0, 0.001, n)
    equity = sleeve + independent if raw_duplicate else independent
    active_returns = independent if raw_duplicate else sleeve
    benchmark = equity - active_returns
    active = g.recompute_active_returns(
        curve_rows(equity_returns=equity, benchmark_returns=benchmark),
        initial_cash=100_000.0,
    )

    result = g.concentration_v2(
        active=active,
        hung_sleeves=[{"sleeve_id": "existing", "returns": sleeve.tolist(), "dates": None}],
        config=g.GATE_V2_CONFIG,
    )

    expected = float(np.corrcoef(equity, sleeve)[0, 1])
    assert result["raw_max"] == pytest.approx(expected)
    assert result["passed"] is (not raw_duplicate)


@pytest.mark.parametrize("missing_form", ["absent", "none", "empty"])
def test_concentration_rejects_missing_raw_returns_without_active_fallback(missing_form) -> None:
    active = active_series_from([0.001, -0.001] * 126)
    if missing_form == "absent":
        active.pop("equity_returns")
    else:
        active["equity_returns"] = None if missing_form == "none" else []

    with pytest.raises(ValueError, match="gate_v2_equity_returns_missing"):
        g.concentration_v2(
            active=active,
            hung_sleeves=[{"sleeve_id": "existing", "returns": [0.002, -0.002] * 126}],
            config=g.GATE_V2_CONFIG,
        )


def test_no_hung_sleeves_means_the_raw_rule_is_not_applicable() -> None:
    active = active_series_from([0.001, -0.001] * 100)
    result = g.concentration_v2(active=active, hung_sleeves=[], config=g.GATE_V2_CONFIG)
    assert result["applicable"] is False
    assert result["passed"] is True
    assert result["residual_reason"] == "no_reference_for_residual"


def test_residual_diagnosis_aligns_sleeve_dates_before_regression() -> None:
    import pandas as pd

    rng = np.random.default_rng(71)
    market = rng.normal(0, 0.01, 80)
    stock = market + rng.normal(0, 0.005, 80)
    dates = pd.bdate_range("2020-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    result = g.concentration_v2(
        active={"equity_returns": stock.tolist(), "dates": dates},
        hung_sleeves=[{"sleeve_id": "same", "returns": stock[::-1].tolist(), "dates": dates[::-1]}],
        benchmark_returns=market.tolist(),
        null_p95=0.5,
    )
    assert result["residual_max"] == pytest.approx(1.0)


@pytest.mark.parametrize("include_comparable", [False, True])
def test_unassessable_existing_sleeve_cannot_pass_concentration(include_comparable) -> None:
    import pandas as pd

    rng = np.random.default_rng(20260920)
    values = rng.normal(0, 0.01, 80).tolist()
    dates = pd.bdate_range("2020-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    active = {"equity_returns": values, "dates": dates}
    sleeves = [
        {
            "sleeve_id": "no-overlap",
            "returns": values,
            "dates": pd.bdate_range("2022-01-01", periods=80).strftime("%Y-%m-%d").tolist(),
        }
    ]
    if include_comparable:
        sleeves.append(
            {
                "sleeve_id": "independent",
                "returns": rng.normal(0, 0.01, 80).tolist(),
                "dates": dates,
            }
        )
    result = g.concentration_v2(active=active, hung_sleeves=sleeves)
    assert result["passed"] is False
    assert result["raw_unavailable_sleeves"] == ["no-overlap"]


def test_paired_increment_accepts_a_real_edge_and_rejects_a_null() -> None:
    rng = np.random.default_rng(21)
    n = 240
    baseline = [float(value) for value in rng.normal(0.0002, 0.01, n)]
    augmented = [value + 0.002 for value in baseline]
    accepted = g.paired_increment_verdict(baseline=baseline, augmented=augmented, seed=5)
    assert accepted["upgrade_accepted"] is True
    null = g.paired_increment_verdict(
        baseline=baseline, augmented=[value - 0.002 for value in baseline], seed=5
    )
    assert null["upgrade_accepted"] is False


def test_paired_increment_is_seed_stable() -> None:
    rng = np.random.default_rng(31)
    n = 240
    baseline = [float(value) for value in rng.normal(0.0, 0.01, n)]
    augmented = [value + 0.0015 for value in baseline]
    first = g.paired_increment_verdict(baseline=baseline, augmented=augmented, seed=9)
    again = g.paired_increment_verdict(baseline=baseline, augmented=augmented, seed=9)
    assert first["bootstrap"]["ci95_low"] == again["bootstrap"]["ci95_low"]
