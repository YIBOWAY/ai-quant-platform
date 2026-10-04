from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from quant_system.d34.docker_runtime import (
    D34DockerConfig,
    D34DockerRuntime,
    D34DockerRuntimeError,
)
from quant_system.d34.research_cli import _existing_env_file


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
    job_dir = roots[0] / "jobs/job-123"
    assert not (job_dir / "docker_failure.stderr.txt").exists()
    assert not (job_dir / "docker_failure.stdout.txt").exists()
    assert not (job_dir / "docker_failure.json").exists()


def test_timeout_cleans_exact_container_and_writes_durable_failure_receipt(
    tmp_path: Path,
) -> None:
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
        if command[1] == "run":
            raise subprocess.TimeoutExpired(
                command,
                60,
                output="partial provider output",
                stderr="provider timeout without secret text",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

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

    with pytest.raises(D34DockerRuntimeError) as failure:
        runtime.run(job_id="job-123", command=("research", "--request", "/input.json"))

    assert failure.value.code == "d34_docker_timeout"
    container_name = "hqa-d34-" + hashlib.sha256(b"job-123").hexdigest()[:20]
    assert ["docker", "stop", "--time", "10", container_name] in calls
    assert ["docker", "rm", "--force", container_name] in calls
    receipt = json.loads(
        (roots[0] / "jobs/job-123/docker_failure.json").read_text(encoding="utf-8")
    )
    assert receipt["contract"] == "hqa.d34_docker_failure/v1"
    assert receipt["code"] == "d34_docker_timeout"
    assert receipt["image_digest"] == "sha256:" + "a" * 64
    assert receipt["command"] == ["research", "--request", "/input.json"]
    assert receipt["stdout_bytes"] == len("partial provider output")
    assert receipt["stderr_bytes"] == len("provider timeout without secret text")
    assert "partial provider output" not in json.dumps(receipt)
    stdout_path = roots[0] / "jobs/job-123/docker_failure.stdout.txt"
    stderr_path = roots[0] / "jobs/job-123/docker_failure.stderr.txt"
    assert stdout_path.read_text(encoding="utf-8") == "partial provider output"
    assert stderr_path.read_text(encoding="utf-8") == "provider timeout without secret text"
    assert receipt["stdout_file"] == "docker_failure.stdout.txt"
    assert receipt["stderr_file"] == "docker_failure.stderr.txt"
    assert receipt["stdout_truncated"] is False
    assert receipt["stderr_truncated"] is False


def test_oom_exit_cleans_exact_container_and_records_returncode(tmp_path: Path) -> None:
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
        if command[1] == "run":
            raise subprocess.CalledProcessError(
                137,
                command,
                output="partial research output",
                stderr="Killed",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

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

    with pytest.raises(D34DockerRuntimeError) as failure:
        runtime.run(job_id="job-oom", command=("research", "--request", "/input.json"))

    assert failure.value.code == "d34_docker_failed"
    container_name = "hqa-d34-" + hashlib.sha256(b"job-oom").hexdigest()[:20]
    assert ["docker", "rm", "--force", container_name] in calls
    receipt = json.loads(
        (roots[0] / "jobs/job-oom/docker_failure.json").read_text(encoding="utf-8")
    )
    assert receipt["code"] == "d34_docker_failed"
    assert receipt["returncode"] == 137
    assert receipt["stdout_bytes"] == len("partial research output")
    assert receipt["stderr_bytes"] == len("Killed")
    assert "partial research output" not in json.dumps(receipt)
    assert "Killed" not in json.dumps(receipt)
    assert (roots[0] / "jobs/job-oom/docker_failure.stdout.txt").read_text(
        encoding="utf-8"
    ) == "partial research output"
    assert (roots[0] / "jobs/job-oom/docker_failure.stderr.txt").read_text(
        encoding="utf-8"
    ) == "Killed"
    assert receipt["stdout_file"] == "docker_failure.stdout.txt"
    assert receipt["stderr_file"] == "docker_failure.stderr.txt"
    assert receipt["stdout_truncated"] is False
    assert receipt["stderr_truncated"] is False


def test_failed_container_clips_long_streams_to_head_and_tail(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for root in roots:
        root.mkdir()
    stdout = ("OUT" * 2000) + "STDOUT_TAIL"
    stderr = ("ERR" * 2000) + "STDERR_TAIL"

    def run(command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="sha256:" + "a" * 64 + "\n",
                stderr="",
            )
        if command[1] == "run":
            raise subprocess.CalledProcessError(
                1,
                command,
                output=stdout,
                stderr=stderr,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

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

    with pytest.raises(D34DockerRuntimeError) as failure:
        runtime.run(job_id="job-long", command=("research", "--request", "/input.json"))

    assert failure.value.code == "d34_docker_failed"
    job_dir = roots[0] / "jobs/job-long"
    receipt = json.loads((job_dir / "docker_failure.json").read_text(encoding="utf-8"))
    stdout_clip = (job_dir / "docker_failure.stdout.txt").read_text(encoding="utf-8")
    stderr_clip = (job_dir / "docker_failure.stderr.txt").read_text(encoding="utf-8")
    assert receipt["stdout_truncated"] is True
    assert receipt["stderr_truncated"] is True
    assert receipt["stdout_file"] == "docker_failure.stdout.txt"
    assert receipt["stderr_file"] == "docker_failure.stderr.txt"
    assert stdout_clip.startswith("OUT")
    assert stdout_clip.endswith("STDOUT_TAIL")
    assert "<<<truncated" in stdout_clip
    assert stderr_clip.startswith("ERR")
    assert stderr_clip.endswith("STDERR_TAIL")
    assert "<<<truncated" in stderr_clip
    assert stdout not in json.dumps(receipt)
    assert stderr not in json.dumps(receipt)


def test_runtime_records_repository_changes_without_resetting_them(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for root in roots:
        root.mkdir()
    for root in roots[1:3]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "d34-test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "D34 Test"], check=True
        )
        (root / "tracked.txt").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)

    def run(command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="sha256:" + "a" * 64 + "\n",
                stderr="",
            )
        if command[1] == "run":
            (roots[1] / "tracked.txt").write_text("changed by container\n", encoding="utf-8")
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

    receipt = runtime.run(job_id="job-dirty-audit", command=("versions",))

    assert (roots[1] / "tracked.txt").read_text(encoding="utf-8") == "changed by container\n"
    assert receipt.repository_changes[0]["repository"] == "platform"
    assert receipt.repository_changes[0]["changed_during_job"] is True
    assert receipt.repository_changes[1]["repository"] == "hqa"
    assert receipt.repository_changes[1]["changed_during_job"] is False
    anomaly = json.loads(
        (roots[0] / "jobs/job-dirty-audit/repository_anomaly.json").read_text(
            encoding="utf-8"
        )
    )
    assert anomaly["contract"] == "hqa.d34_repository_anomaly/v1"
    recorded_diff = anomaly["repositories"][0]["after"]["diff"]
    assert recorded_diff.startswith("diff --git a/tracked.txt b/tracked.txt\n")
    assert "-clean\n+changed by container\n" in recorded_diff


@pytest.mark.parametrize("unsafe_kind", ["world_readable", "symlink"])
def test_runtime_rejects_non_owner_only_provider_env(
    tmp_path: Path, unsafe_kind: str
) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for root in roots:
        root.mkdir()
    owner_env = tmp_path / "d34.env"
    owner_env.write_text("D34_TEST_VALUE=not-a-secret\n", encoding="utf-8")
    owner_env.chmod(0o600 if unsafe_kind == "symlink" else 0o644)
    configured = owner_env
    if unsafe_kind == "symlink":
        configured = tmp_path / "d34-link.env"
        configured.symlink_to(owner_env)

    runtime = D34DockerRuntime(
        D34DockerConfig(
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
            env_file=configured,
            timeout_seconds=60,
        ),
        process_runner=lambda *_args, **_kwargs: pytest.fail(
            "unsafe provider env reached Docker"
        ),
    )

    with pytest.raises(D34DockerRuntimeError, match="Docker research request is invalid"):
        runtime.run(job_id="job-123", command=("versions",))


def test_worker_requires_only_explicit_owner_only_chat_provider_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_file_required"):
        _existing_env_file(repo)

    configured.write_text(
        "LITELLM_CHAT_MODEL=openai/test-chat\n"
        "OPENAI_API_KEY=diag-placeholder-key-not-for-llm\n"
        "OPENAI_API_BASE=http://host.docker.internal:8645/v1\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)

    assert _existing_env_file(repo) == configured.resolve()


def test_worker_rejects_owner_env_without_explicit_chat_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "OPENAI_API_KEY=not-a-real-secret\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_models_required"):
        _existing_env_file(repo)


def test_worker_rejects_secrets_in_rdagent_logged_litellm_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "LITELLM_CHAT_MODEL=test-chat\n"
        "LITELLM_CHAT_OPENAI_API_KEY=must-not-reach-logs\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_logged_secret_forbidden"):
        _existing_env_file(repo)


def test_worker_rejects_example_placeholder_openai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "LITELLM_CHAT_MODEL=grok-4.6\n"
        "OPENAI_API_KEY=local-d34-proxy\n"
        "OPENAI_API_BASE=http://host.docker.internal:8645/v1\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_openai_key_placeholder"):
        _existing_env_file(repo)


def test_worker_rejects_loopback_openai_base_from_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "LITELLM_CHAT_MODEL=grok-4.6\n"
        "OPENAI_API_KEY=diag-placeholder-key-not-for-llm\n"
        "OPENAI_API_BASE=http://127.0.0.1:8645/v1\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_api_base_unreachable_from_container"):
        _existing_env_file(repo)


