"""DSR v2 — the same Bailey–López de Prado math on the active-return input.

Only the *inputs* change relative to v1: ``SR``/``skew``/``kurt``/``n`` come from
the arithmetic active-return series (via v1's ``performance_from_daily_returns``,
so the estimator is bit-identical), and the trial family is the recomputed v2
family. The decision formula itself is delegated wholesale to
``trials.deflated_sharpe_ratio`` — no coefficient is restated here.

Two paths:

* ``data_driven`` (family >= ``DSR_V2_FAMILY_MIN_ENTRIES``): the full DSR with
  the recomputed member Sharpes, pass line ``DSR_V2_MIN`` (an alias of v1's
  ``DSR_DEFAULT_MIN``).
* ``small_family_fixed`` (< the entry floor): ``sr_std`` is an unstable
  dispersion estimate on a tiny family, so a strict fixed PSR line replaces it
  (``PSR`` against ``SR*=0``). This is the *primary* path early on, because only
  a bound validation writes ``equity_curve_digest``, so the v2 family starts
  nearly empty. It additionally requires >= ``DSR_V2_SMALL_FAMILY_MIN_MEMBERS``
  members and >= ``DSR_V2_SMALL_FAMILY_MIN_PERIODS`` periods per member.
* Every path requires the candidate to carry >= ``DSR_V2_MIN_PERIODS_CANDIDATE``
  periods so the wiring identity is computable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from quant_system.research.trials import deflated_sharpe_ratio, performance_from_daily_returns

from ._constants import (
    DSR_V2_MIN_PERIODS_CANDIDATE,
    DSR_V2_SCHEMA_VERSION,
    DSR_V2_SMALL_FAMILY_PASS_MIN,
)

PATH_DATA_DRIVEN = "data_driven"
PATH_SMALL_FAMILY = "small_family_fixed"


def evaluate_dsr_v2(
    *,
    active: Mapping[str, Any],
    family: Mapping[str, Any],
    dsr_min: float,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    perf = performance_from_daily_returns(active.get("active_returns", []))
    members: Sequence[Mapping[str, Any]] = family.get("members", [])
    recomputed = [
        float(item["recomputed_sharpe"])
        for item in members
        if item.get("recomputed_sharpe") is not None
        and math.isfinite(float(item["recomputed_sharpe"]))
    ]
    n_trials = len(recomputed)
    n_periods = int(active.get("n_periods") or 0)
    document: dict[str, Any] = {
        "schema_version": DSR_V2_SCHEMA_VERSION,
        "family_digest": family.get("family_digest"),
        "n_trials": n_trials,
        "n_periods": n_periods,
        "path": None,
        "value": 0.0,
        "threshold_sr": None,
        "dsr_min_used": None,
        "passed": False,
        "reason": None,
        "performance": {
            "sharpe_period": perf["sharpe_period"],
            "skewness": perf["skewness"],
            "kurtosis": perf["kurtosis"],
            "n_periods": perf["n_periods"],
        },
    }
    if perf["sharpe_period"] is None or n_periods < 2:
        return {**document, "reason": "dsr_input_invalid"}
    window_short = n_periods < int(
        config.get("dsr_min_periods_candidate", DSR_V2_MIN_PERIODS_CANDIDATE)
    )
    if n_trials >= int(config["dsr_family_min_entries"]):
        result = deflated_sharpe_ratio(
            sharpe=perf["sharpe_period"],
            n_periods=perf["n_periods"],
            skewness=perf["skewness"],
            kurtosis=perf["kurtosis"],
            trial_sharpes=recomputed,
            dsr_min=dsr_min,
        )
        document.update(
            path=PATH_DATA_DRIVEN,
            value=result["value"],
            threshold_sr=result["threshold_sr"],
            dsr_min_used=dsr_min,
            passed=bool(result["passed"]) and not window_short,
            reason=result.get("reason"),
        )
        if window_short and document["reason"] is None:
            document["reason"] = "candidate_window_too_short"
        return document

    fixed = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=[],
        dsr_min=DSR_V2_SMALL_FAMILY_PASS_MIN,
    )
    reason = None
    if n_trials < int(config["dsr_small_family_min_members"]):
        reason = "family_too_small"
    elif any(
        item.get("n_periods") is None
        or int(item["n_periods"]) < int(config["dsr_small_family_min_periods"])
        for item in members
    ):
        reason = "family_member_short_window"
    elif window_short:
        reason = "candidate_window_too_short"
    document.update(
        path=PATH_SMALL_FAMILY,
        value=fixed["value"],
        threshold_sr=0.0,
        dsr_min_used=DSR_V2_SMALL_FAMILY_PASS_MIN,
        passed=reason is None and fixed["value"] >= DSR_V2_SMALL_FAMILY_PASS_MIN,
        reason=reason,
    )
    return document
