"""Append-only research trial ledger + Deflated Sharpe Ratio admission math.

Every backtest-shaped research attempt (platform backtests, Qlib/d34
experiments) appends one immutable trial. Candidate admission reads the
ledger so a curve-fit survivor of many attempts is measured against the
multiple-testing penalty instead of its own inflated Sharpe.

The DSR follows Bailey & López de Prado (2014): PSR benchmarked against the
expected maximum Sharpe of N zero-signal trials with the observed variance
of trial Sharpes. All Sharpes here are per-period (daily); annualize for
display only.
"""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import logging
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TRIALS_CONTRACT = "qs.research_trials/v1"
# Every backtest-shaped public entry must append a trial or skipped tombstone.
BACKTEST_SHAPED_ENTRY_POINTS = (
    "quant_system.backtest.pipeline:run_backtest",
    "quant_system.experiments.runner:run_experiment",
    "quant_system.factors.lab:build_factor_lab_dashboard",
    "quant_system.replication.reversal_momentum:build_reversal_momentum_replication",
    "quant_system.prediction_market.timeseries_backtest:run_prediction_market_timeseries_backtest",
    "quant_system.prediction_market.backtest:run_prediction_market_quasi_backtest",
    "quant_system.d34.research_driver:execute_research_request",
    "quant_system.research.strategy_study_service:run_studies",
    "quant_system.research.strategy_study_service:_discover",
    "quant_system.research.evaluation_service:refresh_evaluation",
    "quant_system.research.strategy_library:validate_strategy",
)

# Backtest-shaped entry points that deliberately do NOT append a trial or
# tombstone. Every exemption must record WHY, and the OP0k seam-audit test
# pins the union of both lists against every BacktestEngine callsite in src.
BACKTEST_SHAPED_EXEMPTIONS = {
    "quant_system.research.cost_replay:replay_cost_scenarios": (
        "Fixed-signal engineering replays owned by a bound validation. Each cost "
        "scenario rebuilds orders/fills/cash but introduces no new hypothesis or "
        "parameter search; the original attempted hypothesis remains recorded. "
        "Parallel cost artifacts never overwrite original metrics or trials."
    ),
    "quant_system.research.profile_backtests:_run": (
        "Pure internal replay owned by run_studies/_discover. Their owner records "
        "each net hypothesis immediately through _record_study_result; gross, "
        "benchmark and peer replays do not count as extra hypotheses. Successful "
        "studies retain the same recorded-study identity used before admission."
    ),
    "quant_system.research.strategy_runtime:_run": (
        "Pure internal replay owned by strategy_library.validate_strategy. Its "
        "net result is recorded with the definition-validation input identity "
        "before Qlib replay and DSR; gross/benchmark/peer replays must not create "
        "additional trials for the same hypothesis."
    ),
    "quant_system.research.reference_backtests:_result": (
        "Pure portfolio calculation owned by evaluation_service.refresh_evaluation. "
        "The host records each net reference and stitched rolling portfolio via "
        "_record_evaluation_portfolios; benchmark and rolling folds are not extra "
        "hypotheses and the network-disabled Qlib subprocess cannot own the ledger."
    ),
    "quant_system.research.reference_backtests:_monthly_reference": (
        "Monthly gross diagnostic owned by evaluation_service.refresh_evaluation. "
        "Its completion produces an explicit skipped tombstone because monthly "
        "gross returns are not comparable to the daily net DSR family; the QQQ "
        "comparison replay must not be counted as an independent hypothesis."
    ),
    "quant_system.research.reference_backtests:build_reference_backtests": (
        "Pure batch builder owned by evaluation_service.refresh_evaluation. "
        "The owner records every returned reference row immediately, including "
        "tombstones for unavailable drafts; this callsite itself constructs only "
        "the fixed QQQ benchmark, not an additional research hypothesis."
    ),
    "quant_system.experiments.runner:_run_single_backtest": (
        "Internal engine seam owned by run_experiment. Walk-forward folds are "
        "parts of one parameter-combination hypothesis, and run_experiment "
        "appends the resulting trial once after the combination completes; "
        "recording each fold here would inflate the DSR family."
    ),
    "quant_system.d34.platform_replay:run_platform_replay": (
        "Same-hypothesis validation replay of digest-bound target weights for "
        "an already-enqueued d34 attempt. Its daily_returns enter the trials "
        "ledger through the host "
        "worker persist (kind=d34_experiment, run_id identity), so appending "
        "here would double-count the same attempt. Manual CLI replays are "
        "read-only recompute artifacts, not new research attempts."
    ),
}
DSR_DEFAULT_MIN = 0.95
DSR_FAMILY_MIN_PERIODS = 20
_EULER_MASCHERONI = 0.5772156649015329

