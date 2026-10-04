from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.d34.docker_runtime import D34DockerReceipt, D34DockerRuntimeError
from quant_system.d34.engine_comparison import EngineReceipt
from quant_system.d34.research_driver import (
    D34ResearchRequest,
    ResearchProposal,
    render_factor_source,
)
from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    build_owner_request_input,
    digest_document,
)
from quant_system.d34.worker import (
    D34CycleWorker,
    D34WorkerConfig,
    D34WorkerResult,
    _research_request_digest,
)
from quant_system.hermes.d34_job_authority import EnqueueJobCommand, LeasedJobInput
from quant_system.hermes.d34_registry_authority import D34Artifact
from quant_system.options.seller_score import is_us_market_session


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class Futu:
    provider_name = "futu"

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        assert interval == "1d"
        rows = []
        sessions = [
            value
            for value in pd.date_range("2026-08-03", periods=40, tz="UTC")
            if is_us_market_session(value.date())
        ][:25]
        for offset, symbol in enumerate(symbols):
            for day, timestamp in enumerate(sessions, start=1):
                close = 100 + offset + day
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "open": close - 0.5,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1_000_000,
                        "provider": "futu",
                        "interval": "1d",
                        "event_ts": timestamp,
                        "knowledge_ts": pd.Timestamp("2026-09-08", tz="UTC"),
                        "price_adjustment": "qfq",
                    }
                )
        return pd.DataFrame(rows)


class Jobs:
    def __init__(self) -> None:
        self.items = []
        self.input = None
        self.finished = []
        self.heartbeats = 0

    def reconcile_expired(self, *, workspace_id):
        return 0

    def list(self, *, workspace_id, limit, state):
        return list(self.items)

    def enqueue(self, command):
        job = SimpleNamespace(
            job_id="job-cycle-12345678",
            job_key=command.job_key,
            state="queued",
            resource_envelope_id=command.resource_envelope_id,
            budget_reserved_usd=command.budget_reserved_usd,
        )
        self.items.append(job)
        self.input = LeasedJobInput(
            job_id=job.job_id,
            input_digest=command.input_digest,
            input_document=command.input_document,
        )
        return job

    def lease_next(self, *, workspace_id, worker_id, lease_seconds):
        if not self.items or self.items[0].state != "queued":
            return None
        return SimpleNamespace(
            job=self.items[0],
            lease_id="lease-cycle-12345678",
            attempt_id="attempt-cycle-12345678",
        )

    def read_leased_input(self, *, job_id, lease_id):
        return self.input

    def mark_running(self, **kwargs):
        self.items[0].state = "running"
        return self.items[0]

    def heartbeat(self, **kwargs):
        self.heartbeats += 1
        return self.items[0]

    def finish(self, **kwargs):
        self.finished.append(kwargs)
        self.items[0].state = kwargs["state"]
        return self.items[0]


def _force_legacy_hang_if_pass(jobs: Jobs) -> None:
    assert jobs.input is not None
    document = dict(jobs.input.input_document)
    document["hang_if_pass"] = True
    jobs.input = LeasedJobInput(
        job_id=jobs.input.job_id,
        input_digest=_digest(document),
        input_document=document,
    )


