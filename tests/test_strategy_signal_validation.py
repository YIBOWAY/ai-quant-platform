"""Sealed signal timing/component tests; real Qlib execution is checked separately."""

import numpy as np
import pandas as pd
import pytest

from quant_system.research import strategy_signal_validation as validation


def fixture(periods=4):
    signals = pd.date_range("2018-01-31", periods=periods, freq="ME")
    entries = signals + pd.offsets.BDay(1)
    records, rows = [], []
    for index, (signal, entry) in enumerate(zip(signals, entries, strict=True)):
        scores = []
        for order, symbol in enumerate(("AAA", "BBB", "CCC")):
            first, second = order / 2, ((order + index) % 3) / 4
            scores.append(
                {
                    "symbol": symbol,
                    "score": first + second,
                    "components": {"momentum": first, "low_vol": second},
                }
            )
            rows.append(
                {
                    "timestamp": entry,
                    "symbol": symbol,
                    "open": 100 + index * (order + 1),
                    "provider": "futu",
                    "price_adjustment": "qfq",
                }
            )
        records.append(
            {
                "signal_date": signal.strftime("%Y-%m-%d"),
                "trade_date": entry.strftime("%Y-%m-%d"),
                "scores": scores,
            }
        )
    result = {
        "status": "available",
        "profile": {"family": "factor_blend"},
        "definition": {
            "kind": "factor_blend",
            "rebalance": "monthly",
            "factors": [{"factor_id": "momentum"}, {"factor_id": "low_vol"}],
        },
        "end": entries[-1].strftime("%Y-%m-%d"),
        "signals": records,
    }
    return pd.DataFrame(rows), result


def test_labels_use_actual_entry_and_following_exit_with_last_period_unmatured():
    prices, result = fixture()
    pairs, components, coverage = validation.holding_pairs(prices, result)
    assert components == ["momentum", "low_vol"]
    assert len(pairs) == 9 and coverage["unmatured_periods"] == 1
    first = pairs.iloc[0]
    assert first.datetime == "2018-01-31" and first.label_start == "2018-02-01"
    assert first.label_end == "2018-03-01" and first.label == pytest.approx(0.01)
    assert first.label_start < first.label_end


def test_missing_prices_and_components_share_one_explicit_complete_sample():
    prices, result = fixture()
    prices.loc[3, "open"] = np.nan
    result["signals"][1]["scores"][1]["components"].pop("low_vol")
    pairs, _, coverage = validation.holding_pairs(prices, result)
    assert coverage["missing_price_rows"] == 2
    assert coverage["missing_component_rows"] == 1
    assert coverage["excluded_rows"] == 3 and len(pairs) == 6
    assert not pairs.isna().any().any()


def test_components_must_be_actual_additive_contributions():
    prices, result = fixture()
    result["signals"][0]["scores"][0]["score"] = 999
    with pytest.raises(ValueError, match="components_do_not_sum"):
        validation.holding_pairs(prices, result)


def test_a_long_actual_holding_interval_is_not_renamed_one_month():
    prices, result = fixture()
    result["signals"].pop(1)
    pairs, _, _ = validation.holding_pairs(prices, result)
    assert pairs.iloc[0].label_end == "2018-04-02"
    assert pairs.iloc[0].label == pytest.approx(0.02)


def test_component_correlation_uses_same_cross_sections_and_marks_constant_unknown():
    prices, result = fixture()
    pairs, components, _ = validation.holding_pairs(prices, result)
    result = validation.component_correlations(pairs, components)
    assert result["matrix"][0][0] == pytest.approx(1)
    assert result["periods"] == 3
    pairs["component:low_vol"] = 1
    result = validation.component_correlations(pairs, components)
    assert result["matrix"][1][1] is None
    assert result["matrix"][0][1] is None


def test_leave_one_out_uses_identical_rows_and_subtracts_contribution(monkeypatch):
    prices, result = fixture()
    pairs, components, _ = validation.holding_pairs(prices, result)
    observed = []

    def stats(frame, column="score"):
        observed.append((frame[["datetime", "instrument"]].copy(), frame[column].copy()))
        return {"rank_ic": float(frame[column].mean())}

    monkeypatch.setattr(validation, "signal_metrics", stats)
    output = validation.leave_one_out(pairs, components)
    assert observed[0][0].equals(observed[1][0])
    assert np.allclose(observed[1][1], pairs.score - pairs["component:momentum"])
    assert output[0]["paired_samples"] == len(pairs)
    assert output[0]["scope"] == "signal_increment_only_not_portfolio_return_increment"


def test_rolling_folds_slide_and_train_valid_labels_mature_before_next_partition():
    prices, result = fixture(periods=79)
    pairs, _, _ = validation.holding_pairs(prices, result)
    folds = list(validation.rolling_slices(pairs, "monthly"))
    assert len(folds) == 3
    for fold in folds:
        assert fold["train"].datetime.nunique() == 48
        assert fold["valid"].datetime.nunique() == 12
        assert fold["train"].label_end.max() < fold["valid"].datetime.min()
        assert fold["valid"].label_end.max() < fold["test"].datetime.min()
    assert folds[0]["train"].datetime.min() < folds[1]["train"].datetime.min()
    assert not set(folds[0]["test"].datetime) & set(folds[1]["test"].datetime)


def test_insufficient_history_never_claims_a_trained_ridge():
    prices, result = fixture()
    pairs, components, _ = validation.holding_pairs(prices, result)
    ridge = validation.ridge_challenger(pairs, components, result)
    assert ridge["status"] == "unavailable"
    assert ridge["folds"] == [] and ridge["matched_samples"] == 0
    assert ridge["replaces_strategy"] is False


@pytest.mark.parametrize("family", ["rsi_reversion", "index_trend"])
def test_single_index_timing_does_not_inherit_stock_ic(family):
    prices, result = fixture()
    result["profile"]["family"] = family
    output = validation.validate_signals(prices, result)
    assert output["status"] == "not_applicable"
    assert "score" not in output
