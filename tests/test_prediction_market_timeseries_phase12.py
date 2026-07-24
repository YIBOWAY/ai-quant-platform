import pytest

from quant_system.prediction_market.collector import seed_sample_history_dataset
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore
from quant_system.prediction_market.timeseries_backtest import (
    PredictionMarketTimeseriesBacktestConfig,
    run_prediction_market_timeseries_backtest,
)


def test_prediction_market_timeseries_backtest_has_stable_fixture_metrics(tmp_path) -> None:
    seed_sample_history_dataset(tmp_path)
    store = PredictionMarketSnapshotStore(tmp_path)

    result = run_prediction_market_timeseries_backtest(
        store=store,
        config=PredictionMarketTimeseriesBacktestConfig(
            provider="sample",
            min_edge_bps=200,
            capital_limit=1000,
            max_markets=10,
            max_legs=3,
            fee_bps=0,
            display_size_multiplier=1.0,
        ),
    )

    assert result.metrics.market_count == 2
    assert result.metrics.snapshot_count == 3
    assert result.metrics.market_snapshot_count == 6
    # The sample seed places three candidate edges exactly on the 200 bps line
    # (0.42+0.56 and 0.28+0.34+0.36 both sum to 0.98). The scanners include on
    # edge_bps >= min_edge_bps, so all three legitimately qualify -> 9 / 7 / 120.
    assert result.metrics.opportunity_count == 9
    assert result.metrics.simulated_trade_count == 7
    assert result.metrics.cumulative_estimated_profit == pytest.approx(120.0)
    assert [item.opportunity_count for item in result.daily_summary] == [3, 3, 3]
    assert result.sensitivity[-1].cumulative_estimated_profit == pytest.approx(90.0)


def test_prediction_market_timeseries_backtest_respects_time_filter(tmp_path) -> None:
    seed_sample_history_dataset(tmp_path)
    store = PredictionMarketSnapshotStore(tmp_path)

    result = run_prediction_market_timeseries_backtest(
        store=store,
        config=PredictionMarketTimeseriesBacktestConfig(
            provider="sample",
            start_time="2026-01-02T00:00:00Z",
            end_time="2026-01-02T00:00:00Z",
            min_edge_bps=200,
        ),
    )

    assert result.metrics.snapshot_count == 1
    assert result.metrics.market_snapshot_count == 2
    assert len(result.daily_summary) == 1
    assert result.daily_summary[0].date == "2026-01-02"


def test_prediction_market_timeseries_backtest_raises_when_history_missing(tmp_path) -> None:
    store = PredictionMarketSnapshotStore(tmp_path)

    with pytest.raises(ValueError, match="no historical"):
        run_prediction_market_timeseries_backtest(
            store=store,
            config=PredictionMarketTimeseriesBacktestConfig(provider="sample"),
        )
