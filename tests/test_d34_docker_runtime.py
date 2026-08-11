from __future__ import annotations

import subprocess
from pathlib import Path

from quant_system.d34.docker_runtime import D34DockerConfig, D34DockerRuntime


def test_open_local_runtime_mounts_repos_socket_and_cleans_container(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for root in roots:
        root.mkdir()
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(list(command))
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="sha256:" + "a" * 64 + "\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"contract":"hqa.d34_container_versions/v1"}\n',
            stderr="",
        )

    runtime = D34DockerRuntime(
        D34DockerConfig(
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
            timeout_seconds=60,
        ),
        process_runner=run,
    )

    receipt = runtime.run(job_id="job-123", command=("versions",))

    docker_run = calls[1]
    assert docker_run[:2] == ["docker", "run"]
    assert "--user" in docker_run and "0:0" in docker_run
    assert "--network" in docker_run and "bridge" in docker_run
    assert "/var/run/docker.sock:/var/run/docker.sock" in docker_run
    assert f"{roots[1].resolve()}:/workspace/platform" in docker_run
    assert receipt.image_digest == "sha256:" + "a" * 64
    assert receipt.output["contract"] == "hqa.d34_container_versions/v1"
    assert len(receipt.receipt_digest) == 64