class Docker:
    def __init__(
        self,
        workspace: Path,
        *,
        fail_after_research: bool = False,
        fail_after_attempts: int | None = None,
        qlib_job_id: str | None = None,
        qlib_run_id: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.fail_after_research = fail_after_research
        self.fail_after_attempts = fail_after_attempts
        self.qlib_job_id = qlib_job_id
        self.qlib_run_id = qlib_run_id
        self.commands = []

    def _receipt(self, job_id, command, output):
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            image_digest="sha256:" + "9" * 64,
            command=tuple(command),
            output=output,
            receipt_digest=_digest(output),
        )

    def _container_request_digest(self, request):
        # Reproduce the real container boundary: rdagent_qlib_runtime validates
        # research_request.json with D34ResearchRequest.model_validate and
        # commits request.request_digest of model_dump(mode="json"). The file
        # carries container paths, so validate a translated copy against the
        # test workspace (the env checks must really run), but digest the
        # container-visible provider_uri string exactly as the container does.
        translated = {
            **request,
            "provider_uri": str(
                self.workspace
                / str(request["provider_uri"]).removeprefix("/workspace/d34/")
            ),
        }
        validated = D34ResearchRequest.model_validate(translated)
        dump = validated.model_dump(mode="json", exclude_none=True)
        dump["provider_uri"] = str(request["provider_uri"])
        return _digest(dump)

    def run(self, *, job_id, command, timeout_seconds=None):
        self.commands.append(tuple(command))
        if command[0] == "qlib-adapt":
            provider = self.workspace / "jobs" / job_id / "qlib" / "provider"
            provider.mkdir(parents=True)
            return self._receipt(
                job_id,
                command,
                {
                    "contract": "hqa.qlib_provider/v1",
                    "provider_uri": f"/workspace/d34/{provider.relative_to(self.workspace)}",
                    "receipt_digest": "7" * 64,
                },
            )
        if command[0] == "llm-smoke":
            return self._receipt(
                job_id,
                command,
                {"contract": "hqa.d34_llm_smoke/v1", "json_mode": True},
            )
        assert command[0] == "research"
        request_arg = command[command.index("--request") + 1]
        request_path = self.workspace / request_arg.removeprefix("/workspace/d34/")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert isinstance(request["initial_cash"], float)
        output_arg = command[command.index("--output-root") + 1]
        research_root = self.workspace / output_arg.removeprefix("/workspace/d34/")
        root = research_root / "research-result"
        root.mkdir(parents=True)
        proposal = ResearchProposal(
            title="Five day momentum",
            thesis="Relative strength persists.",
            operator="momentum",
            short_window=1,
            long_window=5,
            rationale="Observable baseline.",
        )
        source, code_digest = render_factor_source(proposal=proposal, factor_id="d34_cycle_factor")
        factor = root / "candidate_factor.py"
        factor.write_text(source, encoding="utf-8")
        weights = root / "target_weights.parquet"
        pd.DataFrame(
            {
                "tradeable_ts": pd.to_datetime(request["calendar"][1:]),
                "symbol": ["SPY"] * (len(request["calendar"]) - 1),
                "target_weight": [0.99] * (len(request["calendar"]) - 1),
            }
        ).to_parquet(weights, index=False)
        weights_digest = hashlib.sha256(weights.read_bytes()).hexdigest()
        receipt_body = {
            "contract": "hqa.d34_engine_receipt/v1",
            "engine": "qlib",
            "job_id": self.qlib_job_id or job_id,
            "run_id": self.qlib_run_id or request["run_id"],
            "factor_id": "d34_cycle_factor",
            "candidate_code_digest": code_digest,
            "snapshot_digest": request["snapshot_digest"],
            "universe_digest": _digest(request["universe"]),
            "calendar_digest": _digest(request["calendar"]),
            "target_weights_digest": weights_digest,
            "daily_returns": [
                0.0,
                *[0.002 if index % 2 else -0.001 for index in range(1, len(request["calendar"]))],
            ],
            "return_dates": request["calendar"],
            "terminal_nav": 1.014,
            "terminal_weights": {"SPY": 0.99},
        }
        qlib_receipt = root / "qlib_receipt.json"
        qlib_receipt.write_bytes(
            _canonical({**receipt_body, "receipt_digest": _digest(receipt_body)}) + b"\n"
        )
        experiment_trials = research_root / f"experiment-trials-{self._container_request_digest(request)[:32]}.json"
        attempts_root = research_root / f"experiment-trial-attempts-{self._container_request_digest(request)[:32]}"
        attempts_root.mkdir(parents=True)
        experiment_rows = []
        experiment_count = 1 if request.get("formula") else 9
        for index in range(1, experiment_count + 1):
            experiment_id = (
                f"iteration-{(index - 1) // 3 + 1:02d}-experiment-{(index - 1) % 3 + 1:02d}"
            )
            experiment_rows.append(
                {
                    "experiment_id": experiment_id,
                    "subject": f"momentum:{experiment_id}",
                    "proposal_digest": _digest(
                        {"operator": "momentum", "experiment_id": experiment_id}
                    ),
                    "experiment_receipt_digest": _digest(
                        {"experiment_id": experiment_id, "status": "succeeded"}
                    ),
                    "daily_returns": [
                        0.0,
                        *[
                            0.001 * index if day % 2 else -0.0005
                            for day in range(1, len(request["calendar"]))
                        ],
                    ],
                }
            )
            attempt_body = {
                "contract": "hqa.d34_experiment_trial_attempt/v1",
                "job_id": job_id,
                "request_digest": self._container_request_digest(request),
                "universe": request["universe"],
                "universe_digest": _digest(request["universe"]),
                "calendar_digest": _digest(request["calendar"]),
                "return_dates": request["calendar"],
                "experiment_id": experiment_id,
                "status": "succeeded",
                "subject": experiment_rows[-1]["subject"],
                "proposal_digest": experiment_rows[-1]["proposal_digest"],
                "experiment_receipt_digest": experiment_rows[-1]["experiment_receipt_digest"],
                "daily_returns": experiment_rows[-1]["daily_returns"],
            }
            (attempts_root / f"{experiment_id}.json").write_bytes(
                _canonical({**attempt_body, "receipt_digest": _digest(attempt_body)}) + b"\n"
            )
            if self.fail_after_attempts == index:
                raise D34DockerRuntimeError(
                    "d34_docker_failed", "simulated interrupted experiment loop"
                )
        trial_batch_body = {
            "contract": "hqa.d34_experiment_trial_batch/v1",
            "job_id": job_id,
            "request_digest": self._container_request_digest(request),
            "universe": request["universe"],
            "universe_digest": _digest(request["universe"]),
            "calendar_digest": _digest(request["calendar"]),
            "return_dates": request["calendar"],
            "experiment_count": experiment_count,
            "successful_experiment_count": experiment_count,
            "attempts": [
                {
                    "experiment_id": row["experiment_id"],
                    "status": "succeeded",
                }
                for row in experiment_rows
            ],
            "selected_experiment": "iteration-01-experiment-01",
            "experiments": experiment_rows,
        }
        trial_batch_digest = _digest(trial_batch_body)
        experiment_trials.write_bytes(
            _canonical({**trial_batch_body, "receipt_digest": trial_batch_digest}) + b"\n"
        )
        receipt = self._receipt(
            job_id,
            command,
            {
                "contract": "hqa.d34_research_result/v2",
                "job_id": job_id,
                "request_digest": self._container_request_digest(request),
                "factor_id": "d34_cycle_factor",
                "candidate_code_digest": code_digest,
                "qlib_config_digest": "6" * 64,
                "target_weights_digest": weights_digest,
                "qlib_receipt_digest": _digest(receipt_body),
                "budget_spent_usd": 1.25,
                "factor_path": f"/workspace/d34/{factor.relative_to(self.workspace)}",
                "target_weights_path": f"/workspace/d34/{weights.relative_to(self.workspace)}",
                "qlib_receipt_path": f"/workspace/d34/{qlib_receipt.relative_to(self.workspace)}",
                "experiment_trials_path": (
                    f"/workspace/d34/{experiment_trials.relative_to(self.workspace)}"
                ),
                "experiment_trials_digest": trial_batch_digest,
                "experiment_trials_file_digest": hashlib.sha256(
                    experiment_trials.read_bytes()
                ).hexdigest(),
                "experiment_count": experiment_count,
                "successful_experiment_count": experiment_count,
                "rdagent_commit": "3" * 40,
                "qlib_commit": "4" * 40,
            },
        )
        if self.fail_after_research:
            raise D34DockerRuntimeError("d34_docker_failed", "simulated failure after trial batch")
        return receipt


def _platform_replay_fixture(
    *,
    output_root: Path,
    qlib: EngineReceipt,
    job_id: str,
    run_id: str,
    daily_returns: tuple[float, ...] | None = None,
    turnover_period: float = 0.2,
    raw_job_id: str | None = None,
    raw_run_id: str | None = None,
):
    returns = daily_returns if daily_returns is not None else qlib.daily_returns
    raw = {
        "contract": "hqa.d34_engine_receipt/v1",
        "engine": "platform",
        "job_id": raw_job_id or job_id,
        "run_id": raw_run_id or run_id,
        "snapshot_id": "snapshot-fixture-12345678",
        "snapshot_digest": qlib.snapshot_digest,
        "snapshot_parquet_digest": "a" * 64,
        "universe_digest": qlib.universe_digest,
        "calendar_digest": qlib.calendar_digest,
        "target_weights_digest": qlib.target_weights_digest,
        "config": {"commission_bps": 1.0, "slippage_bps": 5.0},
        "daily_returns": list(returns),
        "return_dates": list(qlib.return_dates),
        "terminal_nav": qlib.terminal_nav,
        "terminal_weights": dict(qlib.terminal_weights),
        "metrics": {"turnover": turnover_period},
        "output_digests": {},
    }
    receipt_digest = _digest(raw)
    output_dir = Path(output_root) / "replay-fixture"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "receipt.json").write_bytes(
        _canonical({**raw, "receipt_digest": receipt_digest}) + b"\n"
    )
    return SimpleNamespace(
        engine_receipt=EngineReceipt(
            engine="platform",
            snapshot_digest=qlib.snapshot_digest,
            universe_digest=qlib.universe_digest,
            calendar_digest=qlib.calendar_digest,
            target_weights_digest=qlib.target_weights_digest,
            daily_returns=returns,
            return_dates=qlib.return_dates,
            terminal_nav=qlib.terminal_nav,
            terminal_weights=qlib.terminal_weights,
            receipt_digest=receipt_digest,
        ),
        turnover_period=turnover_period,
        output_dir=output_dir,
        receipt_digest=receipt_digest,
    )


