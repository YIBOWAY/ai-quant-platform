"""Hand-fixed artificial algebra only; no sampled calibration outcome is inspected."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.research.profile_backtests import _ScheduledTargets

SPEC = importlib.util.spec_from_file_location(
    "calibrate_admission_semantics",
    Path(__file__).resolve().parents[1] / "scripts/calibrate_admission_semantics.py",
)
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


@pytest.mark.parametrize("frequency", [1, 2, 4])
@pytest.mark.parametrize("multiplier", [1, 2, 3])
@pytest.mark.parametrize("cost_model", ["proportional_bps", "qlib_combined_bps"])
def test_declared_cash_factors_match_actual_engine_with_fixed_hand_returns(
    frequency,
    multiplier,
    cost_model,
):
    net = np.array([0.01, 0.005, -0.02, 0.015, 0.0, 0.007])
    market = np.array([0.005, -0.001, 0.002, 0.004, -0.003, 0.001])
    dates = pd.bdate_range("2020-01-02", periods=len(net), tz="UTC")
    gross = calibration.gross_for_net(net, frequency, cost_model)
    expected = calibration.exact_cost_path(gross, frequency, multiplier, cost_model)
    prices, schedule, signals = calibration.artificial_prices(gross, market, frequency, dates)
    commission, slip = calibration.fee_rates(multiplier, cost_model)
    actual = BacktestEngine(
        BacktestConfig(
            initial_cash=10_000, commission_bps=commission * 10000, slippage_bps=slip * 10000
        )
    ).run(
        prices,
        _ScheduledTargets(
            {pd.Timestamp(day, tz="UTC"): target for day, target in schedule.items()}
        ),
    )
    np.testing.assert_allclose(actual.equity_curve.equity, expected["nav"], rtol=0, atol=1e-7)
    assert actual.trade_blotter.commission.sum() == pytest.approx(
        expected["commission"], rel=0, abs=1e-7
    )
    assert actual.trade_blotter.gross_value.sum() / 10_000 == pytest.approx(
        expected["turnover"], rel=0, abs=1e-12
    )
    assert all(row["signal_date"] < row["trade_date"] for row in signals)
    if multiplier == 1:
        np.testing.assert_allclose(expected["returns"], net, rtol=0, atol=1e-15)


def test_frequency_changes_real_cost_compensation_and_stress_without_changing_net_effect():
    desired = np.full(126, 0.0004)
    daily = calibration.gross_for_net(desired, 1)
    monthly = calibration.gross_for_net(desired, 21)
    assert daily.mean() > monthly.mean()
    daily_base = calibration.exact_cost_path(daily, 1)
    monthly_base = calibration.exact_cost_path(monthly, 21)
    np.testing.assert_allclose(daily_base["returns"], desired, rtol=0, atol=1e-15)
    np.testing.assert_allclose(monthly_base["returns"], desired, rtol=0, atol=1e-15)
    assert daily_base["turnover"] > monthly_base["turnover"]
    daily_stress = calibration.exact_cost_path(daily, 1, 3)
    monthly_stress = calibration.exact_cost_path(monthly, 21, 3)
    assert daily_stress["nav"][-1] < monthly_stress["nav"][-1]


def test_beta_one_point_two_has_nonzero_ordinary_active_but_zero_known_beta_alpha():
    market = np.array([0.01, -0.02, 0.005, 0.03])
    pure_beta = 1.2 * market
    np.testing.assert_allclose(pure_beta - market, 0.2 * market, rtol=0, atol=1e-17)
    np.testing.assert_array_equal(pure_beta - 1.2 * market, np.zeros(4))


def test_cell_scope_and_primary_role_are_fixed_before_results():
    rows = calibration.cells()
    assert len(rows) == 270
    assert [row["index"] for row in rows] == list(range(270))
    assert sum(row["primary_null"] for row in rows) == 54
    primary = [row for row in rows if row["primary_positive"]]
    assert len(primary) == 3
    assert {row["return_object"] for row in primary} == {
        "arithmetic_net_active",
        "net_total_return",
    }
    for row in primary:
        assert {key: row[key] for key in ("n", "rho", "frequency", "net_ir")} == {
            "n": 2016,
            "rho": 0.0,
            "frequency": 21,
            "net_ir": 2.0,
        }


def test_exact_binomial_bounds_include_uncertainty_even_at_zero_or_all_passes():
    none = calibration.interval(0, 500)
    all_ = calibration.interval(500, 500)
    assert none["lower"] == 0
    assert none["upper"] == pytest.approx(1 - 0.05 ** (1 / 500), abs=1e-15)
    assert all_["upper"] == 1
    assert all_["lower"] == pytest.approx(0.05 ** (1 / 500), abs=1e-15)


def test_failed_replicate_cannot_be_dropped_to_make_null_calibration_pass():
    cell = calibration.cells()[0]
    rows = [{"eligible": False}] * 499 + [{"status": "failed", "reasons": ["invalid"]}]
    result = calibration.summarize(cell, rows)
    assert result["replicates"] == 500
    assert result["eligible_rate"] == 0
    assert result["failed_replicates"] == 1
    assert result["primary_acceptance"] is False


@pytest.mark.parametrize("object_index", [0, 1, 2])
def test_hand_fixed_example_reaches_real_cost_seam_not_only_engine(tmp_path, object_index):
    cell = {**calibration.cells()[object_index * 90], "n": 6, "frequency": 2}
    desired = np.array([0.01, 0.005, -0.02, 0.015, 0.0, 0.007])
    market = np.array([0.005, -0.001, 0.002, 0.004, -0.003, 0.001])
    generated = {
        "total": desired,
        "gross": calibration.gross_for_net(desired, cell["frequency"], cell["cost_model"]),
        "market": market,
        "benchmark_gross": calibration.gross_for_net(market, 7, cell["cost_model"]),
    }
    result = calibration.verify_engine_case(cell, generated, tmp_path)
    assert result["engine_invocations"] == 4
    assert result["max_nav_error_usd"] < 1e-7


def saved_hand_rows(cell, holdout=False):
    return [
        {**calibration.row_identity(cell, index, holdout), "eligible": False, "status": "completed"}
        for index in range(500)
    ]


def save_hand_cached_summary(directory, cell, rows, holdout=False):
    label = f"cell-{cell['index']:03d}"
    data = directory / (label + ".jsonl")
    data.write_text("".join(json.dumps(row) + "\n" for row in rows))
    summary = {
        **calibration.summarize(cell, rows),
        "holdout": holdout,
        "source_digest": "ARTIFICIAL-CACHE-ONLY",
        "rows_sha256": calibration.sha(data),
    }
    path = directory / (label + ".summary.json")
    path.write_text(json.dumps(summary))
    return path


def test_completed_cache_cannot_import_main_as_independent_holdout(tmp_path):
    cell = calibration.cells()[0]
    save_hand_cached_summary(tmp_path, cell, saved_hand_rows(cell))
    with pytest.raises(ValueError, match="cached_split_seed_or_replicate_mismatch"):
        calibration.load_completed_cell(
            cell, holdout=True, output=tmp_path, expected_source="ARTIFICIAL-CACHE-ONLY"
        )


def test_completed_cache_recomputes_and_rejects_forged_acceptance(tmp_path):
    cell = calibration.cells()[0]
    path = save_hand_cached_summary(tmp_path, cell, saved_hand_rows(cell))
    loaded = calibration.load_completed_cell(
        cell, holdout=False, output=tmp_path, expected_source="ARTIFICIAL-CACHE-ONLY"
    )
    assert loaded["eligible"] == 0
    altered = json.loads(path.read_text())
    altered["eligible"] = 500
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="cached_summary_changed"):
        calibration.load_completed_cell(
            cell, holdout=False, output=tmp_path, expected_source="ARTIFICIAL-CACHE-ONLY"
        )


def test_cache_requires_all_500_replicates_and_preserves_partial_engine_files(tmp_path):
    cell = calibration.cells()[0]
    save_hand_cached_summary(tmp_path, cell, saved_hand_rows(cell)[:-1])
    with pytest.raises(ValueError, match="cached_count_invalid"):
        calibration.load_completed_cell(
            cell, holdout=False, output=tmp_path, expected_source="ARTIFICIAL-CACHE-ONLY"
        )
    directory = tmp_path / "engine" / "cell-000"
    directory.mkdir(parents=True)
    (directory / "partial.json").write_text('{"ARTIFICIAL":"partial"}')
    original = (directory / "partial.json").read_bytes()
    record = calibration.recover_engine_directory(
        directory, output=tmp_path, cell=cell, expected_source="ARTIFICIAL-CACHE-ONLY"
    )
    assert (Path(record["preserved"]) / "partial.json").read_bytes() == original
    assert record["prior_invocation_count"] is None
    assert not directory.exists()
    directory.mkdir()
    with pytest.raises(ValueError, match="repeated_engine_interruption"):
        calibration.recover_engine_directory(
            directory, output=tmp_path, cell=cell, expected_source="ARTIFICIAL-CACHE-ONLY"
        )


def test_recorded_engine_failure_cannot_be_silently_retried(tmp_path):
    cell = calibration.cells()[0]
    directory = tmp_path / "cell-000"
    directory.mkdir()
    (directory / "failure.json").write_text('{"reason":"ARTIFICIAL failure"}')
    with pytest.raises(ValueError, match="requires_diagnosis"):
        calibration.recover_engine_directory(
            directory, output=tmp_path, cell=cell, expected_source="ARTIFICIAL-CACHE-ONLY"
        )


def test_resume_three_failed_rows_stops_before_any_new_generator_call(tmp_path, monkeypatch):
    cell = calibration.cells()[0]
    rows = [
        {
            **calibration.row_identity(cell, i, False),
            "status": "failed",
            "eligible": False,
            "reasons": ["ARTIFICIAL persistent provider failure"],
        }
        for i in range(3)
    ]
    path = tmp_path / "cell-000.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = path.read_bytes()
    calls = []

    def forbidden_new_draw(*args, **kwargs):
        calls.append("generator")
        raise RuntimeError("ARTIFICIAL failure injection, no random or quality computation")

    monkeypatch.setattr(calibration, "sample", forbidden_new_draw)
    with pytest.raises(RuntimeError, match="three_errors_stop_for_diagnosis"):
        calibration.run_cell(
            cell,
            holdout=False,
            output=tmp_path,
            expected_source=calibration.digest(calibration.source_identity()),
        )
    assert calls == []
    assert path.read_bytes() == before


def test_preregistered_combined_engine_base_preserves_exact_fee_contract(tmp_path):
    # Regression for the engineering example that stopped run-v1 before MC.
    # Uses its already-frozen seed/cell; no effect, cutoff or tolerance changes.
    cell = calibration.cells()[181]
    result = calibration.engine_example(cell, tmp_path)
    assert result["engine_invocations"] == 4
    inputs = json.loads((tmp_path / "cell-181/input.json").read_text())
    assert inputs["base_result"]["costs"] == {"commission_bps": 6.0, "slippage_bps": 0.0}
