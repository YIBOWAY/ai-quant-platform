from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.d34.docker_runtime import D34DockerReceipt, D34DockerRuntimeError
from quant_system.d34.engine_comparison import EngineReceipt
from quant_system.d34.research_driver import ResearchProposal, render_factor_source
from quant_system.d34.worker import D34CycleWorker, D34WorkerConfig
from quant_system.hermes.d34_job_authority import LeasedJobInput
from quant_system.hermes.d34_registry_authority import D34Artifact


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class Futu:
    provider_name = "futu"

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        assert interval == "1d"
        rows = []
        for offset, symbol in enumerate(symbols):
            for day in range(1, 7):
                close = 100 + offset + day
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": pd.Timestamp(f"2026-08-0{day}", tz="UTC"),
                        "open": close - 0.5,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1_000_000,
                        "provider": "futu",
                        "interval": "1d",
                        "event_ts": pd.Timestamp(f"2026-08-0{day}", tz="UTC"),
                        "knowledge_ts": pd.Timestamp("2026-08-07", tz="UTC"),
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
            mandate_id=command.mandate_id,
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


class Docker:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
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

    def run(self, *, job_id, command):
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
        assert command[0] == "research"
        request_arg = command[command.index("--request") + 1]
        request_path = self.workspace / request_arg.removeprefix("/workspace/d34/")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        root = self.workspace / "jobs" / job_id / "research-result"
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
            "snapshot_digest": request["snapshot_digest"],
            "universe_digest": _digest(request["universe"]),
            "calendar_digest": _digest(request["calendar"]),
            "target_weights_digest": weights_digest,
            "daily_returns": [0.0, 0.01, -0.002, 0.004, 0.003, -0.001],
            "return_dates": request["calendar"],
            "terminal_nav": 1.014,
            "terminal_weights": {"SPY": 0.99},
        }
        qlib_receipt = root / "qlib_receipt.json"
        qlib_receipt.write_bytes(
            _canonical({**receipt_body, "receipt_digest": _digest(receipt_body)}) + b"\n"
        )
        return self._receipt(
            job_id,
            command,
            {
                "contract": "hqa.d34_research_result/v1",
                "job_id": job_id,
                "factor_id": "d34_cycle_factor",
                "candidate_code_digest": code_digest,
                "qlib_config_digest": "6" * 64,
                "target_weights_digest": weights_digest,
                "qlib_receipt_digest": _digest(receipt_body),
                "budget_spent_usd": 1.25,
                "factor_path": f"/workspace/d34/{factor.relative_to(self.workspace)}",
                "target_weights_path": f"/workspace/d34/{weights.relative_to(self.workspace)}",
                "qlib_receipt_path": f"/workspace/d34/{qlib_receipt.relative_to(self.workspace)}",
                "rdagent_commit": "3" * 40,
                "qlib_commit": "4" * 40,
            },
        )


