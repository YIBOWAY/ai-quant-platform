"""Sealed prices exercise study protocols; no provider or persistence is called."""

import json

import numpy as np
import pandas as pd
import pytest

from quant_system.research.profile_backtests import run_formula_profile, run_profile
from quant_system.research.study_profiles import STOCKS, TECHNOLOGY, list_study_profiles


def prices_for(symbols, start="2019-01-01", end="2020-03-06"):
    dates = pd.bdate_range(start, end, tz="UTC")
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "timestamp": date,
                "open": 100.0,
                "close": 100.0,
                "volume": 1_000_000,
                "provider": "futu",
                "price_adjustment": "qfq",
                "interval": "1d",
            }
            for symbol in symbols
            for date in dates
        ]
    )


def test_month_end_signal_uses_next_real_open_not_month_end_or_weekend():
    prices = prices_for(["SPY", "SHY"])
    # February starts on a weekend. The January close is observed at 200,
    # and the first February open is 300: the strategy cannot earn this gap.
    prices.loc[(prices.symbol == "SPY") & (prices.timestamp >= "2020-01-31"), "close"] = 200.0
    prices.loc[(prices.symbol == "SPY") & (prices.timestamp >= "2020-02-03"), ["open", "close"]] = (
        300.0
    )
    result = run_profile(prices, "spy_sma10", start="2020-01-31", end="2020-02-05")
    assert result["status"] == "available"
    assert result["signals"][0]["signal_date"] == "2020-01-31"
    assert result["signals"][0]["trade_date"] == "2020-02-03"
    assert result["trades"][0]["requested_price"] == 300.0
    assert result["trades"][0]["date"] == "2020-02-03"
    assert result["metrics"]["total_return"] == pytest.approx(1 / (1.0005 * 1.0001) - 1)
    assert result["gross_metrics"]["total_return"] == pytest.approx(0)
    assert result["curve"][0]["equity"] == 100_000


def test_monthly_stock_ranking_and_peer_share_the_same_complete_history_universe():
    prices = prices_for([*TECHNOLOGY, "QQQ"], end="2020-04-03")
    for index, symbol in enumerate(TECHNOLOGY):
        mask = prices.symbol == symbol
        value = 100 * np.exp(np.arange(mask.sum()) * (index + 1) / 10_000)
        prices.loc[mask, ["open", "close"]] = np.column_stack((value, value))
    # CRM's huge recent gain must not admit its incomplete listing history,
    # either into the strategy rank or into the comparison peer.
    prices = prices.loc[~((prices.symbol == "CRM") & (prices.timestamp < "2019-08-01"))]
    result = run_profile(prices, "technology_momentum_12_2", start="2020-01-01", end="2020-03-06")
    assert result["status"] == "available"
    first = next(s for s in result["signals"] if s["ready"])
    assert first["trade_date"] == "2020-02-03"
    assert set(first["targets"]) == {"META", "AVGO", "ORCL"}
    assert "CRM" not in first["eligible_symbols"]
    peer_first = next(s for s in result["peer_signals"] if s["targets"])
    assert peer_first["targets"] == {s: 1 / 8 for s in TECHNOLOGY if s != "CRM"}
    assert result["peer_metrics"] != result["benchmark_metrics"]
    assert result["eligibility"]["peer_uses_strategy_eligible_set"] is True


def test_multifactor_ranks_use_equal_scales_and_ignore_future_prices():
    prices = prices_for([*STOCKS, "SPY"], end="2020-04-03")
    for index, symbol in enumerate(STOCKS):
        mask = prices.symbol == symbol
        x = np.arange(mask.sum())
        value = 100 * np.exp(x * (index + 1) / 100_000 + np.sin(x) * (25 - index) / 10_000)
        prices.loc[mask, ["open", "close"]] = np.column_stack((value, value))
    before = run_profile(prices, "stocks_price_multifactor", start="2020-01-01", end="2020-03-06")
    changed = prices.copy()
    changed.loc[changed.timestamp > "2020-02-10", ["open", "close"]] *= 20
    after = run_profile(changed, "stocks_price_multifactor", start="2020-01-01", end="2020-03-06")
    assert before["status"] == after["status"] == "available"
    first = next(s for s in before["signals"] if s["ready"])
    assert first == next(s for s in after["signals"] if s["ready"])
    assert len(first["targets"]) == 5
    for score in first["scores"]:
        ranks = [score[k] for k in ("momentum_rank", "low_vol_rank", "reversal_rank")]
        assert all(0 < rank <= 1 for rank in ranks)
        assert score["score"] == pytest.approx(np.mean(ranks))
    # Absolute per-security price units cannot change return/volatility ranks.
    scaled = prices.copy()
    scaled.loc[scaled.symbol == STOCKS[-1], ["open", "close"]] *= 1000
    scaled_result = run_profile(
        scaled, "stocks_price_multifactor", start="2020-01-01", end="2020-03-06"
    )
    assert [s["targets"] for s in scaled_result["signals"]] == [
        s["targets"] for s in before["signals"]
    ]


