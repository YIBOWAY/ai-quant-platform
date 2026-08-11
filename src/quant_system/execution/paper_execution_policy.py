"""One deterministic admission policy for all autonomous paper orders.

D-33 and D-34 have different research authorities, but they share the same
paper account and therefore must not implement independent execution limits.
This module is intentionally pure so the exact decision can be replayed and
stored as an audit receipt before an order plan is made durable.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

DECISION_CONTRACT = "hqa.paper_execution_policy_decision/v1"
POLICY_VERSION = "paper-execution-policy/v1"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PaperExecutionLimits:
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
class PaperExecutionBatch:
    source: str
    workspace_id: str
    account_id: str
    sleeve_id: str
    orders: Sequence[Mapping[str, Any]]
    sleeve_equity: float
    nav: float
    aggregate_symbol_values: Mapping[str, float]
    emergency_stop: bool
    paper_execution_enabled: bool
    mandate_active: bool = False
    mandate_paper_execution_allowed: bool = False


@dataclass(frozen=True)
class PaperExecutionDecision:
    source: str
    allowed: bool
    blockers: tuple[str, ...]
    projected_symbol_values: dict[str, float]
    policy_digest: str
    decision_digest: str
    contract: str = DECISION_CONTRACT

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "source": self.source,
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "projected_symbol_values": self.projected_symbol_values,
            "policy_digest": self.policy_digest,
            "decision_digest": self.decision_digest,
        }


class PaperExecutionPolicy:
    """Evaluate a complete autonomous order batch without side effects."""

    def __init__(self, limits: PaperExecutionLimits | Any | None = None) -> None:
        self.limits = limits or PaperExecutionLimits()
        self.policy_digest = _digest(
            {
                "contract": DECISION_CONTRACT,
                "policy_version": POLICY_VERSION,
                "limits": {
                    field: getattr(self.limits, field)
                    for field in asdict(PaperExecutionLimits())
                },
            }
        )

    @staticmethod
    def _append_once(blockers: list[str], code: str) -> None:
        if code not in blockers:
            blockers.append(code)

    def evaluate_batch(self, batch: PaperExecutionBatch) -> PaperExecutionDecision:
        blockers: list[str] = []
        source = str(batch.source).strip().lower()
        if source not in {"d33", "d34"}:
            self._append_once(blockers, "unsupported_automation_source")
        if batch.emergency_stop is True:
            self._append_once(blockers, "emergency_stop_active")
        if batch.paper_execution_enabled is not True:
            self._append_once(blockers, "paper_execution_disabled")
        if source == "d34":
            if batch.mandate_active is not True:
                self._append_once(blockers, "d34_mandate_inactive")
            if batch.mandate_paper_execution_allowed is not True:
                self._append_once(
                    blockers,
                    "d34_mandate_paper_execution_not_allowed",
                )

        for field, code in (
            (batch.workspace_id, "invalid_workspace_id"),
            (batch.account_id, "invalid_account_id"),
            (batch.sleeve_id, "invalid_sleeve_id"),
        ):
            if type(field) is not str or not field.strip():
                self._append_once(blockers, code)

        try:
            sleeve_equity = float(batch.sleeve_equity)
        except (TypeError, ValueError):
            sleeve_equity = math.nan
        try:
            nav = float(batch.nav)
        except (TypeError, ValueError):
            nav = math.nan
        if not math.isfinite(sleeve_equity) or sleeve_equity <= 0:
            self._append_once(blockers, "invalid_sleeve_equity")
        if not math.isfinite(nav) or nav <= 0:
            self._append_once(blockers, "invalid_nav")

        projected: dict[str, float] = {}
        aggregate_valid = True
        for raw_symbol, raw_value in batch.aggregate_symbol_values.items():
            symbol = str(raw_symbol).upper().strip()
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                aggregate_valid = False
                continue
            if not symbol or not math.isfinite(value):
                aggregate_valid = False
                continue
            projected[symbol] = value
        if not aggregate_valid:
            self._append_once(blockers, "invalid_aggregate_symbol_values")

        normalized_orders: list[dict[str, str | float]] = []
        for order in batch.orders:
            symbol = str(order.get("symbol", "")).upper().strip()
            try:
                delta = float(order["notional_delta"])
            except (KeyError, TypeError, ValueError):
                self._append_once(blockers, "invalid_order_notional")
                continue
            if not symbol or not math.isfinite(delta):
                self._append_once(blockers, "invalid_order_notional")
                continue
            normalized_orders.append({"symbol": symbol, "notional_delta": delta})
            if abs(delta) > float(self.limits.max_order_value) + 1e-9:
                self._append_once(blockers, "order_value_limit")
            if (
                math.isfinite(sleeve_equity)
                and sleeve_equity > 0
                and abs(delta)
                > sleeve_equity * float(self.limits.max_sleeve_symbol_fraction) + 1e-9
            ):
                self._append_once(blockers, "sleeve_symbol_limit")
            projected[symbol] = projected.get(symbol, 0.0) + delta
            if (
                math.isfinite(nav)
                and nav > 0
                and abs(projected[symbol])
                > nav * float(self.limits.max_aggregate_symbol_nav_fraction) + 1e-9
            ):
                self._append_once(blockers, "aggregate_symbol_limit")

        projected = dict(sorted(projected.items()))
        decision_payload = {
            "contract": DECISION_CONTRACT,
            "source": source,
            "workspace_id": batch.workspace_id,
            "account_id": batch.account_id,
            "sleeve_id": batch.sleeve_id,
            "orders": normalized_orders,
            "sleeve_equity": sleeve_equity,
            "nav": nav,
            "aggregate_symbol_values": dict(
                sorted(
                    (str(key).upper().strip(), float(value))
                    for key, value in batch.aggregate_symbol_values.items()
                    if str(key).strip()
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                )
            ),
            "emergency_stop": batch.emergency_stop,
            "paper_execution_enabled": batch.paper_execution_enabled,
            "mandate_active": batch.mandate_active,
            "mandate_paper_execution_allowed": (
                batch.mandate_paper_execution_allowed
            ),
            "blockers": blockers,
            "projected_symbol_values": projected,
            "policy_digest": self.policy_digest,
        }
        return PaperExecutionDecision(
            source=source,
            allowed=not blockers,
            blockers=tuple(blockers),
            projected_symbol_values=projected,
            policy_digest=self.policy_digest,
            decision_digest=_digest(decision_payload),
        )


AutomationSource = Literal["d33", "d34"]

__all__ = [
    "DECISION_CONTRACT",
    "POLICY_VERSION",
    "AutomationSource",
    "PaperExecutionBatch",
    "PaperExecutionDecision",
    "PaperExecutionLimits",
    "PaperExecutionPolicy",
]
