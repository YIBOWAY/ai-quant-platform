import pandas as pd

from quant_system.research.wide_factor_set import build_wide_factor_values, frozen_factor_manifest


def test_frozen_27_objects_keep_default_definitions_and_duplicate_relationships():
    manifest = frozen_factor_manifest()
    objects = {x["factor_id"]: x for x in manifest["objects"]}
    assert len(objects) == 27
    assert objects["rsi"]["lookback"] == 14
    assert objects["paper_reversal_momentum_proxy_v2"]["lookback"] == 252
    assert objects["formula_e9ec66887a62cb89"]["lookback"] == 127
    assert objects["formula_a974503e7b46e115"]["duplicate_group"] == "log_range_30"
    assert objects["formula_90a6dd4e7a8f06c4"]["duplicate_group"] == "log_range_30"
    assert len(manifest["digest"]) == 64


def test_values_use_pre_membership_warmup_but_never_future_prices():
    days = pd.date_range("2014-11-03", periods=330, freq="B", tz="UTC")
    prices = pd.DataFrame(
        {
            "symbol": "A",
            "timestamp": days,
            "open": range(100, 430),
            "high": range(102, 432),
            "low": range(98, 428),
            "close": range(101, 431),
            "volume": 1000.0,
        }
    )
    membership = pd.DataFrame({"symbol": "A", "signal_ts": days[270:310]})
    original = build_wide_factor_values(prices, membership, calendar=days)
    perturbed = prices.copy()
    perturbed.loc[perturbed.timestamp > days[309], ["open", "high", "low", "close"]] *= 10
    again = build_wide_factor_values(perturbed, membership, calendar=days)
    pd.testing.assert_frame_equal(original, again)
    assert len(original[original.factor_id == "momentum"]) == 40
    assert original.signal_ts.min() == days[270]
    one = build_wide_factor_values(prices, membership, calendar=days, factor_ids=["momentum"])
    pd.testing.assert_frame_equal(
        one, original[original.factor_id == "momentum"].reset_index(drop=True)
    )


def test_missing_price_session_invalidates_complete_formula_window_without_fill():
    days = pd.date_range("2014-11-03", periods=80, freq="B", tz="UTC")
    prices = pd.DataFrame(
        {
            "symbol": "A",
            "timestamp": days,
            "open": range(100, 180),
            "high": range(102, 182),
            "low": range(98, 178),
            "close": range(101, 181),
            "volume": 1000.0,
        }
    )
    membership = pd.DataFrame({"symbol": "A", "signal_ts": days[50:70]})
    prices = prices[prices.timestamp != days[52]]
    result = build_wide_factor_values(prices, membership, calendar=days)
    five_day = result[result.factor_id == "formula_b66b213aacc0fc66"]
    assert not five_day.signal_ts.isin(days[52:58]).any()
    assert days[59] in set(five_day.signal_ts)
