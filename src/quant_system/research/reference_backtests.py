"""Fixed-rule, real-data reference evaluations without storage or account effects.

Predictions are dated at the close where their inputs become known. The existing
Platform engine executes their positive target weights at the next real session's
open. These are reference portfolios, not standalone performance of a raw factor.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.metrics import calculate_performance_metrics
from quant_system.backtest.models import BacktestConfig, TargetWeight
from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy
from quant_system.factors.registry import build_factor_registry
from quant_system.replication.reversal_momentum import (
    _long_short_returns,
    _monthly_panel,
    _signal_frame,
)
from quant_system.research.active_metrics import active_metrics
from quant_system.strategies.registry import build_default_strategy_registry
from quant_system.universe.registry import build_default_universe_registry

INITIAL_CASH = 100_000.0
COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 5.0
_METRIC_KEYS = (
    "total_return",
    "annualized_return",
    "volatility",
    "sharpe",
    "sortino",
    "calmar",
    "max_drawdown",
    "turnover",
)


def _date(value: str | pd.Timestamp) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True).normalize()


def _prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "timestamp", "open", "close", "volume", "provider", "price_adjustment"}
    if not required.issubset(prices.columns):
        raise ValueError("reference_prices_missing_columns")
    frame = prices.copy()
    providers = set(frame["provider"].dropna().astype(str).str.lower())
    if providers != {"futu"}:
        raise ValueError("reference_real_provider_required")
    if set(frame["price_adjustment"].dropna()) != {"qfq"}:
        raise ValueError("reference_price_adjustment_mismatch")
    if frame["provider"].isna().any() or frame["price_adjustment"].isna().any():
        raise ValueError("reference_price_provenance_missing")
    if "interval" in frame and set(frame["interval"].astype(str)) != {"1d"}:
        raise ValueError("reference_daily_prices_required")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if frame.duplicated(["timestamp", "symbol"]).any():
        raise ValueError("reference_duplicate_bars")
    for column in ("open", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError("reference_nonfinite_prices")
    if (frame[["open", "close"]] <= 0).any().any() or (frame["volume"] < 0).any():
        raise ValueError("reference_invalid_prices")
    return frame.sort_values(["timestamp", "symbol"], ignore_index=True)


def compute_reference_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Direction-adjusted registry factors, retaining unavailable warmup rows.

    The final bar has no next known tradable timestamp, so BaseFactor.compute
    deliberately leaves that signal unmaterialized. No synthetic next bar is added.
    """
    if prices.empty:
        return pd.DataFrame(
            index=pd.MultiIndex.from_arrays([[], []], names=["datetime", "instrument"]),
            columns=build_factor_registry().factor_ids(),
            dtype=float,
        )
    frame = _prepare_prices(prices)
    calendar_index = pd.MultiIndex.from_product(
        [sorted(frame["timestamp"].unique()), sorted(frame["symbol"].unique())],
        names=["timestamp", "symbol"],
    )
    frame = frame.set_index(["timestamp", "symbol"]).reindex(calendar_index).reset_index()
    index = pd.MultiIndex.from_frame(frame[["timestamp", "symbol"]])
    index.names = ["datetime", "instrument"]
    features = pd.DataFrame(index=index)
    registry = build_factor_registry()
    metadata = {}
    for factor_id in registry.factor_ids():
        factor = registry.create(factor_id)  # Each factor owns its actual default lookback.
        result = factor.compute(frame)
        series = result.set_index(["signal_ts", "symbol"])["value"]
        series.index.names = ["datetime", "instrument"]
        direction = -1.0 if factor.direction == "lower_is_better" else 1.0
        features[factor_id] = series.reindex(index) * direction
        features[factor_id] = features[factor_id].where(frame["close"].notna().to_numpy())
        metadata[factor_id] = factor.metadata.model_dump()
        if factor_id == "macd":
            features[factor_id] = features[factor_id] / frame["close"].to_numpy()
            metadata[factor_id]["reference_transform"] = "histogram / signal_day_close"
            metadata[factor_id]["reference_note"] = (
                "跨标的比较使用价格归一化柱值，原始MACD定义不变。"
            )
    features = features.sort_index()
    features.attrs["factors"] = metadata
    features.attrs["source"] = str(frame["provider"].dropna().iloc[0])
    features.attrs["price_adjustment"] = str(frame["price_adjustment"].dropna().iloc[0])
    return features


