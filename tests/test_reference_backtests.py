"""Hermetic behavior tests; fixture prices never enter the application data store."""

import json

import numpy as np
import pandas as pd
import pytest

from quant_system.factors.registry import build_factor_registry
from quant_system.research.reference_backtests import (
    _METRIC_KEYS,
    INITIAL_CASH,
    _metrics,
    _monthly_reference,
    build_reference_backtests,
    compute_reference_features,
    evaluate_predictions,
)
from quant_system.universe.registry import build_default_universe_registry


def fixture_prices(symbols=("QQQ", "AAA"), periods=45, *, varying=True):
    dates = pd.bdate_range("2021-01-04", periods=periods, tz="UTC")
    rows = []
    for index, symbol in enumerate(symbols):
        for position, day in enumerate(dates):
            price = 100 + index * 20 + position * 0.2 + np.sin(position) if varying else 100.0
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": day,
                    "open": price,
                    "close": price,
                    "high": price + 1,
                    "low": price - 1,
                    "volume": 1_000_000,
                    "provider": "futu",
                    "interval": "1d",
                    "price_adjustment": "qfq",
                }
            )
    return pd.DataFrame(rows)


def predictions(records):
    frame = pd.DataFrame(records, columns=["datetime", "instrument", "prediction"])
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    return frame.set_index(["datetime", "instrument"])["prediction"]


def test_features_reuse_each_registered_default_direction_and_preserve_unknowns():
    prices = fixture_prices(periods=290)
    result = compute_reference_features(prices)
    registry = build_factor_registry()
    assert list(result.columns) == registry.factor_ids()
    assert result.index.names == ["datetime", "instrument"]
    assert result.iloc[:2].isna().all().all()
    for factor_id in ("momentum", "rsi", "macd", "paper_reversal_momentum_proxy_v2"):
        factor = registry.create(factor_id)
        expected = factor.compute(prices).set_index(["signal_ts", "symbol"])["value"]
        expected.index.names = ["datetime", "instrument"]
        expected *= -1 if factor.direction == "lower_is_better" else 1
        if factor_id == "macd":
            closes = prices.set_index(["timestamp", "symbol"])["close"]
            closes.index.names = expected.index.names
            expected = expected / closes.reindex(expected.index)
        pd.testing.assert_series_equal(
            result[factor_id], expected.reindex(result.index), check_names=False
        )
    assert result.attrs["factors"]["rsi"]["lookback"] == 14
    assert result.attrs["factors"]["macd"]["lookback"] == 12
    assert result.attrs["factors"]["paper_reversal_momentum_proxy_v2"]["lookback"] == 252
    assert result["paper_reversal_momentum_proxy_v2"].isna().sum() > result["momentum"].isna().sum()


def test_missing_bar_preserves_calendar_lookbacks_and_unavailable_rows():
    prices = fixture_prices(periods=45)
    dates = pd.DatetimeIndex(sorted(prices.timestamp.unique()))
    prices = prices.loc[~((prices.symbol == "AAA") & (prices.timestamp == dates[20]))]
    result = compute_reference_features(prices)
    assert (dates[20], "AAA") in result.index
    assert result.loc[(dates[20], "AAA")].isna().all()
    assert pd.isna(result.loc[(dates[40], "AAA"), "momentum"])
    assert pd.isna(result.loc[(dates[30], "AAA"), "rsi"])


def test_cross_asset_macd_is_invariant_to_price_denomination():
    prices = fixture_prices(periods=60)
    original = compute_reference_features(prices)
    scaled = prices.copy()
    scaled.loc[scaled.symbol == "AAA", ["open", "close", "high", "low"]] *= 10
    changed = compute_reference_features(scaled)
    pd.testing.assert_series_equal(original["macd"], changed["macd"])


