import pandas as pd
import pytest
from pydantic import ValidationError

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig, RebalanceFrequency, TargetWeight
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.data.schema import normalize_ohlcv_dataframe


def _multiweek_ohlcv() -> pd.DataFrame:
    days = pd.bdate_range("2024-01-02", periods=15)  # ~3 ISO weeks
    rows = []
    for i, day in enumerate(days):
        spy = 100.0 + i  # steady uptrend
        qqq = 100.0 - i * 0.5  # steady downtrend -> 50/50 target drifts each bar
        for symbol, price in (("SPY", spy), ("QQQ", qqq)):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": day.strftime("%Y-%m-%d"),
                    "open": price,
                    "high": price + 1,
                    "low": price - 1,
                    "close": price + 0.5,
                    "volume": 1_000,
                }
            )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="test", interval="1d")


def _hold_spy_every_bar_signals() -> pd.DataFrame:
    days = pd.bdate_range("2024-01-02", periods=15)
    rows = []
    for day in days:
        for symbol in ("SPY", "QQQ"):
            rows.append(
                {
                    "symbol": symbol,
                    "signal_ts": pd.Timestamp(day, tz="UTC"),
                    "tradeable_ts": pd.Timestamp(day, tz="UTC"),
                    "score": 1.0,
                }
            )
    return pd.DataFrame(rows)


# --- rebalance frequency -----------------------------------------------------

def test_should_rebalance_gate_logic() -> None:
    every = BacktestEngine(BacktestConfig(rebalance_frequency=RebalanceFrequency.EVERY_BAR))
    weekly = BacktestEngine(BacktestConfig(rebalance_frequency=RebalanceFrequency.WEEKLY))
    monthly = BacktestEngine(BacktestConfig(rebalance_frequency=RebalanceFrequency.MONTHLY))

    mon = pd.Timestamp("2024-01-08", tz="UTC")  # ISO week 2
    same_week = pd.Timestamp("2024-01-10", tz="UTC")  # ISO week 2
    next_week = pd.Timestamp("2024-01-15", tz="UTC")  # ISO week 3
    next_month = pd.Timestamp("2024-02-01", tz="UTC")

    # First call (no prior rebalance) always rebalances.
    assert weekly._should_rebalance(mon, None) is True
    assert every._should_rebalance(same_week, mon) is True  # every bar
    assert weekly._should_rebalance(same_week, mon) is False  # same ISO week -> hold
    assert weekly._should_rebalance(next_week, mon) is True
    assert monthly._should_rebalance(next_week, mon) is False  # same month
    assert monthly._should_rebalance(next_month, mon) is True


def test_weekly_rebalance_only_trades_on_week_boundaries() -> None:
    ohlcv = _multiweek_ohlcv()
    signals = _hold_spy_every_bar_signals()

    every = BacktestEngine(
        BacktestConfig(initial_cash=10_000, commission_bps=0, slippage_bps=0)
    ).run(ohlcv, ScoreSignalStrategy(signals, top_n=2))
    weekly = BacktestEngine(
        BacktestConfig(
            initial_cash=10_000,
            commission_bps=0,
            slippage_bps=0,
            rebalance_frequency=RebalanceFrequency.WEEKLY,
        )
    ).run(ohlcv, ScoreSignalStrategy(signals, top_n=2))

    weekly_ts = pd.to_datetime(weekly.trade_blotter["timestamp"])
    # Trades occur only on distinct week-boundary days (one rebalance per ISO week).
    distinct_trade_days = set(weekly_ts)
    distinct_weeks = {(t.isocalendar()[0], t.isocalendar()[1]) for t in weekly_ts}
    assert len(distinct_trade_days) == len(distinct_weeks)
    # Each weekly trade is the FIRST bar of its ISO week in the data.
    all_days = pd.to_datetime(ohlcv["timestamp"]).sort_values().unique()
    first_of_week = {}
    for d in pd.to_datetime(all_days):
        key = (d.isocalendar()[0], d.isocalendar()[1])
        first_of_week.setdefault(key, d)
    for t in weekly_ts:
        assert t == first_of_week[(t.isocalendar()[0], t.isocalendar()[1])]
    # Every-bar trades strictly more often than weekly.
    assert len(every.trade_blotter) > len(weekly.trade_blotter)


