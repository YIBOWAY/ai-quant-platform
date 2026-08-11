"""Local persistent-worker CLI for D-34."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from quant_system.config.settings import load_settings
from quant_system.d34.docker_runtime import D34DockerConfig, D34DockerRuntime
from quant_system.d34.paper_cycle import run_d34_paper_cycle
from quant_system.d34.platform_replay import run_platform_replay
from quant_system.d34.preflight import run_d34_preflight
from quant_system.d34.worker import D34CycleWorker, D34WorkerConfig
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.execution.d34_canary_activation import (
    D34CanaryActivationRequest,
    activate_d34_paper_canary,
)
from quant_system.execution.d34_canary_monitor import maintain_d34_canaries
from quant_system.execution.paper_strategy_operations import PaperStrategyOperationsRunner
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.price_source import PaperPriceSource
from quant_system.hermes.d34_job_authority import PostgresJobAuthority
from quant_system.hermes.d34_mandate_authority import PostgresMandateAuthority
from quant_system.hermes.d34_registry_authority import PostgresRegistryAuthority
from quant_system.hermes.d34_safety_authority import D34SafetyAuthority

d34_app = typer.Typer(help="Run D-34 autonomous paper-research operations.")
_DEFAULT_PLATFORM_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_HQA_ROOT = Path(
    os.environ.get("QS_D34_HQA_ROOT", "/Users/sunyibo/programs/Hermes-quant-agent")
)


class D34EnvConfigError(RuntimeError):
    """Stable owner-actionable blocker emitted at the D-34 CLI seam."""

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
    required_models = {"LITELLM_CHAT_MODEL", "LITELLM_EMBEDDING_MODEL"}
    configured_models: set[str] = set()
    configured_names: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        name = key.strip()
        configured_names.add(name)
        if name in required_models and value.strip():
            configured_models.add(name)
    if configured_models != required_models:
        raise D34EnvConfigError("d34_env_models_required")
    if any(
        name.startswith("LITELLM_")
        and name.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        for name in configured_names
    ):
        raise D34EnvConfigError("d34_env_logged_secret_forbidden")
    return candidate.resolve()


def build_local_worker(
    *,
    platform_root: Path,
    hqa_root: Path,
    workspace_root: Path,
    cache_root: Path,
    image_ref: str,
    workspace_id: str,
    worker_id: str,
) -> D34CycleWorker:
    settings = load_settings()
    workspace_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    config = D34WorkerConfig(
        workspace_root=workspace_root.resolve(),
        platform_root=platform_root.resolve(),
        hqa_root=hqa_root.resolve(),
        cache_root=cache_root.resolve(),
        workspace_id=workspace_id,
        worker_id=worker_id,
    )
    docker = D34DockerRuntime(
        D34DockerConfig(
            image_ref=image_ref,
            workspace_root=config.workspace_root,
            platform_root=config.platform_root,
            hqa_root=config.hqa_root,
            cache_root=config.cache_root,
            env_file=_existing_env_file(config.platform_root),
            timeout_seconds=7200,
        )
    )
    futu, source = build_ohlcv_provider(settings, requested="futu")
    if source != "futu" or getattr(futu, "provider_name", None) != "futu":
        raise RuntimeError("d34_futu_provider_unavailable")
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(api_runs_dir, settings=settings)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    registry = PostgresRegistryAuthority(settings)
    price_source = PaperPriceSource(settings)
    paper_operations = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=price_source,
    )

    def replay(*, qlib_receipt, **kwargs):
        _ = qlib_receipt
        return run_platform_replay(**kwargs)

    def activate_canary(*, artifact, factor_id, artifact_code_path, universe):
        account = account_storage.load()
        if account is None:
            raise RuntimeError("paper_account_missing")
        symbols = sorted(set(universe) | set(account.positions))
        quotes = price_source.get_prices(symbols)
        if set(quotes) != set(symbols) or any(quote.source != "futu" for quote in quotes.values()):
            raise RuntimeError("d34_canary_requires_futu_prices")
        prices = {symbol: quote.price for symbol, quote in quotes.items()}
        _sleeve, canary = activate_d34_paper_canary(
            D34CanaryActivationRequest(
                artifact=artifact,
                factor_id=factor_id,
                artifact_code_path=artifact_code_path,
                universe=tuple(universe),
                provider="futu",
                nav=account.equity(prices),
                account_updated_at=account.updated_at,
                prices=prices,
                price_metadata={
                    symbol: {
                        "source": quote.source,
                        "kind": quote.price_kind,
                        "as_of": quote.as_of,
                    }
                    for symbol, quote in quotes.items()
                },
            ),
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            registry=registry,
        )
        return canary

    def operate_canaries(safety):
        observed_at = datetime.now().astimezone()
        observed = maintain_d34_canaries(
            now=observed_at,
            workspace_id=workspace_id,
            registry=registry,
            sleeve_storage=sleeve_storage,
            price_source=price_source,
        )
        if safety.get("paper_execution_enabled") is True:
            trading = run_d34_paper_cycle(
                now=observed_at,
                sleeve_storage=sleeve_storage,
                runner=paper_operations,
            )
        else:
            trading = {
                "sleeves_checked": 0,
                "signals_generated": 0,
                "executions_created": 0,
                "executions_processed": 0,
                "executions_filled": 0,
                "executions_blocked": 0,
            }
        return {"monitor": observed, "trading": trading}

    return D34CycleWorker(
        config=config,
        mandates=PostgresMandateAuthority(settings),
        jobs=PostgresJobAuthority(settings),
        registry=registry,
        docker_runtime=docker,
        futu_provider=futu,
        platform_replay=replay,
        canary_activator=activate_canary,
        safety_observer=lambda: D34SafetyAuthority(settings).observe(workspace_id=workspace_id),
        canary_operator=operate_canaries,
    )


@d34_app.command("preflight")
def preflight(
    platform_root: Annotated[
        Path,
        typer.Option("--platform-root", help="Platform source checkout mount."),
    ] = _DEFAULT_PLATFORM_ROOT,
    hqa_root: Annotated[
        Path,
        typer.Option("--hqa-root", help="HQA source checkout mount."),
    ] = _DEFAULT_HQA_ROOT,
    workspace_root: Annotated[
        Path | None,
        typer.Option("--workspace-root", help="Durable D-34 data and receipt root."),
    ] = None,
    cache_root: Annotated[
        Path | None,
        typer.Option("--cache-root", help="Durable RD-Agent/Qlib cache root."),
    ] = None,
    image_ref: Annotated[
        str,
        typer.Option("--image-ref", help="Pinned local D-34 image reference."),
    ] = os.environ.get("D34_IMAGE_REF", "hqa-d34-rdagent-qlib:0.1.0"),
    workspace_id: Annotated[str, typer.Option("--workspace-id")] = "default",
) -> None:
    """Prove schema, live isolation, LLM, Qlib, Futu and Docker readiness."""

    settings = load_settings()
    workspace = (workspace_root or settings.data.data_dir / "d34").resolve()
    cache = (cache_root or workspace / "cache").resolve()
    try:
        runtime = D34DockerRuntime(
            D34DockerConfig(
                image_ref=image_ref,
                workspace_root=workspace,
                platform_root=platform_root.resolve(),
                hqa_root=hqa_root.resolve(),
                cache_root=cache,
                env_file=_existing_env_file(platform_root.resolve()),
                timeout_seconds=7200,
            )
        )
        receipt = run_d34_preflight(
            workspace_root=workspace,
            docker_runtime=runtime,
            safety_observer=lambda: D34SafetyAuthority(settings).observe(
                workspace_id=workspace_id
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        typer.echo(
            json.dumps(
                {
                    "contract": "hqa.d34_preflight/v1",
                    "ready": False,
                    "code": str(getattr(exc, "code", type(exc).__name__)),
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(receipt.to_public_dict(), sort_keys=True))


@d34_app.command("worker-once")
def worker_once(
    platform_root: Annotated[
        Path,
        typer.Option("--platform-root", help="Read-only Platform source checkout mount."),
    ] = _DEFAULT_PLATFORM_ROOT,
    hqa_root: Annotated[
        Path,
        typer.Option("--hqa-root", help="Read-only HQA source checkout mount."),
    ] = _DEFAULT_HQA_ROOT,
    workspace_root: Annotated[
        Path | None,
        typer.Option("--workspace-root", help="Durable D-34 data and receipt root."),
    ] = None,
    cache_root: Annotated[
        Path | None,
        typer.Option("--cache-root", help="Durable RD-Agent/Qlib cache root."),
    ] = None,
    image_ref: Annotated[
        str,
        typer.Option("--image-ref", help="Pinned local D-34 image reference."),
    ] = os.environ.get("D34_IMAGE_REF", "hqa-d34-rdagent-qlib:0.1.0"),
    workspace_id: Annotated[str, typer.Option("--workspace-id")] = "default",
    worker_id: Annotated[str, typer.Option("--worker-id")] = "hqa-d34-launchagent",
) -> None:
    settings = load_settings()
    workspace = (workspace_root or settings.data.data_dir / "d34").resolve()
    cache = (cache_root or workspace / "cache").resolve()
    try:
        worker = build_local_worker(
            platform_root=platform_root,
            hqa_root=hqa_root,
            workspace_root=workspace,
            cache_root=cache,
            image_ref=image_ref,
            workspace_id=workspace_id,
            worker_id=worker_id,
        )
        result = worker.run_once()
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        typer.echo(
            json.dumps(
                {
                    "contract": "hqa.d34_worker_result/v1",
                    "status": "failed",
                    "code": str(getattr(exc, "code", type(exc).__name__)),
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from exc
    canary = result.canary
    if hasattr(canary, "to_public_dict"):
        canary = canary.to_public_dict()
    typer.echo(
        json.dumps(
            {
                "contract": "hqa.d34_worker_result/v1",
                "status": result.status,
                "code": result.code,
                "job_id": result.job_id,
                "artifact_id": result.artifact_id,
                "canary": canary,
                "paper_cycle": result.paper_cycle,
            },
            default=str,
            sort_keys=True,
        )
    )
    if result.status in {"failed", "needs_recovery"}:
        raise typer.Exit(code=1)


__all__ = ["build_local_worker", "d34_app"]
