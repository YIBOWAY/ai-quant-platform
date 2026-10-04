"""One durable D-34 research cycle for the persistent local Mac worker."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from quant_system.d34.docker_runtime import D34DockerRuntimeError
from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineComparison,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.d34.market_data_snapshot import create_market_data_snapshot
from quant_system.d34.preflight import run_d34_llm_preflight
from quant_system.d34.research_driver import RESEARCH_REQUEST_CONTRACT, D34ResearchRequest
from quant_system.d34.research_request import (
    JOB_INPUT_CONTRACT,
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
    OWNER_REQUEST_TRIGGER,
)
from quant_system.hermes.d34_registry_authority import RegisterArtifactCommand
from quant_system.options.seller_score import latest_us_market_session

QLIB_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"
_MARKET_TIMEZONE = ZoneInfo("America/New_York")
_FAILED_EXPERIMENT_ATTEMPT_REASON = "d34_experiment_attempt_failed"


class _D34WorkerValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _research_request_digest(research_request: Mapping[str, object]) -> str:
    # Digest the container will commit for this research_request.json. The
    # container boundary validates with D34ResearchRequest.model_validate and
    # digests model_dump(mode="json"); host-only lineage keys (job_key) never
    # enter it. model_construct applies the same field selection, defaults,
    # and JSON normalization without the container's environment checks —
    # provider_uri is a container path that does not exist on this host.
    values: dict[str, object] = {}
    for name in D34ResearchRequest.model_fields:
        if name not in research_request:
            continue
        value = research_request[name]
        values[name] = tuple(value) if isinstance(value, list) else value
    model = D34ResearchRequest.model_construct(**values)
    return model.request_digest


def _is_digest(value: object) -> bool:
    cleaned = str(value or "")
    return len(cleaned) == 64 and all(character in "0123456789abcdef" for character in cleaned)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qlib_turnover_period(path: Path, *, expected_receipt_digest: str) -> float | None:
    """Bind the metric to the raw receipt already validated by the worker."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    receipt_digest = raw.pop("receipt_digest", None)
    if receipt_digest != expected_receipt_digest or _digest(raw) != receipt_digest:
        raise _D34WorkerValidationError("d34_engine_receipt_lineage_mismatch")
    metrics = raw.get("metrics")
    value = metrics.get("turnover") if isinstance(metrics, dict) else None
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json(document) + b"\n")
    temporary.replace(path)


def _append_and_reconcile_host_trials(
    *,
    data_root: Path,
    job_id: str,
    trials: Sequence[Any],
) -> dict[str, object]:
    from quant_system.research.trials import (
        TrialsLedger,
        reconcile_trial_coverage,
    )

    run_ids = [str(trial.metadata["run_id"]) for trial in trials]
    ledger = TrialsLedger(Path(data_root) / "trials")
    ledger.append_many(trials)
    coverage = reconcile_trial_coverage(
        ledger,
        run_ids,
        scope_metadata={"job_id": job_id},
    )
    if not coverage["passed"]:
        raise _D34WorkerValidationError("d34_experiment_trials_coverage_mismatch")
    return {
        "run_ids": run_ids,
        "trial_ids": [trial.trial_id for trial in trials],
        "trial_coverage": coverage,
    }


def persist_host_d34_experiment_trials(
    *,
    data_root: Path,
    batch_path: Path,
    expected_file_digest: str,
    expected_batch_digest: str,
    expected_job_id: str,
    expected_request_digest: str,
    expected_universe: Sequence[str],
    expected_calendar_digest: str,
    expected_experiment_count: int,
) -> dict[str, object]:
    """Validate one complete batch and persist every experiment attempt.

    The batch is the cross-container seam: raw returns stay digest-bound in the
    durable workspace, while the host derives successful ResearchTrial statistics,
    records failed attempts as skipped tombstones, and owns the authoritative ledger.
    """
    from quant_system.research.trials import ResearchTrial

    try:
        raw_bytes = batch_path.read_bytes()
        document = json.loads(raw_bytes)
        batch_digest = str(document.pop("receipt_digest"))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _D34WorkerValidationError("d34_experiment_trials_unreadable") from exc
    if hashlib.sha256(raw_bytes).hexdigest() != expected_file_digest:
        raise _D34WorkerValidationError("d34_experiment_trials_file_digest_mismatch")
    if batch_digest != expected_batch_digest or _digest(document) != batch_digest:
        raise _D34WorkerValidationError("d34_experiment_trials_digest_mismatch")
    expected_symbols = [str(symbol) for symbol in expected_universe]
    if (
        document.get("contract") != "hqa.d34_experiment_trial_batch/v1"
        or document.get("job_id") != expected_job_id
        or document.get("request_digest") != expected_request_digest
        or document.get("universe") != expected_symbols
        or document.get("universe_digest") != _digest(expected_symbols)
        or document.get("calendar_digest") != expected_calendar_digest
        or document.get("experiment_count") != expected_experiment_count
    ):
        raise _D34WorkerValidationError("d34_experiment_trials_identity_mismatch")
    experiments = document.get("experiments")
    attempts = document.get("attempts")
    return_dates = document.get("return_dates")
    if (
        not isinstance(experiments, list)
        or not isinstance(attempts, list)
        or len(attempts) != expected_experiment_count
        or not isinstance(return_dates, list)
        or not return_dates
        or _digest(return_dates) != expected_calendar_digest
    ):
        raise _D34WorkerValidationError("d34_experiment_trials_count_mismatch")
    attempt_statuses: dict[str, str] = {}
    attempt_order: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise _D34WorkerValidationError("d34_experiment_trial_invalid")
        experiment_id = str(attempt.get("experiment_id") or "").strip()
        status = str(attempt.get("status") or "").strip()
        if (
            not experiment_id
            or experiment_id in attempt_statuses
            or status not in {"succeeded", "failed"}
        ):
            raise _D34WorkerValidationError("d34_experiment_trial_invalid")
        attempt_statuses[experiment_id] = status
        attempt_order.append(experiment_id)
    successful_ids = {
        experiment_id for experiment_id, status in attempt_statuses.items() if status == "succeeded"
    }
    if document.get("successful_experiment_count") != len(successful_ids) or len(
        experiments
    ) != len(successful_ids):
        raise _D34WorkerValidationError("d34_experiment_trials_count_mismatch")

    successful_trials: dict[str, ResearchTrial] = {}
    experiment_ids: set[str] = set()
    for raw in experiments:
        if not isinstance(raw, dict):
            raise _D34WorkerValidationError("d34_experiment_trial_invalid")
        experiment_id = str(raw.get("experiment_id") or "").strip()
        subject = str(raw.get("subject") or "").strip()
        daily_returns = raw.get("daily_returns")
        if (
            not experiment_id
            or experiment_id in experiment_ids
            or not subject
            or not isinstance(daily_returns, list)
            or len(daily_returns) != len(return_dates)
        ):
            raise _D34WorkerValidationError("d34_experiment_trial_invalid")
        try:
            normalized_returns = [float(value) for value in daily_returns]
        except (TypeError, ValueError) as exc:
            raise _D34WorkerValidationError("d34_experiment_trial_invalid") from exc
        if any(not math.isfinite(value) for value in normalized_returns):
            raise _D34WorkerValidationError("d34_experiment_trial_invalid")
        run_id = f"{expected_job_id}:{experiment_id}"
        experiment_ids.add(experiment_id)
        successful_trials[experiment_id] = ResearchTrial.record(
            kind="d34_experiment",
            subject=subject,
            universe=expected_symbols,
            daily_returns=normalized_returns,
            window_start=str(return_dates[0])[:10],
            window_end=str(return_dates[-1])[:10],
            source=run_id,
            metadata={
                "run_id": run_id,
                "job_id": expected_job_id,
                "request_digest": expected_request_digest,
                "experiment_id": experiment_id,
                "attempt_status": "succeeded",
                "proposal_digest": raw.get("proposal_digest"),
                "experiment_receipt_digest": raw.get("experiment_receipt_digest"),
            },
        )
    if experiment_ids != successful_ids:
        raise _D34WorkerValidationError("d34_experiment_trials_count_mismatch")

    trials: list[ResearchTrial] = []
    for experiment_id in attempt_order:
        successful = successful_trials.get(experiment_id)
        if successful is not None:
            trials.append(successful)
            continue
        run_id = f"{expected_job_id}:{experiment_id}"
        trials.append(
            ResearchTrial.skipped(
                kind="d34_experiment",
                subject=f"failed:{experiment_id}",
                universe=expected_symbols,
                reason=_FAILED_EXPERIMENT_ATTEMPT_REASON,
                window_start=str(return_dates[0])[:10],
                window_end=str(return_dates[-1])[:10],
                source=run_id,
                metadata={
                    "run_id": run_id,
                    "job_id": expected_job_id,
                    "request_digest": expected_request_digest,
                    "experiment_id": experiment_id,
                    "attempt_status": "failed",
                },
            )
        )
    persistence = _append_and_reconcile_host_trials(
        data_root=data_root,
        job_id=expected_job_id,
        trials=trials,
    )
    return {
        "contract": "hqa.d34_host_trial_persistence/v1",
        "job_id": expected_job_id,
        "batch_digest": batch_digest,
        "completed_experiment_count": len(trials),
        "successful_experiment_count": len(successful_trials),
        **persistence,
    }


