import pandas as pd
import pytest

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.metrics import calculate_performance_metrics
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.data.schema import normalize_ohlcv_dataframe


def _ohlcv_for_execution_test() -> pd.DataFrame:
    return normalize_ohlcv_dataframe(
        pd.DataFrame(
            {
                "symbol": ["SPY", "SPY", "SPY"],
                "timestamp": ["2024-01-02", "2024-01-03", "2024-01-04"],
                "open": [100.0, 110.0, 120.0],
                "high": [101.0, 111.0, 121.0],
                "low": [99.0, 109.0, 119.0],
                "close": [105.0, 115.0, 125.0],
                "volume": [1_000, 1_000, 1_000],
            }
        ),
        provider="test",
        interval="1d",
    )


def test_backtest_engine_executes_signal_on_next_bar_open_not_signal_close() -> None:
    ohlcv = _ohlcv_for_execution_test()
    signals = pd.DataFrame(
        {
            "symbol": ["SPY"],
            "signal_ts": [pd.Timestamp("2024-01-02", tz="UTC")],
            "tradeable_ts": [pd.Timestamp("2024-01-03", tz="UTC")],
            "score": [1.0],
        }
    )
    strategy = ScoreSignalStrategy(signals, top_n=1)
    engine = BacktestEngine(
        BacktestConfig(initial_cash=1_100, commission_bps=0, slippage_bps=0)
    )

    result = engine.run(ohlcv, strategy)

    assert len(result.trade_blotter) == 1
    fill = result.trade_blotter.iloc[0]
    assert fill["timestamp"] == pd.Timestamp("2024-01-03", tz="UTC")
    assert fill["fill_price"] == pytest.approx(110.0)
    assert fill["fill_price"] != pytest.approx(105.0)
    assert result.equity_curve.iloc[-1]["equity"] == pytest.approx(1_250.0)


def test_performance_metrics_include_return_risk_drawdown_and_turnover() -> None:
    equity_curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-02", periods=4, freq="B", tz="UTC"),
            "equity": [100.0, 110.0, 99.0, 120.0],
        }
    )
    trade_blotter = pd.DataFrame({"gross_value": [50.0, 25.0]})

    metrics = calculate_performance_metrics(
        equity_curve,
        trade_blotter,
        initial_cash=100.0,
        annualization_factor=252,
    )

    assert metrics.total_return == pytest.approx(0.20)
    assert metrics.max_drawdown == pytest.approx(0.10)
    assert metrics.turnover == pytest.approx(0.75)
    assert metrics.volatility > 0
