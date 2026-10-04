from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quant_system.d34.docker_runtime import D34DockerReceipt, D34DockerRuntimeError
from quant_system.d34.preflight import run_d34_llm_preflight, run_d34_preflight

runner = CliRunner()


class DockerBoundary:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        *,
        job_id: str,
        command: tuple[str, ...],
        timeout_seconds: int | None = None,
    ) -> D34DockerReceipt:
        self.commands.append(command)
        assert job_id == "job-d34-preflight"
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            image_digest="sha256:" + "9" * 64,
            command=command,
            output={
                "contract": "hqa.d34_container_smoke/v1",
                "versions": {"contract": "hqa.d34_container_versions/v1"},
                "qlib-smoke": {"contract": "hqa.d34_qlib_smoke/v1"},
                "llm-smoke": {"contract": "hqa.d34_llm_smoke/v1"},
                "futu-smoke": {
                    "contract": "hqa.d34_futu_socket_smoke/v1",
                    "reachable": True,
                },
                "docker-smoke": {
                    "contract": "hqa.d34_docker_child_smoke/v1",
                    "ok": True,
                },
            },
            receipt_digest="8" * 64,
        )


def test_preflight_proves_schema_and_every_real_runtime_boundary(tmp_path: Path) -> None:
    docker = DockerBoundary()

    receipt = run_d34_preflight(
        workspace_root=tmp_path,
        docker_runtime=docker,
        safety_observer=lambda: {
            "contract": "hqa.effective_paper_safety/v2",
            "workspace_id": "default",
            "live_execution_enabled": False,
            "research_execution_enabled": False,
            "paper_execution_enabled": False,
            "research_blockers": ["no_active_mandate"],
            "blockers": ["no_active_mandate"],
        },
    )

    assert receipt.ready is True
    assert docker.commands == [("smoke",)]
    assert receipt.image_digest == "sha256:" + "9" * 64
    assert receipt.safety_contract == "hqa.effective_paper_safety/v2"
    assert receipt.live_execution_enabled is False
    assert len(receipt.receipt_digest) == 64
    durable = json.loads((tmp_path / "preflight/latest.json").read_text(encoding="utf-8"))
    assert durable == receipt.to_public_dict()
    assert durable["smoke_contracts"] == {
        "docker-smoke": "hqa.d34_docker_child_smoke/v1",
        "futu-smoke": "hqa.d34_futu_socket_smoke/v1",
        "llm-smoke": "hqa.d34_llm_smoke/v1",
        "qlib-smoke": "hqa.d34_qlib_smoke/v1",
        "versions": "hqa.d34_container_versions/v1",
    }


class LlmDockerBoundary:
    def __init__(self, *, fail: bool = False, output: dict | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.job_ids: list[str] = []
        self.fail = fail
        self.output = output or {"contract": "hqa.d34_llm_smoke/v1", "json_mode": True}
        self.timeout_seconds: int | None = None

    def run(
        self,
        *,
        job_id: str,
        command: tuple[str, ...],
        timeout_seconds: int | None = None,
    ) -> D34DockerReceipt:
        self.commands.append(command)
        self.job_ids.append(job_id)
        self.timeout_seconds = timeout_seconds
        if self.fail:
            raise D34DockerRuntimeError("d34_docker_failed", "llm smoke failed")
        return D34DockerReceipt(
            contract="hqa.d34_docker_receipt/v1",
            job_id=job_id,
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            image_digest="sha256:" + "9" * 64,
            command=command,
            output=self.output,
            receipt_digest="8" * 64,
        )


def test_llm_preflight_runs_llm_smoke_and_persists_ready_receipt(tmp_path: Path) -> None:
    docker = LlmDockerBoundary()
    job_id = "job-preflight-bound-12345678"

    receipt = run_d34_llm_preflight(
        workspace_root=tmp_path,
        job_id=job_id,
        docker_runtime=docker,
    )

    assert receipt.ready is True
    assert docker.commands == [("llm-smoke",)]
    assert docker.job_ids == [job_id]
    assert docker.timeout_seconds == 120
    durable = json.loads(
        (tmp_path / f"jobs/{job_id}/llm_preflight.json").read_text(encoding="utf-8")
    )
    assert durable["contract"] == "hqa.d34_llm_preflight/v2"
    assert durable["job_id"] == job_id
    assert durable["ready"] is True
    assert durable["llm_contract"] == "hqa.d34_llm_smoke/v1"


def test_llm_preflight_failure_is_not_ready_and_does_not_raise(tmp_path: Path) -> None:
    docker = LlmDockerBoundary(fail=True)
    job_id = "job-preflight-failed-12345678"

    receipt = run_d34_llm_preflight(
        workspace_root=tmp_path,
        job_id=job_id,
        docker_runtime=docker,
    )

    assert receipt.ready is False
    assert receipt.code == "d34_preflight_llm_failed"
    durable = json.loads(
        (tmp_path / f"jobs/{job_id}/llm_preflight.json").read_text(encoding="utf-8")
    )
    assert durable["ready"] is False
    assert durable["code"] == "d34_preflight_llm_failed"


def test_llm_preflight_rejects_empty_or_invalid_llm_reply(tmp_path: Path) -> None:
    docker = LlmDockerBoundary(output={"contract": "hqa.d34_llm_smoke/v1"})

    receipt = run_d34_llm_preflight(
        workspace_root=tmp_path,
        job_id="job-preflight-invalid-12345678",
        docker_runtime=docker,
    )

    assert receipt.ready is False
    assert receipt.code == "d34_preflight_llm_failed"