def persist_host_d34_experiment_attempts(
    *,
    data_root: Path,
    attempts_root: Path,
    expected_job_id: str,
    expected_request_digest: str,
    expected_universe: Sequence[str],
    expected_calendar_digest: str,
    max_experiment_count: int,
) -> dict[str, object]:
    """Persist the completed prefix of an interrupted experiment census."""
    from quant_system.research.trials import ResearchTrial

    paths = sorted(attempts_root.glob("*.json"))
    if len(paths) > max_experiment_count:
        raise _D34WorkerValidationError("d34_experiment_trials_count_mismatch")
    expected_symbols = [str(symbol) for symbol in expected_universe]
    experiment_ids: set[str] = set()
    trials: list[ResearchTrial] = []
    attempt_receipt_digests: dict[str, str] = {}
    for path in paths:
        try:
            raw_bytes = path.read_bytes()
            document = json.loads(raw_bytes)
            receipt_digest = str(document.pop("receipt_digest"))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _D34WorkerValidationError("d34_experiment_trial_attempt_unreadable") from exc
        experiment_id = str(document.get("experiment_id") or "").strip()
        return_dates = document.get("return_dates")
        status = str(document.get("status") or "").strip()
        if (
            _digest(document) != receipt_digest
            or document.get("contract") != "hqa.d34_experiment_trial_attempt/v1"
            or document.get("job_id") != expected_job_id
            or document.get("request_digest") != expected_request_digest
            or document.get("universe") != expected_symbols
            or document.get("universe_digest") != _digest(expected_symbols)
            or document.get("calendar_digest") != expected_calendar_digest
            or not isinstance(return_dates, list)
            or _digest(return_dates) != expected_calendar_digest
            or not experiment_id
            or path.stem != experiment_id
            or experiment_id in experiment_ids
            or status not in {"succeeded", "failed"}
        ):
            raise _D34WorkerValidationError("d34_experiment_trial_attempt_invalid")
        experiment_ids.add(experiment_id)
        attempt_receipt_digests[experiment_id] = receipt_digest
        run_id = f"{expected_job_id}:{experiment_id}"
        if status == "failed":
            trials.append(
                ResearchTrial.skipped(
                    kind="d34_experiment",
                    subject=f"failed:{experiment_id}",
                    universe=expected_symbols,
                    reason=_FAILED_EXPERIMENT_ATTEMPT_REASON,
                    window_start=str(return_dates[0])[:10],
                    window_end=str(return_dates[-1])[:10],
                    source=run_id,
                    metadata={
                        "run_id": run_id,
                        "job_id": expected_job_id,
                        "request_digest": expected_request_digest,
                        "experiment_id": experiment_id,
                        "attempt_status": "failed",
                    },
                )
            )
            continue
        daily_returns = document.get("daily_returns")
        subject = str(document.get("subject") or "").strip()
        if (
            not isinstance(daily_returns, list)
            or len(daily_returns) != len(return_dates)
            or not subject
        ):
            raise _D34WorkerValidationError("d34_experiment_trial_attempt_invalid")
        try:
            normalized_returns = [float(value) for value in daily_returns]
        except (TypeError, ValueError) as exc:
            raise _D34WorkerValidationError("d34_experiment_trial_attempt_invalid") from exc
        if any(not math.isfinite(value) for value in normalized_returns):
            raise _D34WorkerValidationError("d34_experiment_trial_attempt_invalid")
        trials.append(
            ResearchTrial.record(
                kind="d34_experiment",
                subject=subject,
                universe=expected_symbols,
                daily_returns=normalized_returns,
                window_start=str(return_dates[0])[:10],
                window_end=str(return_dates[-1])[:10],
                source=run_id,
                metadata={
                    "run_id": run_id,
                    "job_id": expected_job_id,
                    "request_digest": expected_request_digest,
                    "experiment_id": experiment_id,
                    "attempt_status": "succeeded",
                    "proposal_digest": document.get("proposal_digest"),
                    "experiment_receipt_digest": document.get("experiment_receipt_digest"),
                },
            )
        )
    persistence = _append_and_reconcile_host_trials(
        data_root=data_root,
        job_id=expected_job_id,
        trials=trials,
    )
    return {
        "contract": "hqa.d34_host_trial_persistence/v1",
        "job_id": expected_job_id,
        "completed_experiment_count": len(paths),
        "successful_experiment_count": sum(
            trial.metadata.get("attempt_status") == "succeeded" for trial in trials
        ),
        "attempt_receipt_digests": attempt_receipt_digests,
        "interrupted_research": True,
        **persistence,
    }