class Registry:
    def __init__(self) -> None:
        self.commands = []

    def record_artifact_evaluation(self, command):
        self.commands.append(command)
        artifact = D34Artifact(
            artifact_id="artifact-cycle-test",
            mandate_id=command.mandate_id,
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


def _open_safety(mandate) -> dict[str, object]:
    return {
        "research_execution_enabled": True,
        "research_blockers": [],
        "paper_execution_enabled": True,
        "blockers": [],
        "emergency_stop": {"active": False},
        "active_mandate": {
            "mandate_id": mandate.mandate_id,
            "status": "active",
            "paper_execution_allowed": True,
        },
    }


def test_cycle_honors_emergency_stop_before_research_or_futu(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    jobs = Jobs()
    docker = Docker(roots[0])

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(
            get_active=lambda **_kwargs: pytest.fail("emergency stop queried Mandate")
        ),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("emergency stop replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("emergency stop activated canary"),
        safety_observer=lambda: {
            "research_execution_enabled": False,
            "research_blockers": ["emergency_stop_active"],
        },
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "emergency_stop_active"
    assert jobs.items == []
    assert docker.commands == []


def test_cycle_runs_paper_canary_operations_even_without_a_new_research_job(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    observed: list[dict[str, object]] = []
    safety = {
        "research_execution_enabled": True,
        "research_blockers": [],
        "paper_execution_enabled": True,
    }

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: None),
        jobs=Jobs(),
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("idle cycle replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("idle cycle activated canary"),
        safety_observer=lambda: safety,
        canary_operator=lambda current: observed.append(dict(current)) or {"signals_generated": 1},
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "no_active_mandate"
    assert result.paper_cycle == {"signals_generated": 1}
    assert observed == [safety]


def test_cycle_waits_for_post_close_window_before_snapshot_or_research(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    jobs = Jobs()
    docker = Docker(roots[0])
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("pre-close cycle replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("pre-close canary activated"),
        safety_observer=lambda: _open_safety(mandate),
        canary_operator=lambda _safety: {"sleeves_checked": 0},
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 10, 19, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert result.code == "d34_research_window_closed"
    assert result.paper_cycle == {"sleeves_checked": 0}
    assert jobs.items == []
    assert docker.commands == []


def test_cycle_uses_shanghai_date_when_research_window_crosses_utc_day(
    tmp_path: Path,
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    class SchedulingOnlyJobs(Jobs):
        def lease_next(self, *, workspace_id, worker_id, lease_seconds):
            return None

    jobs = SchedulingOnlyJobs()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("idle cycle replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("idle cycle activated canary"),
        safety_observer=lambda: _open_safety(mandate),
        canary_operator=lambda _safety: {"sleeves_checked": 0},
        now=lambda: datetime(2026, 8, 12, 22, 30, tzinfo=UTC),
    )

    requested = worker.request_research(objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert requested.status == "queued"
    assert requested.code == "d34_research_requested"
    assert result.status == "idle"
    assert result.code == "no_queued_job"
    assert [job.job_key for job in jobs.items] == [requested.job_id]
    assert jobs.input.input_document["cycle_date"] == "2026-08-13"
    assert jobs.input.input_document["trigger"] == "owner_request"
    assert jobs.input.input_document["objective"] == "Find a twenty-day reversal"


def test_run_once_does_not_invent_a_research_cycle(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    jobs = Jobs()
    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=Docker(roots[0]),
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("unsolicited cycle replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("unsolicited canary"),
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
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
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

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
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=FutuUnavailable(),
        platform_replay=lambda **_kwargs: pytest.fail("offline Futu replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("offline Futu activated canary"),
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    requested = worker.request_research(objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert requested.status == "queued"
    assert requested.code == "d34_research_requested"
    assert result.status == "failed"
    assert result.code == "snapshot_futu_unavailable"
    assert [job.job_key for job in jobs.items] == [requested.job_id]
    assert docker.commands == []


def test_cycle_rejects_queued_jobs_that_were_not_owner_requested(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for path in roots:
        path.mkdir()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    document = {
        "contract": "hqa.d34_job_input/v1",
        "cycle_date": "2026-08-11",
        "hypothesis_number": 1,
        "trigger": "schedule",
        "mandate_id": mandate.mandate_id,
        "mandate_policy_digest": mandate.policy_digest,
        "universe": list(mandate.universe),
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
            mandate_id=mandate.mandate_id,
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
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("legacy job replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("legacy job activated canary"),
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
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
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

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
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("tampered input replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("tampered input activated canary"),
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    worker.request_research(objective="Find a twenty-day reversal")
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
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    class TimedOutResearch(Docker):
        def run(self, *, job_id, command):
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
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
        ),
        mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
        jobs=jobs,
        registry=Registry(),
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=lambda **_kwargs: pytest.fail("timed out research replayed"),
        canary_activator=lambda **_kwargs: pytest.fail("timed out research activated canary"),
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    worker.request_research(objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "failed"
    assert result.code == "d34_docker_timeout"
    assert jobs.finished[0]["state"] == "outcome_unknown"
    assert jobs.finished[0]["budget_spent_usd"] == Decimal("0")
    assert [command[0] for command in docker.commands] == ["qlib-adapt", "research"]


def test_cycle_runs_futu_to_dual_engine_artifact_and_real_canary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    activated = []

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return SimpleNamespace(
            engine_receipt=EngineReceipt(
                engine="platform",
                snapshot_digest=qlib.snapshot_digest,
                universe_digest=qlib.universe_digest,
                calendar_digest=qlib.calendar_digest,
                target_weights_digest=qlib.target_weights_digest,
                daily_returns=qlib.daily_returns,
                return_dates=qlib.return_dates,
                terminal_nav=qlib.terminal_nav,
                terminal_weights=qlib.terminal_weights,
                receipt_digest="8" * 64,
            )
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        mandates=SimpleNamespace(get_active=lambda **kwargs: mandate),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        canary_activator=lambda **kwargs: activated.append(kwargs) or "canary-test",
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    worker.request_research(
        objective="Find a twenty-day reversal",
        hang_if_pass=True,
    )
    result = worker.run_once()

    assert result.status == "canary_active"
    assert result.job_id == "job-cycle-12345678"
    assert [command[0] for command in docker.commands] == ["qlib-adapt", "research"]
    assert jobs.finished[0]["state"] == "succeeded"
    assert jobs.finished[0]["budget_spent_usd"] == Decimal("1.25")
    assert jobs.heartbeats >= 2
    assert registry.commands[0].qlib_receipt.engine == "qlib"
    assert registry.commands[0].platform_receipt.engine == "platform"
    assert activated[0]["factor_id"] == "d34_cycle_factor"
    assert activated[0]["artifact"].qualification_scope == "paper_only"


def test_cycle_stops_at_verified_candidate_unless_owner_said_hang(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    activated: list[object] = []

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return SimpleNamespace(
            engine_receipt=EngineReceipt(
                engine="platform",
                snapshot_digest=qlib.snapshot_digest,
                universe_digest=qlib.universe_digest,
                calendar_digest=qlib.calendar_digest,
                target_weights_digest=qlib.target_weights_digest,
                daily_returns=qlib.daily_returns,
                return_dates=qlib.return_dates,
                terminal_nav=qlib.terminal_nav,
                terminal_weights=qlib.terminal_weights,
                receipt_digest="8" * 64,
            )
        )

    worker = D34CycleWorker(
        config=D34WorkerConfig(
            workspace_root=workspace,
            platform_root=platform,
            hqa_root=hqa,
            cache_root=cache,
            workspace_id="default",
            worker_id="test-worker",
        ),
        mandates=SimpleNamespace(get_active=lambda **kwargs: mandate),
        jobs=jobs,
        registry=registry,
        docker_runtime=docker,
        futu_provider=Futu(),
        platform_replay=replay,
        canary_activator=lambda **kwargs: activated.append(kwargs) or "canary-test",
        safety_observer=lambda: _open_safety(mandate),
        today=lambda: date(2026, 8, 11),
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    worker.request_research(objective="Find a twenty-day reversal")
    result = worker.run_once()

    assert result.status == "candidate_ready"
    assert result.code == "verified_candidate_not_hung"
    assert result.artifact_id
    assert activated == []


def test_cycle_recovers_registry_to_canary_after_terminal_crash_without_rerunning_research(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )

    def replay(**kwargs):
        qlib = kwargs.pop("qlib_receipt")
        return SimpleNamespace(
            engine_receipt=EngineReceipt(
                engine="platform",
                snapshot_digest=qlib.snapshot_digest,
                universe_digest=qlib.universe_digest,
                calendar_digest=qlib.calendar_digest,
                target_weights_digest=qlib.target_weights_digest,
                daily_returns=qlib.daily_returns,
                return_dates=qlib.return_dates,
                terminal_nav=qlib.terminal_nav,
                terminal_weights=qlib.terminal_weights,
                receipt_digest="8" * 64,
            )
        )

    calls = 0

    def activate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated crash after registry commit")
        return {"canary_id": "canary-recovered", "artifact": kwargs["artifact"].artifact_id}

    def make_worker() -> D34CycleWorker:
        return D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                platform_root=platform,
                hqa_root=hqa,
                cache_root=cache,
                workspace_id="default",
                worker_id="test-worker",
            ),
            mandates=SimpleNamespace(get_active=lambda **kwargs: mandate),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=Futu(),
            platform_replay=replay,
            canary_activator=activate,
            safety_observer=lambda: _open_safety(mandate),
            today=lambda: date(2026, 8, 11),
            now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        )

    seeded = make_worker()
    seeded.request_research(
        objective="Find a twenty-day reversal",
        hang_if_pass=True,
    )
    failed = seeded.run_once()
    docker_call_count = len(docker.commands)
    recovered = make_worker().run_once()

    assert failed.status == "needs_recovery"
    assert recovered.status == "canary_active"
    assert recovered.artifact_id == "artifact-cycle-test"
    assert recovered.canary == {
        "canary_id": "canary-recovered",
        "artifact": "artifact-cycle-test",
    }
    assert len(docker.commands) == docker_call_count
    assert len(jobs.finished) == 1
    assert len(registry.commands) == 2
    receipt = json.loads(
        (workspace / "jobs" / failed.job_id / "cycle_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["phase"] == "canary_active"


def test_cycle_rechecks_paper_authority_after_research_before_canary(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    platform = tmp_path / "platform"
    hqa = tmp_path / "hqa"
    cache = tmp_path / "cache"
    for path in (workspace, platform, hqa, cache):
        path.mkdir()
    jobs, docker, registry = Jobs(), Docker(workspace), Registry()
    mandate = SimpleNamespace(
        mandate_id="mandate-cycle-12345678",
        workspace_id="default",
        status="active",
        universe=("SPY", "QQQ", "IWM", "DIA"),
        hypotheses_per_cycle=1,
        max_iterations=2,
        max_experiments_per_iteration=2,
        max_concurrent_jobs=1,
        llm_budget_usd=Decimal("100"),
        paper_execution_allowed=True,
        policy_digest="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    authority_open = True
    activated: list[dict[str, object]] = []

    def safety():
        if authority_open:
            return _open_safety(mandate)
        return {
            "research_execution_enabled": False,
            "research_blockers": ["emergency_stop_active"],
            "paper_execution_enabled": False,
            "blockers": ["emergency_stop_active"],
            "emergency_stop": {"active": True},
            "active_mandate": {
                "mandate_id": mandate.mandate_id,
                "status": "active",
                "paper_execution_allowed": True,
            },
        }

    def replay(**kwargs):
        nonlocal authority_open
        qlib = kwargs.pop("qlib_receipt")
        authority_open = False
        return SimpleNamespace(
            engine_receipt=EngineReceipt(
                engine="platform",
                snapshot_digest=qlib.snapshot_digest,
                universe_digest=qlib.universe_digest,
                calendar_digest=qlib.calendar_digest,
                target_weights_digest=qlib.target_weights_digest,
                daily_returns=qlib.daily_returns,
                return_dates=qlib.return_dates,
                terminal_nav=qlib.terminal_nav,
                terminal_weights=qlib.terminal_weights,
                receipt_digest="8" * 64,
            )
        )

    def make_worker() -> D34CycleWorker:
        return D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                platform_root=platform,
                hqa_root=hqa,
                cache_root=cache,
            ),
            mandates=SimpleNamespace(get_active=lambda **_kwargs: mandate),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=Futu(),
            platform_replay=replay,
            canary_activator=lambda **kwargs: activated.append(kwargs) or "canary-test",
            safety_observer=safety,
            today=lambda: date(2026, 8, 11),
            now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        )

    seeded = make_worker()
    seeded.request_research(
        objective="Find a twenty-day reversal",
        hang_if_pass=True,
    )
    blocked = seeded.run_once()

    assert blocked.status == "awaiting_paper_authority"
    assert blocked.code == "emergency_stop_active"
    assert activated == []
    assert jobs.finished[0]["state"] == "succeeded"
    docker_calls = len(docker.commands)
    receipt = json.loads(
        (workspace / "jobs" / blocked.job_id / "cycle_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["phase"] == "needs_recovery"
    assert receipt["failed_phase"] == "canary_activation"

    authority_open = True
    recovered = make_worker().run_once()

    assert recovered.status == "canary_active"
    assert len(activated) == 1
    assert len(docker.commands) == docker_calls
    assert len(jobs.finished) == 1
