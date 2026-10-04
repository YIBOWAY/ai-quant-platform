"""Frozen paired inputs and pre-declared incremental research objectives."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Metric = Literal["total_return", "annualized_return", "sharpe", "max_drawdown", "turnover"]
_LOWER = {"max_drawdown", "turnover"}


class IncrementObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    metric: Metric
    minimum_improvement: float = Field(gt=0)
    max_regressions: dict[Metric, float] = Field(
        description="Explicit allowed deterioration by metric; {} means no additional guard. "
        "Return/drawdown are decimal fractions, Sharpe and turnover in their native units."
    )

    def model_post_init(self, _context):
        if any(value < 0 for value in self.max_regressions.values()):
            raise ValueError("intake_negative_regression_budget")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_snapshot(settings, evaluation):
    value = dict(evaluation)
    identity = value.pop("evaluation_id", None)
    if identity != "evaluation-" + digest(value):
        raise ValueError("intake_evaluation_identity_changed")
    path = Path(value["prices_path"])
    allowed = (settings.data.data_dir / "research_intake" / "evaluations").resolve()
    if not path.is_absolute() or not path.resolve().is_relative_to(allowed):
        raise ValueError("intake_evaluation_path_invalid")
    if file_hash(path) != value["prices_sha256"]:
        raise ValueError("intake_evaluation_prices_changed")
    return path


def compare_increment(job):
    results = {r["variant"]: r for r in job.get("results", [])}
    if "baseline" not in results or "augmented" not in results:
        return {"status": "not_requested", "passed": False, "reason": "intake_baseline_required"}
    first, second = (results[k] for k in ("baseline", "augmented"))
    a, b = (r.get("evaluation") or {} for r in (first, second))
    va, vb = (r.get("validation") or {} for r in (first, second))
    same = (
        bool(a.get("evaluation_id"))
        and a == b
        and all(va.get(key) is not None and va.get(key) == vb.get(key) for key in ("start", "end"))
    )
    same = (
        same
        and bool(first.get("evaluation_calendar_digest"))
        and (first["evaluation_calendar_digest"] == second.get("evaluation_calendar_digest"))
    )
    if job.get("plans"):
        expected = {p["variant"]: p.get("definition_digest") for p in job["plans"]}
        same = same and bool(job.get("evaluation")) and a == job["evaluation"]
        same = same and all(
            result.get("definition_digest") == expected.get(result["variant"])
            and validation.get("definition_digest") == expected.get(result["variant"])
            for result, validation in ((first, va), (second, vb))
        )
    # A baseline can fail admission yet remain a valid measured comparator.
    valid = all(v.get("comparison", {}).get("accepted") is True for v in (va, vb))
    if not same or not valid:
        return {"status": "unavailable", "passed": False, "reason": "intake_pair_not_comparable"}
    objective = job.get("proposal", {}).get("increment_objective")
    if objective is None:
        return {
            "status": "not_declared",
            "passed": False,
            "reason": "intake_increment_objective_required",
            "comparable": True,
        }
    spec = IncrementObjective.model_validate(objective)
    checks = []
    for metric, minimum in [
        (spec.metric, spec.minimum_improvement),
        *((key, -budget) for key, budget in spec.max_regressions.items()),
    ]:
        old, new = (v.get("platform_metrics", {}).get(metric) for v in (va, vb))
        if any(
            not isinstance(x, (float, int)) or isinstance(x, bool) or not math.isfinite(x)
            for x in (old, new)
        ):
            return {
                "status": "unavailable",
                "passed": False,
                "reason": "intake_increment_metric_missing",
                "comparable": True,
            }
        improvement = old - new if metric in _LOWER else new - old
        checks.append(
            {
                "metric": metric,
                "baseline": old,
                "augmented": new,
                "improvement": improvement,
                "minimum": minimum,
                "passed": (bool(checks) or improvement > 0) and improvement + 1e-12 >= minimum,
            }
        )
    passed = all(check["passed"] for check in checks)
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "comparable": True,
        "objective": objective,
        "checks": checks,
        "reason": None if passed else "intake_increment_objective_not_met",
    }
