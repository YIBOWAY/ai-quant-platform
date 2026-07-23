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

_REAL_OHLCV_PROVIDERS = frozenset({"futu", "tiingo"})
_PROXY_SCOPE_WARNING = (
    "Workflow proxy only: this is not a full paper replication; country-level, "
    "earnings-window, and global-market hypothesis tests are not implemented."
)
_CALENDAR_SCOPE_WARNING = (
    "Terminal-month completeness is evaluated per symbol with a generic "
    "Monday-Friday business-month-end heuristic; exchange-specific holiday "
    "calendars are not modeled."
)


def _methodology(
    *,
    formation: str,
    data_evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scope_classification": "workflow_proxy",
        "full_paper_replication": False,
        "implemented_scope": "monthly cross-sectional long-short signal workflow",
        "omitted_paper_tests": [
            "country-level tests",
            "earnings-window tests",
            "global-market hypothesis tests",
        ],
        "data_evidence": dict(data_evidence),
        "terminal_month_completeness": {
            "method": "generic_business_month_end",
            "evaluation_scope": "per_symbol",
            "weekend_aware": True,
            "exchange_holiday_calendar": False,
        },
        "turnover": {
            "target_weights": (
                "unit long and unit short; gross target exposure 2.0 and net exposure 0.0"
            ),
            "gross_definition": "sum(abs(target_weight_t - target_weight_t_minus_1))",
            "one_way_definition": "0.5 * gross turnover",
            "legacy_metric": "cumulative_one_way",
            "initial_build_included": True,
            "initial_state": "all target weights are zero before the first rebalance",
        },
        "formation": formation,
        "reversal_signal": "past 1-month return, ranked contrarian",
        "momentum_signal": "past months t-12 through t-2 return, ranked continuation",
        "holding_period": "subsequent month",
        "price_filter": "exclude signal observations with prior-month close below $1",
    }


def _data_evidence(ohlcv: pd.DataFrame) -> dict[str, Any]:
    if "provider" not in ohlcv.columns:
        providers: list[str] = []
    else:
        providers = sorted(
            {
                str(value).strip().lower()
                for value in ohlcv["provider"].dropna().tolist()
                if str(value).strip()
            }
        )
    provider_consistent = len(providers) == 1
    sample_or_real = (
        "real"
        if provider_consistent and providers[0] in _REAL_OHLCV_PROVIDERS
        else "sample"
    )
    return {
        "actual_providers": providers,
        "provider_consistent": provider_consistent,
        "sample_or_real": sample_or_real,
    }


def _scope_warnings(data_evidence: dict[str, Any]) -> list[str]:
    warnings = [_PROXY_SCOPE_WARNING, _CALENDAR_SCOPE_WARNING]
    providers = data_evidence["actual_providers"]
    if not providers:
        warnings.append(
            "Provider evidence is unavailable; sample_or_real fails closed to sample."
        )
    elif not data_evidence["provider_consistent"]:
        warnings.append(
            "Mixed provider rows were observed; sample_or_real fails closed to sample."
        )
    elif data_evidence["sample_or_real"] != "real":
        warnings.append(
            f"Provider {providers[0]!r} is not verified as real market data; "
            "sample_or_real is sample."
        )
    return warnings


