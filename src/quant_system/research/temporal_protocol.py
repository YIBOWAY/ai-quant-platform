"""Recent research windows, explicitly separate from future forward evidence."""

from __future__ import annotations

from datetime import date

import pandas as pd

from quant_system.backtest.metrics import calculate_performance_metrics


def recent_research_window(watermark: str, *, years: int = 4) -> dict:
    end = pd.Timestamp(watermark)
    if years < 2 or end.date() >= date.today():
        raise ValueError("research_window_requires_completed_history")
    start = (end - pd.DateOffset(years=years)).replace(day=1)
    return {
        "training_start": start.date().isoformat(),
        "training_end": end.date().isoformat(),
        "data_watermark": end.date().isoformat(),
        "mode": "recent_history_research",
        "historical_evaluation": "retrospective_not_unseen_holdout",
        "forward_evaluation": "starts_after_definition_freeze",
        "note": (
            "使用最近四年及最新已完成行情研发。已查看的历史仅作回顾性检验；"
            "新版本冻结后才积累前瞻记录。"
        ),
    }


def research_window_metrics(result: dict, start: str, end: str) -> dict:
    """Slice an existing continuous portfolio; never reset its historical weights."""
    curve = pd.DataFrame(result.get("curve", []))
    if curve.empty:
        return {}
    curve["timestamp"] = pd.to_datetime(curve["date"], utc=True)
    begin, stop = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    window = curve.loc[curve.timestamp.between(begin, stop)]
    if window.empty:
        return {}
    prior = curve.loc[curve.timestamp < begin, "equity"]
    initial = float(prior.iloc[-1]) if len(prior) else 100_000.0
    trades = pd.DataFrame(result.get("trades", []))
    if len(trades):
        trades["timestamp"] = pd.to_datetime(trades.date, utc=True)
        trades = trades.loc[trades.timestamp.between(begin, stop)].copy()
        trades["gross_value"] = trades.quantity * trades.fill_price
    return calculate_performance_metrics(window, trades, initial_cash=initial).model_dump()


def mature_pairs(pairs: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if pairs.empty:
        return pairs
    return pairs.loc[(pairs.datetime >= start) & (pairs.label_end <= end)].copy()