class _BuyAndHold:
    def __init__(self, symbol: str = "QQQ"):
        self.symbol = symbol
        self.entered = False

    def target_weights(self, timestamp):
        if self.entered:
            return None
        self.entered = True
        return [TargetWeight(timestamp=timestamp, symbol=self.symbol, target_weight=1.0)]


def _config(*, terminal_valuation: Literal["close", "open"] = "close") -> BacktestConfig:
    return BacktestConfig(
        initial_cash=INITIAL_CASH,
        commission_bps=COMMISSION_BPS,
        slippage_bps=SLIPPAGE_BPS,
        annualization_factor=252,
        terminal_valuation=terminal_valuation,
    )


def _returns(equity: pd.Series, initial_cash: float) -> pd.Series:
    return equity.div(equity.shift(1).fillna(initial_cash)).sub(1.0)


def _metrics(
    curve: pd.DataFrame, trades: pd.DataFrame, initial_cash: float, annualization: int = 252
) -> dict[str, float | None]:
    if curve.empty:
        return dict.fromkeys(_METRIC_KEYS)
    result = calculate_performance_metrics(
        curve,
        trades,
        initial_cash=initial_cash,
        annualization_factor=annualization,
    ).model_dump()
    result = {key: result[key] for key in _METRIC_KEYS}
    values = _returns(curve["equity"], initial_cash)
    std = float(values.std(ddof=0))
    if len(values) < 2 or not math.isfinite(std) or std <= 1e-12:
        result["sharpe"] = None
    return result


def _costs(trades: pd.DataFrame) -> dict:
    commission = float(trades["commission"].sum()) if len(trades) else 0.0
    slippage = (
        float(((trades["fill_price"] - trades["requested_price"]).abs() * trades["quantity"]).sum())
        if len(trades)
        else 0.0
    )
    return {
        "commission_bps": COMMISSION_BPS,
        "slippage_bps": SLIPPAGE_BPS,
        "commission": commission,
        "slippage": slippage,
        "total": commission + slippage,
        "risk_free_rate": 0.0,
        "cash_interest_rate": 0.0,
    }


def _annual_rows(
    curve: pd.DataFrame,
    trades: pd.DataFrame,
    benchmark_trades: pd.DataFrame,
    *,
    annualization: int = 252,
) -> list[dict]:
    rows, previous_equity, previous_benchmark = [], INITIAL_CASH, INITIAL_CASH
    for year, group in curve.groupby(curve["timestamp"].dt.year, sort=True):
        strategy_curve = group[["timestamp", "equity"]]
        benchmark_curve = group[["timestamp", "benchmark"]].rename(columns={"benchmark": "equity"})
        yearly_trades = trades.loc[trades["timestamp"].dt.year == year] if len(trades) else trades
        yearly_benchmark = (
            benchmark_trades.loc[benchmark_trades["timestamp"].dt.year == year]
            if len(benchmark_trades)
            else benchmark_trades
        )
        rows.append(
            {
                "year": int(year),
                "start": group["timestamp"].iloc[0].date().isoformat(),
                "end": group["timestamp"].iloc[-1].date().isoformat(),
                "metrics": _metrics(strategy_curve, yearly_trades, previous_equity, annualization),
                "benchmark_metrics": _metrics(
                    benchmark_curve, yearly_benchmark, previous_benchmark, annualization
                ),
            }
        )
        previous_equity = float(group["equity"].iloc[-1])
        previous_benchmark = float(group["benchmark"].iloc[-1])
    return rows


