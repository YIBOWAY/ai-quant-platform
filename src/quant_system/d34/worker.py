"""One durable D-34 research cycle for the persistent local Mac worker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
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
from quant_system.d34.research_request import enqueue_owner_research_request
from quant_system.hermes.d34_registry_authority import RegisterArtifactCommand

QLIB_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"
_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_RESEARCH_OPEN_TIME = time(6, 0)
_POST_CLOSE_LOCAL_WEEKDAYS = frozenset({1, 2, 3, 4, 5})


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


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json(document) + b"\n")
    temporary.replace(path)


@dataclass(frozen=True)
class D34WorkerConfig:
    workspace_root: Path
    platform_root: Path
    hqa_root: Path
    cache_root: Path
    workspace_id: str = "default"
    worker_id: str = "hqa-d34-launchagent"
    lookback_days: int = 1095
    lease_seconds: int = 86400

    def __post_init__(self) -> None:
        roots = (
            self.workspace_root,
            self.platform_root,
            self.hqa_root,
            self.cache_root,
        )
        if (
            any(not path.resolve().is_dir() for path in roots)
            or not self.workspace_id
            or not self.worker_id
            or not 90 <= self.lookback_days <= 3650
            or not 900 <= self.lease_seconds <= 86400
        ):
            raise ValueError("d34_worker_config_invalid")


@dataclass(frozen=True)
class D34WorkerResult:
    status: str
    code: str
    job_id: str | None = None
    artifact_id: str | None = None
    canary: object | None = None
    paper_cycle: object | None = None


class D34CycleWorker:
    def __init__(
        self,
        *,
        config: D34WorkerConfig,
        mandates: Any,
        jobs: Any,
        registry: Any,
        docker_runtime: Any,
        futu_provider: Any,
        platform_replay: Callable[..., Any],
        canary_activator: Callable[..., object],
        safety_observer: Callable[[], Mapping[str, object]] | None = None,
        canary_operator: Callable[[Mapping[str, object]], object] | None = None,
        today: Callable[[], date] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.mandates = mandates
        self.jobs = jobs
        self.registry = registry
        self.docker_runtime = docker_runtime
        self.futu_provider = futu_provider
        self.platform_replay = platform_replay
        self.canary_activator = canary_activator
        self.safety_observer = safety_observer or (
            lambda: {
                "research_execution_enabled": False,
                "research_blockers": ["d34_safety_unavailable"],
                "paper_execution_enabled": False,
                "blockers": ["d34_safety_unavailable"],
            }
        )
        self.canary_operator = canary_operator or (lambda _safety: None)
        self.now = now
        self.today = today or (lambda: self.now().astimezone(_LOCAL_TIMEZONE).date())

    def _container_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.config.workspace_root.resolve())
        except ValueError as exc:
            raise ValueError("d34_workspace_path_invalid") from exc
        return f"/workspace/d34/{relative.as_posix()}"

    def _research_window_open(self) -> bool:
        observed = self.now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            return False
        local = observed.astimezone(_LOCAL_TIMEZONE)
        return (
            local.weekday() in _POST_CLOSE_LOCAL_WEEKDAYS
            and local.time().replace(tzinfo=None) >= _RESEARCH_OPEN_TIME
        )

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

    def request_research(self, *, objective: str) -> D34WorkerResult:
        """Enqueue one paper-research job from an explicit owner request.

        Mandate is only the budget/universe envelope. The five-minute worker
        never invents a research cycle on its own.
        """

        cleaned = objective.strip()
        if len(cleaned) < 8:
            return D34WorkerResult(status="failed", code="d34_research_objective_required")
        try:
            safety = self.safety_observer()
        except Exception as exc:  # noqa: BLE001 - authority boundary
            return D34WorkerResult(
                status="failed",
                code=str(getattr(exc, "code", "d34_safety_unavailable")),
            )
        if safety.get("research_execution_enabled") is not True:
            raw_blockers = safety.get("research_blockers")
            blockers = (
                [str(value) for value in raw_blockers]
                if isinstance(raw_blockers, (list, tuple))
                else []
            )
            return D34WorkerResult(
                status="idle",
                code=blockers[0] if blockers else "d34_research_not_authorized",
            )
        mandate = self.mandates.get_active(workspace_id=self.config.workspace_id)
        if (
            mandate is None
            or mandate.status != "active"
            or mandate.expires_at <= self.now()
            or mandate.paper_execution_allowed is not True
        ):
            return D34WorkerResult(status="idle", code="no_active_mandate")
        try:
            job_key = enqueue_owner_research_request(
                jobs=self.jobs,
                mandate=mandate,
                workspace_id=self.config.workspace_id,
                objective=cleaned,
                cycle_date=self.today(),
            )
        except Exception as exc:  # noqa: BLE001 - enqueue authority boundary
            return D34WorkerResult(
                status="failed",
                code=str(getattr(exc, "code", type(exc).__name__)),
            )
        return D34WorkerResult(status="queued", code="d34_research_requested", job_id=job_key)

    def _materialize_snapshot(
        self, document: Mapping[str, object], mandate: Any
    ) -> dict[str, object]:
        if (
            document.get("snapshot_id")
            and document.get("snapshot_digest")
            and document.get("snapshot_parquet")
        ):
            return {
                "snapshot_id": str(document["snapshot_id"]),
                "snapshot_digest": str(document["snapshot_digest"]),
                "snapshot_parquet": self.config.workspace_root
                / str(document["snapshot_parquet"]),
            }
        cycle_date = date.fromisoformat(str(document["cycle_date"]))
        snapshot = create_market_data_snapshot(
            provider=self.futu_provider,
            symbols=tuple(str(value) for value in document.get("universe", mandate.universe)),
            start=(cycle_date - timedelta(days=self.config.lookback_days)).isoformat(),
            end=cycle_date.isoformat(),
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
    def _engine_receipt(path: Path) -> EngineReceipt:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            receipt_digest = str(raw.pop("receipt_digest"))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("d34_engine_receipt_unreadable") from exc
        if _digest(raw) != receipt_digest:
            raise ValueError("d34_engine_receipt_digest_mismatch")
        return EngineReceipt(
            engine=str(raw["engine"]),  # type: ignore[arg-type]
            snapshot_digest=str(raw["snapshot_digest"]),
            universe_digest=str(raw["universe_digest"]),
            calendar_digest=str(raw["calendar_digest"]),
            target_weights_digest=str(raw["target_weights_digest"]),
            daily_returns=tuple(float(value) for value in raw["daily_returns"]),
            return_dates=tuple(str(value) for value in raw["return_dates"]),
            terminal_nav=float(raw["terminal_nav"]),
            terminal_weights={
                str(key): float(value) for key, value in dict(raw["terminal_weights"]).items()
            },
            receipt_digest=receipt_digest,
        )

    def _heartbeat(self, lease: Any) -> None:
        self.jobs.heartbeat(
            job_id=lease.job.job_id,
            lease_id=lease.lease_id,
            lease_seconds=self.config.lease_seconds,
        )

    def _paper_activation_blocker(self, mandate: Any) -> str | None:
        try:
            safety = self.safety_observer()
        except Exception as exc:  # noqa: BLE001 - authority boundary
            return str(getattr(exc, "code", "d34_safety_unavailable"))
        emergency_raw = safety.get("emergency_stop")
        emergency = emergency_raw if isinstance(emergency_raw, Mapping) else {}
        if emergency.get("active") is True:
            return "emergency_stop_active"
        if safety.get("paper_execution_enabled") is not True:
            raw_blockers = safety.get("blockers")
            blockers = (
                [str(value) for value in raw_blockers]
                if isinstance(raw_blockers, (list, tuple))
                else []
            )
            return blockers[0] if blockers else "d34_paper_execution_not_authorized"
        active_raw = safety.get("active_mandate")
        active = active_raw if isinstance(active_raw, Mapping) else {}
        if (
            active.get("mandate_id") != mandate.mandate_id
            or active.get("status") != "active"
            or active.get("paper_execution_allowed") is not True
            or mandate.expires_at <= self.now()
        ):
            return "d34_mandate_changed_before_canary_activation"
        return None

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
        mandate: Any,
        document: dict[str, object],
        research_output: dict[str, object],
        image_digest: str,
        qlib_receipt: EngineReceipt,
        platform_receipt: EngineReceipt,
        comparison: EngineComparison,
    ) -> None:
        body = {
            "contract": "hqa.d34_terminal_recovery/v1",
            "job_id": job_id,
            "mandate_id": mandate.mandate_id,
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
            "comparison": asdict(comparison),
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

    def _recover_terminal(self, mandate: Any) -> D34WorkerResult | None:
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
                    or bundle.get("mandate_id") != mandate.mandate_id
                    or bundle.get("workspace_id") != self.config.workspace_id
                ):
                    continue
                qlib_receipt = self._receipt_from_document(
                    dict(bundle["qlib_receipt"])  # type: ignore[arg-type]
                )
                platform_receipt = self._receipt_from_document(
                    dict(bundle["platform_receipt"])  # type: ignore[arg-type]
                )
                comparison = self._comparison_from_document(
                    dict(bundle["comparison"])  # type: ignore[arg-type]
                )
                evaluation = self.registry.record_artifact_evaluation(
                    RegisterArtifactCommand(
                        job_id=job_id,
                        mandate_id=mandate.mandate_id,
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
                blocker = self._paper_activation_blocker(mandate)
                if blocker is not None:
                    _write_json(
                        phase_path,
                        {
                            **phase_document,
                            "phase": "needs_recovery",
                            "failed_phase": "canary_activation",
                            "artifact_id": artifact.artifact_id,
                            "last_recovery_at": self.now().isoformat(),
                            "last_recovery_code": blocker,
                        },
                    )
                    return D34WorkerResult(
                        status="awaiting_paper_authority",
                        code=blocker,
                        job_id=job_id,
                        artifact_id=artifact.artifact_id,
                    )
                canary = self.canary_activator(
                    artifact=artifact,
                    factor_id=str(bundle["factor_id"]),
                    artifact_code_path=self._host_path(bundle["factor_path"]),
                    universe=tuple(str(value) for value in bundle["universe"]),  # type: ignore[union-attr]
                )
                _write_json(
                    phase_path,
                    {
                        "phase": "canary_active",
                        "job_id": job_id,
                        "artifact_id": artifact.artifact_id,
                        "recovered": True,
                    },
                )
                return D34WorkerResult(
                    status="canary_active",
                    code="d34_terminal_recovery_complete",
                    job_id=job_id,
                    artifact_id=artifact.artifact_id,
                    canary=canary,
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

    def _run_lease(self, lease: Any, mandate: Any) -> D34WorkerResult:
        durable = self.jobs.read_leased_input(job_id=lease.job.job_id, lease_id=lease.lease_id)
        document = durable.input_document
        job_id = lease.job.job_id
        job_root = self.config.workspace_root / "jobs" / job_id
        job_root.mkdir(parents=True, exist_ok=True)
        phase_path = job_root / "cycle_receipt.json"
        terminal = False
        phase = "input_validation"
        research_output: dict[str, object] | None = None
        try:
            if _digest(document) != durable.input_digest:
                raise _D34WorkerValidationError("d34_job_input_digest_mismatch")
            if (
                document.get("mandate_id") != mandate.mandate_id
                or document.get("mandate_policy_digest") != mandate.policy_digest
                or document.get("paper_execution_allowed") is not True
            ):
                raise _D34WorkerValidationError("d34_job_mandate_mismatch")
            phase = "starting"
            self.jobs.mark_running(job_id=job_id, lease_id=lease.lease_id, container_id=None)
            self._heartbeat(lease)
            phase = "snapshot"
            snapshot = self._materialize_snapshot(document, mandate)
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
                "contract": "hqa.d34_research_request/v1",
                "job_id": job_id,
                "mandate_id": mandate.mandate_id,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_digest": snapshot["snapshot_digest"],
                "snapshot_source": "futu",
                "provider_uri": adapter.output["provider_uri"],
                "universe": list(document["universe"]),
                "calendar": list(calendar),
                "max_iterations": int(document["max_iterations"]),
                "experiments_per_iteration": int(document["experiments_per_iteration"]),
                "top_k": int(document["top_k"]),
                "initial_cash": 100_000,
                "budget_reservation_usd": float(lease.job.budget_reserved_usd),
                "objective": str(
                    document.get("objective")
                    or "Find a robust cross-sectional daily paper factor."
                ),
            }
            request_path = job_root / "research_request.json"
            _write_json(request_path, research_request)
            phase = "research"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
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
            research_output = dict(research.output)
            self._heartbeat(lease)
            qlib_receipt = self._engine_receipt(
                self._host_path(research_output["qlib_receipt_path"])
            )
            target_weights_path = self._host_path(research_output["target_weights_path"])
            phase = "platform_replay"
            _write_json(phase_path, {"phase": phase, "job_id": job_id})
            replay = self.platform_replay(
                qlib_receipt=qlib_receipt,
                snapshot_id=str(snapshot["snapshot_id"]),
                snapshot_digest=str(snapshot["snapshot_digest"]),
                snapshot_parquet=snapshot_parquet,
                target_weights_parquet=target_weights_path,
                output_root=job_root / "platform-replay",
                initial_cash=100_000,
                commission_bps=1,
                slippage_bps=5,
                min_order_value=0,
                whole_share_orders=False,
            )
            comparison = compare_engine_receipts(
                qlib=qlib_receipt,
                platform=replay.engine_receipt,
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
                "platform_receipt_digest": replay.engine_receipt.receipt_digest,
                "comparison_digest": comparison.comparison_digest,
                "comparison_accepted": comparison.accepted,
                "factor_path": str(
                    self._host_path(research_output["factor_path"]).relative_to(
                        self.config.workspace_root
                    )
                ),
            }
            self._write_recovery_bundle(
                job_root=job_root,
                job_id=job_id,
                mandate=mandate,
                document=document,
                research_output=research_output,
                image_digest=research.image_digest,
                qlib_receipt=qlib_receipt,
                platform_receipt=replay.engine_receipt,
                comparison=comparison,
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
                    mandate_id=mandate.mandate_id,
                    workspace_id=self.config.workspace_id,
                    qlib_receipt=qlib_receipt,
                    platform_receipt=replay.engine_receipt,
                    comparison=comparison,
                    candidate_code_digest=str(research_output["candidate_code_digest"]),
                    qlib_config_digest=str(research_output["qlib_config_digest"]),
                    rdagent_commit=str(research_output["rdagent_commit"]),
                    qlib_commit=str(research_output["qlib_commit"]),
                    docker_image_digest=research.image_digest,
                )
            )
            if not evaluation.accepted or evaluation.artifact is None:
                _write_json(
                    phase_path,
                    {"phase": "rejected", "job_id": job_id, **outcome_document},
                )
                return D34WorkerResult(status="rejected", code=outcome_code, job_id=job_id)
            phase = "canary_activation"
            artifact = evaluation.artifact
            blocker = self._paper_activation_blocker(mandate)
            if blocker is not None:
                _write_json(
                    phase_path,
                    {
                        "phase": "needs_recovery",
                        "failed_phase": phase,
                        "job_id": job_id,
                        "artifact_id": artifact.artifact_id,
                        "code": blocker,
                        **outcome_document,
                    },
                )
                return D34WorkerResult(
                    status="awaiting_paper_authority",
                    code=blocker,
                    job_id=job_id,
                    artifact_id=artifact.artifact_id,
                )
            canary = self.canary_activator(
                artifact=artifact,
                factor_id=str(research_output["factor_id"]),
                artifact_code_path=self._host_path(research_output["factor_path"]),
                universe=tuple(str(value) for value in document["universe"]),
            )
            _write_json(
                phase_path,
                {
                    "phase": "canary_active",
                    "job_id": job_id,
                    "artifact_id": artifact.artifact_id,
                    **outcome_document,
                },
            )
            return D34WorkerResult(
                status="canary_active",
                code="d34_cycle_complete",
                job_id=job_id,
                artifact_id=artifact.artifact_id,
                canary=canary,
            )
        except Exception as exc:  # noqa: BLE001 - durable worker boundary
            code = getattr(exc, "code", type(exc).__name__)
            if not terminal:
                ambiguous = phase == "research" and isinstance(exc, D34DockerRuntimeError)
                self.jobs.finish(
                    job_id=job_id,
                    lease_id=lease.lease_id,
                    state="outcome_unknown" if ambiguous else "rejected",
                    outcome_code=str(code)[:128],
                    outcome_document={
                        "phase": phase,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2_000],
                        "recovery": "inspect_cycle_receipt_and_content_addressed_outputs",
                    },
                    budget_spent_usd=Decimal("0"),
                )
            _write_json(
                phase_path,
                {
                    "phase": "needs_recovery" if terminal else "failed",
                    "failed_phase": phase,
                    "job_id": job_id,
                    "code": str(code),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2_000],
                },
            )
            return D34WorkerResult(
                status="needs_recovery" if terminal else "failed",
                code=str(code),
                job_id=job_id,
            )

    def run_once(self) -> D34WorkerResult:
        try:
            safety = self.safety_observer()
        except Exception as exc:  # noqa: BLE001 - authority boundary
            return D34WorkerResult(
                status="failed",
                code=str(getattr(exc, "code", "d34_safety_unavailable")),
            )
        try:
            paper_cycle = self.canary_operator(safety)
        except Exception as exc:  # noqa: BLE001 - paper operations boundary
            return D34WorkerResult(
                status="failed",
                code=str(getattr(exc, "code", "d34_canary_operation_failed")),
            )
        mandate = None
        if safety.get("paper_execution_enabled") is True:
            mandate = self.mandates.get_active(workspace_id=self.config.workspace_id)
            if (
                mandate is not None
                and mandate.status == "active"
                and mandate.expires_at > self.now()
                and mandate.paper_execution_allowed is True
            ):
                recovered = self._recover_terminal(mandate)
                if recovered is not None:
                    return replace(recovered, paper_cycle=paper_cycle)
        if safety.get("research_execution_enabled") is not True:
            raw_blockers = safety.get("research_blockers")
            blockers = (
                [str(value) for value in raw_blockers]
                if isinstance(raw_blockers, (list, tuple))
                else []
            )
            return D34WorkerResult(
                status="idle",
                code=blockers[0] if blockers else "d34_research_not_authorized",
                paper_cycle=paper_cycle,
            )
        self.jobs.reconcile_expired(workspace_id=self.config.workspace_id)
        if mandate is None:
            mandate = self.mandates.get_active(workspace_id=self.config.workspace_id)
        if mandate is None:
            return D34WorkerResult(status="idle", code="no_active_mandate", paper_cycle=paper_cycle)
        if (
            mandate.status != "active"
            or mandate.expires_at <= self.now()
            or mandate.paper_execution_allowed is not True
        ):
            return D34WorkerResult(status="idle", code="mandate_inactive", paper_cycle=paper_cycle)
        if not self._research_window_open():
            return D34WorkerResult(
                status="idle",
                code="d34_research_window_closed",
                paper_cycle=paper_cycle,
            )
        lease = self.jobs.lease_next(
            workspace_id=self.config.workspace_id,
            worker_id=self.config.worker_id,
            lease_seconds=self.config.lease_seconds,
        )
        if lease is None:
            return D34WorkerResult(status="idle", code="no_queued_job", paper_cycle=paper_cycle)
        return replace(self._run_lease(lease, mandate), paper_cycle=paper_cycle)


__all__ = ["D34CycleWorker", "D34WorkerConfig", "D34WorkerResult"]
