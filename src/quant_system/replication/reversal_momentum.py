from __future__ import annotations

import math
from typing import Any

import pandas as pd

from quant_system.api.schemas.common import dataframe_records
from quant_system.backtest.metrics import calculate_performance_metrics

PAPER_METADATA = {
    "title": "Short-Term Reversals and Longer-Term Momentum around the World: Theory and Evidence",
    "authors": [
        "Narasimhan Jegadeesh",
        "Jiang Luo",
        "Avanidhar Subrahmanyam",
        "Sheridan Titman",
    ],
    "doi": "10.1093/rfs/hhaf057",
    "journal": "The Review of Financial Studies",
}


def build_reversal_momentum_replication(
    ohlcv: pd.DataFrame,
    *,
    initial_cash: float = 1.0,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Build a monthly long-short replication from normalized daily OHLCV data."""

    warnings: list[str] = []
    if ohlcv.empty:
        return _empty_result(initial_cash, ["No OHLCV rows were available."])

    monthly = _monthly_panel(ohlcv)
    if monthly.empty or monthly["symbol"].nunique() < 2:
        return _empty_result(
            initial_cash,
            ["At least two symbols with monthly closes are required."],
        )

    low_price_observations = _low_price_observation_count(monthly)
    signal_frame = _signal_frame(monthly)
    if signal_frame.empty:
        return _empty_result(
            initial_cash,
            ["Not enough monthly history. Need roughly 14 monthly closes for 12-2 momentum."],
        )

    effective_top_n = top_n or max(
        1,
        math.floor(signal_frame.groupby("timestamp")["symbol"].nunique().min() * 0.1),
    )
    effective_top_n = max(1, effective_top_n)
    formation = "decile long-short portfolios" if top_n is None else f"top/bottom {effective_top_n}"

    monthly_returns = []
    positions = []
    for strategy, score_column in [
        ("reversal", "reversal_score"),
        ("momentum", "momentum_score"),
        ("composite", "composite_score"),
    ]:
        strategy_rows, strategy_positions = _long_short_returns(
            signal_frame,
            score_column=score_column,
            strategy=strategy,
            top_n=effective_top_n,
        )
        monthly_returns.extend(strategy_rows)
        if strategy == "composite":
            positions.extend(strategy_positions)

    monthly_returns_frame = pd.DataFrame(monthly_returns)
    composite_returns = monthly_returns_frame[
        monthly_returns_frame["strategy"] == "composite"
    ].sort_values("return_date")

    if composite_returns.empty:
        return _empty_result(
            initial_cash,
            [
                "The selected universe did not produce any investable "
                "monthly long-short observations."
            ],
        )

    equity_curve = _equity_curve(composite_returns, initial_cash=initial_cash)
    metrics = calculate_performance_metrics(
        equity_curve[["timestamp", "equity"]],
        pd.DataFrame(),
        initial_cash=initial_cash,
        annualization_factor=12,
    ).model_dump()
    metrics["observation_months"] = int(len(composite_returns))
    metrics["average_monthly_return"] = float(composite_returns["return"].mean())
    metrics["average_reversal_return"] = _strategy_average(monthly_returns_frame, "reversal")
    metrics["average_momentum_return"] = _strategy_average(monthly_returns_frame, "momentum")

    diagnostics = _diagnostics(monthly_returns_frame, signal_frame)
    if monthly["symbol"].nunique() < 10:
        warnings.append(
            "Small local universes are useful for workflow testing but are "
            "not a full global-stock replication."
        )
    if low_price_observations:
        warnings.append(
            f"Excluded {low_price_observations} monthly signal observations "
            "with prior-month close below $1."
        )

    return {
        "paper": PAPER_METADATA,
        "methodology": {
            "formation": formation,
            "reversal_signal": "past 1-month return, ranked contrarian",
            "momentum_signal": "past months t-12 through t-2 return, ranked continuation",
            "holding_period": "subsequent month",
            "price_filter": "exclude signal observations with prior-month close below $1",
        },
        "metrics": metrics,
        "diagnostics": diagnostics,
        "equity_curve": dataframe_records(equity_curve),
        "monthly_returns": dataframe_records(monthly_returns_frame),
        "positions": dataframe_records(pd.DataFrame(positions)),
        "legs": [
            {
                "strategy": "reversal",
                "signal": "Contrarian rank on the previous month's return.",
            },
            {
                "strategy": "momentum",
                "signal": "Continuation rank on months t-12 through t-2.",
            },
            {
                "strategy": "composite",
                "signal": "Equal blend of reversal and longer-term momentum ranks.",
            },
        ],
        "warnings": warnings,
    }


def _monthly_panel(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "timestamp", "close"])
    monthly = (
        frame.sort_values(["symbol", "timestamp"])
        .set_index("timestamp")
        .groupby("symbol")["close"]
        .resample("ME")
        .last()
        .dropna()
        .rename("close")
        .reset_index()
    )
    monthly["monthly_return"] = monthly.groupby("symbol")["close"].pct_change()
    return monthly.dropna(subset=["monthly_return"]).reset_index(drop=True)


def _signal_frame(monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _symbol, group in monthly.groupby("symbol"):
        ordered = group.sort_values("timestamp").copy()
        returns = pd.to_numeric(ordered["monthly_return"], errors="coerce")
        ordered["one_month_return"] = returns.shift(1)
        ordered["prior_close"] = ordered["close"].shift(1)
        ordered["momentum_return_12_2"] = (
            (1.0 + returns.shift(2)).rolling(11).apply(lambda values: values.prod(), raw=True)
            - 1.0
        )
        ordered["next_month_return"] = returns.shift(-1)
        rows.append(ordered)
    signal = pd.concat(rows, ignore_index=True)
    signal = signal.dropna(
        subset=["one_month_return", "momentum_return_12_2", "next_month_return", "prior_close"]
    )
    if signal.empty:
        return signal
    signal["reversal_score"] = -signal["one_month_return"]
    signal["momentum_score"] = signal["momentum_return_12_2"]
    signal = signal.loc[signal["prior_close"] >= 1.0].copy()
    if signal.empty:
        return signal
    signal["noise_proxy"] = signal.groupby("timestamp")["one_month_return"].transform("std")
    signal["reversal_z"] = signal.groupby("timestamp")["reversal_score"].transform(_zscore)
    signal["momentum_z"] = signal.groupby("timestamp")["momentum_score"].transform(_zscore)
    signal["composite_score"] = signal["reversal_z"] + signal["momentum_z"]
    return signal.reset_index(drop=True)


def _long_short_returns(
    signal: pd.DataFrame,
    *,
    score_column: str,
    strategy: str,
    top_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    returns: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    for timestamp, group in signal.groupby("timestamp"):
        investable = group.dropna(subset=[score_column, "next_month_return"]).sort_values(
            score_column,
            ascending=False,
        )
        if len(investable) < 2:
            continue
        count = min(top_n, len(investable) // 2)
        if count < 1:
            continue
        longs = investable.head(count)
        shorts = investable.tail(count)
        long_return = float(longs["next_month_return"].mean())
        short_return = float(shorts["next_month_return"].mean())
        return_date = (
            pd.Timestamp(timestamp) + pd.offsets.MonthEnd(1)
        ).isoformat()
        returns.append(
            {
                "strategy": strategy,
                "rebalance_date": pd.Timestamp(timestamp).isoformat(),
                "return_date": return_date,
                "long_return": long_return,
                "short_return": short_return,
                "return": long_return - short_return,
                "long_count": int(len(longs)),
                "short_count": int(len(shorts)),
            }
        )
        for side, rows in [("long", longs), ("short", shorts)]:
            for _, row in rows.iterrows():
                positions.append(
                    {
                        "strategy": strategy,
                        "rebalance_date": pd.Timestamp(timestamp).isoformat(),
                        "return_date": return_date,
                        "symbol": row["symbol"],
                        "side": side,
                        "one_month_return": float(row["one_month_return"]),
                        "momentum_return_12_2": float(row["momentum_return_12_2"]),
                        "composite_score": float(row["composite_score"]),
                        "next_month_return": float(row["next_month_return"]),
                    }
                )
    return returns, positions


def _equity_curve(monthly_returns: pd.DataFrame, *, initial_cash: float) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.Timestamp(monthly_returns["rebalance_date"].iloc[0]),
            "equity": float(initial_cash),
            "monthly_return": 0.0,
        }
    ]
    equity = float(initial_cash)
    for _, row in monthly_returns.sort_values("return_date").iterrows():
        monthly_return = float(row["return"])
        equity *= 1.0 + monthly_return
        rows.append(
            {
                "timestamp": pd.Timestamp(row["return_date"]),
                "equity": equity,
                "monthly_return": monthly_return,
            }
        )
    return pd.DataFrame(rows)


def _low_price_observation_count(monthly: pd.DataFrame) -> int:
    ordered = monthly.sort_values(["symbol", "timestamp"]).copy()
    ordered["prior_close"] = ordered.groupby("symbol")["close"].shift(1)
    return int(ordered["prior_close"].lt(1.0).sum())


def _diagnostics(monthly_returns: pd.DataFrame, signal: pd.DataFrame) -> dict[str, float | None]:
    pivot = monthly_returns.pivot_table(
        index="return_date",
        columns="strategy",
        values="return",
        aggfunc="first",
    )
    relation = None
    if {"reversal", "momentum"} <= set(pivot.columns) and len(pivot) > 1:
        pair = pivot[["reversal", "momentum"]].dropna()
        if (
            len(pair) > 1
            and pair["reversal"].std(ddof=0) > 0
            and pair["momentum"].std(ddof=0) > 0
        ):
            relation = float(pair["reversal"].corr(pair["momentum"]))

    noise_by_month = signal.groupby("timestamp")["noise_proxy"].first().dropna()
    reversal = pivot.get("reversal")
    if reversal is None or noise_by_month.empty:
        high_noise_reversal = None
        low_noise_reversal = None
    else:
        aligned = pd.DataFrame(
            {
                "noise": noise_by_month,
                "reversal": reversal.rename(
                    index=lambda value: str(
                        pd.Timestamp(value) - pd.offsets.MonthEnd(1)
                    )
                ),
            }
        ).dropna()
        if len(aligned) < 2:
            high_noise_reversal = None
            low_noise_reversal = None
        else:
            median_noise = aligned["noise"].median()
            high_noise_reversal = float(
                aligned.loc[aligned["noise"] >= median_noise, "reversal"].mean()
            )
            low_noise_reversal = float(
                aligned.loc[aligned["noise"] < median_noise, "reversal"].mean()
            )
    return {
        "reversal_momentum_return_correlation": relation,
        "high_noise_average_reversal_return": high_noise_reversal,
        "low_noise_average_reversal_return": low_noise_reversal,
    }


def _zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / std


def _strategy_average(frame: pd.DataFrame, strategy: str) -> float | None:
    values = frame.loc[frame["strategy"] == strategy, "return"]
    if values.empty:
        return None
    return float(values.mean())


def _empty_result(initial_cash: float, warnings: list[str]) -> dict[str, Any]:
    return {
        "paper": PAPER_METADATA,
        "methodology": {
            "formation": "decile long-short portfolios",
            "reversal_signal": "past 1-month return, ranked contrarian",
            "momentum_signal": "past months t-12 through t-2 return, ranked continuation",
            "holding_period": "subsequent month",
            "price_filter": "exclude signal observations with prior-month close below $1",
        },
        "metrics": {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
            "observation_months": 0,
            "average_monthly_return": 0.0,
            "average_reversal_return": None,
            "average_momentum_return": None,
        },
        "diagnostics": {
            "reversal_momentum_return_correlation": None,
            "high_noise_average_reversal_return": None,
            "low_noise_average_reversal_return": None,
        },
        "equity_curve": [],
        "monthly_returns": [],
        "positions": [],
        "legs": [],
        "warnings": warnings,
    }