TrialKind = Literal[
    "platform_backtest",
    "qlib_backtest",
    "factor_lab",
    "factor_scorecard",
    "d34_experiment",
    "experiment",
    "strategy_replication",
    "prediction_market",
]


class _BacktestEngineCallsiteVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.callsites: set[str] = set()

    def _visit_scope(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        target = node.func
        is_engine = (
            isinstance(target, ast.Name) and target.id == "BacktestEngine"
        ) or (
            isinstance(target, ast.Attribute) and target.attr == "BacktestEngine"
        )
        if is_engine:
            scope = ".".join(self.scope) if self.scope else "<module>"
            self.callsites.add(f"{self.module}:{scope}")
        self.generic_visit(node)


def enumerate_backtest_engine_callsites(
    package_root: Path | str,
    *,
    package: str = "quant_system",
) -> set[str]:
    """Return exact ``module:function`` seams that construct BacktestEngine."""
    root = Path(package_root)
    callsites: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).with_suffix("")
        module_parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        module = ".".join((package, *module_parts))
        visitor = _BacktestEngineCallsiteVisitor(module)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        callsites.update(visitor.callsites)
    return callsites


def universe_digest(symbols: Iterable[str]) -> str:
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()


def performance_from_daily_returns(daily_returns: Sequence[float]) -> dict[str, Any]:
    values = [float(item) for item in daily_returns if math.isfinite(float(item))]
    n = len(values)
    if n < 2:
        return {
            "n_periods": n,
            "sharpe_period": None,
            "sharpe_annual": None,
            "skewness": None,
            "kurtosis": None,
            "total_return": None,
            "max_drawdown": None,
        }
    mean = sum(values) / n
    variance = sum((item - mean) ** 2 for item in values) / (n - 1)
    std = math.sqrt(variance)
    sharpe_period = mean / std if std > 1e-12 else None
    skew = kurt = None
    if std > 1e-12 and n >= 3:
        skew = sum(((item - mean) / std) ** 3 for item in values) * n / (n - 1) / (n - 2)
    if std > 1e-12 and n >= 4:
        m4 = sum(((item - mean) / std) ** 4 for item in values) / n
        adjusted_m4 = m4 * (
            n * n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))
        )
        kurt = (
            adjusted_m4
            - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))
            + 3
        )  # plain (not excess) kurtosis, adjusted-sample estimator
    total = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for item in values:
        total *= 1.0 + item
        peak = max(peak, total)
        if peak > 0:
            max_drawdown = max(max_drawdown, 1.0 - total / peak)
    return {
        "n_periods": n,
        "sharpe_period": sharpe_period,
        "sharpe_annual": sharpe_period * math.sqrt(252) if sharpe_period is not None else None,
        "skewness": skew,
        "kurtosis": kurt,
        "total_return": total - 1.0,
        "max_drawdown": max_drawdown,
    }