class Registry:
    def __init__(self) -> None:
        self.commands = []

    def record_artifact_evaluation(self, command):
        self.commands.append(command)
        artifact = D34Artifact(
            artifact_id="artifact-cycle-test",
            resource_envelope_id=command.resource_envelope_id,
            workspace_id=command.workspace_id,
            status="qualified",
            qualification_scope="paper_only",
            policy_digest=command.comparison.policy_digest,
            snapshot_digest=command.qlib_receipt.snapshot_digest,
            candidate_code_digest=command.candidate_code_digest,
            qlib_config_digest=command.qlib_config_digest,
            rdagent_commit=command.rdagent_commit,
            qlib_commit=command.qlib_commit,
            docker_image_digest=command.docker_image_digest,
            qlib_receipt_digest=command.qlib_receipt.receipt_digest,
            platform_receipt_digest=command.platform_receipt.receipt_digest,
            comparison_digest=command.comparison.comparison_digest,
            policy_decision_id="decision-cycle-test",
            created_at=datetime(2026, 8, 11, tzinfo=UTC),
            updated_at=datetime(2026, 8, 11, tzinfo=UTC),
            version=1,
        )
        return SimpleNamespace(accepted=True, artifact=artifact)


def _request_research(
    worker: D34CycleWorker,
    *,
    objective: str,
    formula: str | None = None,
) -> D34WorkerResult:
    universe = ["SPY", "QQQ", "IWM", "DIA"]
    material_digest = digest_document(
        {"note": objective, "formula": "test_formula = rank(close.pct_change(5))", "universe": universe}
    )
    platform_session_id = "platform-session-worker-test"
    hermes_session_id = "hermes-session-worker-test"
    operation_id = digest_document(
        {
            "contract": "hqa.chat_research_operation/v1",
            "hermes_session_id": hermes_session_id,
            "material_digest": material_digest,
            "platform_session_id": platform_session_id,
        }
    )
    job_key = f"assistant-remote:{operation_id}"
    document = build_owner_request_input(objective=objective, universe=universe)
    document.update(
        {
            "job_key": job_key,
            "operation_id": operation_id,
            "material_digest": material_digest,
            "platform_session_id": platform_session_id,
            "hermes_session_id": hermes_session_id,
        }
    )
    if formula is not None:
        document["formula"] = formula
    worker.jobs.enqueue(
        EnqueueJobCommand(
            resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
            workspace_id=worker.config.workspace_id,
            job_key=job_key,
            input_digest=digest_document(document),
            input_document=document,
            budget_reserved_usd=Decimal("10"),
            max_attempts=1,
        )
    )
    return D34WorkerResult(status="queued", code="d34_research_requested", job_id=job_key)

