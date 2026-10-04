"""Pure fixed-profile evaluations using the real Platform backtest engine.

Only the supplied prices are read. No provider, trial, candidate, account or
artifact is created. Month boundaries are identified from consecutive observed
benchmark sessions; a partial final month never acquires a future month-end label.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig, TargetWeight
from quant_system.research.active_metrics import active_metrics
from quant_system.research.reference_backtests import (
    COMMISSION_BPS,
    INITIAL_CASH,
    SLIPPAGE_BPS,
    _costs,
    _date,
    _metrics,
    _prepare_prices,
)
from quant_system.research.study_profiles import list_study_profiles


class _ScheduledTargets:
    def __init__(self, targets: dict[pd.Timestamp, dict[str, float]]):
        self.targets = targets

    def target_weights(self, timestamp):
        targets = self.targets.get(pd.Timestamp(timestamp))
        if targets is None:
            return None
        return [
            TargetWeight(timestamp=timestamp, symbol=symbol, target_weight=weight)
            for symbol, weight in sorted(targets.items())
        ]


def _run(frame, targets, *, gross=False):
    config = BacktestConfig(
        initial_cash=INITIAL_CASH,
        commission_bps=0.0 if gross else COMMISSION_BPS,
        slippage_bps=0.0 if gross else SLIPPAGE_BPS,
    )
    return BacktestEngine(config).run(frame, _ScheduledTargets(targets))


def _month_boundaries(sessions):
    return [
        (previous, current)
        for previous, current in zip(sessions[:-1], sessions[1:], strict=True)
        if (previous.year, previous.month) != (current.year, current.month)
    ]


def _wilder_rsi(prices: pd.Series, period: int = 2) -> pd.Series:
    """Wilder's arithmetic seed followed by alpha=1/period smoothing.

    A missing observation breaks the chain; no missing price or return is carried.
    A completely flat seeded window has RSI 50, gains only 100, losses only 0.
    """
    output = np.full(len(prices), np.nan)
    previous, average_gain, average_loss = np.nan, 0.0, 0.0
    count = 0
    for i, value in enumerate(prices.to_numpy(dtype=float)):
        if not np.isfinite(value):
            previous, count, average_gain, average_loss = np.nan, 0, 0.0, 0.0
            continue
        if not np.isfinite(previous):
            previous = value
            continue
        change = value - previous
        previous = value
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if count < period:
            average_gain += gain / period
            average_loss += loss / period
            count += 1
            if count < period:
                continue
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        total = average_gain + average_loss
        output[i] = 100 * average_gain / total if total > 0 else 50.0
    return pd.Series(output, index=prices.index)


def _rsi_signals(close, profile, start, end):
    symbol = profile["peer_symbols"][0]
    values = close[symbol]
    rsi, average = _wilder_rsi(values), values.rolling(200, min_periods=200).mean()
    targets, records, invested = {}, [], False
    for position in range(2, len(values) - 1):
        signal, trade = values.index[position], values.index[position + 1]
        if not start <= trade <= end:
            continue
        r1, r2, current = rsi.iloc[position - 2 : position + 1]
        mean, price = average.iloc[position], values.iloc[position]
        if not np.isfinite([r1, r2, current, mean, price]).all():
            continue
        weights = None
        action = "hold" if invested else "flat"
        if invested and current > 75:
            weights, invested, action = {}, False, "sell"
        elif not invested and price > mean and r1 < 65 and r1 > r2 > current:
            weights, invested, action = {symbol: 1.0}, True, "buy"
        if weights is not None:
            targets[trade] = weights
        records.append(
            {
                "signal_date": signal.date().isoformat(),
                "trade_date": trade.date().isoformat(),
                "targets": weights,
                "action": action,
                "ready": True,
                "eligible_count": 1,
                "eligible_symbols": [symbol],
                "scores": [
                    {
                        "symbol": symbol,
                        "rsi_day1": float(r1),
                        "rsi_day2": float(r2),
                        "rsi2": float(current),
                        "sma200": float(mean),
                        "close": float(price),
                    }
                ],
            }
        )
    return targets, records


def _monthly_signals(close, profile, start, end, formula_scores=None):
    boundaries = _month_boundaries(close.index)
    month_dates = [signal for signal, _ in boundaries]
    monthly = close.reindex(month_dates)
    monthly.index = pd.PeriodIndex([f"{d.year}-{d.month:02d}" for d in month_dates], freq="M")
    # Explicit calendar reindex leaves absent months missing, never shifts by
    # the count of available months or carries an old price to a new month-end.
    if len(monthly):
        monthly = monthly.reindex(pd.period_range(monthly.index[0], monthly.index[-1], freq="M"))
    sma10 = monthly.rolling(10, min_periods=10).mean()
    complete13 = monthly.rolling(13, min_periods=13).count().eq(13)
    momentum = (monthly.shift(1) / monthly.shift(12) - 1).where(complete13)
    reversal = -(monthly / monthly.shift(1) - 1)
    daily_vol = close.pct_change(fill_method=None).rolling(252, min_periods=252).std(ddof=1)
    relative = sum(monthly / monthly.shift(window) - 1 for window in (3, 6, 12)) / 3
    relative = relative.where(complete13)
    targets, records = {}, []
    symbol = profile["peer_symbols"][0]
    universe = profile["peer_symbols"]
    for signal, trade in boundaries:
        if not start <= trade <= end:
            continue
        period = pd.Period(f"{signal.year}-{signal.month:02d}", freq="M")
        family = profile["family"]
        if family == "index_trend":
            price, average = monthly.loc[period, symbol], sma10.loc[period, symbol]
            if not np.isfinite(price) or not np.isfinite(average):
                continue
            weights = {symbol if price > average else "SHY": 1.0}
            eligible, scores = (
                [symbol],
                [{"symbol": symbol, "close": float(price), "sma10": float(average)}],
            )
        else:
            if family == "formula_hypothesis":
                valid = (
                    formula_scores.loc[signal, universe]
                    .where(momentum.loc[period, universe].notna())
                    .dropna()
                )
                scores = [{"symbol": key, "score": float(value)} for key, value in valid.items()]
            elif family == "price_multifactor":
                factors = pd.DataFrame(
                    {
                        "momentum_rank": momentum.loc[period, universe],
                        "low_vol_rank": -daily_vol.loc[signal, universe],
                        "reversal_rank": reversal.loc[period, universe],
                    }
                ).dropna()
                ranks = factors.rank(method="average", pct=True)
                ranks["score"] = ranks.mean(axis=1)
                scores = [
                    {"symbol": key, **{k: float(v) for k, v in row.items()}}
                    for key, row in ranks.iterrows()
                ]
            else:
                value = relative if family == "asset_momentum" else momentum
                valid = value.loc[period, universe].dropna()
                scores = [{"symbol": key, "score": float(value)} for key, value in valid.items()]
            scores.sort(key=lambda row: (-row["score"], row["symbol"]))
            eligible = sorted(row["symbol"] for row in scores)
            top_n = profile["top_n"]
            if len(eligible) < top_n:
                # No partially warmed top-N comparison is silently relabelled
                # as a fully formed strategy; previously held names are exited.
                weights = {}
            else:
                weights = {}
                for score in scores[:top_n]:
                    selected = score["symbol"]
                    if profile["defensive_symbol"] and not (
                        monthly.loc[period, selected] > sma10.loc[period, selected]
                    ):
                        selected = profile["defensive_symbol"]
                    weights[selected] = weights.get(selected, 0.0) + 1.0 / top_n
        targets[trade] = weights
        records.append(
            {
                "signal_date": signal.date().isoformat(),
                "trade_date": trade.date().isoformat(),
                "targets": weights,
                "eligible_count": len(eligible),
                "eligible_symbols": eligible,
                "ready": len(eligible) >= (profile["top_n"] or 1),
                "scores": scores,
            }
        )
    return targets, records


def _peer_schedule(profile, evaluation_sessions, records):
    symbols = profile["peer_symbols"]
    if len(symbols) == 1:
        return {evaluation_sessions[0]: {symbols[0]: 1.0}}
    return {
        _date(record["trade_date"]): (
            {symbol: 1.0 / len(record["eligible_symbols"]) for symbol in record["eligible_symbols"]}
            if record["ready"]
            else {}
        )
        for record in records
    }


def _period_row(curve, results, *, start, end, label):
    group = curve.loc[curve.timestamp.between(start, end)]
    row = {"label": label, "start": start.date().isoformat(), "end": end.date().isoformat()}
    for field, key, result in zip(
        ("equity", "benchmark", "peer"),
        ("metrics", "benchmark_metrics", "peer_metrics"),
        results,
        strict=True,
    ):
        previous = curve.loc[curve.timestamp < start, field]
        initial = float(previous.iloc[-1]) if len(previous) else INITIAL_CASH
        trades = result.trade_blotter
        if len(trades):
            trades = trades.loc[trades.timestamp.between(start, end)]
        row[key] = _metrics(
            group[["timestamp", field]].rename(columns={field: "equity"}), trades, initial
        )
    row["sessions"] = len(group)
    row["status"] = "available" if len(group) else "unavailable"
    return row


def _unavailable(profile, status, reason):
    empty = _metrics(pd.DataFrame(), pd.DataFrame(), INITIAL_CASH)
    return {
        "profile": profile,
        "status": status,
        "reason": reason,
        "diagnostic": reason,
        "metrics": empty.copy(),
        "benchmark_metrics": empty.copy(),
        "peer_metrics": empty.copy(),
        "gross_metrics": empty.copy(),
        "active_metrics": None,
        "curve": [],
        "by_year": [],
        "splits": {},
        "costs": None,
        "average_exposure": None,
        "trade_count": 0,
        "signals": [],
        "trades": [],
    }


def run_profile(prices: pd.DataFrame, profile_id: str, *, start, end) -> dict:
    """Evaluate fixed rules from close-known data; malformed/missing data fails visibly.

    ``prices`` uses the existing Futu/QFQ/1d reference schema, including pre-start
    warmup bars. Dates are inclusive UTC-normalized session dates. Unknown profile
    IDs raise KeyError; data failures return ``failed`` without partial metrics.
    """
    profile = next((p for p in list_study_profiles() if p["id"] == profile_id), None)
    if profile is None:
        raise KeyError(f"unknown study profile {profile_id!r}")
    try:
        return _evaluate(prices, profile, _date(start), _date(end))
    except (ValueError, KeyError) as exc:
        return _unavailable(profile, "failed", str(exc))


def run_formula_profile(
    prices: pd.DataFrame, expression: str, *, start, end, proposal_id: str, title: str
) -> dict:
    """Evaluate one frozen, unregistered hypothesis using the same stock protocol."""
    from quant_system.d34.qlib_expr import compile_qlib_expr

    profile = next(p for p in list_study_profiles() if p["id"] == "stocks_momentum_12_2")
    profile.update(
        {
            "id": f"rdagent:{proposal_id}",
            "name": title,
            "description": "RD-Agent固定公式假说的历史评价",
            "family": "formula_hypothesis",
            "proposal_id": proposal_id,
            "registered": False,
            "hypothesis_status": "unverified",
            "expression": expression,
            "formation": "与24股动量同13个月末历史，另需max(252,公式lookback)完整日线窗口",
            "rules": ["仅用白名单编译后的公式值排序，前5等权月调仓，其余执行与同池对照规则不变。"],
        }
    )
    profile["limitations"].append("RD-Agent提出的未注册假说；历史回测不授予候选资格、不证明alpha。")
    try:
        compiled = compile_qlib_expr(expression)
        profile.update(
            {
                "expression": compiled.qlib,
                "formula_lookback": compiled.lookback,
                "eligibility_window": max(252, compiled.lookback),
            }
        )
        return _evaluate(prices, profile, _date(start), _date(end), compiled=compiled)
    except (ValueError, KeyError) as exc:
        return _unavailable(profile, "failed", str(exc))


def _formula_scores(frame, sessions, profile, compiled):
    fields = set(re.findall(r"\$([a-z]+)", compiled.qlib)) | {"close"}
    if fields - set(frame.columns):
        raise ValueError("study_formula_missing_fields:" + ",".join(sorted(fields - set(frame))))
    index = pd.MultiIndex.from_product(
        [sessions, profile["peer_symbols"]], names=["timestamp", "symbol"]
    )
    dense = frame.set_index(["timestamp", "symbol"]).reindex(index).reset_index()
    dense = dense.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    for field in fields:
        dense[field] = pd.to_numeric(dense[field], errors="raise")
    complete = np.isfinite(dense[sorted(fields)]).all(axis=1)
    window = profile["eligibility_window"]
    eligible = complete.groupby(dense.symbol, sort=False).transform(
        lambda values: values.rolling(window, min_periods=window).sum().eq(window)
    )
    # Only the existing AST-whitelisted compiler's generated body is executed;
    # neither model-authored Python nor candidate modules are loaded.
    values = eval(compiled.pandas_body, {"__builtins__": {}, "frame": dense, "np": np})  # noqa: S307
    dense["score"] = pd.Series(values, index=dense.index).where(eligible)
    dense["score"] = dense.score.replace([np.inf, -np.inf], np.nan)
    return dense.pivot(index="timestamp", columns="symbol", values="score")


def _evaluate(prices, profile, start, end, *, compiled=None):
    if start > end:
        raise ValueError("study_invalid_date_range")
    frame = _prepare_prices(prices)
    needed = set(profile["symbols"]) | {profile["benchmark_symbol"]}
    missing = needed - set(frame.symbol)
    if missing:
        raise ValueError("study_missing_symbols:" + ",".join(sorted(missing)))
    frame = frame.loc[frame.symbol.isin(needed) & (frame.timestamp <= end)]
    benchmark = profile["benchmark_symbol"]
    sessions = pd.DatetimeIndex(frame.loc[frame.symbol == benchmark, "timestamp"].sort_values())
    evaluation_sessions = sessions[sessions >= start]
    if not len(evaluation_sessions):
        return _unavailable(profile, "unavailable", "study_no_evaluation_sessions")
    # A missing benchmark bar must not silently remove a real asset session.
    if set(frame.timestamp) - set(sessions):
        raise ValueError("study_benchmark_session_missing")
    close = frame.pivot(index="timestamp", columns="symbol", values="close").reindex(sessions)
    if profile["family"] == "rsi_reversion":
        targets, records = _rsi_signals(close, profile, start, end)
    else:
        formula_scores = _formula_scores(frame, sessions, profile, compiled) if compiled else None
        targets, records = _monthly_signals(close, profile, start, end, formula_scores)
    if not any(record["ready"] for record in records):
        return _unavailable(profile, "unavailable", "study_no_signal_with_complete_history")
    evaluation = frame.loc[frame.timestamp.isin(evaluation_sessions)]
    result = _run(evaluation, targets)
    gross = _run(evaluation, targets, gross=True)
    benchmark_result = _run(
        evaluation.loc[evaluation.symbol == benchmark], {evaluation_sessions[0]: {benchmark: 1.0}}
    )
    peer_targets = _peer_schedule(profile, evaluation_sessions, records)
    peer_result = _run(evaluation, peer_targets)
    curve = result.equity_curve[["timestamp", "equity"]].copy()
    for key, other in (("benchmark", benchmark_result), ("peer", peer_result)):
        if not curve.timestamp.equals(other.equity_curve.timestamp):
            raise ValueError("study_comparison_sessions_mismatch")
        curve[key] = other.equity_curve.equity.to_numpy()
    results = (result, benchmark_result, peer_result)
    years = [
        {
            "year": int(year),
            **_period_row(
                curve,
                results,
                start=group.timestamp.iloc[0],
                end=group.timestamp.iloc[-1],
                label=str(year),
            ),
        }
        for year, group in curve.groupby(curve.timestamp.dt.year, sort=True)
    ]
    split_dates = (
        ("train", "2018-01-01", "2021-12-31"),
        ("validation", "2022-01-01", "2024-12-31"),
        ("test", "2025-01-01", max(end, _date("2025-01-01")).date().isoformat()),
    )
    splits = {
        label: _period_row(curve, results, start=_date(lo), end=_date(hi), label=label)
        for label, lo, hi in split_dates
    }
    equity = result.equity_curve
    exposure = equity.market_value.div(equity.equity)
    risk_positions = result.positions.loc[result.positions.symbol != profile["defensive_symbol"]]
    risk_value = (
        risk_positions.groupby("timestamp")
        .market_value.sum()
        .reindex(equity.timestamp, fill_value=0)
    )
    risk_exposure = risk_value.to_numpy() / equity.equity.to_numpy()
    trades = [
        {
            "date": r.timestamp.date().isoformat(),
            "symbol": r.symbol,
            "side": r.side,
            "quantity": float(r.quantity),
            "requested_price": float(r.requested_price),
            "fill_price": float(r.fill_price),
            "commission": float(r.commission),
        }
        for r in result.trade_blotter.itertuples(index=False)
    ]
    return {
        "profile": profile,
        "status": "available",
        "reason": None,
        "diagnostic": None,
        "metrics": _metrics(equity, result.trade_blotter, INITIAL_CASH),
        "gross_metrics": _metrics(gross.equity_curve, gross.trade_blotter, INITIAL_CASH),
        "benchmark_metrics": _metrics(
            benchmark_result.equity_curve, benchmark_result.trade_blotter, INITIAL_CASH
        ),
        "peer_metrics": _metrics(peer_result.equity_curve, peer_result.trade_blotter, INITIAL_CASH),
        "active_metrics": active_metrics(
            curve, initial_cash=INITIAL_CASH, benchmark_symbol=benchmark
        ),
        "curve": [
            {
                "date": r.timestamp.date().isoformat(),
                "equity": float(r.equity),
                "benchmark": float(r.benchmark),
                "peer": float(r.peer),
            }
            for r in curve.itertuples(index=False)
        ],
        "by_year": years,
        "splits": splits,
        "costs": _costs(result.trade_blotter),
        "benchmark_costs": _costs(benchmark_result.trade_blotter),
        "peer_costs": _costs(peer_result.trade_blotter),
        "average_exposure": float(exposure.mean()),
        "average_risk_exposure": float(np.mean(risk_exposure)),
        "trade_count": len(trades),
        "signals": records,
        "trades": trades,
        "peer_signals": [
            {"trade_date": date.date().isoformat(), "targets": weights}
            for date, weights in peer_targets.items()
        ],
        "eligibility": {
            "peer_uses_strategy_eligible_set": len(profile["peer_symbols"]) > 1,
            "method": (
                "200个连续有效收盘与Wilder RSI2；单指数peer为全窗口买入持有。"
                if profile["family"] == "rsi_reversion"
                else "10个完整月末价格；单指数peer为全窗口买入持有。"
                if profile["family"] == "index_trend"
                else f"完整13个月末价格及{profile['eligibility_window']}个完整公式输入日线。"
                if profile["family"] == "formula_hypothesis"
                else "完整13个月末价格；三因子另需252个连续有效日收益；同一期完整字段交集内排名。"
            ),
            "peer_method": "与策略同日、同历史资格内全体等权月调仓；不足Top N时共同持有现金。"
            if len(profile["peer_symbols"]) > 1
            else "原指数ETF于评价首日开盘买入持有，承担相同交易费用。",
            "signal_sessions": len(records),
            "ready_signal_sessions": sum(record["ready"] for record in records),
            "eligible_counts": [
                {"signal_date": record["signal_date"], "count": record["eligible_count"]}
                for record in records
            ],
        },
        "start": evaluation_sessions[0].date().isoformat(),
        "end": evaluation_sessions[-1].date().isoformat(),
        "source": "futu",
        "price_adjustment": "qfq",
        "frequency": "daily",
        "evaluation_note": (
            "连续组合按日历分区、不重置持仓；规则固定无调参，不称完全未查看的历史样本外。"
        ),
        "coverage": {
            "requested_start": start.date().isoformat(),
            "requested_end": end.date().isoformat(),
            "loaded_start": frame.timestamp.min().date().isoformat(),
            "loaded_end": frame.timestamp.max().date().isoformat(),
            "evaluation_sessions": len(evaluation_sessions),
            "universe_count": len(profile["peer_symbols"]),
            "price_fill": "none",
            "holdings_missing_price": "failed",
        },
    }
