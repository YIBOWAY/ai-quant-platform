"""Active-return recomputation from a *serialized* platform curve.

The v2 gate must consume the same arithmetic active-return definition that the
T2.2 ``active_metrics`` sibling block publishes, but it must not read that
document as an input (the block is display-only and pinned
``dsr_family_member=False``). Instead it re-derives the series from the raw
curve and the two are reconciled by a wiring identity in the tests.

The definition is inherited verbatim, not restated: ``_daily_returns`` funds the
first mark from ``initial_cash`` and leaves interior holes as NaN; ``_aligned``
requires the two legs to share an index and drops pairwise NaNs; the active
series is ``strategy - reference``. Both helpers are imported from
``research.active_metrics`` so there is exactly one implementation.

Two traps this module exists to avoid:

* The serialized ``platform-result.json["curve"]`` rows carry
  ``date/equity/benchmark/peer`` — there is **no** ``timestamp`` column (that
  only exists pre-serialization). The index is therefore built from ``date``.
* The initial cash comes from the caller as
  ``result.get("evaluation_initial_cash", 100_000.0)``; it is never assumed to
  be the ``10_000`` validation allocation, and both legs use the *same* value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from quant_system.research.active_metrics import _aligned, _daily_returns, _leg
from quant_system.research.evaluation_service import _hash

ACTIVE_RETURN_RULE = "strategy_minus_benchmark_daily_arithmetic"
INITIAL_CASH_RULE = "evaluation_initial_cash|fallback_100000"
DEFAULT_INITIAL_CASH = 100_000.0
_REQUIRED_COLUMNS = ("date", "equity", "benchmark")


def _empty(reason: str) -> dict[str, Any]:
    return {
        "active_returns": [],
        "equity_returns": [],
        "dates": [],
        "n_periods": 0,
        "start": None,
        "end": None,
        "initial_cash_rule": INITIAL_CASH_RULE,
        "returns_digest": None,
        "dates_digest": None,
        "reason": reason,
    }


def recompute_active_returns(
    curve_rows: Sequence[Mapping[str, Any]], *, initial_cash: float
) -> dict[str, Any]:
    """Rebuild the arithmetic daily active series from serialized curve rows."""
    if isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float)):
        raise ValueError("gate_v2_initial_cash_invalid")
    if not math.isfinite(float(initial_cash)) or float(initial_cash) <= 0.0:
        raise ValueError("gate_v2_initial_cash_invalid")
    if not curve_rows:
        return _empty("no_curve")
    frame = pd.DataFrame([dict(row) for row in curve_rows])
    if not set(_REQUIRED_COLUMNS).issubset(frame.columns):
        return _empty("active_curve_missing_columns")
    index = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    equity_returns = _daily_returns(_leg(frame, "equity", index), float(initial_cash))
    benchmark_returns = _daily_returns(_leg(frame, "benchmark", index), float(initial_cash))
    aligned = _aligned(equity_returns, benchmark_returns)
    if aligned.empty:
        return _empty("insufficient_observations")
    strategy = aligned["strategy"]
    active = strategy - aligned["reference"]
    active_values = [float(value) for value in active.tolist()]
    equity_values = [float(value) for value in strategy.tolist()]
    dates = [stamp.strftime("%Y-%m-%d") for stamp in aligned.index]
    return {
        "active_returns": active_values,
        "equity_returns": equity_values,
        "dates": dates,
        "n_periods": len(active_values),
        "start": dates[0],
        "end": dates[-1],
        "initial_cash_rule": INITIAL_CASH_RULE,
        "returns_digest": _hash(active_values),
        "dates_digest": _hash(dates),
        "reason": None,
    }


def active_series(
    *,
    active_returns: Sequence[float],
    equity_returns: Sequence[float],
    dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Assemble an ``ActiveSeries`` from already-computed arrays (harness seam).

    Used by the random-control harness, which receives raw return arrays from a
    variant factory rather than a serialized curve. The digest contract is
    identical to :func:`recompute_active_returns`.
    """
    active_values = [float(value) for value in active_returns]
    equity_values = [float(value) for value in equity_returns]
    if len(active_values) != len(equity_values):
        raise ValueError("gate_v2_active_equity_length_mismatch")
    date_labels = (
        [str(label)[:10] for label in dates]
        if dates is not None
        else [f"t{position:05d}" for position in range(len(active_values))]
    )
    return {
        "active_returns": active_values,
        "equity_returns": equity_values,
        "dates": date_labels,
        "n_periods": len(active_values),
        "start": date_labels[0] if date_labels else None,
        "end": date_labels[-1] if date_labels else None,
        "initial_cash_rule": INITIAL_CASH_RULE,
        "returns_digest": _hash(active_values),
        "dates_digest": _hash(date_labels),
        "reason": None if active_values else "insufficient_observations",
    }