def test_research_worker_does_not_consult_paper_emergency_authority(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    jobs = Jobs()
    docker = Docker(roots[0])

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("emergency stop replayed"),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "no_queued_job"
    assert jobs.items == []
    assert docker.commands == []


def test_research_cycle_never_calls_canary_or_paper_without_a_research_job(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=Jobs(),
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("idle cycle replayed"),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "no_queued_job"


def test_research_worker_without_a_job_does_not_create_a_schedule_cycle(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    jobs = Jobs()
    docker = Docker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("pre-close cycle replayed"),
        now=lambda: datetime(2026, 8, 10, 19, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "no_queued_job"
    assert jobs.items == []
    assert docker.commands == []


def test_research_job_input_has_no_client_selected_cycle_date(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class SchedulingOnlyJobs(Jobs):
        def lease_next(self, *, workspace_id, worker_id, lease_seconds):
            return None

    jobs = SchedulingOnlyJobs()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("idle cycle replayed"),
        now=lambda: datetime(2026, 8, 12, 22, 30, tzinfo=UTC),
    )

    requested = _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert requested.status == "queued"
    assert requested.code == "d34_research_requested"
    assert result.status == "idle"
    assert result.code == "no_queued_job"
    assert [job.job_key for job in jobs.items] == [requested.job_id]
    assert "cycle_date" not in jobs.input.input_document
    assert jobs.input.input_document["trigger"] == "owner_request"
    assert jobs.input.input_document["objective"] == "Find a twenty-day reversal"


def test_run_once_does_not_invent_a_research_cycle(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    jobs = Jobs()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("unsolicited cycle replayed"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "no_queued_job"
    assert jobs.items == []


def test_cycle_records_futu_unavailable_when_processing_owner_request(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class FutuUnavailable:
        provider_name = "futu"

        def fetch_ohlcv(self, *_args, **_kwargs):
            error = RuntimeError("Futu OpenD unavailable")
            error.code = "d34_futu_unavailable"  # type: ignore[attr-defined]
            raise error

    jobs = Jobs()
    docker = Docker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=FutuUnavailable(),
        platform_replay=lambda **_kwargs: pytest.fail("offline Futu replayed"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    requested = _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert requested.status == "queued"
    assert requested.code == "d34_research_requested"
    assert result.status == "failed"
    assert result.code == "snapshot_futu_unavailable"
    assert [job.job_key for job in jobs.items] == [requested.job_id]
    assert docker.commands == [("llm-smoke",)]


def test_cycle_rejects_queued_jobs_that_were_not_owner_requested(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    document = {
        "contract": "hqa.d34_job_input/v1",
        "cycle_date": "2026-08-11",
        "hypothesis_number": 1,
        "trigger": "schedule",
        "mandate_id": "mandate-retired-cycle",
        "mandate_policy_digest": "5" * 64,
        "universe": ["SPY", "QQQ", "IWM", "DIA"],
        "max_iterations": 2,
        "experiments_per_iteration": 2,
        "top_k": 1,
        "paper_execution_allowed": True,
    }
    jobs = Jobs()
    jobs.items.append(
        SimpleNamespace(
            job_id="job-cycle-12345678",
            job_key="cycle:2026-08-11:hypothesis:1",
            state="queued",
            resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
            budget_reserved_usd=Decimal("10"),
        )
    )
    jobs.input = LeasedJobInput(
        job_id="job-cycle-12345678",
        input_digest=_digest(document),
        input_document=document,
    )
    docker = Docker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("legacy job replayed"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_job_not_owner_requested"
    assert jobs.finished[0]["state"] == "rejected"
    assert docker.commands == []


def test_cycle_rejects_tampered_durable_job_input_without_leaking_the_lease(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class TamperedJobs(Jobs):
        def read_leased_input(self, *, job_id, lease_id):
            durable = super().read_leased_input(job_id=job_id, lease_id=lease_id)
            return LeasedJobInput(
                job_id=durable.job_id,
                input_digest="0" * 64,
                input_document=durable.input_document,
            )

    jobs = TamperedJobs()
    docker = Docker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("tampered input replayed"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_job_input_digest_mismatch"
    assert jobs.finished[0]["state"] == "rejected"
    assert jobs.finished[0]["budget_spent_usd"] == Decimal("0")
    assert docker.commands == []


def test_cycle_marks_research_container_timeout_outcome_unknown(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class TimedOutResearch(Docker):
        def run(self, *, job_id, command, timeout_seconds=None):
            if command[0] == "research":
                self.commands.append(tuple(command))
                raise D34DockerRuntimeError(
                    "d34_docker_timeout",
                    "research container exceeded its bounded timeout",
                )
            return super().run(job_id=job_id, command=command)

    jobs = Jobs()
    docker = TimedOutResearch(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("timed out research replayed"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_docker_timeout"
    assert jobs.finished[0]["state"] == "outcome_unknown"
    assert jobs.finished[0]["budget_spent_usd"] == Decimal("0")
    assert [command[0] for command in docker.commands] == [
        "llm-smoke",
        "qlib-adapt",
        "research",
    ]


@pytest.mark.parametrize("formula", [None, "$close/Ref($close,20)-1"])
def test_cycle_preserves_formula_and_never_executes_paper(
    tmp_path: Path,
    formula,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    projected_running: list[str] = []

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        research_state_projector=projected_running.append,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal", formula=formula)
    _force_legacy_hang_if_pass(jobs)
    result = worker.run_once()

    assert result.status == "candidate_ready"
    request_document = json.loads(
        (workspace / "jobs" / result.job_id / "research_request.json").read_text()
    )
    assert request_document.get("formula") == formula
    assert result.code == "verified_candidate_not_hung"
    assert result.job_id == "job-cycle-12345678"
    assert [command[0] for command in docker.commands] == [
        "llm-smoke",
        "qlib-adapt",
        "research",
    ]
    assert jobs.finished[0]["state"] == "succeeded"
    assert jobs.finished[0]["budget_spent_usd"] == Decimal("1.25")
    assert jobs.heartbeats >= 2
    assert registry.commands[0].qlib_receipt.engine == "qlib"
    assert registry.commands[0].platform_receipt.engine == "platform"
    assert projected_running == [result.job_id]
    job_root = workspace / "jobs" / result.job_id
    request = json.loads((job_root / "research_request.json").read_text(encoding="utf-8"))
    recovery = json.loads((job_root / "terminal_recovery.json").read_text(encoding="utf-8"))
    assert "hang_if_pass" not in request
    assert "hang_if_pass" not in recovery
    assert "hang_if_pass" not in jobs.finished[0]["outcome_document"]


@pytest.mark.parametrize(
    ("qlib_job_id", "qlib_run_id"),
    [
        ("job-other-research", None),
        (None, "attempt-other-research"),
    ],
)
def test_cycle_rejects_raw_engine_receipt_from_another_job_or_run_before_registry(
    tmp_path: Path,
    qlib_job_id: str | None,
    qlib_run_id: str | None,
) -> None:
    workspace, platform, hqa, cache = [
        tmp_path / name for name in ("workspace", "platform", "hqa", "cache")
    ]
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs = Jobs()
    registry = Registry()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=Docker(
            workspace,
            qlib_job_id=qlib_job_id,
            qlib_run_id=qlib_run_id,
        ),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("foreign receipt reached replay"),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_engine_receipt_lineage_mismatch"
    assert registry.commands == []


def test_cycle_rejects_platform_raw_receipt_from_another_run_before_registry(
    tmp_path: Path,
) -> None:
    workspace, platform, hqa, cache = [
        tmp_path / name for name in ("workspace", "platform", "hqa", "cache")
    ]
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs = Jobs()
    registry = Registry()

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
            raw_run_id="attempt-other-platform-run",
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=Docker(workspace),
        futu_provider=Futu(),
        platform_replay=replay,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_engine_receipt_lineage_mismatch"
    assert registry.commands == []


def test_cycle_comparison_rejection_writes_terminal_failure_evidence(
    tmp_path: Path,
) -> None:
    workspace, platform, hqa, cache = [
        tmp_path / name for name in ("workspace", "platform", "hqa", "cache")
    ]
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs = Jobs()

    class RejectingRegistry(Registry):
        def record_artifact_evaluation(self, command):
            self.commands.append(command)
            return SimpleNamespace(accepted=False, artifact=None)

    def divergent_replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
            daily_returns=tuple(-value for value in qlib.daily_returns),
            turnover_period=0.2,
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
        ),
        jobs=jobs,
        registry=RejectingRegistry(),
        docker_runtime=Docker(workspace),
        futu_provider=Futu(),
        platform_replay=divergent_replay,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )
    _request_research(worker, objective="Reject a divergent twenty-day reversal")

    result = worker.run_once()

    assert result.status == "rejected"
    assert result.code == "dual_engine_comparison_rejected"
    assert jobs.finished[0]["state"] == "rejected"
    job_root = workspace / "jobs" / result.job_id
    cycle = json.loads((job_root / "cycle_receipt.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_root / "evidence_manifest.json").read_text(encoding="utf-8"))
    terminal_bundle = json.loads((job_root / "terminal_bundle.json").read_text(encoding="utf-8"))
    assert cycle["phase"] == "rejected"
    assert cycle["failed_phase"] == "comparison"
    assert manifest["terminal_status"] == "rejected"
    assert manifest["failed_phase"] == "comparison"
    assert manifest["cycle_receipt_digest"] == _digest(cycle)
    assert terminal_bundle["cycle_receipt"] == cycle
    assert terminal_bundle["evidence_manifest"] == manifest


def test_cycle_copies_budget_metering_failed_onto_job_outcome(tmp_path: Path) -> None:
    class MeterFailedDocker(Docker):
        def run(self, *, job_id, command, timeout_seconds=None):
            receipt = super().run(job_id=job_id, command=command, timeout_seconds=timeout_seconds)
            if command[0] != "research":
                return receipt
            output = dict(receipt.output)
            output["budget_spent_usd"] = 0.0
            output["budget_metering"] = "d34_budget_metering_failed"
            return self._receipt(job_id, command, output)

    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), MeterFailedDocker(workspace), Registry()

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "candidate_ready"
    finished = jobs.finished[0]
    assert finished["state"] == "succeeded"
    assert finished["budget_spent_usd"] == Decimal("0")
    assert finished["outcome_document"]["budget_metering"] == "d34_budget_metering_failed"


def test_cycle_request_api_has_no_hang_shortcut_and_stops_at_verified_candidate(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    assert not hasattr(worker, "request_research")

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "candidate_ready"
    assert result.code == "verified_candidate_not_hung"
    assert result.artifact_id


def test_successful_cycle_appends_every_experiment_trial_to_the_host_ledger(
    tmp_path: Path,
) -> None:
    from quant_system.d34.worker import persist_host_d34_experiment_trials
    from quant_system.research.trials import TrialsLedger, evaluate_candidate_dsr

    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    before = TrialsLedger(platform / "trials").list()
    result = worker.run_once()
    after = TrialsLedger(platform / "trials").list()

    assert result.status == "candidate_ready"
    assert len(after) == len(before) + 9
    appended = after[len(before) :]
    assert {trial.kind for trial in appended} == {"d34_experiment"}
    assert all(trial.source.startswith("job-cycle-12345678") for trial in appended)
    assert {trial.metadata["run_id"] for trial in appended} == {
        f"job-cycle-12345678:iteration-{iteration:02d}-experiment-{experiment:02d}"
        for iteration in range(1, 4)
        for experiment in range(1, 4)
    }
    request = json.loads(
        (workspace / "jobs" / "job-cycle-12345678" / "research_request.json").read_text(
            encoding="utf-8"
        )
    )
    batch_path = (
        workspace
        / "jobs"
        / "job-cycle-12345678"
        / "research"
        / f"experiment-trials-{_research_request_digest(request)[:32]}.json"
    )
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    dsr = evaluate_candidate_dsr(
        TrialsLedger(platform / "trials"),
        universe=request["universe"],
        daily_returns=batch["experiments"][0]["daily_returns"],
    )
    assert dsr["n_trials"] == 9
    replay_receipt = persist_host_d34_experiment_trials(
        data_root=platform,
        batch_path=batch_path,
        expected_file_digest=hashlib.sha256(batch_path.read_bytes()).hexdigest(),
        expected_batch_digest=batch["receipt_digest"],
        expected_job_id="job-cycle-12345678",
        expected_request_digest=_research_request_digest(request),
        expected_universe=request["universe"],
        expected_calendar_digest=_digest(request["calendar"]),
        expected_experiment_count=9,
    )
    assert replay_receipt["successful_experiment_count"] == 9
    assert len(TrialsLedger(platform / "trials").list()) == 9


@pytest.mark.parametrize(
    ("docker_kwargs", "expected_experiment_ids"),
    [
        (
            {"fail_after_research": True},
            {
                f"iteration-{iteration:02d}-experiment-{experiment:02d}"
                for iteration in range(1, 4)
                for experiment in range(1, 4)
            },
        ),
        (
            {"fail_after_attempts": 2},
            {
                "iteration-01-experiment-01",
                "iteration-01-experiment-02",
            },
        ),
    ],
)
def test_research_failure_still_persists_completed_trials(
    tmp_path: Path,
    docker_kwargs: dict[str, object],
    expected_experiment_ids: set[str],
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs = Jobs()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            data_root=platform,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=Docker(workspace, **docker_kwargs),
        futu_provider=Futu(),
        platform_replay=lambda **kwargs: pytest.fail(
            "failed research must not reach platform replay"
        ),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_docker_failed"
    from quant_system.research.trials import TrialsLedger

    rows = TrialsLedger(platform / "trials").list()
    assert len(rows) == len(expected_experiment_ids)
    assert {str(row.metadata["experiment_id"]) for row in rows} == expected_experiment_ids
    persistence = jobs.finished[0]["outcome_document"]["trial_persistence"]
    assert {run_id.split(":", 1)[1] for run_id in persistence["run_ids"]} == expected_experiment_ids
    assert persistence["trial_ids"] == [row.trial_id for row in rows]
    assert persistence["trial_coverage"]["passed"] is True
    cycle = json.loads(
        (workspace / "jobs" / result.job_id / "cycle_receipt.json").read_text(encoding="utf-8")
    )
    assert cycle["trial_persistence"] == persistence
    manifest = json.loads(
        (workspace / "jobs" / result.job_id / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    manifest_digest = manifest.pop("manifest_digest")
    assert manifest_digest == _digest(manifest)
    assert manifest["terminal_status"] == "failed"
    assert manifest["failed_phase"] == cycle["failed_phase"]
    assert "research" in manifest["failed_phase"]
    assert len(manifest["operation_id"]) == 64
    assert len(manifest["material_digest"]) == 64


def test_legacy_recovery_flag_still_stops_at_candidate_without_rerunning_research(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker = Jobs(), Docker(workspace)

    class FailOnceRegistry(Registry):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def record_artifact_evaluation(self, command):
            self.calls += 1
            if self.calls == 1:
                self.commands.append(command)
                raise OSError("simulated registry response loss")
            return super().record_artifact_evaluation(command)

    registry = FailOnceRegistry()

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    calls = 0

    def activate(**kwargs):
        nonlocal calls
        calls += 1
        return {"unexpected": kwargs["artifact"].artifact_id}

    def make_worker() -> D34CycleWorker:
        return D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                data_root=platform,
                platform_root=platform,
                hqa_root=hqa,
                cache_root=cache,
                workspace_id="default",
                worker_id="test-worker",
            ),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=Futu(),
            platform_replay=replay,
            now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        )

    seeded = make_worker()
    _request_research(seeded, objective="Find a twenty-day reversal")
    _force_legacy_hang_if_pass(jobs)
    initial = seeded.run_once()
    assert initial.status == "needs_recovery"
    assert initial.code == "OSError"
    assert calls == 0

    job_root = workspace / "jobs" / initial.job_id
    recovery_path = job_root / "terminal_recovery.json"
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery.pop("recovery_digest")
    assert "hang_if_pass" not in recovery
    recovery["hang_if_pass"] = True
    recovery_path.write_text(
        json.dumps({**recovery, "recovery_digest": _digest(recovery)}),
        encoding="utf-8",
    )
    phase_path = job_root / "cycle_receipt.json"
    (job_root / "evidence_manifest.json").unlink()
    (job_root / "terminal_bundle.json").unlink()
    phase_path.write_text(
        json.dumps({"phase": "platform_replay", "job_id": initial.job_id}),
        encoding="utf-8",
    )
    docker_call_count = len(docker.commands)
    recovered = make_worker().run_once()

    assert recovered.status == "candidate_ready"
    assert recovered.code == "verified_candidate_not_hung"
    assert recovered.artifact_id == "artifact-cycle-test"
    assert calls == 0
    assert len(docker.commands) == docker_call_count
    assert len(jobs.finished) == 1
    assert len(registry.commands) == 2
    from quant_system.research.trials import TrialsLedger

    assert len(TrialsLedger(platform / "trials").list()) == 9
    receipt = json.loads(
        (workspace / "jobs" / initial.job_id / "cycle_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["phase"] == "candidate_ready"
    assert receipt["recovered"] is True
    assert receipt["comparison_accepted"] is True
    manifest = json.loads((job_root / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["cycle_receipt_digest"] == _digest(receipt)
    terminal_bundle = json.loads((job_root / "terminal_bundle.json").read_text(encoding="utf-8"))
    assert terminal_bundle["cycle_receipt"] == receipt
    assert terminal_bundle["evidence_manifest"] == manifest
    replayed = make_worker().run_once()
    assert replayed.status == "idle"
    assert len(registry.commands) == 2


def test_terminal_receipt_recovers_same_lease_after_finish_response_loss(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    data_root = tmp_path / "data"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, data_root, hqa, cache):
        path.mkdir()

    class CrashOnceJobs(Jobs):
        crashed = False

        def finish(self, **kwargs):
            if not self.crashed and kwargs["outcome_code"] == "artifact_policy_accepted":
                self.crashed = True
                raise KeyboardInterrupt("simulated process loss after terminal receipt")
            return super().finish(**kwargs)

    jobs = CrashOnceJobs()
    registry = Registry()
    docker = Docker(workspace)

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    def make_worker() -> D34CycleWorker:
        return D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                data_root=data_root,
                platform_root=data_root,
                hqa_root=hqa,
                cache_root=cache,
            ),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=Futu(),
            platform_replay=replay,
            now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        )

    initial_worker = make_worker()
    _request_research(initial_worker, objective="Find a twenty-day reversal")
    with pytest.raises(KeyboardInterrupt, match="terminal receipt"):
        initial_worker.run_once()

    recovery_path = workspace / "jobs/job-cycle-12345678/terminal_recovery.json"
    assert recovery_path.is_file()
    assert jobs.items[0].state == "running"

    recovered = make_worker().run_once()

    assert recovered.status == "candidate_ready"
    assert jobs.items[0].state == "succeeded"
    assert len(jobs.finished) == 1
    assert len(registry.commands) == 1


def test_legacy_hang_flag_never_enters_canary_authority_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    def make_worker() -> D34CycleWorker:
        return D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                data_root=platform,
                platform_root=platform,
                hqa_root=hqa,
                cache_root=cache,
            ),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=Futu(),
            platform_replay=replay,
            now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        )

    seeded = make_worker()
    _request_research(seeded, objective="Find a twenty-day reversal")
    _force_legacy_hang_if_pass(jobs)
    result = seeded.run_once()

    assert result.status == "candidate_ready"
    assert result.code == "verified_candidate_not_hung"
    assert jobs.finished[0]["state"] == "succeeded"
    receipt = json.loads(
        (workspace / "jobs" / result.job_id / "cycle_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["phase"] == "candidate_ready"
    assert len(jobs.finished) == 1


class _LeaseProbeJobs(Jobs):
    def __init__(self) -> None:
        super().__init__()
        self.lease_calls = 0

    def lease_next(self, *, workspace_id, worker_id, lease_seconds):
        self.lease_calls += 1
        return super().lease_next(
            workspace_id=workspace_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )


def test_run_once_leases_exact_job_before_llm_preflight_failure(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class FailingLlmDocker(Docker):
        def run(self, *, job_id, command, timeout_seconds=None):
            self.commands.append(tuple(command))
            if command[0] == "llm-smoke":
                job_dir = self.workspace / "jobs" / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "docker_failure.stderr.txt").write_text(
                    "Provider NOT provided. You passed model=grok-4.6",
                    encoding="utf-8",
                )
                raise D34DockerRuntimeError(
                    "d34_docker_failed",
                    "D-34 container failed; inspect its failure receipt",
                )
            raise AssertionError(f"research docker ran after failed preflight: {command}")

    jobs = _LeaseProbeJobs()
    docker = FailingLlmDocker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("preflight failure replayed"),
        now=lambda: datetime(2026, 8, 18, 4, tzinfo=UTC),
    )

    requested = _request_research(worker, objective="Find a five-day momentum factor")
    result = worker.run_once()

    assert requested.status == "queued"
    assert result.status == "failed"
    assert result.code == "d34_preflight_llm_failed"
    assert jobs.lease_calls == 1
    assert jobs.finished[0]["state"] == "rejected"
    assert jobs.finished[0]["outcome_code"] == "d34_preflight_llm_failed"
    assert [job.state for job in jobs.items] == ["rejected"]
    assert docker.commands == [("llm-smoke",)]
    job_root = roots[0] / "jobs" / "job-cycle-12345678"
    receipt = json.loads((job_root / "llm_preflight.json").read_text(encoding="utf-8"))
    assert receipt["job_id"] == "job-cycle-12345678"
    assert receipt["ready"] is False
    assert receipt["code"] == "d34_preflight_llm_failed"
    assert (job_root / "docker_failure.stderr.txt").read_text(
        encoding="utf-8"
    ) == "Provider NOT provided. You passed model=grok-4.6"


def test_run_once_runs_llm_preflight_under_the_exact_lease(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()

    class OrderDocker(Docker):
        def run(self, *, job_id, command, timeout_seconds=None):
            if command[0] == "llm-smoke":
                self.commands.append(tuple(command))
                return self._receipt(
                    job_id,
                    command,
                    {"contract": "hqa.d34_llm_smoke/v1", "json_mode": True},
                )
            return super().run(job_id=job_id, command=command)

    jobs = _LeaseProbeJobs()
    docker = OrderDocker(roots[0])

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return _platform_replay_fixture(
            output_root=kwargs["output_root"],
            qlib=qlib,
            job_id=kwargs["job_id"],
            run_id=kwargs["run_id"],
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            data_root=roots[1],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        now=lambda: datetime(2026, 8, 18, 4, tzinfo=UTC),
    )

    _request_research(worker, objective="Find a five-day momentum factor")
    result = worker.run_once()

    assert docker.commands[0] == ("llm-smoke",)
    assert jobs.lease_calls == 1
    assert result.status != "failed" or result.code != "d34_preflight_llm_failed"
    receipt = json.loads(
        (roots[0] / "jobs/job-cycle-12345678/llm_preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["job_id"] == "job-cycle-12345678"
    assert receipt["ready"] is True


def _write_trial_batch(jobs_dir: Path, *, job_id: str) -> tuple[Path, dict]:
    return_dates = ["2026-08-10", "2026-08-11", "2026-08-12"]
    document: dict = {
        "contract": "hqa.d34_experiment_trial_batch/v1",
        "job_id": job_id,
        "request_digest": "c" * 64,
        "universe": ["SPY"],
        "universe_digest": _digest(["SPY"]),
        "calendar_digest": _digest(return_dates),
        "experiment_count": 1,
        "return_dates": return_dates,
        "experiments": [
            {
                "experiment_id": "iteration-01-experiment-01",
                "subject": "momentum:test",
                "daily_returns": [0.001, -0.002, 0.003],
                "proposal_digest": "a" * 64,
                "experiment_receipt_digest": "b" * 64,
            }
        ],
        "attempts": [{"experiment_id": "iteration-01-experiment-01", "status": "succeeded"}],
        "successful_experiment_count": 1,
    }
    document["receipt_digest"] = _digest(document)
    path = jobs_dir / f"batch-{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(document))
    return path, document


def _persist_kwargs(path: Path, document: dict) -> dict:
    return {
        "batch_path": path,
        "expected_file_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
        "expected_batch_digest": document["receipt_digest"],
        "expected_job_id": document["job_id"],
        "expected_request_digest": document["request_digest"],
        "expected_universe": document["universe"],
        "expected_calendar_digest": document["calendar_digest"],
        "expected_experiment_count": document["experiment_count"],
    }


def test_host_persist_receipt_carries_ledger_coverage(tmp_path: Path) -> None:
    """N(ran)=N(posted) is enforced at the persist seam, not only in tests."""
    from quant_system.d34.worker import persist_host_d34_experiment_trials

    platform = tmp_path / "platform"
    platform.mkdir()
    path, document = _write_trial_batch(tmp_path / "jobs", job_id="job-coverage-1")
    kwargs = _persist_kwargs(path, document)
    receipt = persist_host_d34_experiment_trials(data_root=platform, **kwargs)
    coverage = receipt["trial_coverage"]
    assert coverage["passed"] is True
    assert coverage["n_runs"] == 1
    assert coverage["n_ledger"] == 1
    assert coverage["missing"] == []
    assert coverage["extras"] == []
    # idempotent re-persist still reconciles clean
    second = persist_host_d34_experiment_trials(data_root=platform, **kwargs)
    assert second["trial_coverage"]["passed"] is True


def test_complete_batch_persists_one_trial_or_tombstone_per_attempt(
    tmp_path: Path,
) -> None:
    from quant_system.d34.worker import persist_host_d34_experiment_trials
    from quant_system.research.trials import TrialsLedger

    platform = tmp_path / "platform"
    platform.mkdir()
    path, document = _write_trial_batch(tmp_path / "jobs", job_id="job-mixed-1")
    document["experiment_count"] = 2
    document["attempts"].append(
        {
            "experiment_id": "iteration-01-experiment-02",
            "status": "failed",
        }
    )
    document["receipt_digest"] = _digest(
        {key: value for key, value in document.items() if key != "receipt_digest"}
    )
    path.write_bytes(_canonical(document))

    receipt = persist_host_d34_experiment_trials(
        data_root=platform,
        **_persist_kwargs(path, document),
    )
    rows = TrialsLedger(platform / "trials").list()

    expected_run_ids = [
        "job-mixed-1:iteration-01-experiment-01",
        "job-mixed-1:iteration-01-experiment-02",
    ]
    assert len(rows) == 2
    assert [row.metadata["run_id"] for row in rows] == expected_run_ids
    assert rows[0].metadata.get("skipped") is not True
    assert rows[1].metadata["skipped"] is True
    assert rows[1].metadata["skip_reason"] == "d34_experiment_attempt_failed"
    assert receipt["batch_digest"] == document["receipt_digest"]
    assert all("batch_digest" not in row.metadata for row in rows)
    assert rows[1].n_periods == 0
    assert rows[1].sharpe is None
    assert receipt["run_ids"] == expected_run_ids
    assert receipt["trial_ids"] == [row.trial_id for row in rows]
    assert receipt["successful_experiment_count"] == 1
    assert receipt["trial_coverage"] == {
        "n_runs": 2,
        "n_ledger": 2,
        "n_ledger_rows": 2,
        "n_unique_run_ids": 2,
        "missing": [],
        "extras": [],
        "duplicate_expected_run_ids": [],
        "duplicate_ledger_run_ids": [],
        "passed": True,
    }
    replay = persist_host_d34_experiment_trials(
        data_root=platform,
        **_persist_kwargs(path, document),
    )
    assert replay["trial_ids"] == receipt["trial_ids"]
    assert len(TrialsLedger(platform / "trials").list()) == 2


def test_interrupted_prefix_persists_one_trial_or_tombstone_per_completed_attempt(
    tmp_path: Path,
) -> None:
    from quant_system.d34.worker import persist_host_d34_experiment_attempts
    from quant_system.research.trials import TrialsLedger

    platform = tmp_path / "platform"
    attempts_root = tmp_path / "attempts"
    platform.mkdir()
    attempts_root.mkdir()
    job_id = "job-interrupted-1"
    return_dates = ["2026-08-10", "2026-08-11", "2026-08-12"]
    common = {
        "contract": "hqa.d34_experiment_trial_attempt/v1",
        "job_id": job_id,
        "request_digest": "c" * 64,
        "universe": ["SPY"],
        "universe_digest": _digest(["SPY"]),
        "calendar_digest": _digest(return_dates),
        "return_dates": return_dates,
    }
    succeeded = {
        **common,
        "experiment_id": "iteration-01-experiment-01",
        "status": "succeeded",
        "subject": "momentum:iteration-01-experiment-01",
        "proposal_digest": "a" * 64,
        "experiment_receipt_digest": "b" * 64,
        "daily_returns": [0.001, -0.002, 0.003],
    }
    failed = {
        **common,
        "experiment_id": "iteration-01-experiment-02",
        "status": "failed",
    }
    for document in (succeeded, failed):
        payload = {**document, "receipt_digest": _digest(document)}
        (attempts_root / f"{document['experiment_id']}.json").write_bytes(_canonical(payload))

    receipt = persist_host_d34_experiment_attempts(
        data_root=platform,
        attempts_root=attempts_root,
        expected_job_id=job_id,
        expected_request_digest="c" * 64,
        expected_universe=["SPY"],
        expected_calendar_digest=_digest(return_dates),
        max_experiment_count=4,
    )
    rows = TrialsLedger(platform / "trials").list()

    expected_run_ids = [
        "job-interrupted-1:iteration-01-experiment-01",
        "job-interrupted-1:iteration-01-experiment-02",
    ]
    assert len(rows) == 2
    assert [row.metadata["run_id"] for row in rows] == expected_run_ids
    assert rows[0].metadata.get("skipped") is not True
    assert rows[1].metadata["skipped"] is True
    assert rows[1].metadata["skip_reason"] == "d34_experiment_attempt_failed"
    assert receipt["attempt_receipt_digests"] == {
        "iteration-01-experiment-01": _digest(succeeded),
        "iteration-01-experiment-02": _digest(failed),
    }
    assert all("attempt_receipt_digest" not in row.metadata for row in rows)
    assert all("interrupted_research" not in row.metadata for row in rows)
    assert rows[1].n_periods == 0
    assert rows[1].sharpe is None
    assert receipt["completed_experiment_count"] == 2
    assert receipt["successful_experiment_count"] == 1
    assert receipt["run_ids"] == expected_run_ids
    assert receipt["trial_ids"] == [row.trial_id for row in rows]
    assert receipt["trial_coverage"] == {
        "n_runs": 2,
        "n_ledger": 2,
        "n_ledger_rows": 2,
        "n_unique_run_ids": 2,
        "missing": [],
        "extras": [],
        "duplicate_expected_run_ids": [],
        "duplicate_ledger_run_ids": [],
        "passed": True,
    }
    replay = persist_host_d34_experiment_attempts(
        data_root=platform,
        attempts_root=attempts_root,
        expected_job_id=job_id,
        expected_request_digest="c" * 64,
        expected_universe=["SPY"],
        expected_calendar_digest=_digest(return_dates),
        max_experiment_count=4,
    )
    assert replay["trial_ids"] == receipt["trial_ids"]
    assert len(TrialsLedger(platform / "trials").list()) == 2


def test_interrupted_prefix_then_complete_batch_converges_on_same_attempt_rows(
    tmp_path: Path,
) -> None:
    from quant_system.d34.worker import (
        persist_host_d34_experiment_attempts,
        persist_host_d34_experiment_trials,
    )
    from quant_system.research.trials import TrialsLedger

    platform = tmp_path / "platform"
    attempts_root = tmp_path / "attempts"
    platform.mkdir()
    attempts_root.mkdir()
    batch_path, batch = _write_trial_batch(
        tmp_path / "jobs",
        job_id="job-interrupted-complete-1",
    )
    batch["experiment_count"] = 2
    batch["attempts"].append({"experiment_id": "iteration-01-experiment-02", "status": "failed"})
    batch["receipt_digest"] = _digest(
        {key: value for key, value in batch.items() if key != "receipt_digest"}
    )
    batch_path.write_bytes(_canonical(batch))

    successful = {
        "contract": "hqa.d34_experiment_trial_attempt/v1",
        "job_id": batch["job_id"],
        "request_digest": batch["request_digest"],
        "universe": batch["universe"],
        "universe_digest": batch["universe_digest"],
        "calendar_digest": batch["calendar_digest"],
        "return_dates": batch["return_dates"],
        **batch["experiments"][0],
        "status": "succeeded",
    }
    failed = {
        key: successful[key]
        for key in (
            "contract",
            "job_id",
            "request_digest",
            "universe",
            "universe_digest",
            "calendar_digest",
            "return_dates",
        )
    }
    failed.update(
        {
            "experiment_id": "iteration-01-experiment-02",
            "status": "failed",
        }
    )
    for document in (successful, failed):
        payload = {**document, "receipt_digest": _digest(document)}
        (attempts_root / f"{document['experiment_id']}.json").write_bytes(_canonical(payload))

    interrupted = persist_host_d34_experiment_attempts(
        data_root=platform,
        attempts_root=attempts_root,
        expected_job_id=str(batch["job_id"]),
        expected_request_digest=str(batch["request_digest"]),
        expected_universe=batch["universe"],
        expected_calendar_digest=str(batch["calendar_digest"]),
        max_experiment_count=2,
    )
    complete = persist_host_d34_experiment_trials(
        data_root=platform,
        **_persist_kwargs(batch_path, batch),
    )
    rows = TrialsLedger(platform / "trials").list()

    assert interrupted["trial_coverage"]["passed"] is True
    assert complete["trial_coverage"]["passed"] is True
    assert interrupted["trial_ids"] == complete["trial_ids"]
    assert len(rows) == 2
    assert rows[0].metadata["attempt_status"] == "succeeded"
    assert rows[1].metadata["attempt_status"] == "failed"

    batch["experiments"][0]["daily_returns"][0] = 0.5
    batch["receipt_digest"] = _digest(
        {key: value for key, value in batch.items() if key != "receipt_digest"}
    )
    batch_path.write_bytes(_canonical(batch))
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        persist_host_d34_experiment_trials(
            data_root=platform,
            **_persist_kwargs(batch_path, batch),
        )


def test_host_persist_fails_closed_on_tampered_job_scope(tmp_path: Path) -> None:
    """An extra/missing scoped ledger row must raise, not silently pass."""
    from quant_system.d34.worker import (
        _D34WorkerValidationError,
        persist_host_d34_experiment_trials,
    )
    from quant_system.research.trials import ResearchTrial, TrialsLedger

    platform = tmp_path / "platform"
    platform.mkdir()
    ledger = TrialsLedger(platform / "trials")
    ledger.append(
        ResearchTrial.skipped(
            kind="d34_experiment",
            subject="tamper",
            universe=["SPY"],
            reason="test_only",
            source="job-coverage-2:iteration-99-experiment-99",
            metadata={
                "run_id": "job-coverage-2:iteration-99-experiment-99",
                "job_id": "job-coverage-2",
            },
        )
    )
    path, document = _write_trial_batch(tmp_path / "jobs", job_id="job-coverage-2")
    with pytest.raises(_D34WorkerValidationError) as excinfo:
        persist_host_d34_experiment_trials(
            data_root=platform, **_persist_kwargs(path, document)
        )
    assert excinfo.value.code == "d34_experiment_trials_coverage_mismatch"
