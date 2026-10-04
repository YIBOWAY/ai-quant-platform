"""Artificial fixtures only; these tests are not market or alpha evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "phase3_etf_research", Path(__file__).parents[1] / "scripts/phase3_etf_research.py"
)
etf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(etf)


def spec():
    return {
        **etf.FIXED,
        "history_start": "2019-01-01",
        "evaluation_start": "2021-01-01",
        "evaluation_end": "2021-04-30",
        "splits": {"artificial": ["2021-01-01", "2021-04-30"]},
    }


def artificial_prices():
    """Known deterministic artificial data carrying the provider schema under test."""
    sessions = etf.expected_sessions(spec()["history_start"], spec()["evaluation_end"])
    rng = np.random.default_rng(25092026)
    rows = []
    for index, symbol in enumerate(etf.SYMBOLS):
        closes = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.007 + index * 0.001, len(sessions))))
        rows.extend(
            {
                "timestamp": day,
                "symbol": symbol,
                "open": value * 0.999,
                "high": value * 1.002,
                "low": value * 0.998,
                "close": value,
                "volume": 1000000,
                "provider": "futu",
                "price_adjustment": "qfq",
                "interval": "1d",
            }
            for day, value in zip(sessions, closes, strict=True)
        )
    return pd.DataFrame(rows)


def test_frozen_protocol_rejects_changed_parameters_and_digest(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps({"family_b": spec()}))
    digest = etf.sha256(path)
    assert etf.read_preregistration(path, digest)["symbols"] == list(etf.SYMBOLS)
    bad = spec()
    bad["momentum_months"] = 6
    path.write_text(json.dumps({"family_b": bad}))
    with pytest.raises(ValueError, match="digest_mismatch"):
        etf.read_preregistration(path, digest)
    with pytest.raises(ValueError, match="scope_mismatch:momentum_months"):
        etf.read_preregistration(path, etf.sha256(path))


def test_missing_symbol_or_one_session_is_explicit_and_cannot_run():
    prices = artificial_prices()
    for missing in (prices.loc[prices.symbol != "EEM"], prices.drop(index=1)):
        _, coverage = etf.input_coverage(missing, spec())
        assert coverage["status"] == "waiting_data"
        assert sum(row["missing_count"] for row in coverage["inventory"]) > 0
        with pytest.raises(ValueError, match="complete_universe_prices_required"):
            etf.build_schedules(missing, spec())


def test_no_future_quote_changes_past_signals_or_risk_weights():
    prices = artificial_prices()
    targets, records = etf.build_schedules(prices, spec())
    altered = prices.copy()
    future = altered.timestamp >= pd.Timestamp("2021-03-01", tz="UTC")
    altered.loc[future, ["open", "high", "low", "close"]] *= 3
    second, second_records = etf.build_schedules(altered, spec())
    for candidate in etf.CANDIDATES:
        past = {day: value for day, value in targets[candidate].items() if day.month < 3}
        assert past == {day: value for day, value in second[candidate].items() if day.month < 3}
        assert records[candidate][0] == second_records[candidate][0]
        assert all(row["signal_date"] < row["trade_date"] for row in records[candidate])


def test_erc_is_equal_risk_not_equal_capital():
    rng = np.random.default_rng(9)
    returns = pd.DataFrame(rng.normal(size=(252, 3)), columns=["a", "b", "c"])
    returns *= [0.01, 0.02, 0.04]
    weights, evidence = etf.equal_risk_weights(returns)
    assert sum(weights.values()) == pytest.approx(1)
    assert weights["a"] > weights["b"] > weights["c"]
    assert evidence["maximum_budget_error"] < 1e-6
    assert list(evidence["risk_contribution_fractions"].values()) == pytest.approx([1 / 3] * 3)


def test_zero_variance_does_not_fall_back_to_equal_weights():
    with pytest.raises(ValueError, match="zero_or_invalid_variance"):
        etf.equal_risk_weights(pd.DataFrame({"a": np.ones(252), "b": np.arange(252)}))


def test_strategy_does_not_replace_failed_trend_with_another_asset():
    prices = artificial_prices()
    for symbol in etf.SYMBOLS:
        mask = prices.symbol == symbol
        declining = 100 * 0.998 ** np.arange(mask.sum())
        for column in ("open", "high", "low", "close"):
            prices.loc[mask, column] = declining
    targets, _ = etf.build_schedules(prices, spec())
    assert all(
        weights == {} for candidate in etf.CANDIDATES for weights in targets[candidate].values()
    )
    assert all(len(weights) == 10 for weights in targets["EW"].values())


def test_original_engine_charges_cost_pressure_without_changing_targets():
    prices = artificial_prices()
    targets, _ = etf.build_schedules(prices, spec())
    evaluation = prices.loc[prices.timestamp >= pd.Timestamp("2021-01-01", tz="UTC")]
    base = etf.replay(evaluation, targets["EW"], 1)
    pressure = etf.replay(evaluation, targets["EW"], 3)
    assert len(base.trade_blotter) > 0
    assert pressure.equity_curve.equity.iloc[-1] < base.equity_curve.equity.iloc[-1]
    assert set(base.trade_blotter.slippage_bps) == {5.0}
    assert set(pressure.trade_blotter.slippage_bps) == {15.0}
    with pytest.raises(ValueError, match="unregistered_cost_multiplier"):
        etf.replay(evaluation, targets["EW"], 4)


def test_caps_and_volatility_target_only_reduce_exposure_and_never_refill_cash():
    rng = np.random.default_rng(42)
    returns = pd.DataFrame(rng.normal(0, 0.07, size=(252, 2)), columns=["a", "b"])
    weights, risk = etf.constrained_risk_weights(returns)
    assert all(0 < weight <= 0.25 for weight in weights.values())
    assert sum(weights.values()) < 0.5
    assert risk["predicted_annual_volatility"] <= 0.1 + 1e-12
    assert risk["scale_down"] < 1
    single, single_risk = etf.constrained_risk_weights(returns[["a"]] * 0.01)
    assert single == {"a": pytest.approx(0.25)}
    assert single_risk["cash_weight"] == pytest.approx(0.75)


def test_holm_keeps_all_three_frozen_hypotheses_in_the_family():
    adjusted = etf.holm_adjusted({"B_MOM": 0.01, "B_SMA": 0.02, "B_COMBINED": 0.06})
    assert adjusted == {"B_MOM": 0.03, "B_SMA": 0.04, "B_COMBINED": 0.06}
    with pytest.raises(ValueError, match="complete_preregistered_family_required"):
        etf.holm_adjusted({"B_MOM": 0.01})
    assert set(etf.holm_adjusted({"B_MOM": None, "B_SMA": 0.01, "B_COMBINED": 0.02}).values()) == {
        None
    }


def test_active_mean_null_is_paired_and_does_not_call_negative_result_significant():
    dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="UTC")
    common = np.random.default_rng(21).normal(0.001, 0.01, len(dates))
    curve = pd.DataFrame(
        {
            "timestamp": dates,
            "equity": etf.INITIAL_CASH * np.cumprod(1 + common - 0.001),
            "peer": etf.INITIAL_CASH * np.cumprod(1 + common),
        }
    )
    negative = etf.paired_active_mean_test(curve)
    assert negative["p"] == 1
    assert negative["mean_daily_active_return"] == pytest.approx(-0.001)
    curve["equity"] = etf.INITIAL_CASH * np.cumprod(1 + common + 0.001)
    assert etf.paired_active_mean_test(curve)["p"] <= 0.001


def test_correlated_and_opposing_assets_still_satisfy_original_erc_equations():
    rng = np.random.default_rng(101)
    common = rng.normal(size=252)
    returns = pd.DataFrame(
        {
            "a": common * 0.01,
            "b": common * 0.02 + rng.normal(0, 0.001, 252),
            "c": -common * 0.005 + rng.normal(0, 0.003, 252),
        }
    )
    weights, risk = etf.equal_risk_weights(returns)
    vector = np.array([weights[name] for name in returns])
    covariance = returns.cov().to_numpy()
    covariance = covariance * 0.9 + np.diag(np.diag(covariance)) * 0.1
    contributions = vector * (covariance @ vector)
    assert contributions / contributions.sum() == pytest.approx(np.full(3, 1 / 3), abs=1e-6)
    assert risk["maximum_budget_error"] < 1e-6