# --- weight constraints ------------------------------------------------------

def _targets(weights: dict[str, float]) -> list[TargetWeight]:
    ts = pd.Timestamp("2024-01-03", tz="UTC")
    return [TargetWeight(timestamp=ts, symbol=s, target_weight=w) for s, w in weights.items()]


def test_max_weight_per_symbol_caps_targets() -> None:
    gen = OrderGenerator(BacktestConfig(max_weight_per_symbol=0.3))
    capped = gen._apply_weight_constraints({"SPY": 0.8, "QQQ": 0.1})
    assert capped == {"SPY": pytest.approx(0.3), "QQQ": pytest.approx(0.1)}


def test_sector_cap_scales_down_over_cap_sector() -> None:
    gen = OrderGenerator(
        BacktestConfig(sector_cap=0.5, sector_map={"SPY": "tech", "QQQ": "tech", "TLT": "bond"})
    )
    capped = gen._apply_weight_constraints({"SPY": 0.4, "QQQ": 0.4, "TLT": 0.2})
    assert capped["SPY"] + capped["QQQ"] == pytest.approx(0.5)
    assert capped["SPY"] == pytest.approx(0.25)
    assert capped["TLT"] == pytest.approx(0.2)  # other sector untouched


def test_sector_cap_requires_sector_map() -> None:
    with pytest.raises(ValidationError, match="sector_map"):
        BacktestConfig(sector_cap=0.5)


def test_constraints_are_noop_by_default() -> None:
    gen = OrderGenerator(BacktestConfig())
    target_map = {"SPY": 0.8, "QQQ": 0.1}
    assert gen._apply_weight_constraints(target_map) == target_map


def test_max_weight_constraint_changes_resulting_orders() -> None:
    portfolio = Portfolio(initial_cash=10_000)
    prices = {"SPY": 100.0, "QQQ": 100.0}
    targets = _targets({"SPY": 0.9, "QQQ": 0.1})

    uncapped = OrderGenerator(BacktestConfig(min_order_value=1)).generate_orders(
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        targets=targets,
        portfolio=Portfolio(initial_cash=10_000),
        prices=prices,
    )
    capped = OrderGenerator(
        BacktestConfig(min_order_value=1, max_weight_per_symbol=0.3)
    ).generate_orders(
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        targets=targets,
        portfolio=portfolio,
        prices=prices,
    )
    spy_uncapped = next(o for o in uncapped if o.symbol == "SPY").quantity
    spy_capped = next(o for o in capped if o.symbol == "SPY").quantity
    assert spy_capped < spy_uncapped
    assert spy_capped * 100.0 <= 0.3 * 10_000 + 1e-6


# --- attribution -------------------------------------------------------------

def test_attribution_is_recorded_and_signed_correctly() -> None:
    ohlcv = _multiweek_ohlcv()  # steady uptrend
    signals = _hold_spy_every_bar_signals()
    result = BacktestEngine(
        BacktestConfig(initial_cash=10_000, commission_bps=0, slippage_bps=0)
    ).run(ohlcv, ScoreSignalStrategy(signals, top_n=2))

    assert not result.attribution.empty
    assert list(result.attribution.columns) == ["timestamp", "symbol", "contribution"]
    # Per-symbol aggregation surfaced on metrics.
    assert result.metrics.attribution
    spy = next(row for row in result.metrics.attribution if row["symbol"] == "SPY")
    assert set(spy) == {"symbol", "contribution", "contribution_pct"}
    # Held a rising name -> positive contribution (sign sanity, not exact tie-out).
    assert spy["contribution"] > 0
    assert spy["contribution_pct"] == pytest.approx(spy["contribution"] / 10_000)


def test_attribution_defaults_empty_without_holdings() -> None:
    # No signals -> no positions -> no attribution rows, metrics list empty.
    ohlcv = _multiweek_ohlcv()
    empty_signals = pd.DataFrame(
        {"symbol": [], "signal_ts": [], "tradeable_ts": [], "score": []}
    )
    result = BacktestEngine(BacktestConfig(initial_cash=10_000)).run(
        ohlcv, ScoreSignalStrategy(empty_signals, top_n=1)
    )
    assert result.attribution.empty
    assert result.metrics.attribution == []