def test_signal_close_cannot_buy_same_day_open_and_benchmark_pays_same_entry_cost():
    prices = fixture_prices(periods=4, varying=False)
    dates = sorted(prices.timestamp.unique())
    # A tenfold overnight gap must not be captured by a signal only known at day-one close.
    prices.loc[(prices.symbol == "AAA") & (prices.timestamp == dates[0]), ["open", "close"]] = 10
    score = predictions([(dates[0], "AAA", -1.0), (dates[0], "QQQ", -2.0)])
    result = evaluate_predictions(prices, score, start="2021-01-05", end="2021-01-07", top_n=1)
    expected = 1 / (1.0005 * 1.0001) - 1
    assert result["status"] == "available"
    assert result["metrics"]["total_return"] == pytest.approx(expected)
    assert result["benchmark_metrics"]["total_return"] == pytest.approx(expected)
    assert result["curve"][0]["date"] == "2021-01-05"
    assert result["sample_counts"]["fills"] == result["sample_counts"]["benchmark_fills"] == 1
    assert result["costs"]["commission"] > 0 and result["costs"]["slippage"] > 0
    assert result["daily_returns"][0] == pytest.approx(expected)
    assert result["daily_returns"][1:] == [0.0, 0.0]
    assert len(result["daily_returns"]) == len(result["return_dates"]) == len(result["curve"])
    json.dumps(result, allow_nan=False)


def test_unavailable_unselected_asset_cannot_delay_the_next_market_session():
    prices = fixture_prices(("QQQ", "AAA", "BBB"), periods=4, varying=False)
    prices = prices.loc[~((prices.symbol == "BBB") & (prices.timestamp == _day("2021-01-05")))]
    score = predictions(
        [
            ("2021-01-04", "AAA", 1.0),
            ("2021-01-04", "BBB", np.nan),
        ]
    )
    result = evaluate_predictions(prices, score, start="2021-01-05", end="2021-01-07", top_n=1)
    assert result["curve"][0]["date"] == "2021-01-05"
    assert result["sample_counts"]["sessions"] == 3


def _day(value):
    return pd.Timestamp(value, tz="UTC")


def test_reference_rows_attach_the_active_metrics_sibling_block():
    universe = build_default_universe_registry().get("etf").normalized_symbols()
    prices = fixture_prices(universe, periods=200)
    days = pd.DatetimeIndex(sorted(prices.timestamp.unique()))
    result = build_reference_backtests(
        prices, start=days[30].date().isoformat(), end=days[-1].date().isoformat()
    )
    row = next(item for item in result["rows"] if item["key"] == "strategy:cross_sectional_top_n")
    block = row["active_metrics"]
    assert block["schema_version"] == "active_metrics_v1"
    assert block["status"] == "ready"
    assert block["disclosure"]["evaluation_only"] is True
    assert block["disclosure"]["dsr_family_member"] is False
    assert block["n_observations"] >= 126
    assert block["vs_benchmark"]["benchmark_symbol"] == "QQQ"
    assert block["vs_benchmark"]["sharpe_se_ci"]["sharpe"] is not None
    assert block["vs_peer"] is None
    assert set(row["metrics"]) == set(_METRIC_KEYS)
    assert "active_metrics" not in row["metrics"]
    json.dumps(result, allow_nan=False)


def test_unavailable_reference_shape_keeps_the_active_block_empty():
    from quant_system.research.reference_backtests import _empty

    assert _empty("sealed")["active_metrics"] is None
    assert set(_empty("sealed")["metrics"]) == set(_METRIC_KEYS)


@pytest.mark.parametrize("missing_symbol", ["AAA", "QQQ"])
def test_missing_next_execution_or_benchmark_bar_is_not_silently_skipped(missing_symbol):
    prices = fixture_prices(periods=4)
    prices = prices.loc[
        ~((prices.symbol == missing_symbol) & (prices.timestamp == _day("2021-01-05")))
    ]
    score = predictions([("2021-01-04", "AAA", 1.0)])
    with pytest.raises(ValueError, match="prices_missing"):
        evaluate_predictions(prices, score, start="2021-01-05", end="2021-01-07", top_n=1)


