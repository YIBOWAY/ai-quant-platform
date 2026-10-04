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
    engine = BacktestEngine(BacktestConfig(initial_cash=1_100, commission_bps=0, slippage_bps=0))

    result = engine.run(ohlcv, strategy)

    assert len(result.trade_blotter) == 1
    fill = result.trade_blotter.iloc[0]
    assert fill["timestamp"] == pd.Timestamp("2024-01-03", tz="UTC")
    assert fill["fill_price"] == pytest.approx(110.0)
    assert fill["fill_price"] != pytest.approx(105.0)
    assert result.equity_curve.iloc[-1]["equity"] == pytest.approx(1_250.0)


def test_terminal_open_is_shared_by_equity_positions_and_attribution():
    ohlcv = _ohlcv_for_execution_test()
    signals = pd.DataFrame(
        {
            "symbol": ["SPY"],
            "signal_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "tradeable_ts": [pd.Timestamp("2024-01-02", tz="UTC")],
            "score": [1.0],
        }
    )
    result = BacktestEngine(
        BacktestConfig(
            initial_cash=1_000,
            commission_bps=0,
            slippage_bps=0,
            terminal_valuation="open",
        )
    ).run(ohlcv, ScoreSignalStrategy(signals, top_n=1))
    assert result.equity_curve.iloc[-1].equity == pytest.approx(1_200)
    assert result.positions.iloc[-1].close_price == 120
    assert result.positions.iloc[-1].market_value == pytest.approx(1_200)
    assert result.attribution.iloc[-1].contribution == pytest.approx(50)
    assert len(result.trade_blotter) == 1  # Valuation does not create a terminal sale.
    assert ohlcv.iloc[-1].close == 125  # Original quotes are never rewritten.


def test_engine_rejects_missing_execution_price_instead_of_ignoring_target():
    signals = pd.DataFrame(
        {
            "symbol": ["MISSING"],
            "signal_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "tradeable_ts": [pd.Timestamp("2024-01-02", tz="UTC")],
            "score": [1.0],
        }
    )
    with pytest.raises(ValueError, match="missing order generation price"):
        BacktestEngine(BacktestConfig()).run(
            _ohlcv_for_execution_test(), ScoreSignalStrategy(signals, top_n=1)
        )


def test_engine_rejects_missing_held_asset_mark():
    prices = _ohlcv_for_execution_test()
    prices.loc[prices.timestamp == prices.timestamp.max(), "symbol"] = "QQQ"
    signals = pd.DataFrame(
        {
            "symbol": ["SPY"],
            "signal_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "tradeable_ts": [pd.Timestamp("2024-01-02", tz="UTC")],
            "score": [1.0],
        }
    )
    with pytest.raises(ValueError, match="missing mark prices: SPY"):
        BacktestEngine(BacktestConfig()).run(prices, ScoreSignalStrategy(signals, top_n=1))


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


def test_metrics_include_first_session_loss_and_initial_capital_peak() -> None:
    curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-02", periods=2, tz="UTC"),
            "equity": [90.0, 99.0],
        }
    )
    metrics = calculate_performance_metrics(
        curve, pd.DataFrame(), initial_cash=100.0, annualization_factor=2
    )
    assert metrics.total_return == pytest.approx(-0.01)
    assert metrics.annualized_return == pytest.approx(-0.01)
    assert metrics.volatility == pytest.approx(0.1 * 2**0.5)
    assert metrics.sharpe == pytest.approx(0.0, abs=1e-12)
    assert metrics.max_drawdown == pytest.approx(0.1)


def test_performance_metrics_match_hand_calculated_return_and_sharpe() -> None:
    equity_curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-02", periods=5, freq="B", tz="UTC"),
            "equity": [100.0, 110.0, 132.0, 118.8, 124.74],
        }
    )

    metrics = calculate_performance_metrics(
        equity_curve,
        pd.DataFrame(),
        initial_cash=100.0,
        annualization_factor=4,
    )

    assert metrics.total_return == pytest.approx(0.2474)
    # The first marked session earned zero; it is still one observed period.
    returns = pd.Series([0.0, 0.10, 0.20, -0.10, 0.05])
    assert metrics.annualized_return == pytest.approx(1.2474 ** (4 / 5) - 1)
    assert metrics.volatility == pytest.approx(returns.std(ddof=0) * 2)
    assert metrics.sharpe == pytest.approx(returns.mean() / returns.std(ddof=0) * 2)


def test_performance_metrics_include_sortino_and_calmar() -> None:
    # returns: +10%, -10%, +21.21...%; downside deviation from -10% only
    equity_curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-02", periods=4, freq="B", tz="UTC"),
            "equity": [100.0, 110.0, 99.0, 120.0],
        }
    )

    metrics = calculate_performance_metrics(
        equity_curve,
        pd.DataFrame(),
        initial_cash=100.0,
        annualization_factor=252,
    )

    assert metrics.sortino is not None and metrics.sortino > metrics.sharpe
    assert metrics.calmar is not None and metrics.calmar > 0
    # calmar = annualized_return / max_drawdown
    assert metrics.calmar == pytest.approx(metrics.annualized_return / 0.10)