def test_profiles_freeze_all_nine_adaptations_and_bounded_static_stock_lists():
    profiles = list_study_profiles()
    assert len(profiles) == 9
    assert len(set(STOCKS)) == 24 and "XLV" not in STOCKS
    assert len(TECHNOLOGY) == 9
    assert all(p["sources"] and p["limitations"] for p in profiles)
    profiles[0]["symbols"].clear()
    assert len(list_study_profiles()[0]["symbols"]) == 9


@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
def test_r2_wilder_pullback_entry_and_strength_exit_occur_at_next_open(symbol):
    prices = prices_for([symbol], end="2019-11-15")
    values = np.r_[np.linspace(100, 200, len(prices) - 6), [199, 198, 197, 205, 206, 207]]
    prices["close"] = values
    prices["open"] = values
    dates = prices.timestamp.tolist()
    prices.loc[prices.timestamp == dates[-3], "open"] = 198
    result = run_profile(prices, symbol.lower() + "_r2", start=dates[-6], end=dates[-1])
    assert result["status"] == "available"
    assert [(t["date"], t["side"]) for t in result["trades"]] == [
        (dates[-3].date().isoformat(), "buy"),
        (dates[-2].date().isoformat(), "sell"),
    ]
    assert result["trades"][0]["requested_price"] == 198
    entry = next(s for s in result["signals"] if s["targets"])
    rsi = entry["scores"][0]
    assert rsi["rsi_day1"] < 65 and rsi["rsi_day1"] > rsi["rsi_day2"] > rsi["rsi2"]
    assert entry["signal_date"] == dates[-4].date().isoformat()
    assert 0 < result["average_risk_exposure"] < 0.5


def test_five_asset_defense_redirects_each_failed_slot_without_increasing_risk_weights():
    symbols = ["SPY", "EFA", "IEF", "VNQ", "DBC", "SHY"]
    prices = prices_for(symbols)
    result = run_profile(
        prices, "etf_relative_momentum_trend", start="2020-02-01", end="2020-03-06"
    )
    assert result["status"] == "available"
    assert all(s["targets"] == {"SHY": 1.0} for s in result["signals"])
    assert result["average_risk_exposure"] == 0
    assert result["average_exposure"] > 0.99
    assert result["peer_signals"][0]["targets"] == {s: 0.2 for s in symbols if s != "SHY"}
    plain = run_profile(prices, "etf_relative_momentum", start="2020-02-01", end="2020-03-06")
    assert plain["status"] == "available"
    assert set(plain["signals"][0]["targets"]) == {"DBC", "EFA", "IEF"}
    assert plain["average_risk_exposure"] > 0.99


def test_year_and_fixed_calendar_splits_chain_without_reinitializing_portfolio():
    prices = prices_for(["SPY", "SHY"], start="2023-01-02", end="2025-02-07")
    mask = prices.symbol == "SPY"
    values = 100 + np.arange(mask.sum()) * 0.1
    prices.loc[mask, ["open", "close"]] = np.column_stack((values, values))
    result = run_profile(prices, "spy_sma10", start="2024-12-02", end="2025-02-07")
    assert result["status"] == "available"
    splits = result["splits"]
    assert splits["train"]["status"] == "unavailable"
    val, test = [splits[s]["metrics"]["total_return"] for s in ("validation", "test")]
    assert (1 + val) * (1 + test) - 1 == pytest.approx(result["metrics"]["total_return"])
    assert [row["year"] for row in result["by_year"]] == [2024, 2025]


