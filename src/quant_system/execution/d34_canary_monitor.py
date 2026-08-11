"""Price and enforce D-34 canary health without depending on D-33 state."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.execution.d34_canary_control import D34CanaryController
from quant_system.execution.factor_automation_safety import (
    evaluate_auto_sleeve_health,
)
from quant_system.execution.paper_strategy_sleeves import (
    StrategySleeve,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import D34Canary


def _value(canary: D34Canary | Mapping[str, object], field: str) -> object:
    if isinstance(canary, Mapping):
        return canary[field]
    return getattr(canary, field)


def _validate_factor(sleeve: StrategySleeve) -> None:
    code_path = sleeve.metadata.get("artifact_code_path")
    code_digest = sleeve.metadata.get("candidate_code_digest")
    factor_id = sleeve.metadata.get("factor_id")
    if not all(isinstance(item, str) and item for item in (code_path, code_digest, factor_id)):
        raise ValueError("d34_artifact_lineage_invalid")
    load_d34_paper_factor_registry(
        code_path=Path(str(code_path)),
        expected_code_digest=str(code_digest),
        expected_factor_id=str(factor_id),
    )


def _quote_price(quote: object) -> float:
    value = quote.get("price") if isinstance(quote, Mapping) else quote.price  # type: ignore[attr-defined]
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("d34_canary_price_invalid")
    return price


def _quote_source(quote: object) -> str:
    value = quote.get("source") if isinstance(quote, Mapping) else getattr(quote, "source", None)
    return str(value or "")


def maintain_d34_canaries(
    *,
    now: datetime,
    workspace_id: str,
    registry: Any,
    sleeve_storage: Any,
    price_source: Any,
    factor_validator: Callable[[StrategySleeve], None] = _validate_factor,
) -> dict[str, int]:
    """Persist health observations and pause breached canaries, preserving holdings."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("d34_canary_monitor_clock_invalid")
    controller = D34CanaryController(registry=registry, sleeve_storage=sleeve_storage)
    checked = observed = paused = demoted = 0
    day = now.date().isoformat()
    canaries = registry.list_canaries(workspace_id=workspace_id, limit=100)
    for canary in canaries:
        registry_status = str(_value(canary, "status"))
        if registry_status not in {"running", "paused", "demoted", "rolled_back"}:
            continue
        checked += 1
        canary_id = str(_value(canary, "canary_id"))
        sleeve_id = str(_value(canary, "sleeve_id"))
        artifact_id = str(_value(canary, "artifact_id"))
        sleeve = sleeve_storage.load_sleeve(sleeve_id)
        if (
            sleeve.metadata.get("automation_managed") is not True
            or sleeve.metadata.get("automation_source") != "d34"
            or sleeve.metadata.get("artifact_id") != artifact_id
            or sleeve.metadata.get("promotion_scope") != "paper_only"
        ):
            raise ValueError("d34_canary_lineage_invalid")
        if registry_status in {"running", "paused"}:
            try:
                factor_validator(sleeve)
            except (OSError, ValueError) as exc:
                controller.transition(
                    canary_id=canary_id,
                    action="demote",
                    expected_version=int(_value(canary, "version")),
                    reason=str(exc)[:1000] or "d34_artifact_lineage_invalid",
                )
                demoted += 1
                continue

        lots = sleeve_storage.load_sleeve_lots(sleeve_id)
        symbols = sorted({lot.symbol.upper() for lot in lots})
        quotes = price_source.get_prices(symbols) if symbols else {}
        if set(quotes) != set(symbols) or any(
            _quote_source(quotes[symbol]) != "futu" for symbol in symbols
        ):
            raise ValueError("d34_canary_requires_futu_prices")
        prices = {symbol: _quote_price(quotes[symbol]) for symbol in symbols}
        with sleeve_storage.mutation_lock():
            current = sleeve_storage.load_sleeve(sleeve_id)
            current_lots = sleeve_storage.load_sleeve_lots(sleeve_id)
            equity = current.cash + sum(
                lot.quantity * prices[lot.symbol.upper()] for lot in current_lots
            )
            prior_day = current.metadata.get("automation_health_day")
            day_start = (
                float(current.metadata.get("automation_day_start_equity", equity))
                if prior_day == day
                else equity
            )
            peak = max(float(current.metadata.get("automation_peak_equity", equity)), equity)
            daily_pnl = equity - day_start
            drawdown = max(0.0, 1.0 - equity / peak)
            breaches = evaluate_auto_sleeve_health(
                equity=equity,
                peak_equity=peak,
                daily_pnl=daily_pnl,
            )
            current.metadata.update(
                {
                    "automation_health_day": day,
                    "automation_day_start_equity": day_start,
                    "automation_peak_equity": peak,
                    "automation_last_equity": equity,
                    "automation_last_observed_at": now.isoformat(),
                }
            )
            sleeve_storage.save_sleeve(current)

        updated = registry.record_canary_observation(
            canary_id=canary_id,
            expected_version=int(_value(canary, "version")),
            daily_pnl=Decimal(str(round(daily_pnl, 2))),
            drawdown_fraction=Decimal(str(round(drawdown, 9))),
            observation={
                "contract": "hqa.d34_canary_observation/v1",
                "observed_at": now.isoformat(),
                "equity": f"{equity:.2f}",
                "peak_equity": f"{peak:.2f}",
                "daily_pnl": f"{daily_pnl:.2f}",
                "drawdown_fraction": f"{drawdown:.9f}",
                "price_sources": {
                    symbol: str(
                        quotes[symbol].get("source")
                        if isinstance(quotes[symbol], Mapping)
                        else getattr(quotes[symbol], "source", "unknown")
                    )
                    for symbol in symbols
                },
            },
        )
        observed += 1
        if (
            breaches
            and registry_status == "running"
            and current.status == StrategySleeveStatus.RUNNING
        ):
            controller.transition(
                canary_id=canary_id,
                action="pause",
                expected_version=int(_value(updated, "version")),
                reason=",".join(breaches),
            )
            paused += 1
    return {
        "checked": checked,
        "observed": observed,
        "paused": paused,
        "demoted": demoted,
    }


__all__ = ["maintain_d34_canaries"]
