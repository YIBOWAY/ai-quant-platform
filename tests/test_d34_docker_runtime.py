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


def test_dockerfile_pins_exact_upstream_tarball_bytes() -> None:
    dockerfile = Path("docker/d34/Dockerfile").read_text(encoding="utf-8")
    assert "codeload.github.com/microsoft/qlib/tar.gz/${QLIB_COMMIT}" in dockerfile
    assert "codeload.github.com/microsoft/RD-Agent/tar.gz/${RDAGENT_COMMIT}" in dockerfile
    assert "016ec8f5d415e4b4251412e60a395154332cb2db0239c20a522b04de6198131f" in dockerfile
    assert "c3af9e4f153a5ef407deaa2a04b281be62d3fd7c380e2ca647d30cec5b7bc07c" in dockerfile
    assert "sha256sum --check" in dockerfile


def test_dockerfile_installs_headless_worker_dependencies_not_notebook_stacks() -> None:
    dockerfile = Path("docker/d34/Dockerfile").read_text(encoding="utf-8")

    assert (
        "python -m pip install --no-build-isolation --no-deps /opt/qlib /opt/rdagent" in dockerfile
    )
    assert '"litellm==1.96.0"' in dockerfile
    assert '"setuptools-scm==9.2.2"' in dockerfile
    assert '"mlflow-skinny==3.1.4"' in dockerfile
    assert '"gym==0.26.2"' in dockerfile
    assert '"cvxpy==1.7.5"' in dockerfile
    assert '"fuzzywuzzy==0.18.0"' in dockerfile
    assert '"psutil==7.2.2"' in dockerfile
    assert '"duckdb==1.5.5"' in dockerfile
    assert '"futu-api==10.9.6908"' in dockerfile
    assert '"typer==0.27.1"' in dockerfile
    assert '"pyarrow==24.0.0"' in dockerfile
    assert '"docker==7.2.0"' in dockerfile
    assert "PYTHONPATH=/opt/rdagent" in dockerfile
    assert "python -m pip install --no-deps /opt/platform" in dockerfile
    assert "python -m pip install /opt/qlib" not in dockerfile
    assert '"jupyter"' not in dockerfile
    assert '"streamlit"' not in dockerfile
    assert '"azureml-mlflow"' not in dockerfile


def test_qlib_smoke_uses_pinned_dump_bin_argument_contract() -> None:
    entrypoint = Path("docker/d34/container_entrypoint.py").read_text(encoding="utf-8")

    assert '"--data_path"' in entrypoint
    assert '"--csv_path"' not in entrypoint
    assert "backtest_daily" in entrypoint
    assert "TopkDropoutStrategy" in entrypoint
    assert "periods=16" in entrypoint
    assert "start, end = days[0], days[-2]" in entrypoint
