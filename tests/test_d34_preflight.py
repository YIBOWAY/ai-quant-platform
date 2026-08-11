from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.d34.docker_runtime import D34DockerReceipt
from quant_system.d34.preflight import run_d34_preflight

runner = CliRunner()


class DockerBoundary:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, *, job_id: str, command: tuple[str, ...]) -> D34DockerReceipt:
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
    durable = json.loads(
        (tmp_path / "preflight/latest.json").read_text(encoding="utf-8")
    )
    assert durable == receipt.to_public_dict()
    assert durable["smoke_contracts"] == {
        "docker-smoke": "hqa.d34_docker_child_smoke/v1",
        "futu-smoke": "hqa.d34_futu_socket_smoke/v1",
        "llm-smoke": "hqa.d34_llm_smoke/v1",
        "qlib-smoke": "hqa.d34_qlib_smoke/v1",
        "versions": "hqa.d34_container_versions/v1",
    }


def test_preflight_cli_emits_one_machine_readable_ready_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = {name: tmp_path / name for name in ("platform", "hqa", "workspace", "cache")}
    for root in roots.values():
        root.mkdir()
    env_file = tmp_path / "d34.env"
    env_file.write_text(
        "LITELLM_CHAT_MODEL=test-chat\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(env_file))

    docker = DockerBoundary()
    monkeypatch.setattr(
        "quant_system.d34.cli.D34DockerRuntime",
        lambda _config: docker,
    )

    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str):
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "live_execution_enabled": False,
                "research_blockers": ["no_active_mandate"],
                "blockers": ["no_active_mandate"],
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    result = runner.invoke(
        app,
        [
            "d34",
            "preflight",
            "--platform-root",
            str(roots["platform"]),
            "--hqa-root",
            str(roots["hqa"]),
            "--workspace-root",
            str(roots["workspace"]),
            "--cache-root",
            str(roots["cache"]),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["contract"] == "hqa.d34_preflight/v1"
    assert payload["ready"] is True
    assert payload["live_execution_enabled"] is False
    assert docker.commands == [("smoke",)]


def test_preflight_cli_emits_a_stable_owner_env_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = {name: tmp_path / name for name in ("platform", "hqa", "workspace", "cache")}
    for root in roots.values():
        root.mkdir()
    env_file = tmp_path / "d34.env"
    env_file.write_text("OPENAI_API_KEY=local-proxy\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(env_file))

    result = runner.invoke(
        app,
        [
            "d34",
            "preflight",
            "--platform-root",
            str(roots["platform"]),
            "--hqa-root",
            str(roots["hqa"]),
            "--workspace-root",
            str(roots["workspace"]),
            "--cache-root",
            str(roots["cache"]),
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "code": "d34_env_models_required",
        "contract": "hqa.d34_preflight/v1",
        "message": "d34_env_models_required",
        "ready": False,
    }
