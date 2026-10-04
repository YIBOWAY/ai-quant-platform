"""Concentration, residual diagnosis and paired increment for gate v2.

Three distinct rules with three distinct authorities:

* **New independent sleeve concentration** — the raw daily-return Pearson
  against each already-hung sleeve (``date_aligned_correlation`` with >=20 shared
  days, else ``returns_correlation``), maximum over sleeves. This is an
  equivalent quantity to v1's rule and **can** block. ``CORRELATION_MAX_V2`` is
  an alias of v1's ``FACTOR_CORRELATION_MAX`` — one truth source, not two.
* **Residual correlation** — each leg hedged against the benchmark by full-sample
  OLS (the ``scripts/random_top5_null.ols_resid`` convention), then Pearson of
  the two residual streams, calibrated against a per-universe null p95 from a
  circular block bootstrap that breaks cross-leg alignment while preserving each
  leg's own autocorrelation. **Diagnostic only** — never blocks on its own.
* **Upgrade of an existing version** — a studentized paired block bootstrap of
  the annualized Sharpe difference, delegated to
  ``active_metrics.paired_block_bootstrap``. Accepted iff the interval is ready
  and ``ci95_low > 0``. Called only on an explicit increment path; it must never
  touch ``_existing_hang_sleeve``'s no-new-gate recovery semantics.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from numbers import Real
from typing import Any

import numpy as np

from quant_system.research.active_metrics import BOOTSTRAP_BLOCK_LENGTH, paired_block_bootstrap
from quant_system.research.trials import date_aligned_correlation, returns_correlation

from ._constants import (
    CORR_V2_SCHEMA_VERSION,
    CORRELATION_MAX_V2,
    NULL_BLOCK_LENGTH,
    NULL_P95_LEVEL,
)

_MIN_OBSERVATIONS = 20


def ols_resid(y: Sequence[float], x: Sequence[float]) -> np.ndarray:
    """Full-sample OLS residuals of ``y`` on ``x`` (same convention as the script)."""
    target = np.asarray(y, dtype=float)
    regressor = np.asarray(x, dtype=float)
    design = np.column_stack([np.ones(len(regressor)), regressor])
    beta, *_ = np.linalg.lstsq(design, target, rcond=None)
    return target - design @ beta


def _paired_residuals(
    left_returns: Sequence[float],
    right_returns: Sequence[float],
    benchmark_returns: Sequence[float],
) -> tuple[np.ndarray, np.ndarray] | None:
    n = min(len(left_returns), len(right_returns), len(benchmark_returns))
    if n < _MIN_OBSERVATIONS:
        return None
    benchmark = list(benchmark_returns[:n])
    return (
        ols_resid(list(left_returns[:n]), benchmark),
        ols_resid(list(right_returns[:n]), benchmark),
    )


def residual_correlation_v2(
    *,
    left_returns: Sequence[float],
    right_returns: Sequence[float],
    benchmark_returns: Sequence[float] | None,
    null_p95: float | None,
) -> dict[str, Any]:
    """Diagnostic residual correlation; passes iff it does not exceed the null p95."""
    document: dict[str, Any] = {
        "schema_version": CORR_V2_SCHEMA_VERSION,
        "residual_corr": None,
        "null_p95": null_p95,
        "passed": None,
        "reason": None,
        "authority": "diagnostic_only",
    }
    if benchmark_returns is None:
        return {**document, "reason": "benchmark_required_for_residual"}
    residuals = _paired_residuals(left_returns, right_returns, benchmark_returns)
    if residuals is None:
        return {**document, "reason": "insufficient_observations"}
    correlation = returns_correlation(residuals[0].tolist(), residuals[1].tolist())
    if correlation is None:
        return {**document, "reason": "residual_correlation_unavailable"}
    if null_p95 is None:
        return {**document, "residual_corr": correlation, "reason": "null_calibration_missing"}
    return {
        **document,
        "residual_corr": correlation,
        "passed": bool(correlation <= null_p95),
        "reason": None if correlation <= null_p95 else "residual_correlation_above_null",
    }


def _circular_block_indices(rng: np.random.Generator, n: int, block: int, blocks: int, limit: int):
    starts = rng.integers(0, n, size=blocks)
    offsets = np.arange(block)
    index = (starts[:, None] + offsets[None, :]) % n
    return index.reshape(-1)[:limit]


def residual_null_p95(
    *,
    left_returns: Sequence[float],
    right_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    block_length: int = NULL_BLOCK_LENGTH,
    n_resamples: int = 2000,
    seed: int,
) -> dict[str, Any]:
    """Per-universe null p95 for the residual correlation.

    Each leg's residual stream is resampled with its **own** independent block
    starts, so contemporaneous cross-leg alignment is destroyed while each leg's
    autocorrelation survives. The p95 of the resampled residual correlations is
    the calibration line.
    """
    document: dict[str, Any] = {
        "schema_version": CORR_V2_SCHEMA_VERSION,
        "null_p95": None,
        "n_resamples": int(n_resamples),
        "block_length": int(block_length),
        "seed": int(seed),
        "reason": None,
    }
    if int(block_length) < 1:
        return {**document, "reason": "invalid_block_length"}
    residuals = _paired_residuals(left_returns, right_returns, benchmark_returns)
    if residuals is None:
        return {**document, "reason": "insufficient_observations"}
    left, right = residuals
    n = len(left)
    blocks = math.ceil(n / int(block_length))
    rng = np.random.default_rng(int(seed))
    correlations: list[float] = []
    for _ in range(int(n_resamples)):
        left_index = _circular_block_indices(rng, n, int(block_length), blocks, n)
        right_index = _circular_block_indices(rng, n, int(block_length), blocks, n)
        value = returns_correlation(left[left_index].tolist(), right[right_index].tolist())
        if value is not None:
            correlations.append(value)
    if len(correlations) < 0.5 * int(n_resamples):
        return {**document, "reason": "null_calibration_unstable"}
    p95 = float(np.quantile(np.asarray(correlations, dtype=float), NULL_P95_LEVEL))
    return {**document, "null_p95": p95, "null_median": float(np.median(correlations))}


def _concentration_curve(values, dates, *, require_dates):
    """Validate before any alignment; never truncate or collapse duplicate days."""
    if isinstance(values, (str, bytes, Mapping)) or values is None:
        return [], None, "returns_invalid"
    try:
        returns = list(values)
    except TypeError:
        return [], None, "returns_invalid"
    if not returns or any(
        isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value)
        for value in returns
    ):
        return [], None, "returns_invalid"
    if dates is None or isinstance(dates, (list, tuple)) and not dates:
        return returns, None, "dates_missing" if require_dates else None
    if isinstance(dates, (str, bytes, Mapping)):
        return returns, None, "dates_invalid"
    try:
        days = list(dates)
    except TypeError:
        return returns, None, "dates_invalid"
    if len(days) != len(returns):
        return returns, None, "dates_length_mismatch"
    for day in days:
        if not isinstance(day, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
            return returns, None, "dates_invalid"
        try:
            date.fromisoformat(day)
        except ValueError:
            return returns, None, "dates_invalid"
    if len(set(days)) != len(days):
        return returns, None, "dates_duplicate"
    return returns, days, None


def raw_concentration_v2(
    *,
    candidate_returns: Sequence[float],
    candidate_dates: Sequence[str] | None,
    hung_sleeves: Sequence[Mapping[str, Any]] = (),
    limit: float = CORRELATION_MAX_V2,
    require_dates: bool = False,
) -> dict[str, Any]:
    """Evaluate every supplied peer, retaining unknowns as blocking evidence.

    Funding callers must set ``require_dates=True``. The false setting retains
    positional mathematics for explicit diagnostics and historical callers only.
    Caller-verified peer identity/lineage and replacement exclusions are outside
    this pure calculation. An empty peer set is distinct from unknown peers.
    """
    correlations: list[tuple[str, float]] = []
    unavailable: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    identities = [sleeve.get("sleeve_id") for sleeve in hung_sleeves]
    for sleeve in hung_sleeves:
        identity = sleeve.get("sleeve_id")
        key = str(identity or "?")
        # Explicit positional diagnostics ignore date metadata when either leg
        # has no calendar. Strict funding calls never enter this branch.
        positional = not require_dates and (
            candidate_dates is None or sleeve.get("dates") is None
            or isinstance(candidate_dates, (list, tuple)) and not candidate_dates
            or isinstance(sleeve.get("dates"), (list, tuple)) and not sleeve["dates"]
        )
        own, own_dates, own_error = _concentration_curve(
            candidate_returns, None if positional else candidate_dates,
            require_dates=require_dates,
        )
        other, other_dates, other_error = _concentration_curve(
            sleeve.get("returns"), None if positional else sleeve.get("dates"),
            require_dates=require_dates,
        )
        reason = (
            "peer_identity_invalid"
            if (
                not isinstance(identity, str) or not identity.strip()
                or identities.count(identity) != 1
            )
            else "candidate_" + own_error if own_error
            else "peer_" + other_error if other_error
            else None
        )
        aligned = own_dates is not None and other_dates is not None
        shared = (
            len(set(own_dates) & set(other_dates)) if aligned
            else min(len(own), len(other)) if reason is None else None
        )
        if reason is None and shared < _MIN_OBSERVATIONS:
            reason = "insufficient_shared_observations"
        value = None
        if reason is None and aligned:
            value = date_aligned_correlation(
                own, own_dates, other, other_dates,
            )
        elif reason is None:
            value = returns_correlation(own, other)
        if reason is None and (value is None or not math.isfinite(value)):
            reason = "correlation_unmeasurable"
        if reason is None:
            correlations.append((key, float(value)))
        else:
            unavailable.append(key)
        diagnostics.append({
            "sleeve_id": key,
            "status": "evaluated" if reason is None else "not_evaluated",
            "reason": reason,
            "shared_observations": shared,
            "alignment": (
                "calendar_dates" if aligned
                else "positional_diagnostic" if not require_dates and reason is None
                else None
            ),
            "correlation": float(value) if reason is None else None,
        })
    raw_max = max((value for _, value in correlations), default=None)
    return {
        "raw_status": (
            "not_applicable" if not hung_sleeves
            else "not_evaluated" if unavailable else "evaluated"
        ),
        "raw_reason": (
            "no_peers" if not hung_sleeves
            else "peer_comparison_unavailable" if unavailable
            else "correlation_above_limit" if raw_max > limit else None
        ),
        "raw_max": raw_max,
        "raw_limit": limit,
        "raw_passed": not unavailable and (raw_max is None or bool(raw_max <= limit)),
        "raw_unavailable_sleeves": unavailable,
        "raw_by_sleeve": [{"sleeve_id": key, "correlation": value} for key, value in correlations],
        "n_hung_sleeves": len(hung_sleeves),
        "raw_peer_diagnostics": diagnostics,
        "dates_required": require_dates,
    }


def concentration_v2(
    *,
    active: Mapping[str, Any],
    hung_sleeves: Sequence[Mapping[str, Any]] = (),
    benchmark_returns: Sequence[float] | None = None,
    null_p95: float | None = None,
    config: Mapping[str, Any] | None = None,
    require_dates: bool = False,
) -> dict[str, Any]:
    """Combined concentration block: raw rule (blocking) + residual diagnosis."""
    limit = float((config or {}).get("correlation_max", CORRELATION_MAX_V2))
    # Concentration compares actual sleeve exposure. Benchmark-relative returns
    # belong to DSR; subtracting the benchmark here can hide a duplicate sleeve.
    candidate_returns = list(active.get("equity_returns") or [])
    if hung_sleeves and not candidate_returns:
        raise ValueError("gate_v2_equity_returns_missing")
    candidate_dates = active.get("dates") or None
    raw = raw_concentration_v2(
        candidate_returns=candidate_returns,
        candidate_dates=candidate_dates,
        hung_sleeves=hung_sleeves,
        limit=limit,
        require_dates=require_dates,
    )
    applicable = bool(hung_sleeves)
    reference = None
    for entry in raw["raw_by_sleeve"]:
        if reference is None or entry["correlation"] > reference["correlation"]:
            reference = entry
    residual: dict[str, Any]
    if reference is None or not hung_sleeves:
        residual = {
            "schema_version": CORR_V2_SCHEMA_VERSION,
            "residual_corr": None,
            "null_p95": null_p95,
            "passed": None,
            "reason": "no_reference_for_residual",
            "authority": "diagnostic_only",
        }
    else:
        sleeve = next(
            item
            for item in hung_sleeves
            if str(item.get("sleeve_id", "?")) == reference["sleeve_id"]
        )
        other_returns = list(sleeve.get("returns") or [])
        other_dates = sleeve.get("dates")
        # Raw concentration is date-aligned; its diagnostic must use the same
        # dates rather than correlating two unrelated positional prefixes.
        aligned = (
            candidate_dates is not None
            and other_dates is not None
            and len(candidate_dates) == len(candidate_returns)
            and len(other_dates) == len(other_returns)
            and len(set(candidate_dates)) == len(candidate_dates)
            and len(set(other_dates)) == len(other_dates)
            and (benchmark_returns is None or len(benchmark_returns) == len(candidate_returns))
        )
        if not aligned:
            residual = {
                "residual_corr": None,
                "null_p95": null_p95,
                "passed": None,
                "reason": "residual_date_alignment_required",
            }
        else:
            other_by_date = dict(zip(other_dates, other_returns, strict=True))
            indices = [i for i, day in enumerate(candidate_dates) if day in other_by_date]
            residual = residual_correlation_v2(
                left_returns=[candidate_returns[i] for i in indices],
                right_returns=[other_by_date[candidate_dates[i]] for i in indices],
                benchmark_returns=(
                    None if benchmark_returns is None else [benchmark_returns[i] for i in indices]
                ),
                null_p95=null_p95,
            )
    return {
        "schema_version": CORR_V2_SCHEMA_VERSION,
        "applicable": applicable,
        "raw_max": raw["raw_max"],
        "raw_limit": raw["raw_limit"],
        "raw_passed": raw["raw_passed"],
        "raw_by_sleeve": raw["raw_by_sleeve"],
        "raw_unavailable_sleeves": raw["raw_unavailable_sleeves"],
        "raw_status": raw["raw_status"],
        "raw_reason": raw["raw_reason"],
        "raw_peer_diagnostics": raw["raw_peer_diagnostics"],
        "dates_required": raw["dates_required"],
        "residual_max": residual["residual_corr"],
        "null_p95": residual["null_p95"],
        "residual_passed": residual["passed"],
        "residual_reason": residual["reason"],
        "residual_authority": "diagnostic_only",
        "passed": True if not applicable else bool(raw["raw_passed"]),
    }


def paired_increment_verdict(
    *,
    baseline: Sequence[float],
    augmented: Sequence[float],
    block_length: int = BOOTSTRAP_BLOCK_LENGTH,
    n_resamples: int = 2000,
    seed: int,
) -> dict[str, Any]:
    """Paired Sharpe-difference interval; accepts an upgrade iff ``ci95_low > 0``."""
    import pandas as pd

    interval = paired_block_bootstrap(
        pd.Series([float(v) for v in augmented]),
        pd.Series([float(v) for v in baseline]),
        block_length=block_length,
        n_resamples=n_resamples,
        seed=seed,
    )
    status = interval.get("status")
    ci_low = interval.get("ci95_low")
    accepted = status == "ready" and ci_low is not None and float(ci_low) > 0.0
    return {
        "schema_version": CORR_V2_SCHEMA_VERSION,
        "applicable": True,
        "upgrade_accepted": bool(accepted),
        "accepted_evidence": "primary" if accepted else None,
        "secondary": interval.get("fraction_bootstrap_positive"),
        "bootstrap": interval,
        "reason": None if status == "ready" else interval.get("reason"),
    }
