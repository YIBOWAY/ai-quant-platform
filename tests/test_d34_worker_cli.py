from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.d34 import research_cli
from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    build_owner_request_input,
    digest_document,
)
from quant_system.d34.worker import D34WorkerResult
from quant_system.hermes.d34_job_authority import LeasedJobInput


def test_build_local_research_worker_never_constructs_paper_dependencies(
    monkeypatch,
    tmp_path: Path,
) -> None:
    forbidden_calls: list[str] = []

    def forbidden(name: str):
        def call(*_args, **_kwargs):
            forbidden_calls.append(name)
            raise AssertionError(f"research worker constructed {name}")

        return call

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(research_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(research_cli, "_existing_env_file", forbidden("d34_env"))
    monkeypatch.setattr(research_cli, "D34DockerRuntime", forbidden("docker"))
    monkeypatch.setattr(
        research_cli,
        "build_ohlcv_provider",
        forbidden("futu"),
    )
    monkeypatch.setattr(
        research_cli,
        "PostgresRegistryAuthority",
        lambda _settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        research_cli,
        "PostgresJobAuthority",
        lambda _settings: SimpleNamespace(),
    )
    worker = research_cli.build_local_research_worker(
        platform_root=tmp_path,
        hqa_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        data_root=tmp_path / "data",
        cache_root=tmp_path / "cache",
        image_ref="sha256:" + "a" * 64,
        workspace_id="default",
        worker_id="test-research-worker",
    )

    assert worker.futu_provider.provider_name == "futu"
    assert worker.config.lease_seconds == 7200
    assert forbidden_calls == []


def test_missing_hqa_runtime_fails_the_exact_leased_job_before_provider_io(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "d34.env"
    env_file.write_text("OPENAI_API_KEY=fixture-not-used\n", encoding="utf-8")
    env_file.chmod(0o600)
    document = build_owner_request_input(
        objective="Research a twenty-day reversal factor",
        universe=["SPY", "QQQ"],
    )
    document.update(
        {
            "job_key": "assistant-remote:missing-hqa",
            "operation_id": "a" * 64,
            "material_digest": "b" * 64,
            "platform_session_id": "platform-session-missing-hqa",
            "hermes_session_id": "hermes-session-missing-hqa",
        }
    )
    job = SimpleNamespace(
        job_id="job-missing-hqa-runtime",
        job_key=document["job_key"],
        state="queued",
        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        budget_reserved_usd=Decimal("10"),
    )

    class Jobs:
        def __init__(self) -> None:
            self.finished: list[dict[str, object]] = []

        def list(self, **_kwargs):
            return [job]

        def reconcile_expired(self, **_kwargs):
            return []

        def lease_next(self, **_kwargs):
            return SimpleNamespace(
                job=job,
                lease_id="lease-missing-hqa-runtime",
                attempt_id="attempt-missing-hqa-runtime",
            )

        def read_leased_input(self, **_kwargs):
            return LeasedJobInput(
                job_id=job.job_id,
                input_digest=digest_document(document),
                input_document=document,
            )

        def mark_running(self, **_kwargs):
            job.state = "running"
            return job

        def finish(self, **kwargs):
            self.finished.append(kwargs)
            job.state = str(kwargs["state"])
            return job

    class Registry:
        def __init__(self) -> None:
            self.calls = 0

        def record_artifact_evaluation(self, _command):
            self.calls += 1
            raise AssertionError("invalid HQA runtime reached registry")

    jobs = Jobs()
    registry = Registry()
    provider = SimpleNamespace(
        provider_name="futu",
        fetch_ohlcv=lambda *_args, **_kwargs: pytest.fail("invalid HQA runtime called Futu"),
    )
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(research_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(research_cli, "_existing_env_file", lambda _root: env_file)
    monkeypatch.setattr(research_cli, "build_ohlcv_provider", lambda *_args, **_kwargs: (provider, "futu"))
    monkeypatch.setattr(research_cli, "PostgresJobAuthority", lambda _settings: jobs)
    monkeypatch.setattr(research_cli, "PostgresRegistryAuthority", lambda _settings: registry)

    worker = research_cli.build_local_research_worker(
        platform_root=tmp_path,
        hqa_root=tmp_path / "missing-hqa",
        workspace_root=tmp_path / "workspace",
        data_root=tmp_path / "data",
        cache_root=tmp_path / "cache",
        image_ref="sha256:" + "a" * 64,
        workspace_id="default",
        worker_id="test-missing-hqa",
    )
    result = worker.run_once()

    assert result.status == "failed"
    assert result.job_id == job.job_id
    assert len(jobs.finished) == 1
    assert jobs.finished[0]["state"] == "rejected"
    assert registry.calls == 0


@pytest.mark.parametrize(
    "worker_result",
    [
        D34WorkerResult(
            status="candidate_ready",
            code="accepted",
            job_id="job-stage3",
            artifact_id="artifact-stage3",
        ),
        D34WorkerResult(status="idle", code="no_job"),
    ],
)
def test_research_worker_once_projects_before_and_after_without_paper_fields(
    monkeypatch,
    tmp_path: Path,
    worker_result: D34WorkerResult,
    capsys,
) -> None:
    calls: list[str] = []
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    worker = SimpleNamespace(run_once=lambda: calls.append("research") or worker_result)
    monkeypatch.setattr(research_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        research_cli,
        "build_local_research_worker",
        lambda **_kwargs: worker,
    )
    monkeypatch.setattr(
        research_cli,
        "_project_terminal_research_results",
        lambda _settings: (
            calls.append("project")
            or {
                "contract": "hqa.assistant_remote_projector/v1",
                "requests_checked": 0,
                "requests_projected": 0,
            }
        ),
    )

    exit_code = research_cli.main(
        [
            "--platform-root",
            str(tmp_path),
            "--hqa-root",
            str(tmp_path),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--cache-root",
            str(tmp_path / "cache"),
        ],
    )

    output = capsys.readouterr().out
    assert exit_code == 0, output
    assert calls == ["project", "research", "project"]
    assert '"contract": "hqa.d34_research_worker_result/v2"' in output
    assert '"canary"' not in output
    assert '"paper_cycle"' not in output
