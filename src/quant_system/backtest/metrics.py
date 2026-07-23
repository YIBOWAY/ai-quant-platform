from __future__ import annotations

import math

import pandas as pd
from pydantic import BaseModel, Field


class PerformanceMetrics(BaseModel):
    total_return: float
    annualized_return: float
    volatility: float
    sharpe: float
    max_drawdown: float
    turnover: float
    # Per-symbol contribution to the run's P&L (mark-to-market on held quantity).
    # Empty by default so existing callers/artifacts are unchanged.
    attribution: list[dict[str, float | str]] = Field(default_factory=list)


def _aggregate_attribution(
    attribution_frame: pd.DataFrame | None, *, initial_cash: float
) -> list[dict[str, float | str]]:
    if attribution_frame is None or attribution_frame.empty:
        return []
    if "symbol" not in attribution_frame or "contribution" not in attribution_frame:
        return []
    grouped = (
        pd.to_numeric(attribution_frame["contribution"], errors="coerce")
        .groupby(attribution_frame["symbol"])
        .sum()
        .sort_values(ascending=False)
    )
    denominator = initial_cash if initial_cash else 0.0
    rows: list[dict[str, float | str]] = []
    for symbol, contribution in grouped.items():
        contribution = float(contribution)
        rows.append(
            {
                "symbol": str(symbol),
                "contribution": contribution,
                "contribution_pct": contribution / denominator if denominator else 0.0,
            }
        )
    return rows


def calculate_performance_metrics(
    equity_curve: pd.DataFrame,
    trade_blotter: pd.DataFrame,
    *,
    initial_cash: float,
    annualization_factor: int = 252,
    attribution_frame: pd.DataFrame | None = None,
) -> PerformanceMetrics:
    attribution = _aggregate_attribution(attribution_frame, initial_cash=initial_cash)
    if equity_curve.empty:
        return PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            volatility=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            turnover=0.0,
            attribution=attribution,
        )

    curve = equity_curve.sort_values("timestamp").copy()
    equity = pd.to_numeric(curve["equity"], errors="coerce").dropna()
    if equity.empty:
        raise ValueError("equity_curve must contain numeric equity values")

    first_equity = float(equity.iloc[0])
    last_equity = float(equity.iloc[-1])
    denominator = initial_cash if initial_cash > 0 else first_equity
    total_return = last_equity / denominator - 1 if denominator else 0.0

    returns = equity.pct_change(fill_method=None).dropna()
    periods = max(len(returns), 1)
    annualized_return = (
        (last_equity / denominator) ** (annualization_factor / periods) - 1
        if denominator and last_equity > 0
        else 0.0
    )
    volatility = (
        float(returns.std(ddof=0) * math.sqrt(annualization_factor)) if len(returns) else 0.0
    )
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * math.sqrt(annualization_factor))
        if len(returns) and returns.std(ddof=0) > 0
        else 0.0
    )
    running_max = equity.cummax()
    drawdowns = equity / running_max - 1
    max_drawdown = abs(float(drawdowns.min())) if len(drawdowns) else 0.0

    gross_traded = 0.0
    if not trade_blotter.empty and "gross_value" in trade_blotter.columns:
        gross_traded = float(
            pd.to_numeric(trade_blotter["gross_value"], errors="coerce").fillna(0).sum()
        )
    turnover = gross_traded / initial_cash if initial_cash else 0.0

    return PerformanceMetrics(
        total_return=float(total_return),
        annualized_return=float(annualized_return),
        volatility=float(volatility),
        sharpe=float(sharpe),
        max_drawdown=float(max_drawdown),
        turnover=float(turnover),
        attribution=attribution,
    )
