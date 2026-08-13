"""Conservative limits for automatically promoted paper-only factors.

The module is intentionally pure.  Durable promote/demote quotas live in the
029 PostgreSQL authority; these helpers guard the sleeve and order boundaries.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_system.execution.paper_execution_policy import (
    PaperExecutionBatch,
    PaperExecutionDecision,
    PaperExecutionPolicy,
)
from quant_system.execution.paper_strategy_sleeves import StrategySleeve
from quant_system.risk.models import RiskLimits

_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class FactorAutomationLimitError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FactorAutomationLimits:
    max_sleeve_cash: float = 10_000.0
    max_sleeve_nav_fraction: float = 0.01
    max_total_nav_fraction: float = 0.10
    max_daily_promotions: int = 1
    max_daily_demotions: int = 5
    max_daily_loss: float = 0.02
    max_drawdown: float = 0.10
    max_sleeve_symbol_fraction: float = 0.40
    max_aggregate_symbol_nav_fraction: float = 0.05
    max_order_value: float = 10_000.0


@dataclass(frozen=True)
class AutoSleeveAdmission:
    allocated_cash: float
    metadata: dict[str, object]


def _positive_finite(value: float, *, code: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise FactorAutomationLimitError(code)
    return normalized


def _digest(value: str, *, code: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise FactorAutomationLimitError(code)
    return value


def admit_auto_sleeve(
    *,
    nav: float,
    existing_sleeves: Sequence[StrategySleeve],
    factor_id: str,
    manifest_digest: str,
    automation_policy_digest: str,
    requested_cash: float | None = None,
    limits: FactorAutomationLimits | None = None,
) -> AutoSleeveAdmission:
    active_limits = limits or FactorAutomationLimits()
    normalized_nav = _positive_finite(nav, code="invalid_nav")
    if type(factor_id) is not str or not factor_id.strip():
        raise FactorAutomationLimitError("invalid_factor_id")
    normalized_factor = factor_id.strip()
    normalized_manifest = _digest(manifest_digest, code="invalid_manifest_digest")
    normalized_policy = _digest(
        automation_policy_digest,
        code="invalid_automation_policy_digest",
    )
    active = [
        sleeve
        for sleeve in existing_sleeves
        if sleeve.metadata.get("automation_managed") is True
        and sleeve.status.value != "demoted_complete"
    ]
    for sleeve in active:
        if sleeve.metadata.get("factor_id") == normalized_factor:
            raise FactorAutomationLimitError("duplicate_factor")
        if sleeve.metadata.get("manifest_digest") == normalized_manifest:
            raise FactorAutomationLimitError("duplicate_manifest")

    maximum = min(
        active_limits.max_sleeve_cash,
        normalized_nav * active_limits.max_sleeve_nav_fraction,
    )
    allocation = maximum if requested_cash is None else _positive_finite(
        requested_cash,
        code="invalid_sleeve_cash",
    )
    if allocation > maximum + 1e-9:
        raise FactorAutomationLimitError("single_sleeve_cash_limit")
    total = sum(float(sleeve.initial_allocated_cash) for sleeve in active)
    if total + allocation > normalized_nav * active_limits.max_total_nav_fraction + 1e-9:
        raise FactorAutomationLimitError("aggregate_auto_cash_limit")
    return AutoSleeveAdmission(
        allocated_cash=allocation,
        metadata={
            "automation_managed": True,
            "automation_source": "d33",
            "factor_id": normalized_factor,
            "manifest_digest": normalized_manifest,
            "automation_policy_digest": normalized_policy,
            "promotion_scope": "paper_only",
            "reviewer": "auto",
        },
    )


def automation_risk_limits(
    allowed_symbols: Sequence[str],
    *,
    limits: FactorAutomationLimits | None = None,
) -> RiskLimits:
    active = limits or FactorAutomationLimits()
    symbols = [symbol.upper().strip() for symbol in allowed_symbols]
    if not symbols or any(not symbol for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise FactorAutomationLimitError("invalid_allowed_symbols")
    return RiskLimits(
        kill_switch=False,
        max_position_size=active.max_sleeve_symbol_fraction,
        max_daily_loss=active.max_daily_loss,
        max_drawdown=active.max_drawdown,
        max_order_value=active.max_order_value,
        allowed_symbols=symbols,
    )


def evaluate_auto_sleeve_health(
    *,
    equity: float,
    peak_equity: float,
    daily_pnl: float,
    limits: FactorAutomationLimits | None = None,
) -> tuple[str, ...]:
    active = limits or FactorAutomationLimits()
    normalized_equity = _positive_finite(equity, code="invalid_sleeve_equity")
    normalized_peak = _positive_finite(peak_equity, code="invalid_peak_equity")
    normalized_pnl = float(daily_pnl)
    if not math.isfinite(normalized_pnl):
        raise FactorAutomationLimitError("invalid_daily_pnl")
    breaches: list[str] = []
    if normalized_pnl < 0 and abs(normalized_pnl) / normalized_equity >= active.max_daily_loss:
        breaches.append("max_daily_loss")
    drawdown = max(0.0, 1.0 - normalized_equity / normalized_peak)
    if drawdown >= active.max_drawdown:
        breaches.append("max_drawdown")
    return tuple(breaches)


def validate_auto_execution_orders(
    *,
    orders: Sequence[Mapping[str, Any]],
    sleeve_equity: float,
    nav: float,
    aggregate_symbol_values: Mapping[str, float],
    limits: FactorAutomationLimits | None = None,
    source: str = "d33",
    workspace_id: str = "local-default",
    account_id: str = "legacy-paper-account",
    sleeve_id: str = "legacy-auto-sleeve",
    emergency_stop: bool = False,
    paper_execution_enabled: bool = True,
    mandate_active: bool = False,
    mandate_paper_execution_allowed: bool = False,
    hung_observation: bool = False,
) -> PaperExecutionDecision:
    decision = PaperExecutionPolicy(limits or FactorAutomationLimits()).evaluate_batch(
        PaperExecutionBatch(
            source=source,
            workspace_id=workspace_id,
            account_id=account_id,
            sleeve_id=sleeve_id,
            orders=orders,
            sleeve_equity=sleeve_equity,
            nav=nav,
            aggregate_symbol_values=aggregate_symbol_values,
            emergency_stop=emergency_stop,
            paper_execution_enabled=paper_execution_enabled,
            mandate_active=mandate_active,
            mandate_paper_execution_allowed=mandate_paper_execution_allowed,
            hung_observation=hung_observation,
        )
    )
    if not decision.allowed:
        raise FactorAutomationLimitError(decision.blockers[0])
    return decision


__all__ = [
    "AutoSleeveAdmission",
    "FactorAutomationLimitError",
    "FactorAutomationLimits",
    "admit_auto_sleeve",
    "automation_risk_limits",
    "evaluate_auto_sleeve_health",
    "validate_auto_execution_orders",
]