@dataclass(frozen=True)
class D34WorkerConfig:
    workspace_root: Path
    data_root: Path
    platform_root: Path
    hqa_root: Path
    cache_root: Path
    workspace_id: str = "default"
    worker_id: str = "hqa-d34-launchagent"
    lookback_days: int = 1095
    lease_seconds: int = 7200

    def __post_init__(self) -> None:
        roots = (
            self.workspace_root,
            self.data_root,
            self.platform_root,
            self.cache_root,
        )
        if (
            any(not path.resolve().is_dir() for path in roots)
            or not self.workspace_id
            or not self.worker_id
            or not 90 <= self.lookback_days <= 3650
            or self.lease_seconds != 7200
        ):
            raise ValueError("d34_worker_config_invalid")


@dataclass(frozen=True)
class D34WorkerResult:
    status: str
    code: str
    job_id: str | None = None
    artifact_id: str | None = None


class D34CycleWorker:
    def __init__(
        self,
        *,
        config: D34WorkerConfig,
        jobs: Any,
        registry: Any,
        docker_runtime: Any,
        futu_provider: Any,
        platform_replay: Callable[..., Any],
        research_state_projector: Callable[[str], None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.jobs = jobs
        self.registry = registry
        self.docker_runtime = docker_runtime
        self.futu_provider = futu_provider
        self.platform_replay = platform_replay
        self.research_state_projector = research_state_projector or (lambda _job_id: None)
        self.now = now

    def _container_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.config.workspace_root.resolve())
        except ValueError as exc:
            raise ValueError("d34_workspace_path_invalid") from exc
        return f"/workspace/d34/{relative.as_posix()}"

    def _host_path(self, raw: object) -> Path:
        prefix = "/workspace/d34/"
        value = str(raw)
        if not value.startswith(prefix):
            raise ValueError("d34_container_path_invalid")
        path = (self.config.workspace_root / value.removeprefix(prefix)).resolve()
        try:
            path.relative_to(self.config.workspace_root.resolve())
        except ValueError as exc:
            raise ValueError("d34_container_path_invalid") from exc
        return path

    def _materialize_snapshot(self, document: Mapping[str, object]) -> dict[str, object]:
        market_session = latest_us_market_session(self.now().astimezone(_MARKET_TIMEZONE).date())
        snapshot = create_market_data_snapshot(
            provider=self.futu_provider,
            symbols=tuple(str(value) for value in document["universe"]),  # type: ignore[index]
            start=(market_session - timedelta(days=self.config.lookback_days)).isoformat(),
            end=market_session.isoformat(),
            output_root=self.config.workspace_root / "snapshots",
            now=self.now,
        )
        bars = pd.read_parquet(snapshot.parquet_path)
        latest = pd.to_datetime(bars["timestamp"], utc=True).max()
        if pd.Timestamp(self.now()) - latest > pd.Timedelta(days=7):
            raise ValueError("d34_snapshot_stale")
        return {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_digest": snapshot.snapshot_digest,
            "snapshot_parquet": snapshot.parquet_path,
        }

    @staticmethod
    def _engine_receipt(
        path: Path,
        *,
        expected_engine: str,
        expected_job_id: str,
        expected_run_id: str,
        expected_factor_id: str | None = None,
        expected_candidate_code_digest: str | None = None,
    ) -> EngineReceipt:
        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result

        try:
            raw = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("nonfinite JSON number")
                ),
            )
            if not isinstance(raw, dict):
                raise ValueError("engine receipt must be an object")
            receipt_digest = str(raw.pop("receipt_digest"))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("d34_engine_receipt_unreadable") from exc
        daily_returns = raw.get("daily_returns")
        return_dates = raw.get("return_dates")
        terminal_nav = raw.get("terminal_nav")
        terminal_weights = raw.get("terminal_weights")
        if (
            _digest(raw) != receipt_digest
            or raw.get("contract") != "hqa.d34_engine_receipt/v1"
            or raw.get("engine") != expected_engine
            or raw.get("job_id") != expected_job_id
            or raw.get("run_id") != expected_run_id
            or (expected_factor_id is not None and raw.get("factor_id") != expected_factor_id)
            or (
                expected_candidate_code_digest is not None
                and raw.get("candidate_code_digest") != expected_candidate_code_digest
            )
            or type(daily_returns) is not list
            or len(daily_returns) < 2
            or any(
                type(value) not in {int, float} or not math.isfinite(float(value))
                for value in daily_returns
            )
            or type(return_dates) is not list
            or len(return_dates) != len(daily_returns)
            or any(type(value) is not str or not value for value in return_dates)
            or type(terminal_nav) not in {int, float}
            or not math.isfinite(float(terminal_nav))
            or float(terminal_nav) <= 0
            or type(terminal_weights) is not dict
            or any(
                type(symbol) is not str
                or not symbol
                or type(weight) not in {int, float}
                or not math.isfinite(float(weight))
                for symbol, weight in terminal_weights.items()
            )
        ):
            raise _D34WorkerValidationError("d34_engine_receipt_lineage_mismatch")
        return EngineReceipt(
            engine=expected_engine,  # type: ignore[arg-type]
            snapshot_digest=str(raw["snapshot_digest"]),
            universe_digest=str(raw["universe_digest"]),
            calendar_digest=str(raw["calendar_digest"]),
            target_weights_digest=str(raw["target_weights_digest"]),
            daily_returns=tuple(float(value) for value in daily_returns),
            return_dates=tuple(return_dates),
            terminal_nav=float(terminal_nav),
            terminal_weights={symbol: float(value) for symbol, value in terminal_weights.items()},
            receipt_digest=receipt_digest,
        )

    def _heartbeat(self, lease: Any) -> None:
        self.jobs.heartbeat(
            job_id=lease.job.job_id,
            lease_id=lease.lease_id,
            lease_seconds=self.config.lease_seconds,
        )

    @staticmethod
    def _receipt_from_document(raw: dict[str, object]) -> EngineReceipt:
        return EngineReceipt(
            engine=str(raw["engine"]),  # type: ignore[arg-type]
            snapshot_digest=str(raw["snapshot_digest"]),
            universe_digest=str(raw["universe_digest"]),
            calendar_digest=str(raw["calendar_digest"]),
            target_weights_digest=str(raw["target_weights_digest"]),
            daily_returns=tuple(float(value) for value in raw["daily_returns"]),  # type: ignore[union-attr]
            return_dates=tuple(str(value) for value in raw["return_dates"]),  # type: ignore[union-attr]
            terminal_nav=float(raw["terminal_nav"]),  # type: ignore[arg-type]
            terminal_weights={
                str(key): float(value)
                for key, value in dict(raw["terminal_weights"]).items()  # type: ignore[arg-type]
            },
            receipt_digest=str(raw["receipt_digest"]),
        )

    @staticmethod
    def _comparison_from_document(raw: dict[str, object]) -> EngineComparison:
        return EngineComparison(
            contract=str(raw["contract"]),
            accepted=bool(raw["accepted"]),
            reason_codes=tuple(str(value) for value in raw["reason_codes"]),  # type: ignore[union-attr]
            exact_inputs=bool(raw["exact_inputs"]),
            daily_return_correlation=float(raw["daily_return_correlation"]),  # type: ignore[arg-type]
            terminal_nav_difference_bps=float(raw["terminal_nav_difference_bps"]),  # type: ignore[arg-type]
            max_symbol_weight_difference_bps=float(
                raw["max_symbol_weight_difference_bps"]  # type: ignore[arg-type]
            ),
            policy_digest=str(raw["policy_digest"]),
            qlib_receipt_digest=str(raw["qlib_receipt_digest"]),
            platform_receipt_digest=str(raw["platform_receipt_digest"]),
            comparison_digest=str(raw["comparison_digest"]),
            per_symbol_weight_difference_bps={
                str(key): float(value)
                for key, value in dict(
                    raw["per_symbol_weight_difference_bps"]  # type: ignore[arg-type]
                ).items()
            },
        )

    def _write_recovery_bundle(
        self,
        *,
        job_root: Path,
        job_id: str,
        resource_envelope_id: str,
        resource_policy_digest: str,
        lease_id: str,
        run_id: str,
        document: dict[str, object],
        research_output: dict[str, object],
        image_digest: str,
        qlib_receipt: EngineReceipt,
        platform_receipt: EngineReceipt,
        qlib_raw_receipt_path: Path,
        platform_raw_receipt_path: Path,
        comparison: EngineComparison,
        outcome_document: Mapping[str, object],
        budget_spent_usd: Decimal,
        provider_receipt_digest: str,
    ) -> None:
        body = {
            "contract": "hqa.d34_terminal_recovery/v1",
            "job_id": job_id,
            "lease_id": lease_id,
            "run_id": run_id,
            "resource_envelope_id": resource_envelope_id,
            "resource_policy_digest": resource_policy_digest,
            "workspace_id": self.config.workspace_id,
            "universe": list(document["universe"]),
            "factor_id": research_output["factor_id"],
            "factor_path": research_output["factor_path"],
            "candidate_code_digest": research_output["candidate_code_digest"],
            "qlib_config_digest": research_output["qlib_config_digest"],
            "rdagent_commit": research_output["rdagent_commit"],
            "qlib_commit": research_output["qlib_commit"],
            "docker_image_digest": image_digest,
            "qlib_receipt": asdict(qlib_receipt),
            "platform_receipt": asdict(platform_receipt),
            "qlib_raw_receipt_path": self._container_path(qlib_raw_receipt_path),
            "platform_raw_receipt_path": self._container_path(platform_raw_receipt_path),
            "comparison": asdict(comparison),
            "outcome_document": dict(outcome_document),
            "budget_spent_usd": f"{budget_spent_usd:.6f}",
            "provider_receipt_digest": provider_receipt_digest,
        }
        _write_json(
            job_root / "terminal_recovery.json",
            {**body, "recovery_digest": _digest(body)},
        )

    def _read_recovery_bundle(self, path: Path) -> dict[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            recovery_digest = str(raw.pop("recovery_digest"))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("d34_recovery_bundle_unreadable") from exc
        if raw.get("contract") != "hqa.d34_terminal_recovery/v1" or _digest(raw) != recovery_digest:
            raise ValueError("d34_recovery_bundle_digest_mismatch")
        return raw

    def _publish_success_terminal(
        self,
        *,
        job_root: Path,
        phase_path: Path,
        job_id: str,
        document: Mapping[str, object],
        input_digest: str,
        research_request: Mapping[str, object],
        artifact: Any,
        factor_path: Path,
        qlib_bound_path: Path,
        platform_bound_path: Path,
        qlib_raw_path: Path,
        platform_raw_path: Path,
        qlib_receipt: EngineReceipt,
        platform_receipt: EngineReceipt,
        comparison: EngineComparison,
        recovery_digest: str,
        outcome_document: Mapping[str, object],
        commission_bps: float,
        slippage_bps: float,
        recovered: bool = False,
    ) -> dict[str, object]:
        cycle_document: dict[str, object] = {
            "phase": "candidate_ready",
            "job_id": job_id,
            "run_id": str(research_request.get("run_id") or ""),
            "artifact_id": artifact.artifact_id,
            **dict(outcome_document),
        }
        if recovered:
            cycle_document["recovered"] = True
        factor_relative = factor_path.resolve().relative_to(job_root.resolve())
        qlib_relative = qlib_bound_path.resolve().relative_to(job_root.resolve())
        platform_relative = platform_bound_path.resolve().relative_to(job_root.resolve())
        evidence_body = {
            "contract": "hqa.d34_research_evidence/v1",
            "job_id": job_id,
            "run_id": str(research_request.get("run_id") or ""),
            "job_key": str(document.get("job_key") or ""),
            "operation_id": str(document.get("operation_id") or ""),
            "material_digest": str(document.get("material_digest") or ""),
            "job_input_digest": input_digest,
            "research_request_digest": _digest(dict(research_request)),
            "cycle_receipt_digest": _digest(cycle_document),
            "terminal_recovery_digest": recovery_digest,
            "artifact_id": artifact.artifact_id,
            "artifact_version": artifact.version,
            "candidate_code_path": factor_relative.as_posix(),
            "candidate_code_digest": str(outcome_document["candidate_code_digest"]),
            "qlib_receipt_path": qlib_relative.as_posix(),
            "qlib_receipt_file_digest": _file_digest(qlib_bound_path),
            "qlib_receipt_digest": qlib_receipt.receipt_digest,
            "qlib_raw_receipt_path": qlib_raw_path.resolve()
            .relative_to(job_root.resolve())
            .as_posix(),
            "qlib_raw_receipt_file_digest": _file_digest(qlib_raw_path),
            "platform_receipt_path": platform_relative.as_posix(),
            "platform_receipt_file_digest": _file_digest(platform_bound_path),
            "platform_receipt_digest": platform_receipt.receipt_digest,
            "platform_raw_receipt_path": platform_raw_path.resolve()
            .relative_to(job_root.resolve())
            .as_posix(),
            "platform_raw_receipt_file_digest": _file_digest(platform_raw_path),
            "comparison_digest": comparison.comparison_digest,
            "comparison": {
                "accepted": comparison.accepted,
                "daily_return_correlation": comparison.daily_return_correlation,
                "terminal_nav_difference_bps": comparison.terminal_nav_difference_bps,
                "max_symbol_weight_difference_bps": (comparison.max_symbol_weight_difference_bps),
            },
            "cost_model": {
                "commission_bps": commission_bps,
                "slippage_bps": slippage_bps,
            },
        }
        evidence_document = {
            **evidence_body,
            "manifest_digest": _digest(evidence_body),
        }
        terminal_bundle = {
            "contract": "hqa.d34_terminal_bundle/v1",
            "job_id": job_id,
            "cycle_receipt": cycle_document,
            "evidence_manifest": evidence_document,
        }
        _write_json(
            job_root / "terminal_bundle.json",
            {**terminal_bundle, "bundle_digest": _digest(terminal_bundle)},
        )
        _write_json(phase_path, cycle_document)
        _write_json(job_root / "evidence_manifest.json", evidence_document)
        return cycle_document

    def _recover_terminal(self) -> D34WorkerResult | None:
        for phase_path in sorted(
            (self.config.workspace_root / "jobs").glob("job-*/cycle_receipt.json")
        ):
            try:
                phase_document = json.loads(phase_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if phase_document.get("phase") != "needs_recovery":
                continue
            job_root = phase_path.parent
            job_id = str(phase_document.get("job_id", job_root.name))
            try:
                bundle = self._read_recovery_bundle(job_root / "terminal_recovery.json")
                if (
                    bundle.get("job_id") != job_id
                    or bundle.get("resource_envelope_id") != LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID
                    or bundle.get("resource_policy_digest") != LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST
                    or bundle.get("workspace_id") != self.config.workspace_id
                ):
                    continue
                run_id = str(bundle.get("run_id") or "")
                qlib_receipt = self._engine_receipt(
                    self._host_path(bundle["qlib_raw_receipt_path"]),
                    expected_engine="qlib",
                    expected_job_id=job_id,
                    expected_run_id=run_id,
                    expected_factor_id=str(bundle.get("factor_id") or ""),
                    expected_candidate_code_digest=str(bundle.get("candidate_code_digest") or ""),
                )
                platform_receipt = self._engine_receipt(
                    self._host_path(bundle["platform_raw_receipt_path"]),
                    expected_engine="platform",
                    expected_job_id=job_id,
                    expected_run_id=run_id,
                )
                if (
                    self._receipt_from_document(
                        dict(bundle["qlib_receipt"])  # type: ignore[arg-type]
                    )
                    != qlib_receipt
                    or self._receipt_from_document(
                        dict(bundle["platform_receipt"])  # type: ignore[arg-type]
                    )
                    != platform_receipt
                ):
                    raise ValueError("d34_recovery_engine_receipt_mismatch")
                comparison = self._comparison_from_document(
                    dict(bundle["comparison"])  # type: ignore[arg-type]
                )
                evaluation = self.registry.record_artifact_evaluation(
                    RegisterArtifactCommand(
                        job_id=job_id,
                        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
                        workspace_id=self.config.workspace_id,
                        qlib_receipt=qlib_receipt,
                        platform_receipt=platform_receipt,
                        comparison=comparison,
                        candidate_code_digest=str(bundle["candidate_code_digest"]),
                        qlib_config_digest=str(bundle["qlib_config_digest"]),
                        rdagent_commit=str(bundle["rdagent_commit"]),
                        qlib_commit=str(bundle["qlib_commit"]),
                        docker_image_digest=str(bundle["docker_image_digest"]),
                    )
                )
                if not evaluation.accepted or evaluation.artifact is None:
                    _write_json(phase_path, {"phase": "rejected", "job_id": job_id})
                    return D34WorkerResult(
                        status="rejected",
                        code="dual_engine_comparison_rejected",
                        job_id=job_id,
                    )
                artifact = evaluation.artifact
                input_receipt = json.loads(
                    (job_root / "job_input.json").read_text(encoding="utf-8")
                )
                input_receipt_digest = str(input_receipt.pop("receipt_digest"))
                document = input_receipt.get("input_document")
                input_digest = str(input_receipt.get("input_digest") or "")
                outcome_document = bundle.get("outcome_document")
                if (
                    input_receipt.get("contract") != "hqa.d34_job_input_receipt/v1"
                    or input_receipt.get("job_id") != job_id
                    or input_receipt_digest != _digest(input_receipt)
                    or not isinstance(document, dict)
                    or input_digest != _digest(document)
                    or not isinstance(outcome_document, dict)
                    or outcome_document.get("comparison_accepted") is not True
                    or outcome_document.get("candidate_code_digest")
                    != bundle.get("candidate_code_digest")
                    or outcome_document.get("qlib_receipt_digest") != qlib_receipt.receipt_digest
                    or outcome_document.get("platform_receipt_digest")
                    != platform_receipt.receipt_digest
                    or outcome_document.get("comparison_digest") != comparison.comparison_digest
                ):
                    raise ValueError("d34_recovery_evidence_invalid")
                research_request = json.loads(
                    (job_root / "research_request.json").read_text(encoding="utf-8")
                )
                if (
                    not isinstance(research_request, dict)
                    or research_request.get("job_id") != job_id
                    or research_request.get("job_key") != document.get("job_key")
                ):
                    raise ValueError("d34_recovery_request_invalid")
                from quant_system.config.settings import load_settings

                paper_costs = load_settings().paper_account
                self._publish_success_terminal(
                    job_root=job_root,
                    phase_path=phase_path,
                    job_id=job_id,
                    document=document,
                    input_digest=input_digest,
                    research_request=research_request,
                    artifact=artifact,
                    factor_path=self._host_path(bundle["factor_path"]),
                    qlib_bound_path=job_root / "qlib_engine_receipt.json",
                    platform_bound_path=job_root / "platform_engine_receipt.json",
                    qlib_raw_path=self._host_path(bundle["qlib_raw_receipt_path"]),
                    platform_raw_path=self._host_path(bundle["platform_raw_receipt_path"]),
                    qlib_receipt=qlib_receipt,
                    platform_receipt=platform_receipt,
                    comparison=comparison,
                    recovery_digest=_digest(bundle),
                    outcome_document=outcome_document,
                    commission_bps=paper_costs.commission_bps,
                    slippage_bps=paper_costs.slippage_bps,
                    recovered=True,
                )
                return D34WorkerResult(
                    status="candidate_ready",
                    code="verified_candidate_not_hung",
                    job_id=job_id,
                    artifact_id=artifact.artifact_id,
                )
            except Exception as exc:  # noqa: BLE001 - durable recovery boundary
                _write_json(
                    phase_path,
                    {
                        **phase_document,
                        "phase": "needs_recovery",
                        "last_recovery_at": self.now().isoformat(),
                        "last_recovery_code": str(getattr(exc, "code", type(exc).__name__)),
                        "last_recovery_error": str(exc)[:2_000],
                    },
                )
                return D34WorkerResult(
                    status="needs_recovery",
                    code=str(getattr(exc, "code", type(exc).__name__)),
                    job_id=job_id,
                )
        return None

    def _recover_research_terminal(self) -> D34WorkerResult | None:
        job_rows: dict[str, object] = {}
        for item in self.jobs.list(
            workspace_id=self.config.workspace_id,
            limit=100,
            state=None,
        ):
            job_id = str(item.get("job_id") if isinstance(item, Mapping) else item.job_id)
            job_rows[job_id] = item
        for recovery_path in sorted(
            (self.config.workspace_root / "jobs").glob("job-*/terminal_recovery.json")
        ):
            phase_path = recovery_path.parent / "cycle_receipt.json"
            try:
                phase_document = (
                    json.loads(phase_path.read_text(encoding="utf-8"))
                    if phase_path.is_file()
                    else {}
                )
                bundle = self._read_recovery_bundle(recovery_path)
                job_id = str(bundle.get("job_id") or recovery_path.parent.name)
                row = job_rows.get(job_id)
                state = str(
                    row.get("state") if isinstance(row, Mapping) else getattr(row, "state", "")
                )
                if phase_document.get("phase") in {"candidate_ready", "rejected", "failed"}:
                    continue
                if (
                    bundle.get("resource_envelope_id") != LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID
                    or bundle.get("resource_policy_digest") != LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST
                ):
                    continue
                if state in {"leased", "running"}:
                    comparison = bundle.get("comparison")
                    outcome_document = bundle.get("outcome_document")
                    if not isinstance(comparison, dict) or not isinstance(outcome_document, dict):
                        raise ValueError("d34_recovery_evidence_invalid")
                    accepted = comparison.get("accepted") is True
                    state = "succeeded" if accepted else "rejected"
                    self.jobs.finish(
                        job_id=job_id,
                        lease_id=str(bundle.get("lease_id") or ""),
                        state=state,
                        outcome_code=(
                            "artifact_policy_accepted"
                            if accepted
                            else "dual_engine_comparison_rejected"
                        ),
                        outcome_document=outcome_document,
                        budget_spent_usd=Decimal(str(bundle["budget_spent_usd"])),
                        provider_receipt_digest=str(bundle["provider_receipt_digest"]),
                    )
                if state not in {"succeeded", "rejected"}:
                    continue
                if phase_document.get("phase") != "needs_recovery":
                    _write_json(
                        phase_path,
                        {
                            "phase": "needs_recovery",
                            "job_id": job_id,
                            "recovery": "terminal_job_projection",
                        },
                    )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            return self._recover_terminal()
        return None

    def _run_lease(self, lease: Any) -> D34WorkerResult:
        durable = self.jobs.read_leased_input(job_id=lease.job.job_id, lease_id=lease.lease_id)
        document = durable.input_document
        job_id = lease.job.job_id
        job_root = self.config.workspace_root / "jobs" / job_id
        job_root.mkdir(parents=True, exist_ok=True)
        phase_path = job_root / "cycle_receipt.json"
        terminal = False
        phase = "input_validation"
        preflight_receipt_digest: str | None = None
        research_output: dict[str, object] | None = None
        trial_persistence: dict[str, object] | None = None
        try:
            if _digest(document) != durable.input_digest:
                raise _D34WorkerValidationError("d34_job_input_digest_mismatch")
            job_input_receipt = {
                "contract": "hqa.d34_job_input_receipt/v1",
                "job_id": job_id,
                "input_digest": durable.input_digest,
                "input_document": document,
            }
            _write_json(
                job_root / "job_input.json",
                {
                    **job_input_receipt,
                    "receipt_digest": _digest(job_input_receipt),
                },
            )
            if (
                document.get("contract") != JOB_INPUT_CONTRACT
                or document.get("trigger") != OWNER_REQUEST_TRIGGER
                or len(str(document.get("objective", "")).strip()) < 8
                or not _is_digest(document.get("operation_id"))
                or not _is_digest(document.get("material_digest"))
                or not str(document.get("platform_session_id") or "").strip()
                or not str(document.get("hermes_session_id") or "").strip()
            ):
                raise _D34WorkerValidationError("d34_job_not_owner_requested")
            if (
                lease.job.resource_envelope_id != LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID
                or document.get("resource_envelope_id") != lease.job.resource_envelope_id
                or document.get("resource_policy_digest") != LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST
                or document.get("research_only") is not True
                or document.get("paper_execution_allowed") is not False
            ):
                raise _D34WorkerValidationError("d34_research_job_envelope_mismatch")
            phase = "llm_preflight"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            preflight = run_d34_llm_preflight(
                workspace_root=self.config.workspace_root,
                job_id=job_id,
                docker_runtime=self.docker_runtime,
                now=self.now,
            )
            preflight_receipt_digest = preflight.receipt_digest
            if not preflight.ready:
                raise _D34WorkerValidationError(str(preflight.code or "d34_preflight_llm_failed"))
            phase = "starting"
            self.jobs.mark_running(job_id=job_id, lease_id=lease.lease_id, container_id=None)
            self.research_state_projector(job_id)
            self._heartbeat(lease)
            phase = "snapshot"
            snapshot = self._materialize_snapshot(document)
            snapshot_parquet = Path(str(snapshot["snapshot_parquet"]))
            phase = "qlib_adapt"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            qlib_root = job_root / "qlib"
            adapter = self.docker_runtime.run(
                job_id=job_id,
                command=(
                    "qlib-adapt",
                    "--snapshot-id",
                    str(snapshot["snapshot_id"]),
                    "--snapshot-digest",
                    str(snapshot["snapshot_digest"]),
                    "--snapshot-parquet",
                    self._container_path(snapshot_parquet),
                    "--output-root",
                    self._container_path(qlib_root),
                ),
            )
            self._heartbeat(lease)
            bars = pd.read_parquet(snapshot_parquet)
            calendar = tuple(
                pd.Timestamp(value).isoformat()
                for value in sorted(pd.to_datetime(bars["timestamp"], utc=True).unique())
            )
            research_request = {
                "contract": RESEARCH_REQUEST_CONTRACT,
                "job_id": job_id,
                "run_id": lease.attempt_id,
                "resource_envelope_id": lease.job.resource_envelope_id,
                "resource_policy_digest": LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_digest": snapshot["snapshot_digest"],
                "snapshot_source": "futu",
                "provider_uri": adapter.output["provider_uri"],
                "universe": list(document["universe"]),
                "calendar": list(calendar),
                "max_iterations": int(document["max_iterations"]),
                "experiments_per_iteration": int(document["experiments_per_iteration"]),
                "top_k": int(document["top_k"]),
                "initial_cash": 100_000.0,
                "budget_reservation_usd": float(lease.job.budget_reserved_usd),
                "objective": str(document["objective"]).strip(),
                "preflight_receipt_digest": preflight_receipt_digest,
                # Admission-side lineage: lets the assistant-remote book join an
                # accepted artifact back to the owner's dispatched request.
                "job_key": str(document.get("job_key") or lease.job.job_key),
            }
            if "formula" in document:
                research_request["formula"] = document["formula"]
            experiment_count = (
                1 if research_request.get("formula") else
                int(research_request["max_iterations"])
                * int(research_request["experiments_per_iteration"])
            )
            request_path = job_root / "research_request.json"
            _write_json(request_path, research_request)
            phase = "research"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            try:
                research = self.docker_runtime.run(
                    job_id=job_id,
                    command=(
                        "research",
                        "--request",
                        self._container_path(request_path),
                        "--output-root",
                        self._container_path(job_root / "research"),
                    ),
                )
            except D34DockerRuntimeError:
                batch_path = (
                    job_root
                    / "research"
                    / f"experiment-trials-{_research_request_digest(research_request)[:32]}.json"
                )
                attempts_root = (
                    job_root
                    / "research"
                    / f"experiment-trial-attempts-{_research_request_digest(research_request)[:32]}"
                )
                if batch_path.is_file():
                    raw_batch = batch_path.read_bytes()
                    batch_document = json.loads(raw_batch)
                    phase = "trial_persistence_after_research_failure"
                    _write_json(phase_path, {"phase": phase, "job_id": job_id})
                    trial_persistence = persist_host_d34_experiment_trials(
                        data_root=self.config.data_root,
                        batch_path=batch_path,
                        expected_file_digest=hashlib.sha256(raw_batch).hexdigest(),
                        expected_batch_digest=str(batch_document["receipt_digest"]),
                        expected_job_id=job_id,
                        expected_request_digest=_research_request_digest(research_request),
                        expected_universe=tuple(str(value) for value in document["universe"]),
                        expected_calendar_digest=_digest(list(research_request["calendar"])),
                        expected_experiment_count=experiment_count,
                    )
                elif attempts_root.is_dir():
                    phase = "trial_persistence_after_interrupted_research"
                    _write_json(phase_path, {"phase": phase, "job_id": job_id})
                    trial_persistence = persist_host_d34_experiment_attempts(
                        data_root=self.config.data_root,
                        attempts_root=attempts_root,
                        expected_job_id=job_id,
                        expected_request_digest=_research_request_digest(research_request),
                        expected_universe=tuple(str(value) for value in document["universe"]),
                        expected_calendar_digest=_digest(list(research_request["calendar"])),
                        max_experiment_count=experiment_count,
                    )
                raise
            research_output = dict(research.output)
            self._heartbeat(lease)
            phase = "trial_persistence"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            trial_persistence = persist_host_d34_experiment_trials(
                data_root=self.config.data_root,
                batch_path=self._host_path(research_output["experiment_trials_path"]),
                expected_file_digest=str(research_output["experiment_trials_file_digest"]),
                expected_batch_digest=str(research_output["experiment_trials_digest"]),
                expected_job_id=job_id,
                expected_request_digest=_research_request_digest(research_request),
                expected_universe=tuple(str(value) for value in document["universe"]),
                expected_calendar_digest=_digest(list(research_request["calendar"])),
                expected_experiment_count=experiment_count,
            )
            self._heartbeat(lease)
            qlib_receipt_path = self._host_path(research_output["qlib_receipt_path"])
            qlib_receipt = self._engine_receipt(
                qlib_receipt_path,
                expected_engine="qlib",
                expected_job_id=job_id,
                expected_run_id=lease.attempt_id,
                expected_factor_id=str(research_output["factor_id"]),
                expected_candidate_code_digest=str(research_output["candidate_code_digest"]),
            )
            qlib_raw_relative = qlib_receipt_path.resolve().relative_to(job_root.resolve())
            qlib_bound_body = {
                "contract": "hqa.d34_bound_engine_receipt/v2",
                "job_id": job_id,
                "run_id": lease.attempt_id,
                "resource_envelope_id": lease.job.resource_envelope_id,
                "engine": "qlib",
                "raw_receipt_path": qlib_raw_relative.as_posix(),
                "raw_receipt_file_digest": _file_digest(qlib_receipt_path),
                "engine_receipt": asdict(qlib_receipt),
                "turnover_period": _qlib_turnover_period(
                    qlib_receipt_path, expected_receipt_digest=qlib_receipt.receipt_digest
                ),
            }
            qlib_bound_path = job_root / "qlib_engine_receipt.json"
            _write_json(
                qlib_bound_path,
                {
                    **qlib_bound_body,
                    "receipt_digest": _digest(qlib_bound_body),
                },
            )
            target_weights_path = self._host_path(research_output["target_weights_path"])
            phase = "platform_replay"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            # R3 parity: the replay charges the same costs as every paper path,
            # from the single PaperAccountSettings source instead of literals.
            from quant_system.config.settings import load_settings

            paper_costs = load_settings().paper_account
            replay = self.platform_replay(
                qlib_receipt=qlib_receipt,
                job_id=job_id,
                run_id=lease.attempt_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                snapshot_digest=str(snapshot["snapshot_digest"]),
                snapshot_parquet=snapshot_parquet,
                target_weights_parquet=target_weights_path,
                output_root=job_root / "platform-replay",
                initial_cash=100_000,
                commission_bps=paper_costs.commission_bps,
                slippage_bps=paper_costs.slippage_bps,
                min_order_value=0,
                whole_share_orders=False,
            )
            platform_raw_path = Path(replay.output_dir) / "receipt.json"
            try:
                platform_raw_relative = platform_raw_path.resolve().relative_to(job_root.resolve())
            except ValueError as exc:
                raise _D34WorkerValidationError("platform_replay_receipt_outside_job") from exc
            if not platform_raw_path.is_file() or platform_raw_path.is_symlink():
                raise _D34WorkerValidationError("platform_replay_receipt_missing")
            platform_receipt = self._engine_receipt(
                platform_raw_path,
                expected_engine="platform",
                expected_job_id=job_id,
                expected_run_id=lease.attempt_id,
            )
            if platform_receipt != replay.engine_receipt:
                raise _D34WorkerValidationError("d34_engine_receipt_lineage_mismatch")
            platform_bound_body = {
                "contract": "hqa.d34_bound_engine_receipt/v2",
                "job_id": job_id,
                "run_id": lease.attempt_id,
                "resource_envelope_id": lease.job.resource_envelope_id,
                "engine": "platform",
                "raw_receipt_path": platform_raw_relative.as_posix(),
                "raw_receipt_file_digest": _file_digest(platform_raw_path),
                "engine_receipt": asdict(platform_receipt),
                "turnover_period": getattr(replay, "turnover_period", None),
            }
            platform_receipt_path = job_root / "platform_engine_receipt.json"
            _write_json(
                platform_receipt_path,
                {
                    **platform_bound_body,
                    "receipt_digest": _digest(platform_bound_body),
                },
            )
            comparison = compare_engine_receipts(
                qlib=qlib_receipt,
                platform=platform_receipt,
                policy=ComparisonPolicy.initial(),
            )
            state = "succeeded" if comparison.accepted else "rejected"
            outcome_code = (
                "artifact_policy_accepted"
                if comparison.accepted
                else "dual_engine_comparison_rejected"
            )
            outcome_document = {
                "contract": "hqa.d34_job_outcome/v1",
                "snapshot_digest": snapshot["snapshot_digest"],
                "candidate_code_digest": research_output["candidate_code_digest"],
                "qlib_receipt_digest": qlib_receipt.receipt_digest,
                "platform_receipt_digest": platform_receipt.receipt_digest,
                "comparison_digest": comparison.comparison_digest,
                "comparison_accepted": comparison.accepted,
                "trial_persistence": trial_persistence,
                "factor_path": str(
                    self._host_path(research_output["factor_path"]).relative_to(
                        self.config.workspace_root
                    )
                ),
            }
            metering = research_output.get("budget_metering")
            if metering:
                outcome_document["budget_metering"] = metering
            self._write_recovery_bundle(
                job_root=job_root,
                job_id=job_id,
                resource_envelope_id=lease.job.resource_envelope_id,
                resource_policy_digest=LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
                lease_id=lease.lease_id,
                run_id=lease.attempt_id,
                document=document,
                research_output=research_output,
                image_digest=research.image_digest,
                qlib_receipt=qlib_receipt,
                platform_receipt=platform_receipt,
                qlib_raw_receipt_path=qlib_receipt_path,
                platform_raw_receipt_path=platform_raw_path,
                comparison=comparison,
                outcome_document=outcome_document,
                budget_spent_usd=Decimal(str(research_output["budget_spent_usd"])),
                provider_receipt_digest=research.receipt_digest,
            )
            self.jobs.finish(
                job_id=job_id,
                lease_id=lease.lease_id,
                state=state,
                outcome_code=outcome_code,
                outcome_document=outcome_document,
                budget_spent_usd=Decimal(str(research_output["budget_spent_usd"])),
                provider_receipt_digest=research.receipt_digest,
            )
            terminal = True
            phase = "artifact_registry"
            evaluation = self.registry.record_artifact_evaluation(
                RegisterArtifactCommand(
                    job_id=job_id,
                    resource_envelope_id=lease.job.resource_envelope_id,
                    workspace_id=self.config.workspace_id,
                    qlib_receipt=qlib_receipt,
                    platform_receipt=platform_receipt,
                    comparison=comparison,
                    candidate_code_digest=str(research_output["candidate_code_digest"]),
                    qlib_config_digest=str(research_output["qlib_config_digest"]),
                    rdagent_commit=str(research_output["rdagent_commit"]),
                    qlib_commit=str(research_output["qlib_commit"]),
                    docker_image_digest=research.image_digest,
                )
            )
            if not evaluation.accepted or evaluation.artifact is None:
                rejected_cycle = {
                    "phase": "rejected",
                    "failed_phase": "comparison",
                    "job_id": job_id,
                    "code": outcome_code,
                    **outcome_document,
                }
                rejected_evidence = {
                    "contract": "hqa.d34_research_evidence/v1",
                    "job_id": job_id,
                    "job_key": str(document.get("job_key") or lease.job.job_key),
                    "operation_id": str(document.get("operation_id") or ""),
                    "material_digest": str(document.get("material_digest") or ""),
                    "job_input_digest": durable.input_digest,
                    "cycle_receipt_digest": _digest(rejected_cycle),
                    "terminal_status": "rejected",
                    "failed_phase": "comparison",
                    "failure_code": outcome_code,
                    "preflight_receipt_digest": preflight_receipt_digest,
                }
                rejected_evidence_document = {
                    **rejected_evidence,
                    "manifest_digest": _digest(rejected_evidence),
                }
                rejected_bundle = {
                    "contract": "hqa.d34_terminal_bundle/v1",
                    "job_id": job_id,
                    "cycle_receipt": rejected_cycle,
                    "evidence_manifest": rejected_evidence_document,
                }
                _write_json(
                    job_root / "terminal_bundle.json",
                    {
                        **rejected_bundle,
                        "bundle_digest": _digest(rejected_bundle),
                    },
                )
                _write_json(phase_path, rejected_cycle)
                _write_json(
                    job_root / "evidence_manifest.json",
                    rejected_evidence_document,
                )
                return D34WorkerResult(status="rejected", code=outcome_code, job_id=job_id)
            artifact = evaluation.artifact
            factor_path = self._host_path(research_output["factor_path"])
            recovery_document = json.loads(
                (job_root / "terminal_recovery.json").read_text(encoding="utf-8")
            )
            self._publish_success_terminal(
                job_root=job_root,
                phase_path=phase_path,
                job_id=job_id,
                document=document,
                input_digest=durable.input_digest,
                research_request=research_request,
                artifact=artifact,
                factor_path=factor_path,
                qlib_bound_path=qlib_bound_path,
                platform_bound_path=platform_receipt_path,
                qlib_raw_path=qlib_receipt_path,
                platform_raw_path=platform_raw_path,
                qlib_receipt=qlib_receipt,
                platform_receipt=platform_receipt,
                comparison=comparison,
                recovery_digest=str(recovery_document.get("recovery_digest") or ""),
                outcome_document=outcome_document,
                commission_bps=paper_costs.commission_bps,
                slippage_bps=paper_costs.slippage_bps,
            )
            return D34WorkerResult(
                status="candidate_ready",
                code="verified_candidate_not_hung",
                job_id=job_id,
                artifact_id=artifact.artifact_id,
            )
        except Exception as exc:  # noqa: BLE001 - durable worker boundary
            code = getattr(exc, "code", type(exc).__name__)
            failure_outcome: dict[str, object] = {
                "phase": phase,
                "error_type": type(exc).__name__,
                "error": str(exc)[:2_000],
                "recovery": "inspect_cycle_receipt_and_content_addressed_outputs",
            }
            if trial_persistence is not None:
                failure_outcome["trial_persistence"] = trial_persistence
            if not terminal:
                ambiguous = phase == "research" and isinstance(exc, D34DockerRuntimeError)
                self.jobs.finish(
                    job_id=job_id,
                    lease_id=lease.lease_id,
                    state="outcome_unknown" if ambiguous else "rejected",
                    outcome_code=str(code)[:128],
                    outcome_document=failure_outcome,
                    budget_spent_usd=Decimal("0"),
                )
            failure_document = {
                "phase": "needs_recovery" if terminal else "failed",
                "failed_phase": phase,
                "job_id": job_id,
                "code": str(code),
                "error_type": type(exc).__name__,
                "error": str(exc)[:2_000],
                **(
                    {"trial_persistence": trial_persistence}
                    if trial_persistence is not None
                    else {}
                ),
            }
            failure_evidence = {
                "contract": "hqa.d34_research_evidence/v1",
                "job_id": job_id,
                "job_key": str(document.get("job_key") or lease.job.job_key),
                "operation_id": str(document.get("operation_id") or ""),
                "material_digest": str(document.get("material_digest") or ""),
                "job_input_digest": durable.input_digest,
                "cycle_receipt_digest": _digest(failure_document),
                "terminal_status": failure_document["phase"],
                "failed_phase": phase,
                "failure_code": str(code),
                "preflight_receipt_digest": preflight_receipt_digest,
            }
            failure_evidence_document = {
                **failure_evidence,
                "manifest_digest": _digest(failure_evidence),
            }
            failure_bundle = {
                "contract": "hqa.d34_terminal_bundle/v1",
                "job_id": job_id,
                "cycle_receipt": failure_document,
                "evidence_manifest": failure_evidence_document,
            }
            _write_json(
                job_root / "terminal_bundle.json",
                {
                    **failure_bundle,
                    "bundle_digest": _digest(failure_bundle),
                },
            )
            _write_json(phase_path, failure_document)
            _write_json(
                job_root / "evidence_manifest.json",
                failure_evidence_document,
            )
            return D34WorkerResult(
                status="needs_recovery" if terminal else "failed",
                code=str(code),
                job_id=job_id,
            )

    def run_once(self) -> D34WorkerResult:
        recovered = self._recover_research_terminal()
        if recovered is not None:
            return recovered
        self.jobs.reconcile_expired(workspace_id=self.config.workspace_id)
        lease = self.jobs.lease_next(
            workspace_id=self.config.workspace_id,
            worker_id=self.config.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if lease is None:
            return D34WorkerResult(status="idle", code="no_queued_job")
        return self._run_lease(lease)


__all__ = ["D34CycleWorker", "D34WorkerConfig", "D34WorkerResult"]
