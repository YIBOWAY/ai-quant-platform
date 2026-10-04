"""Research-only one-shot runner for the fixed local D-34 resource envelope."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from quant_system.config.settings import load_settings
from quant_system.d34.docker_runtime import D34DockerConfig, D34DockerRuntime
from quant_system.d34.platform_replay import run_platform_replay
from quant_system.d34.worker import D34CycleWorker, D34WorkerConfig
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.hermes.d34_job_authority import PostgresJobAuthority
from quant_system.hermes.d34_registry_authority import PostgresRegistryAuthority

_DEFAULT_PLATFORM_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_HQA_ROOT = Path(
    os.environ.get("QS_D34_HQA_ROOT", "/Users/sunyibo/programs/Hermes-quant-agent")
)


class D34EnvConfigError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _existing_env_file(repo: Path) -> Path:
    configured = os.environ.get("QS_D34_ENV_FILE", "").strip()
    candidate = Path(configured).expanduser() if configured else repo / "docker/d34/.env"
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as exc:
        raise D34EnvConfigError("d34_env_file_required") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise D34EnvConfigError("d34_env_file_must_be_owner_only")
    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise D34EnvConfigError("d34_env_file_unreadable") from exc
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    if not values.get("LITELLM_CHAT_MODEL"):
        raise D34EnvConfigError("d34_env_models_required")
    if any(
        name.startswith("LITELLM_") and name.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        for name in values
    ):
        raise D34EnvConfigError("d34_env_logged_secret_forbidden")
    openai_key = values.get("OPENAI_API_KEY", "")
    if openai_key in {"", "local-d34-proxy", "changeme", "your-key-here"} or len(
        openai_key
    ) < 16:
        raise D34EnvConfigError("d34_env_openai_key_placeholder")
    api_base = values.get("OPENAI_API_BASE", "")
    if "127.0.0.1" in api_base or "localhost" in api_base:
        raise D34EnvConfigError("d34_env_api_base_unreachable_from_container")
    if not api_base:
        raise D34EnvConfigError("d34_env_api_base_required")
    if "/" not in values["LITELLM_CHAT_MODEL"]:
        raise D34EnvConfigError("d34_env_model_missing_provider_prefix")
    return candidate.resolve()


class _LazyResearchRuntime:
    provider_name = "futu"

    def __init__(self, *, settings, config: D34WorkerConfig, image_ref: str) -> None:
        self._settings = settings
        self._config = config
        self._image_ref = image_ref
        self._docker = None
        self._futu = None

    def _load(self):
        if self._docker is None or self._futu is None:
            docker = D34DockerRuntime(
                D34DockerConfig(
                    image_ref=self._image_ref,
                    workspace_root=self._config.workspace_root,
                    platform_root=self._config.platform_root,
                    hqa_root=self._config.hqa_root,
                    cache_root=self._config.cache_root,
                    env_file=_existing_env_file(self._config.platform_root),
                    timeout_seconds=7200,
                )
            )
            futu, source = build_ohlcv_provider(self._settings, requested="futu")
            if source != "futu" or getattr(futu, "provider_name", None) != "futu":
                raise RuntimeError("d34_futu_provider_unavailable")
            self._docker = docker
            self._futu = futu
        return self._docker, self._futu

    def run(self, **kwargs):
        docker, _futu = self._load()
        return docker.run(**kwargs)

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        _docker, futu = self._load()
        return futu.fetch_ohlcv(symbols, start=start, end=end, interval=interval)

    def replay(self, *, qlib_receipt, **kwargs):
        self._load()
        _ = qlib_receipt
        return run_platform_replay(**kwargs)


def build_local_research_worker(
    *,
    platform_root: Path,
    hqa_root: Path,
    workspace_root: Path,
    data_root: Path,
    cache_root: Path,
    image_ref: str,
    workspace_id: str,
    worker_id: str,
) -> D34CycleWorker:
    settings = load_settings()
    workspace_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    config = D34WorkerConfig(
        workspace_root=workspace_root.resolve(),
        data_root=data_root.resolve(),
        platform_root=platform_root.resolve(),
        hqa_root=hqa_root.resolve(),
        cache_root=cache_root.resolve(),
        workspace_id=workspace_id,
        worker_id=worker_id,
    )
    runtime = _LazyResearchRuntime(settings=settings, config=config, image_ref=image_ref)
    registry = PostgresRegistryAuthority(settings)
    jobs = PostgresJobAuthority(settings)

    def project_running(_job_id: str) -> None:
        from quant_system.execution.assistant_remote import project_terminal_research_results

        project_terminal_research_results(settings, jobs=jobs, registry=registry)

    return D34CycleWorker(
        config=config,
        jobs=jobs,
        registry=registry,
        docker_runtime=runtime,
        futu_provider=runtime,
        platform_replay=runtime.replay,
        research_state_projector=project_running,
    )


def _project_terminal_research_results(settings) -> object:
    from quant_system.execution.assistant_remote import project_terminal_research_results

    return project_terminal_research_results(
        settings,
        jobs=PostgresJobAuthority(settings),
        registry=PostgresRegistryAuthority(settings),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant-system-d34-research")
    parser.add_argument("--platform-root", type=Path, default=_DEFAULT_PLATFORM_ROOT)
    parser.add_argument("--hqa-root", type=Path, default=_DEFAULT_HQA_ROOT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument(
        "--image-ref",
        default=os.environ.get("D34_IMAGE_REF", "hqa-d34-rdagent-qlib:0.1.0"),
    )
    parser.add_argument("--workspace-id", default="default")
    parser.add_argument("--worker-id", default="hqa-d34-research-launchagent")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    data_root = settings.data.data_dir.resolve()
    workspace = (args.workspace_root or data_root / "_runtime" / "d34").resolve()
    cache = (args.cache_root or workspace / "cache").resolve()
    try:
        projection_before = _project_terminal_research_results(settings)
        worker = build_local_research_worker(
            platform_root=args.platform_root,
            hqa_root=args.hqa_root,
            workspace_root=workspace,
            data_root=data_root,
            cache_root=cache,
            image_ref=args.image_ref,
            workspace_id=args.workspace_id,
            worker_id=args.worker_id,
        )
        result = worker.run_once()
        projection_after = _project_terminal_research_results(settings)
        introductions = []
        evaluations = []
        if result.status == "candidate_ready" and result.job_id:
            # The job result and paper activation are already persisted. Descriptive
            # text is optional and runs outside all research/account locks.
            from quant_system.research.collection_catalog import generate_completed_job_introduction

            try:
                introductions = generate_completed_job_introduction(settings, result.job_id)
            except Exception as exc:  # noqa: BLE001 - cannot rewrite a successful research result
                introductions = [{"status": "failed", "error": type(exc).__name__}]
            from quant_system.research.evaluation_service import evaluate_completed_job

            try:
                evaluations = evaluate_completed_job(settings, result.job_id)
            except Exception as exc:  # noqa: BLE001 - quality report is independent of admission
                evaluations = [{"status": "failed", "error": type(exc).__name__}]
        document = {
            "contract": "hqa.d34_research_worker_result/v2",
            "status": result.status,
            "code": result.code,
            "job_id": result.job_id,
            "artifact_id": result.artifact_id,
            "projection_before": projection_before,
            "projection_after": projection_after,
            "introductions": introductions,
            "evaluations": evaluations,
        }
        print(json.dumps(document, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - secret-free process boundary
        print(
            json.dumps(
                {
                    "contract": "hqa.d34_research_worker_result/v2",
                    "status": "failed",
                    "code": str(getattr(exc, "code", type(exc).__name__)),
                    "message": "Research worker failed; inspect its content-addressed receipt.",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["D34EnvConfigError", "build_local_research_worker", "main"]