class ResearchTrial(BaseModel):
    contract: str = TRIALS_CONTRACT
    trial_id: str
    ts: str
    kind: TrialKind
    subject: str
    universe: list[str]
    universe_digest: str
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    n_periods: int
    sharpe: Optional[float] = None  # per-period (daily)
    sharpe_annual: Optional[float] = None
    skewness: Optional[float] = None
    kurtosis: Optional[float] = None
    total_return: Optional[float] = None
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def record(
        cls,
        *,
        kind: TrialKind,
        subject: str,
        universe: Sequence[str],
        daily_returns: Sequence[float],
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        source: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ResearchTrial":
        perf = performance_from_daily_returns(daily_returns)
        symbols = sorted({str(symbol).strip().upper() for symbol in universe if str(symbol).strip()})
        payload = {
            "kind": kind,
            "subject": subject,
            "universe": symbols,
            "window_start": window_start,
            "window_end": window_end,
            "n_periods": perf["n_periods"],
            "sharpe": perf["sharpe_period"],
            "sharpe_annual": perf["sharpe_annual"],
            "skewness": perf["skewness"],
            "kurtosis": perf["kurtosis"],
            "total_return": perf["total_return"],
            "source": source,
            "metadata": metadata or {},
        }
        run_id = str(payload["metadata"].get("run_id") or "").strip()
        identity = (
            f"{kind}:{run_id}".encode()
            if run_id
            else json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        trial_id = hashlib.sha256(identity).hexdigest()[:24]
        return cls(trial_id=trial_id, ts=datetime.now(UTC).isoformat(), universe_digest=universe_digest(symbols), **payload)

    @classmethod
    def skipped(
        cls,
        *,
        kind: TrialKind,
        subject: str,
        universe: Sequence[str],
        reason: str,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        source: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ResearchTrial":
        """Append-only tombstone: the run happened, DSR must not count it."""
        if not str(reason).strip():
            raise ValueError("skipped tombstone requires a non-empty reason")
        extra = dict(metadata or {})
        extra["skipped"] = True
        extra["skip_reason"] = str(reason).strip()
        return cls.record(
            kind=kind,
            subject=subject,
            universe=universe,
            daily_returns=[],
            window_start=window_start,
            window_end=window_end,
            source=source,
            metadata=extra,
        )


def _ends_with_newline(path: Path) -> bool:
    """True when the ledger's final byte terminates a line. Callers must
    confirm the file is non-empty first."""
    with path.open("rb") as probe:
        probe.seek(-1, os.SEEK_END)
        return probe.read(1) == b"\n"


class TrialsLedger:
    """Append-only JSONL ledger. Never mutates or removes a trial."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "trials.jsonl"

    def append(self, trial: ResearchTrial) -> None:
        self.append_many([trial])

    def append_many(self, trials: Sequence[ResearchTrial]) -> None:
        """Validate a whole receipt batch before appending any new rows."""
        if not trials:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The append-only ledger inode is the shared authority for every owner.
        # Keep read -> validate -> write -> flush inside one cross-process lock.
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            rows = self._read_rows(handle)
            pending = self._pending_trials(trials, rows)
            if not pending:
                return
            # Serialize the whole batch before the first byte reaches the file:
            # an unserializable payload must reject the batch instead of
            # leaving a half-written receipt behind.
            serialized = [
                json.dumps(trial.model_dump(mode="json"), sort_keys=True) + "\n"
                for trial in pending
            ]
            # Append mode writes at EOF; a truncated tail without a trailing
            # newline would otherwise fuse the new receipt into the damaged
            # physical line and silently drop it.
            if self.path.stat().st_size and not _ends_with_newline(self.path):
                handle.write("\n")
            for line in serialized:
                handle.write(line)
            handle.flush()
            # Durability inside the lock: fsync before close so the bytes are
            # on disk no later than the moment the exclusive lock is released.
            os.fsync(handle.fileno())
            # Closing releases flock after the stream has been flushed; no
            # early LOCK_UN can expose a buffered/partial record to readers.

    @staticmethod
    def _pending_trials(trials, rows):
        by_trial_id = {row.trial_id: row for row in rows}
        by_run_id = {
            str(row.metadata.get("run_id") or "").strip(): row
            for row in rows
            if str(row.metadata.get("run_id") or "").strip()
        }
        pending: list[ResearchTrial] = []
        for trial in trials:
            trial_document = trial.model_dump(mode="json", exclude={"ts"})
            run_id = str(trial.metadata.get("run_id") or "").strip()
            existing = by_trial_id.get(trial.trial_id)
            if existing is not None:
                if existing.model_dump(mode="json", exclude={"ts"}) == trial_document:
                    continue
                raise ValueError("trial_run_id_conflict")
            if run_id and run_id in by_run_id:
                raise ValueError("trial_run_id_conflict")
            by_trial_id[trial.trial_id] = trial
            if run_id:
                by_run_id[run_id] = trial
            pending.append(trial)
        return pending

    def list(self, *, universe: Optional[str] = None) -> list[ResearchTrial]:
        try:
            handle = self.path.open("r", encoding="utf-8")
        except FileNotFoundError:
            return []
        with handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            return self._read_rows(handle, universe=universe)

    @staticmethod
    def _read_rows(handle, *, universe: str | None = None) -> list[ResearchTrial]:
        rows: list[ResearchTrial] = []
        malformed: list[int] = []
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                # One damaged line must not cascade: skip it, keep the rest of
                # the append-only ledger readable for every consumer.
                malformed.append(line_number)
                logger.warning(
                    "trials ledger %s: skipping malformed JSON on line %d: %s",
                    getattr(handle, "name", "<unknown>"),
                    line_number,
                    exc,
                )
                continue
            row = ResearchTrial.model_validate(document)
            if universe is None or row.universe_digest == universe:
                rows.append(row)
        if malformed:
            logger.warning(
                "trials ledger %s: skipped %d malformed row(s) on line(s) %s",
                getattr(handle, "name", "<unknown>"),
                len(malformed),
                ", ".join(str(number) for number in malformed),
            )
        return rows

    def trial_sharpes(self, *, universe: Optional[str] = None) -> list[float]:
        return [
            row.sharpe
            for row in self.list(universe=universe)
            if row.sharpe is not None and row.n_periods >= DSR_FAMILY_MIN_PERIODS
        ]


def deflated_sharpe_ratio(
    *,
    sharpe: float,
    n_periods: int,
    skewness: Optional[float],
    kurtosis: Optional[float],
    trial_sharpes: Sequence[float],
    dsr_min: float = DSR_DEFAULT_MIN,
) -> dict[str, Any]:
    """Bailey–López de Prado DSR: PSR against the expected max of N null trials."""
    if not math.isfinite(sharpe) or n_periods < 2:
        return {"value": 0.0, "n_trials": len(trial_sharpes), "threshold_sr": None,
                "passed": False, "reason": "dsr_input_invalid"}
    family = [float(value) for value in trial_sharpes if math.isfinite(float(value))]
    n_trials = max(len(family), 1)
    if n_trials > 1 and len(family) > 1:
        mean = sum(family) / len(family)
        variance = sum((value - mean) ** 2 for value in family) / (len(family) - 1)
        sr_std = math.sqrt(variance)
        normal = NormalDist()
        first = normal.inv_cdf(1.0 - 1.0 / n_trials)
        second = normal.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
        threshold = sr_std * ((1.0 - _EULER_MASCHERONI) * first + _EULER_MASCHERONI * second)
    else:
        threshold = 0.0
    skew = float(skewness) if skewness is not None else 0.0
    kurt = float(kurtosis) if kurtosis is not None else 3.0
    denominator = 1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe**2
    if denominator <= 0:
        return {"value": 0.0, "n_trials": n_trials, "threshold_sr": threshold,
                "passed": False, "reason": "dsr_moments_invalid"}
    z = (sharpe - threshold) * math.sqrt(n_periods - 1) / math.sqrt(denominator)
    value = NormalDist().cdf(z)
    return {
        "value": value,
        "n_trials": n_trials,
        "threshold_sr": threshold,
        "passed": value >= dsr_min,
        "dsr_min": dsr_min,
    }


def evaluate_candidate_dsr(
    ledger: TrialsLedger,
    *,
    universe: Sequence[str],
    daily_returns: Sequence[float],
    dsr_min: float = DSR_DEFAULT_MIN,
) -> dict[str, Any]:
    perf = performance_from_daily_returns(daily_returns)
    if perf["sharpe_period"] is None:
        return {"status": "performance_missing", "passed": False}
    family = ledger.trial_sharpes(universe=universe_digest(universe))
    result = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=family,
        dsr_min=dsr_min,
    )
    return {"status": "evaluated", **result, "performance": perf}


FACTOR_CORRELATION_MAX = 0.7


def returns_correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Pearson correlation of two return series on the shared prefix."""
    n = min(len(left), len(right))
    if n < 20:
        return None
    a = [float(v) for v in left[:n]]
    b = [float(v) for v in right[:n]]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a <= 0 or var_b <= 0:
        return None
    return cov / (var_a ** 0.5 * var_b ** 0.5)


def date_aligned_correlation(
    left_returns: Sequence[float],
    left_dates: Sequence[str],
    right_returns: Sequence[float],
    right_dates: Sequence[str],
) -> float | None:
    """Pearson correlation of two return series on their shared calendar days.

    Positional pairing silently mis-pairs candidates measured over different
    windows (day i of one against day i of the other); alignment is by ISO
    calendar date instead. Fewer than 20 shared days is not measurable.
    """

    def _by_date(
        values: Sequence[float], dates: Sequence[str]
    ) -> dict[str, float]:
        return {
            str(day)[:10]: float(value)
            for day, value in zip(dates, values, strict=False)
        }

    left = _by_date(left_returns, left_dates)
    right = _by_date(right_returns, right_dates)
    shared = sorted(set(left) & set(right))
    if len(shared) < 20:
        return None
    return returns_correlation(
        [left[day] for day in shared], [right[day] for day in shared]
    )


def cost_sensitivity_verdict(
    *,
    annual_return: float,
    annual_turnover: float,
    cost_bps: float,
    multiplier: float = 2.0,
) -> dict:
    """Net edge after `multiplier` x roundtrip costs; fails when it dies.

    Annual cost drag is turnover x roundtrip cost. A candidate whose edge
    vanishes under doubled costs is churn, not alpha.
    """
    if annual_turnover < 0 or cost_bps < 0 or multiplier <= 0:
        raise ValueError("cost sensitivity inputs are invalid")
    drag_1x = annual_turnover * cost_bps / 10_000
    net = annual_return - drag_1x * multiplier
    return {
        "passed": net > 0.0,
        "net_return_at_2x": net,
        "cost_drag_annual_1x": drag_1x,
        "multiplier": multiplier,
        "cost_bps": cost_bps,
    }


def reconcile_trial_coverage(
    ledger: TrialsLedger,
    run_ids: Sequence[str],
    *,
    scope_metadata: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Check an isolated batch census: N(runs) == N(cited ledger rows).

    The caller must scope ``ledger`` to the same batch; unrelated history is
    intentionally reported as extra coverage rather than silently ignored.
    ``scope_metadata`` narrows the census to ledger rows carrying the exact
    metadata key=value pairs (for example one job's trials inside a shared
    production ledger), which is how the d34 host persist path reconciles a
    batch without letting unrelated history read as extras.
    """
    expected = [str(run_id).strip() for run_id in run_ids if str(run_id).strip()]
    rows = ledger.list()
    if scope_metadata:
        scope = {str(k): str(v) for k, v in scope_metadata.items()}
        rows = [
            row
            for row in rows
            if all(
                str(row.metadata.get(key) or "") == value
                for key, value in scope.items()
            )
        ]
    cited_rows = [
        str(row.metadata.get("run_id") or "").strip()
        for row in rows
        if str(row.metadata.get("run_id") or "").strip()
    ]
    expected_counts = Counter(expected)
    cited_counts = Counter(cited_rows)
    missing = sorted((expected_counts - cited_counts).elements())
    extras = sorted((cited_counts - expected_counts).elements())
    duplicate_expected = sorted(
        run_id for run_id, count in expected_counts.items() if count > 1
    )
    duplicate_ledger = sorted(
        run_id for run_id, count in cited_counts.items() if count > 1
    )
    return {
        "n_runs": len(expected),
        "n_ledger": sum(
            min(expected_counts[run_id], cited_counts[run_id])
            for run_id in expected_counts
        ),
        "n_ledger_rows": len(cited_rows),
        "n_unique_run_ids": len(cited_counts),
        "missing": missing,
        "extras": extras,
        "duplicate_expected_run_ids": duplicate_expected,
        "duplicate_ledger_run_ids": duplicate_ledger,
        "passed": (
            expected_counts == cited_counts
            and not duplicate_expected
            and not duplicate_ledger
        ),
    }


def daily_returns_from_equity(equity: Sequence[float]) -> list[float]:
    values = [float(item) for item in equity if math.isfinite(float(item))]
    if len(values) < 2:
        return []
    return [
        values[index] / values[index - 1] - 1.0
        for index in range(1, len(values))
        if values[index - 1] != 0
    ]


__all__ = [
    "DSR_DEFAULT_MIN",
    "DSR_FAMILY_MIN_PERIODS",
    "TRIALS_CONTRACT",
    "BACKTEST_SHAPED_ENTRY_POINTS",
    "BACKTEST_SHAPED_EXEMPTIONS",
    "ResearchTrial",
    "TrialsLedger",
    "deflated_sharpe_ratio",
    "evaluate_candidate_dsr",
    "performance_from_daily_returns",
    "universe_digest",
    "FACTOR_CORRELATION_MAX",
    "returns_correlation",
    "date_aligned_correlation",
    "cost_sensitivity_verdict",
    "reconcile_trial_coverage",
    "daily_returns_from_equity",
    "enumerate_backtest_engine_callsites",
]
