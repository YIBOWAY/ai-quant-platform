"""Health checks v2 — three independent total-return sub-verdicts.

Measured on the strategy's *own* (benchmark-aligned) return stream, not on the
active series, so they answer "is this a usable sleeve at all" independently of
the DSR question. Each sub-check carries its own reason code; a failure in one
never hides another.

``PSR_total > 0.5`` is a **floor, not a discriminator**: with an empty trial
family the DSR threshold is 0, so ``Phi(z) >= 0.5`` is exactly ``Sharpe >= 0``.
It is reported as such and the design's honesty note is carried on the record.
Drawdown is the loss cap (tighter of the two proposals); volatility is the
dispersion physical (looser), so a compliant long-only sleeve is not misfired.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from quant_system.research.trials import deflated_sharpe_ratio, performance_from_daily_returns

from ._constants import (
    HEALTH_ANNUAL_VOL_MAX,
    HEALTH_MAX_DRAWDOWN_MAX,
    HEALTH_PSR0_MIN,
    HEALTH_V2_SCHEMA_VERSION,
)

ANNUALIZATION = 252
VOL_DDOF = 1
PSR_FLOOR_NOTE = "PSR>0.5 <=> Sharpe>0 (floor, not a discriminator)"


def _annual_volatility(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((item - mean) ** 2 for item in values) / (n - VOL_DDOF)
    return math.sqrt(variance) * math.sqrt(ANNUALIZATION)


def health_checks_v2(*, active: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    equity = [
        float(value)
        for value in active.get("equity_returns", [])
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    perf = performance_from_daily_returns(equity)
    psr_min = float(config.get("health_psr0_min", HEALTH_PSR0_MIN))
    dd_max = float(config.get("health_max_drawdown_max", HEALTH_MAX_DRAWDOWN_MAX))
    vol_max = float(config.get("health_annual_vol_max", HEALTH_ANNUAL_VOL_MAX))
    psr_value: float | None = None
    if perf["sharpe_period"] is not None and perf["n_periods"] >= 2:
        psr_value = deflated_sharpe_ratio(
            sharpe=perf["sharpe_period"],
            n_periods=perf["n_periods"],
            skewness=perf["skewness"],
            kurtosis=perf["kurtosis"],
            trial_sharpes=[],
        )["value"]
    volatility = _annual_volatility(equity)

    if psr_value is None:
        psr = {
            "value": None,
            "min": psr_min,
            "passed": False,
            "reason": "insufficient_observations",
        }
    else:
        psr = {
            "value": psr_value,
            "min": psr_min,
            "passed": psr_value > psr_min,
            "reason": None if psr_value > psr_min else "psr_total_below_floor",
        }
    drawdown_value = perf["max_drawdown"]
    if drawdown_value is None:
        drawdown = {
            "value": None,
            "max": dd_max,
            "passed": False,
            "reason": "insufficient_observations",
        }
    else:
        drawdown = {
            "value": drawdown_value,
            "max": dd_max,
            "passed": drawdown_value <= dd_max,
            "reason": None if drawdown_value <= dd_max else "max_drawdown_above_cap",
        }
    if volatility is None:
        volatility_block = {
            "value": None,
            "max": vol_max,
            "passed": False,
            "reason": "insufficient_observations",
        }
    else:
        volatility_block = {
            "value": volatility,
            "max": vol_max,
            "passed": volatility <= vol_max,
            "reason": None if volatility <= vol_max else "annual_volatility_above_cap",
        }
    reasons = [
        block["reason"]
        for block in (psr, drawdown, volatility_block)
        if block["reason"] is not None
    ]
    return {
        "schema_version": HEALTH_V2_SCHEMA_VERSION,
        "psr_total": psr,
        "max_drawdown": drawdown,
        "annual_volatility": volatility_block,
        "vol_ddof": VOL_DDOF,
        "psr_floor_note": PSR_FLOOR_NOTE,
        "passed": not reasons,
        "reasons": reasons,
    }