def test_formula_evaluation_keeps_calendar_gaps_and_same_peer_eligibility():
    prices = prices_for([*STOCKS, "SPY"], end="2020-03-06")
    # A missing session inside an otherwise sufficient history invalidates
    # that stock's complete window; compressing rows would falsely admit it.
    prices = prices.loc[~((prices.symbol == "CRM") & (prices.timestamp == "2019-08-15"))]
    result = run_formula_profile(
        prices,
        "$close / Ref($close, 20)",
        start="2020-02-01",
        end="2020-03-06",
        proposal_id="fixed-one",
        title="固定假说",
    )
    assert result["status"] == "available"
    assert result["profile"]["registered"] is False
    assert result["profile"]["hypothesis_status"] == "unverified"
    assert all("CRM" not in signal["eligible_symbols"] for signal in result["signals"])
    assert all("CRM" not in signal["targets"] for signal in result["peer_signals"])
    assert len(result["signals"][0]["targets"]) == 5
    assert result["profile"]["formula_lookback"] == 21
    assert result["profile"]["eligibility_window"] == 252
    invalid = run_formula_profile(
        prices,
        "__import__('os')",
        start="2020-02-01",
        end="2020-03-06",
        proposal_id="invalid",
        title="非法表达式",
    )
    assert invalid["status"] == "failed" and invalid["curve"] == []
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("profile", list_study_profiles(), ids=lambda p: p["id"])
def test_all_fixed_profiles_return_json_without_trial_writes(profile, monkeypatch):
    from quant_system.research.trials import TrialsLedger

    monkeypatch.setattr(TrialsLedger, "append", lambda *a, **k: pytest.fail("trial write"))
    symbols = sorted(set(profile["symbols"]) | {profile["benchmark_symbol"]})
    result = run_profile(prices_for(symbols), profile["id"], start="2020-02-01", end="2020-03-06")
    assert result["status"] == "available"
    assert set(result["splits"]) == {"train", "validation", "test"}
    assert all(set(point) == {"date", "equity", "benchmark", "peer"} for point in result["curve"])
    assert 0 <= result["average_exposure"] <= 1.00000001
    assert 0 <= result["average_risk_exposure"] <= 1.00000001
    assert result["costs"]["commission_bps"] == 1 and result["costs"]["slippage_bps"] == 5
    json.dumps(result, allow_nan=False)


def test_profile_result_carries_the_active_metrics_sibling_block():
    prices = prices_for(["SPY", "SHY"], start="2019-01-02", end="2020-03-06")
    mask = prices.symbol == "SPY"
    path = np.arange(mask.sum())
    values = 100 * np.exp(path * 0.0006 + np.sin(path) * 0.01)
    prices.loc[mask, ["open", "close"]] = np.column_stack((values, values))
    result = run_profile(prices, "spy_sma10", start="2019-06-03", end="2020-03-06")
    assert result["status"] == "available"
    block = result["active_metrics"]
    disclosure = block["disclosure"]
    assert block["schema_version"] == "active_metrics_v1"
    assert block["status"] == "ready"
    assert disclosure["evaluation_only"] is True
    assert disclosure["dsr_family_member"] is False
    assert disclosure["tradeable_claim"] is False
    assert disclosure["annualization_factor"] == 252
    assert disclosure["benchmark_definition"].startswith("per-profile benchmark_symbol")
    assert block["vs_benchmark"]["benchmark_symbol"] == "SPY"
    assert block["vs_benchmark"]["information_ratio"]["value"] is not None
    assert block["vs_benchmark"]["block_bootstrap"]["status"] == "ready"
    assert block["vs_peer"]["reference_kind"] == "peer"
    assert len(result["metrics"]) == 8 and "active_metrics" not in result["metrics"]
    assert all(set(point) == {"date", "equity", "benchmark", "peer"} for point in result["curve"])
    json.dumps(result, allow_nan=False)

    failed = run_profile(prices_for(["SPY"]), "spy_sma10", start="2020-01-31", end="2020-02-05")
    assert failed["status"] == "failed" and failed["active_metrics"] is None


def test_held_asset_missing_bar_fails_and_never_marks_it_as_zero():
    prices = prices_for(["SPY", "SHY"])
    prices = prices.loc[~((prices.symbol == "SHY") & (prices.timestamp == "2020-02-04"))]
    result = run_profile(prices, "spy_sma10", start="2020-02-01", end="2020-03-06")
    assert result["status"] == "failed"
    assert "missing mark prices" in result["reason"] and "SHY" in result["reason"]
    assert result["curve"] == [] and result["metrics"]["total_return"] is None


def test_latest_month_spike_is_skipped_and_partial_final_month_has_no_signal():
    prices = prices_for([*TECHNOLOGY, "QQQ"])
    spiked = prices.copy()
    spiked.loc[
        (spiked.symbol == "CRM") & (spiked.timestamp >= "2020-01-01"), ["open", "close"]
    ] *= 10
    base = run_profile(prices, "technology_momentum_12_2", start="2020-02-01", end="2020-02-14")
    after = run_profile(spiked, "technology_momentum_12_2", start="2020-02-01", end="2020-02-14")
    assert base["signals"] == after["signals"]
    assert len(base["signals"]) == 1 and base["signals"][0]["signal_date"] == "2020-01-31"
    no_next_open = run_profile(prices, "spy_sma10", start="2020-01-31", end="2020-01-31")
    assert no_next_open["status"] == "failed"  # The supplied frame lacks required SHY.
    complete = run_profile(
        prices_for(["SPY", "SHY"]), "spy_sma10", start="2020-01-31", end="2020-01-31"
    )
    assert complete["status"] == "unavailable" and complete["trades"] == []
