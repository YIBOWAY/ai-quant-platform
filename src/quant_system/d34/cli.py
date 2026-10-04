"""Local persistent-worker CLI for D-34."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

import typer

from quant_system.config.settings import load_settings
from quant_system.d34.paper_cycle import (
    SHANGHAI,
    PaperCycleDryPlanner,
    plan_d34_paper_cycle,
    run_d34_paper_cycle,
)
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.execution.paper_observation_safety import (
    observe_paper_emergency_stop,
)
from quant_system.execution.paper_strategy_operations import PaperStrategyOperationsRunner
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.price_source import PaperPriceSource

d34_app = typer.Typer(help="Run D-34 autonomous paper-research operations.")


@d34_app.callback()
def d34() -> None:
    """Keep the installed ``d34 paper-cycle`` command group stable."""


def _receipt_scalar(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _paper_cycle_signal_outcomes(
    sleeve_storage: PaperStrategySleeveStorage,
    *,
    signal_date: str,
) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "generated": 0,
        "data_unavailable": 0,
        "invalid": 0,
        "read_failed": 0,
        "provider_error_codes": [],
    }
    provider_codes: set[str] = set()
    for sleeve in sleeve_storage.list_sleeves():
        metadata = getattr(sleeve, "metadata", None) or {}
        raw_sleeve_status = getattr(sleeve, "status", None)
        sleeve_status = str(getattr(raw_sleeve_status, "value", raw_sleeve_status) or "").lower()
        if (
            metadata.get("automation_managed") is not True
            or metadata.get("automation_source") != "d34"
            or sleeve_status != "running"
        ):
            continue
        try:
            signals = sleeve_storage.load_signals(sleeve.sleeve_id)
        except Exception:  # noqa: BLE001 - failed sleeve must not hide healthy cycle receipts
            counts["read_failed"] += 1
            continue
        for signal in signals:
            if str(getattr(signal, "signal_date", "")) != signal_date:
                continue
            raw_status = getattr(signal, "status", None)
            status = str(getattr(raw_status, "value", raw_status) or "").lower()
            if status in ("generated", "data_unavailable", "invalid"):
                counts[status] += 1
            signal_metadata = getattr(signal, "metadata", None) or {}
            provider_error = signal_metadata.get("provider_error")
            if isinstance(provider_error, dict) and provider_error.get("code"):
                provider_codes.add(str(provider_error["code"]))
    counts["provider_error_codes"] = sorted(provider_codes)
    return counts


@d34_app.command("paper-cycle")
def paper_cycle(
    workspace_id: Annotated[str, typer.Option("--workspace-id")] = "default",
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
) -> None:
    """Run only the digest-gated paper observation cycle for hung sleeves.

    This is the observation-day driver. It never enqueues research jobs,
    activates canaries, consults a mandate, or touches docker/LLM; the
    research factory switch stays separate. Sleeves must pass the hung
    observation gate (digest-bound, running, non-fossil) to do anything.
    """
    if as_of is not None and dry_run is not True:
        typer.echo(
            json.dumps(
                {
                    "contract": "hqa.d34_paper_cycle/v1",
                    "code": "as_of_requires_dry_run",
                    "message": "--as-of is only allowed together with --dry-run",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2)
    settings = load_settings()
    # The observation gate is the platform safety contract plus emergency
    # stop — deliberately NOT the research factory's mandate-coupled
    # paper_execution_enabled. Per-sleeve fills still require the digest
    # bound hung-observation gate inside the runner.
    safety_cfg = getattr(settings, "safety", None)
    emergency = observe_paper_emergency_stop(settings, workspace_id=workspace_id)
    emergency_active = emergency.get("active") is True
    gate = {
        "contract": "hung_observation",
        "paper_trading": getattr(safety_cfg, "paper_trading", False) is True,
        "live_trading_enabled": getattr(safety_cfg, "live_trading_enabled", None),
        "paper_observation_enabled": (
            getattr(safety_cfg, "paper_observation_enabled", False) is True
        ),
        "emergency_stop_active": emergency_active,
        "research_factory_gate": "ignored_by_design",
    }
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(api_runs_dir, settings=settings)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    paper_operations = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=PaperPriceSource(settings),
    )
    now = datetime.now().astimezone()
    if as_of is not None:
        try:
            parsed = datetime.fromisoformat(as_of)
        except ValueError as exc:
            typer.echo(
                json.dumps(
                    {
                        "contract": "hqa.d34_paper_cycle/v1",
                        "code": "as_of_invalid",
                        "message": str(exc),
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(code=2) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            typer.echo(
                json.dumps(
                    {
                        "contract": "hqa.d34_paper_cycle/v1",
                        "code": "as_of_timezone_required",
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(code=2)
        now = parsed
    if dry_run:
        planner = PaperCycleDryPlanner(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        )
        plan = plan_d34_paper_cycle(
            now=now,
            sleeve_storage=sleeve_storage,
            runner=paper_operations,
            dry_run=True,
            planner=planner,
            paper_costs=getattr(settings, "paper_account", None),
        )
        typer.echo(
            json.dumps(
                {
                    "contract": "hqa.d34_paper_cycle/v1",
                    "as_of": now.isoformat(),
                    "status": "dry_run",
                    "workspace_id": workspace_id,
                    "gate": {key: _receipt_scalar(value) for key, value in gate.items()},
                    "plan": plan,
                },
                sort_keys=True,
                default=str,
            )
        )
        return
    gate_open = (
        gate["paper_trading"]
        and gate["live_trading_enabled"] is not True
        and gate["paper_observation_enabled"]
        and not emergency_active
    )
    if gate_open:
        trading = run_d34_paper_cycle(
            now=now,
            sleeve_storage=sleeve_storage,
            runner=paper_operations,
        )
        signal_outcomes = _paper_cycle_signal_outcomes(
            sleeve_storage,
            signal_date=now.astimezone(SHANGHAI).date().isoformat(),
        )
        if trading.get("sleeves_failed", 0) or signal_outcomes["read_failed"]:
            status = "partial_failed"
        elif signal_outcomes["data_unavailable"] or signal_outcomes["invalid"]:
            status = "data_unavailable"
        else:
            status = "ok"
    else:
        trading = {
            "sleeves_checked": 0,
            "signals_generated": 0,
            "executions_created": 0,
            "executions_processed": 0,
            "executions_filled": 0,
            "executions_blocked": 0,
            "executions_missed_window": 0,
        }
        signal_outcomes = {"generated": 0, "data_unavailable": 0, "invalid": 0, "read_failed": 0, "provider_error_codes": []}
        status = "blocked"
    typer.echo(
        json.dumps(
            {
                "contract": "hqa.d34_paper_cycle/v1",
                "as_of": now.isoformat(),
                "status": status,
                "calendar_ran": gate_open,
                "signal_outcomes": signal_outcomes,
                "workspace_id": workspace_id,
                "gate": {key: _receipt_scalar(value) for key, value in gate.items()},
                "trading": trading,
            },
            sort_keys=True,
        )
    )


__all__ = ["d34_app"]