def build_reversal_momentum_replication(
    ohlcv: pd.DataFrame,
    *,
    initial_cash: float = 1.0,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Build the paper-inspired monthly long-short workflow proxy."""

    data_evidence = _data_evidence(ohlcv)
    warnings = _scope_warnings(data_evidence)
    if ohlcv.empty:
        return _empty_result(
            initial_cash,
            [*warnings, "No OHLCV rows were available."],
            data_evidence=data_evidence,
        )

    monthly = _monthly_panel(ohlcv)
    if monthly.empty or monthly["symbol"].nunique() < 2:
        return _empty_result(
            initial_cash,
            [*warnings, "At least two symbols with monthly closes are required."],
            data_evidence=data_evidence,
        )

    low_price_observations = _low_price_observation_count(monthly)
    signal_frame = _signal_frame(monthly)
    if signal_frame.empty:
        return _empty_result(
            initial_cash,
            [
                *warnings,
                "Not enough monthly history. Need roughly 14 monthly closes for "
                "12-2 momentum.",
            ],
            data_evidence=data_evidence,
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
                *warnings,
                "The selected universe did not produce any investable "
                "monthly long-short observations."
            ],
            data_evidence=data_evidence,
        )

    equity_curve = _equity_curve(composite_returns, initial_cash=initial_cash)
    metrics = calculate_performance_metrics(
        equity_curve[["timestamp", "equity"]],
        pd.DataFrame(),
        initial_cash=initial_cash,
        annualization_factor=12,
    ).model_dump()
    metrics.update(_turnover_metrics(pd.DataFrame(positions)))
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
        "methodology": _methodology(
            formation=formation,
            data_evidence=data_evidence,
        ),
        "data_evidence": data_evidence,
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
    if frame.empty:
        return pd.DataFrame(
            columns=["symbol", "timestamp", "close", "monthly_return"]
        )
    observed_ends = frame.groupby("symbol")["timestamp"].max()
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
    # Resampling labels every terminal observation as calendar month-end. Use
    # each symbol's raw last observation to exclude a genuinely in-progress
    # month, while treating a Friday before a weekend month-end as complete.
    complete_groups = []
    for symbol, group in monthly.groupby("symbol", sort=False):
        observed_end = observed_ends.loc[symbol]
        terminal_month_start = observed_end.normalize().replace(day=1)
        terminal_month_end = terminal_month_start + pd.offsets.BMonthEnd(0)
        if observed_end.normalize() < terminal_month_end.normalize():
            last_complete_month_end = observed_end - pd.offsets.MonthEnd(1)
            group = group.loc[
                group["timestamp"] <= last_complete_month_end.normalize()
            ]
        complete_groups.append(group)
    monthly = pd.concat(complete_groups, ignore_index=True)
    monthly["monthly_return"] = monthly.groupby("symbol")["close"].pct_change(
        fill_method=None
    )
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
            target_weight = (1.0 if side == "long" else -1.0) / len(rows)
            for _, row in rows.iterrows():
                positions.append(
                    {
                        "strategy": strategy,
                        "rebalance_date": pd.Timestamp(timestamp).isoformat(),
                        "return_date": return_date,
                        "symbol": row["symbol"],
                        "side": side,
                        "target_weight": target_weight,
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


def _turnover_metrics(positions: pd.DataFrame) -> dict[str, float | int]:
    if positions.empty:
        return {
            "turnover": 0.0,
            "turnover_one_way": 0.0,
            "turnover_gross": 0.0,
            "turnover_average_one_way": 0.0,
            "turnover_average_gross": 0.0,
            "turnover_initial_build_one_way": 0.0,
            "turnover_initial_build_gross": 0.0,
            "turnover_rebalances": 0,
        }

    previous_weights: dict[str, float] = {}
    cumulative_gross = 0.0
    initial_gross = 0.0
    rebalance_count = 0
    for _rebalance_date, group in positions.groupby("rebalance_date", sort=True):
        current_weights = {
            str(symbol): float(weight)
            for symbol, weight in zip(
                group["symbol"],
                group["target_weight"],
                strict=True,
            )
        }
        symbols = set(previous_weights) | set(current_weights)
        gross = sum(
            abs(current_weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        if rebalance_count == 0:
            initial_gross = gross
        cumulative_gross += gross
        previous_weights = current_weights
        rebalance_count += 1

    cumulative_one_way = cumulative_gross / 2.0
    return {
        # Keep the longstanding field, but now define it explicitly as the
        # cumulative one-way target-weight turnover instead of a fake zero.
        "turnover": cumulative_one_way,
        "turnover_one_way": cumulative_one_way,
        "turnover_gross": cumulative_gross,
        "turnover_average_one_way": cumulative_one_way / rebalance_count,
        "turnover_average_gross": cumulative_gross / rebalance_count,
        "turnover_initial_build_one_way": initial_gross / 2.0,
        "turnover_initial_build_gross": initial_gross,
        "turnover_rebalances": rebalance_count,
    }


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
        noise_by_month.index = pd.to_datetime(noise_by_month.index, utc=True)
        reversal_by_rebalance_month = reversal.copy()
        reversal_by_rebalance_month.index = (
            pd.to_datetime(reversal_by_rebalance_month.index, utc=True)
            - pd.offsets.MonthEnd(1)
        )
        aligned = pd.concat(
            [
                noise_by_month.rename("noise"),
                reversal_by_rebalance_month.rename("reversal"),
            ],
            axis=1,
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


def _empty_result(
    initial_cash: float,
    warnings: list[str],
    *,
    data_evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "paper": PAPER_METADATA,
        "methodology": _methodology(
            formation="decile long-short portfolios",
            data_evidence=data_evidence,
        ),
        "data_evidence": data_evidence,
        "metrics": {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
            "turnover_one_way": 0.0,
            "turnover_gross": 0.0,
            "turnover_average_one_way": 0.0,
            "turnover_average_gross": 0.0,
            "turnover_initial_build_one_way": 0.0,
            "turnover_initial_build_gross": 0.0,
            "turnover_rebalances": 0,
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