def _result(
    frame: pd.DataFrame,
    strategy,
    *,
    signal_sessions: int,
    terminal_valuation: Literal["close", "open"] = "close",
) -> dict:
    config = _config(terminal_valuation=terminal_valuation)
    engine_result = BacktestEngine(config).run(frame, strategy)
    benchmark_result = BacktestEngine(config).run(frame[frame["symbol"] == "QQQ"], _BuyAndHold())
    curve = engine_result.equity_curve[["timestamp", "equity"]].merge(
        benchmark_result.equity_curve[["timestamp", "equity"]].rename(
            columns={"equity": "benchmark"}
        ),
        on="timestamp",
        validate="one_to_one",
    )
    daily = _returns(curve["equity"], INITIAL_CASH)
    metrics = _metrics(engine_result.equity_curve, engine_result.trade_blotter, INITIAL_CASH)
    benchmark_metrics = _metrics(
        benchmark_result.equity_curve, benchmark_result.trade_blotter, INITIAL_CASH
    )
    return {
        "status": "available",
        "reason": None,
        "metrics": metrics,
        "benchmark_metrics": benchmark_metrics,
        "active_metrics": active_metrics(
            curve, initial_cash=INITIAL_CASH, benchmark_symbol="QQQ", include_peer=False
        ),
        "curve": [
            {
                "date": row.timestamp.date().isoformat(),
                "equity": float(row.equity),
                "benchmark": float(row.benchmark),
            }
            for row in curve.itertuples(index=False)
        ],
        "by_year": _annual_rows(curve, engine_result.trade_blotter, benchmark_result.trade_blotter),
        "daily_returns": daily.tolist(),
        "benchmark_daily_returns": _returns(curve["benchmark"], INITIAL_CASH).tolist(),
        "return_dates": curve["timestamp"].dt.strftime("%Y-%m-%d").tolist(),
        "costs": _costs(engine_result.trade_blotter),
        "benchmark_costs": _costs(benchmark_result.trade_blotter),
        "turnover": metrics["turnover"],
        "sample_counts": {
            "sessions": len(curve),
            "signal_sessions": int(signal_sessions),
            "fills": len(engine_result.trade_blotter),
            "benchmark_fills": len(benchmark_result.trade_blotter),
        },
        "source": str(frame["provider"].iloc[0]),
        "price_adjustment": str(frame["price_adjustment"].iloc[0]),
        "start": curve["timestamp"].iloc[0].date().isoformat(),
        "end": curve["timestamp"].iloc[-1].date().isoformat(),
        "frequency": "daily",
        "terminal_valuation": terminal_valuation,
        "terminal_liquidation": False,
    }


def _empty(reason: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "metrics": dict.fromkeys(_METRIC_KEYS),
        "benchmark_metrics": dict.fromkeys(_METRIC_KEYS),
        "active_metrics": None,
        "curve": [],
        "by_year": [],
        "daily_returns": [],
        "return_dates": [],
        "benchmark_daily_returns": [],
        "costs": None,
        "turnover": None,
        "sample_counts": {"sessions": 0, "signal_sessions": 0},
        "source": None,
    }