def test_owner_env_template_uses_pinned_rdagent_litellm_model_names() -> None:
    template = Path("docker/d34/.env.example").read_text(encoding="utf-8")

    assert "LITELLM_CHAT_MODEL=openai/grok-4.6" in template
    assert "provider prefix" in template
    assert "LITELLM_EMBEDDING_MODEL=" not in template
    assert "\nCHAT_MODEL=" not in template
    assert "OPENAI_API_KEY=" in template
    assert "OPENAI_API_BASE=http://host.docker.internal:8645/v1" in template
    assert "local-d34-proxy" not in template
    assert "127.0.0.1:8645" not in template
    assert "LITELLM_MAX_RETRY=3" in template
    assert "LITELLM_RETRY_WAIT_SECONDS=2" in template
    assert "LITELLM_LOG_LLM_CHAT_CONTENT=false" in template
    assert "LITELLM_PROXY_API_KEY=" not in template
    assert "LITELLM_PROXY_API_BASE=" not in template
    assert "\nMAX_RETRY=" not in template
    assert "\nRETRY_WAIT_SECONDS=" not in template
    assert "\nLOG_LLM_CHAT_CONTENT=" not in template


def test_failure_sidecar_redacts_env_file_secrets_before_persist(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("workspace", "platform", "hqa", "cache")]
    for root in roots:
        root.mkdir()
    secret = "sk-test-literal-secret-value"
    token = "tok-extra-secret-value"
    env_file = tmp_path / "d34.env"
    env_file.write_text(
        f"OPENAI_API_KEY={secret}\n"
        f"HERMES_API_TOKEN={token}\n"
        "OPENAI_API_BASE=http://host.docker.internal:8645/v1\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    stderr = (
        f"LiteLLM_Params: api_key='{secret}', extra_token={token}, model=grok-4.6\n"
    )

    def run(command, **kwargs):
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="sha256:" + "a" * 64 + "\n",
                stderr="",
            )
        if command[1] == "run":
            raise subprocess.CalledProcessError(
                1,
                command,
                output="research started",
                stderr=stderr,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    runtime = D34DockerRuntime(
        D34DockerConfig(
            image_ref="hqa-d34-rdagent-qlib:0.1.0",
            workspace_root=roots[0],
            platform_root=roots[1],
            hqa_root=roots[2],
            cache_root=roots[3],
            env_file=env_file,
            timeout_seconds=60,
        ),
        process_runner=run,
    )

    with pytest.raises(D34DockerRuntimeError) as failure:
        runtime.run(job_id="job-secret", command=("research", "--request", "/input.json"))

    assert failure.value.code == "d34_docker_failed"
    job_dir = roots[0] / "jobs/job-secret"
    persisted = (job_dir / "docker_failure.stderr.txt").read_text(encoding="utf-8")
    receipt = json.loads((job_dir / "docker_failure.json").read_text(encoding="utf-8"))
    assert secret not in persisted
    assert token not in persisted
    assert persisted.count("<redacted>") == 2
    redacted = stderr.replace(secret, "<redacted>").replace(token, "<redacted>")
    assert receipt["stderr_digest"] == hashlib.sha256(redacted.encode("utf-8")).hexdigest()
    assert receipt["redacted"] is True
    assert secret not in json.dumps(receipt)
    assert token not in json.dumps(receipt)


def test_worker_accepts_openai_compatible_model_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "LITELLM_CHAT_MODEL=openai/grok-4.6\n"
        "OPENAI_API_KEY=diag-placeholder-key-not-for-llm\n"
        "OPENAI_API_BASE=http://host.docker.internal:8645/v1\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    assert _existing_env_file(repo) == configured.resolve()


def test_worker_rejects_model_without_provider_prefix_when_api_base_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "platform"
    repo.mkdir()
    configured = tmp_path / "owner-d34.env"
    configured.write_text(
        "LITELLM_CHAT_MODEL=grok-4.6\n"
        "OPENAI_API_KEY=diag-placeholder-key-not-for-llm\n"
        "OPENAI_API_BASE=http://host.docker.internal:8645/v1\n",
        encoding="utf-8",
    )
    configured.chmod(0o600)
    monkeypatch.setenv("QS_D34_ENV_FILE", str(configured))

    with pytest.raises(RuntimeError, match="d34_env_model_missing_provider_prefix"):
        _existing_env_file(repo)


def test_llm_smoke_uses_rdagent_portable_json_mode() -> None:
    entrypoint = Path("docker/d34/container_entrypoint.py").read_text(encoding="utf-8")

    assert "json_mode=True" in entrypoint
    assert "response_format=JsonAnswer" not in entrypoint


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
    assert (
        "python -m pip install --no-build-isolation --no-deps /opt/platform"
        in dockerfile
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
    assert "python -m pip install /opt/qlib" not in dockerfile
    assert '"jupyter"' not in dockerfile
    assert '"streamlit"' not in dockerfile
    assert '"azureml-mlflow"' not in dockerfile


def test_docker_build_context_contains_only_the_python_platform_package() -> None:
    dockerfile = Path("docker/d34/Dockerfile").read_text(encoding="utf-8")
    dockerignore = Path("docker/d34/Dockerfile.dockerignore").read_text(
        encoding="utf-8"
    )

    assert "COPY src/quant_system /opt/platform/src/quant_system" in dockerfile
    assert "COPY src /opt/platform/src" not in dockerfile
    assert "!src/quant_system/**" in dockerignore
    assert "!src/**" not in dockerignore


def test_qlib_smoke_uses_pinned_dump_bin_argument_contract() -> None:
    entrypoint = Path("docker/d34/container_entrypoint.py").read_text(encoding="utf-8")

    assert '"--data_path"' in entrypoint
    assert '"--csv_path"' not in entrypoint
    assert "backtest_daily" in entrypoint
    assert "TopkDropoutStrategy" in entrypoint
    assert "periods=16" in entrypoint
    assert "start, end = days[0], days[-2]" in entrypoint