def test_last_signal_without_next_observed_open_is_not_executed():
    prices = fixture_prices(periods=4)
    last = prices.timestamp.max()
    result = evaluate_predictions(
        prices, predictions([(last, "AAA", 9.0)]), start="2021-01-04", end="2021-01-07", top_n=1
    )
    assert result["status"] == "unavailable"
    assert result["metrics"]["total_return"] is None
    assert result["metrics"]["sharpe"] is None


def test_zero_return_is_known_but_zero_volatility_sharpe_is_undefined():
    curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=3, tz="UTC"),
            "equity": [INITIAL_CASH] * 3,
        }
    )
    result = _metrics(curve, pd.DataFrame(), INITIAL_CASH)
    assert result["total_return"] == 0
    assert result["volatility"] == 0
    assert result["sharpe"] is None
    unknown = _metrics(curve.iloc[:0], pd.DataFrame(), INITIAL_CASH)
    assert unknown["total_return"] is None
    assert unknown["sharpe"] is None


def test_provenance_duplicates_and_invalid_predictions_are_rejected():
    prices = fixture_prices(periods=4)
    score = predictions([("2021-01-04", "AAA", 1.0)])
    with pytest.raises(ValueError, match="real_provider"):
        evaluate_predictions(
            prices.assign(provider="sample"), score, start="2021-01-04", end="2021-01-07", top_n=1
        )
    with pytest.raises(ValueError, match="duplicate_bars"):
        evaluate_predictions(
            pd.concat([prices, prices.iloc[:1]]),
            score,
            start="2021-01-04",
            end="2021-01-07",
            top_n=1,
        )
    with pytest.raises(ValueError, match="nonfinite_prediction"):
        evaluate_predictions(prices, score * np.inf, start="2021-01-04", end="2021-01-07", top_n=1)


def test_reference_portfolios_do_not_use_sample_or_write_trial_ledger(monkeypatch):
    from quant_system.research.trials import TrialsLedger

    monkeypatch.setattr(
        TrialsLedger, "append", lambda *_, **__: pytest.fail("unexpected trial write")
    )
    universe = build_default_universe_registry().get("etf").normalized_symbols()
    prices = fixture_prices(universe, periods=45, varying=False)
    result = build_reference_backtests(prices, start="2021-02-15", end="2021-03-05")
    rows = {row["key"]: row for row in result["rows"]}
    assert result["source"] == "futu" and result["benchmark_symbol"] == "QQQ"
    assert rows["strategy:cross_sectional_top_n"]["metrics"]["total_return"] == 0
    assert rows["strategy:cross_sectional_top_n"]["metrics"]["sharpe"] is None
    assert rows["factor:paper_reversal_momentum_proxy_v2"]["status"] == "unavailable"
    assert rows["strategy:drift_regime_reversal_top_n_v1"]["status"] == "unavailable"
    assert rows["strategy:reversal_momentum"]["status"] == "unavailable"
    assert len(rows) == 11
    json.dumps(result, allow_nan=False)


def test_monthly_replication_is_labelled_gross_monthly_and_never_appends_trial(monkeypatch):
    from quant_system.research.trials import TrialsLedger

    monkeypatch.setattr(
        TrialsLedger, "append", lambda *_, **__: pytest.fail("unexpected trial write")
    )
    frame = fixture_prices(("QQQ", "AAA", "BBB"), periods=600)
    result = _monthly_reference(frame, start="2022-06-01", end="2023-02-28")
    assert result["status"] == "available"
    assert result["frequency"] == "monthly" and result["costs"] is None
    assert result["metrics"]["turnover"] is None
    assert "借券" in result["reason"]
    assert result["by_year"]
    assert all(point["equity"] > 0 and point["benchmark"] > 0 for point in result["curve"])
    json.dumps(result, allow_nan=False)