def _score_frame(
    prices: pd.DataFrame, predictions: pd.Series, *, start: str, end: str, top_n: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if top_n < 1 or _date(start) > _date(end):
        raise ValueError("invalid_reference_evaluation_window")
    if not isinstance(predictions.index, pd.MultiIndex) or list(predictions.index.names) != [
        "datetime",
        "instrument",
    ]:
        raise ValueError("prediction_index_must_be_datetime_instrument")
    scores = (
        predictions.rename("score")
        .reset_index()
        .rename(columns={"datetime": "signal_ts", "instrument": "symbol"})
    )
    scores["signal_ts"] = pd.to_datetime(scores["signal_ts"], utc=True).dt.normalize()
    scores["symbol"] = scores["symbol"].astype(str).str.strip().str.upper()
    scores["score"] = pd.to_numeric(scores["score"], errors="raise")
    if scores.duplicated(["signal_ts", "symbol"]).any():
        raise ValueError("duplicate_prediction")
    if np.isinf(scores["score"]).any():
        raise ValueError("nonfinite_prediction")
    symbols = set(scores["symbol"]) | {"QQQ"}
    if not symbols.issubset(set(prices["symbol"])):
        raise ValueError("prediction_or_benchmark_prices_missing")
    active = prices.loc[prices["symbol"].isin(symbols)]
    calendar = pd.DatetimeIndex(sorted(prices["timestamp"].unique()))
    evaluation_dates = calendar[(calendar >= _date(start)) & (calendar <= _date(end))]
    benchmark_dates = active.loc[active["symbol"] == "QQQ", "timestamp"]
    if not evaluation_dates.isin(benchmark_dates).all():
        raise ValueError("benchmark_session_prices_missing")
    previous_dates = calendar[calendar < _date(start)]
    earliest_signal = previous_dates[-1] if len(previous_dates) else _date(start)
    scores = scores.loc[scores["signal_ts"].between(earliest_signal, _date(end))]
    if not scores["signal_ts"].isin(calendar).all():
        raise ValueError("prediction_date_has_incomplete_prices")
    next_session = dict(zip(calendar[:-1], calendar[1:], strict=True))
    scores["tradeable_ts"] = scores["signal_ts"].map(next_session)
    scores = scores.dropna(subset=["score", "tradeable_ts"])
    scores = scores.loc[scores["tradeable_ts"].between(_date(start), _date(end))]
    eligible = scores.groupby("tradeable_ts")["symbol"].transform("nunique") >= top_n
    scores = scores.loc[eligible, ["symbol", "signal_ts", "tradeable_ts", "score"]]
    execution_keys = pd.MultiIndex.from_frame(scores[["tradeable_ts", "symbol"]])
    price_keys = pd.MultiIndex.from_frame(active[["timestamp", "symbol"]])
    if not execution_keys.isin(price_keys).all():
        raise ValueError("prediction_execution_prices_missing")
    frame = active.loc[
        active["timestamp"].isin(calendar) & active["timestamp"].between(_date(start), _date(end))
    ]
    return frame, scores


def evaluate_predictions(
    prices: pd.DataFrame,
    predictions: pd.Series,
    *,
    start: str,
    end: str,
    top_n: int = 3,
    terminal_valuation: Literal["close", "open"] = "close",
) -> dict:
    """Rank signal-day forecasts; positive long-only targets execute next open.

    Negative forecasts are eligible for ranking. ``long_only=False`` only disables
    the ScoreSignalStrategy's positive-score gate; it never creates short weights.
    """
    if prices.empty:
        return _empty("no_prices")
    frame = _prepare_prices(prices)
    if predictions.empty:
        return _empty("no_predictions")
    frame, signals = _score_frame(frame, predictions, start=start, end=end, top_n=top_n)
    if frame.empty or signals.empty:
        return _empty("no_usable_predictions_in_evaluation_window")
    return _result(
        frame,
        ScoreSignalStrategy(signals, top_n=top_n, long_only=False),
        signal_sessions=signals["tradeable_ts"].nunique(),
        terminal_valuation=terminal_valuation,
    )


def _monthly_reference(frame: pd.DataFrame, *, start: str, end: str) -> dict:
    """Reuse the resident replication's pure calculations, not its trial-writing entry point."""
    panel = _monthly_panel(frame)
    if panel.empty or panel["symbol"].nunique() < 2:
        return _empty("insufficient_monthly_history")
    signal = _signal_frame(panel)
    if signal.empty:
        return _empty("insufficient_monthly_history")
    n = max(1, int(signal.groupby("timestamp")["symbol"].nunique().min() * 0.1))
    records, _positions = _long_short_returns(
        signal, score_column="composite_score", strategy="composite", top_n=n
    )
    monthly = pd.DataFrame(records)
    if monthly.empty:
        return _empty("no_monthly_positions")
    monthly["timestamp"] = pd.to_datetime(monthly["return_date"], utc=True)
    month_begin = monthly["timestamp"].map(lambda day: day.replace(day=1))
    monthly = monthly.loc[(month_begin >= _date(start)) & (monthly["timestamp"] <= _date(end))]
    if monthly.empty:
        return _empty("no_complete_monthly_evaluation_period")
    begin = monthly["timestamp"].iloc[0].replace(day=1)
    finish = monthly["timestamp"].iloc[-1]
    qqq = frame.loc[(frame["symbol"] == "QQQ") & frame["timestamp"].between(begin, finish)]
    benchmark = BacktestEngine(_config()).run(qqq, _BuyAndHold())
    benchmark_monthly = (
        benchmark.equity_curve.set_index("timestamp")["equity"].resample("ME").last()
    )
    monthly["equity"] = INITIAL_CASH * (1 + monthly["return"]).cumprod()
    monthly["benchmark"] = monthly["timestamp"].map(benchmark_monthly)
    benchmark_curve = monthly[["timestamp", "benchmark"]].rename(columns={"benchmark": "equity"})
    annual = _annual_rows(monthly, pd.DataFrame(), benchmark.trade_blotter, annualization=12)
    for row in annual:
        row["metrics"]["turnover"] = None
    result = {
        "status": "available",
        "reason": "月频多空毛收益探索，未计成交成本、借券费用与可借券限制。",
        "metrics": _metrics(monthly, pd.DataFrame(), INITIAL_CASH, annualization=12),
        "benchmark_metrics": _metrics(benchmark_curve, benchmark.trade_blotter, INITIAL_CASH, 12),
        # The monthly diagnostic keeps the daily-window active blocks out: its calendar
        # is not the daily one the 252/126 constants describe.
        "active_metrics": None,
        "curve": [
            {
                "date": row.timestamp.date().isoformat(),
                "equity": float(row.equity),
                "benchmark": float(row.benchmark),
            }
            for row in monthly.itertuples(index=False)
        ],
        "by_year": annual,
        "frequency": "monthly",
        "source": str(frame["provider"].iloc[0]),
        "sample_counts": {"months": len(monthly)},
        "costs": None,
    }
    # A monthly diagnostic is explicitly not the comparable, net-cost daily reference.
    result["metrics"]["turnover"] = None
    return result


def build_reference_backtests(prices: pd.DataFrame, *, start: str, end: str) -> dict:
    frame = _prepare_prices(prices)
    universe = build_default_universe_registry().get("etf").normalized_symbols()
    if not set(universe).issubset(set(frame["symbol"])):
        raise ValueError("reference_etf_universe_incomplete")
    frame = frame.loc[frame["symbol"].isin(universe)]
    features = compute_reference_features(frame)
    rows: list[dict[str, Any]] = []
    for factor_id in features.columns:
        result = evaluate_predictions(frame, features[factor_id], start=start, end=end)
        rows.append(
            {
                "key": f"factor:{factor_id}",
                "kind": "factor",
                "rule": (
                    "使用该因子真实默认窗口，按登记方向在固定10只ETF中"
                    "每日取前3只等权做多；次日开盘。"
                ),
                **result,
            }
        )
    registry = build_default_strategy_registry()
    for metadata in registry.list_metadata():
        key = f"strategy:{metadata.id}"
        if metadata.id == "reversal_momentum":
            result = _monthly_reference(frame, start=start, end=end)
            rule = "复用当前月频反转/动量标准化合成与多空分组；毛收益不与每日净收益混作同类。"
        elif metadata.id in {"cross_sectional_top_n", "mean_reversion_top_n"}:
            weights = metadata.default_payload["weights"]
            selected = features[list(weights)].dropna()
            standardized = selected.groupby(level="datetime").transform(
                lambda col: (
                    (col - col.mean()) / col.std(ddof=0)
                    if col.nunique() > 1 and col.std(ddof=0) > 0
                    else col * 0
                )
            )
            predictions = standardized.mul(pd.Series(weights)).sum(axis=1) / sum(
                abs(value) for value in weights.values()
            )
            evaluation, signals = _score_frame(frame, predictions, start=start, end=end, top_n=3)
            if signals.empty or evaluation.empty:
                result = _empty("insufficient_factor_history")
            else:
                strategy = (
                    MeanReversionTopN(signals, top_n=3)
                    if metadata.id == ("mean_reversion_top_n")
                    else ScoreSignalStrategy(signals, top_n=3)
                )
                result = _result(
                    evaluation, strategy, signal_sessions=signals["tradeable_ts"].nunique()
                )
            rule = (
                "真实默认三因子权重：动量1、波动率0.5、流动性0.5；"
                "按原模板排序及正分条件，每日等权。"
            )
        else:
            result = _empty("draft_has_no_executable_strategy")
            rule = "研究草稿没有对应执行器，不代入动量或其他策略。"
        rows.append({"key": key, "kind": "strategy", "rule": rule, **result})
    benchmark_frame = frame.loc[
        (frame["symbol"] == "QQQ") & frame["timestamp"].between(_date(start), _date(end))
    ]
    benchmark_result = BacktestEngine(_config()).run(benchmark_frame, _BuyAndHold())
    return {
        "source": str(frame["provider"].iloc[0]),
        "price_adjustment": str(frame["price_adjustment"].iloc[0]),
        "start": str(start),
        "end": str(end),
        "universe": universe,
        "benchmark_symbol": "QQQ",
        "benchmark": {
            "metrics": _metrics(
                benchmark_result.equity_curve, benchmark_result.trade_blotter, INITIAL_CASH
            ),
            "costs": _costs(benchmark_result.trade_blotter),
        },
        "rows": rows,
    }
