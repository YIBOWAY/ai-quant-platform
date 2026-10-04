"""The preregistered 27 T2.4 objects, with default definitions held fixed.

Statistical evaluation lives in factors.scorecard. This module only computes
registered factors, whitelist-compiled expressions, and the three PMF components.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.d34.qlib_expr import compile_qlib_expr
from quant_system.factors.pipeline import compute_factor_pipeline
from quant_system.factors.registry import build_factor_registry

REGISTRY_OBJECTS = (
    ("momentum", 20, "higher_is_better"),
    ("volatility", 20, "lower_is_better"),
    ("liquidity", 20, "higher_is_better"),
    ("rsi", 14, "lower_is_better"),
    ("macd", 12, "higher_is_better"),
    ("agent_candidate_wave2_sceneb_mom20_v3", 20, "higher_is_better"),
    ("paper_reversal_momentum_proxy_v2", 252, "higher_is_better"),
)
# IDs and formula strings are frozen from the 09-20 preregistration, not selected
# on observed performance. Equivalent variants remain distinct registered trials.
FORMULA_OBJECTS = (
    ("fcc06e9c023c8e3f", "($close/Max($close,252))", 252),
    ("e9ec66887a62cb89", "Mean((Abs((Delta($close,1)/Ref($close,1)))/($close*$volume)),126)", 127),
    ("68350bf276a2a793", "-(Max((Delta($close,1)/Ref($close,1)),21))", 22),
    (
        "9e56df092c6f2fb0",
        "(Mean((Delta($close,1)/Ref($close,1)),60)/Std((Delta($close,1)/Ref($close,1)),60))",
        61,
    ),
    ("c62d1250f8302415", "Mean((($open-Ref($close,1))/Ref($close,1)),21)", 22),
    ("b66b213aacc0fc66", "Mean(((Ref($close,1)-$close)/Ref($close,1)),5)", 6),
    ("6d955a021e897eee", "Mean((($close-$open)/$open),21)", 21),
    ("588af785d5b97dd5", "(Mean($volume,5)/Mean($volume,49))", 49),
    ("a318aeea101855ed", "Mean(Log($close),30)", 30),
    ("935e569eb6d466ac", "Mean((($high-$low)/$low),30)", 30),
    ("8ec472f12dee0d1f", "Mean(Log($high),30)", 30),
    ("a974503e7b46e115", "Mean((Log($high)-Log($low)),30)", 30),
    ("90a6dd4e7a8f06c4", "Mean(Log(($high/$low)),30)", 30),
    ("97bfebd272e499bd", "Mean((Log($low)-Log($high)),30)", 30),
    ("ef9ac7ff3d5608d3", "(Abs(Delta($close,20))/Sum(Abs(Delta($close,1)),20))", 21),
    ("b3ac9f6ae9705b36", "Mean(Sign(Delta($close,1)),20)", 21),
    ("7f12cf82b242c0b5", "Mean(((Abs(Delta($close,1))-Delta($close,1))/Ref($close,1)),63)", 64),
)
PMF_OBJECTS = (
    ("pmf_momentum_12_2", 252, "monthly.shift(1)/monthly.shift(12)-1; complete13"),
    ("pmf_low_vol_252", 252, "-daily_return.rolling(252,min_periods=252).std(ddof=1)"),
    ("pmf_reversal_1m", 21, "-(monthly/monthly.shift(1)-1)"),
)


def frozen_factor_manifest() -> dict:
    registry = build_factor_registry()
    objects = []
    for factor_id, lookback, direction in REGISTRY_OBJECTS:
        factor = registry.create(factor_id)
        if (factor.lookback, factor.direction) != (lookback, direction):
            raise ValueError(f"registered_definition_drift:{factor_id}")
        source = Path(inspect.getfile(type(factor))).read_bytes()
        objects.append(
            {
                "factor_id": factor_id,
                "kind": "registry",
                "lookback": lookback,
                "direction": direction,
                "frequency": "daily",
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "duplicate_group": "mom20"
                if "mom20" in factor_id or factor_id == "momentum"
                else None,
            }
        )
    for suffix, expression, lookback in FORMULA_OBJECTS:
        compiled = compile_qlib_expr(expression)
        if (
            hashlib.sha256(compiled.qlib.encode()).hexdigest()[:16] != suffix
            or compiled.lookback != lookback
        ):
            raise ValueError(f"compiled_definition_drift:formula_{suffix}")
        objects.append(
            {
                "factor_id": f"formula_{suffix}",
                "kind": "formula",
                "qlib": compiled.qlib,
                "lookback": lookback,
                "direction": "higher_is_better",
                "frequency": "daily",
                "compiled_sha256": hashlib.sha256(compiled.pandas_body.encode()).hexdigest(),
                "duplicate_group": "log_range_30"
                if suffix in {"a974503e7b46e115", "90a6dd4e7a8f06c4", "97bfebd272e499bd"}
                else None,
                "duplicate_sign": -1 if suffix == "97bfebd272e499bd" else 1,
            }
        )
    objects.extend(
        {
            "factor_id": key,
            "kind": "pmf_component",
            "lookback": lookback,
            "direction": "higher_is_better",
            "frequency": "month_end",
            "definition": definition,
        }
        for key, lookback, definition in PMF_OBJECTS
    )
    manifest = {
        "schema_version": "qs.wide_factor_manifest/v1",
        "objects": objects,
        "signal_window": ["2016-01-01", "2026-08-31"],
        "horizons": [1, 5, 21],
        "quantiles": 5,
        "benchmark": "SPY",
        "membership_mode": "point_in_time",
        "factor_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "eligibility": "complete_exchange_sessions_no_fill; signal_membership_only",
        "duplicate_policy": "retain_all_27_objects_and_report_equivalences",
    }
    manifest["digest"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest


def _result(frame: pd.DataFrame, factor_id: str, values: pd.Series, lookback: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": frame.symbol,
            "signal_ts": frame.timestamp,
            "tradeable_ts": frame.groupby("symbol", sort=False).timestamp.shift(-1),
            "factor_id": factor_id,
            "factor_version": "wide_v1",
            "factor_name": factor_id,
            "lookback": lookback,
            "value": values,
        }
    ).replace([np.inf, -np.inf], np.nan)


def build_wide_factor_values(
    ohlcv: pd.DataFrame,
    membership: pd.DataFrame,
    *,
    calendar: pd.DatetimeIndex,
    factor_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Compute before membership filtering, retaining missing sessions as missing.

    Dense rows contain NaN, never invented prices. This prevents windows from
    silently stepping across absent sessions and guarantees future perturbations
    cannot change an earlier signal. The benchmark is never a stock candidate.
    """
    frozen = frozen_factor_manifest()
    selected = (
        set(factor_ids) if factor_ids is not None else {x["factor_id"] for x in frozen["objects"]}
    )
    if not selected or selected - {x["factor_id"] for x in frozen["objects"]}:
        raise ValueError("unregistered_wide_factor_selection")
    symbols = sorted(set(membership.symbol) & set(ohlcv.symbol))
    if not symbols:
        return pd.DataFrame(columns=["symbol", "signal_ts", "tradeable_ts", "factor_id", "value"])
    index = pd.MultiIndex.from_product([symbols, calendar], names=["symbol", "timestamp"])
    dense = ohlcv.set_index(["symbol", "timestamp"]).reindex(index).reset_index()
    complete = np.isfinite(dense[["open", "high", "low", "close", "volume"]]).all(axis=1)
    registry = build_factor_registry()
    outputs = []
    registered = [registry.create(k) for k, _, _ in REGISTRY_OBJECTS if k in selected]
    if registered:
        outputs.append(compute_factor_pipeline(dense, factors=registered))
    for suffix, expression, lookback in FORMULA_OBJECTS:
        if f"formula_{suffix}" not in selected:
            continue
        compiled = compile_qlib_expr(expression)
        eligible = complete.groupby(dense.symbol, sort=False).transform(
            lambda x, window=lookback: x.rolling(window, min_periods=window).sum().eq(window)
        )
        values = eval(compiled.pandas_body, {"__builtins__": {}, "frame": dense, "np": np})  # noqa: S307
        outputs.append(
            _result(dense, f"formula_{suffix}", pd.Series(values).where(eligible), lookback)
        )
    close = dense.pivot(index="timestamp", columns="symbol", values="close")
    month_days = pd.Series(calendar, index=calendar).groupby(calendar.strftime("%Y-%m")).last()
    monthly = close.reindex(pd.DatetimeIndex(month_days))
    monthly.index = monthly.index.tz_localize(None).to_period("M")
    monthly = monthly.reindex(pd.period_range(monthly.index.min(), monthly.index.max(), freq="M"))
    complete13 = monthly.rolling(13, min_periods=13).count().eq(13)
    components = {
        "pmf_momentum_12_2": (monthly.shift(1) / monthly.shift(12) - 1).where(complete13),
        "pmf_reversal_1m": -(monthly / monthly.shift(1) - 1),
        "pmf_low_vol_252": -close.pct_change(fill_method=None)
        .rolling(252, min_periods=252)
        .std(ddof=1),
    }
    for factor_id, lookback, _ in PMF_OBJECTS:
        if factor_id not in selected:
            continue
        values = components[factor_id].copy()
        if factor_id != "pmf_low_vol_252":
            lookup = {pd.Period(key, freq="M"): value for key, value in month_days.items()}
            values.index = pd.DatetimeIndex([lookup.get(p, pd.NaT) for p in values.index])
        values = values.reindex(pd.DatetimeIndex(month_days)).rename_axis(
            index="timestamp", columns="symbol"
        )
        stacked = values.stack(future_stack=True).rename("value").reset_index()
        stacked["signal_ts"] = stacked.pop("timestamp")
        stacked["factor_id"] = factor_id
        stacked["lookback"] = lookback
        stacked["factor_version"] = "wide_v1"
        stacked["factor_name"] = factor_id
        stacked["tradeable_ts"] = stacked.signal_ts.map(
            dict(zip(calendar[:-1], calendar[1:], strict=True))
        )
        outputs.append(stacked)
    result = pd.concat(outputs, ignore_index=True)
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=["value"])
    result = result.merge(
        membership[["symbol", "signal_ts"]], on=["symbol", "signal_ts"], validate="many_to_one"
    )
    return result.sort_values(["factor_id", "symbol", "signal_ts"]).reset_index(drop=True)
