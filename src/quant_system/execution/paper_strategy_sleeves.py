from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from quant_system.execution.account import DEFAULT_ACCOUNT_ID, PaperAccount

MANUAL_SLEEVE_ID = "manual"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CashAllocationError(ValueError):
    """Raised when sleeve cash allocation would violate account cash ownership."""


class InsufficientSleeveLotQuantity(ValueError):
    """Raised when a sell asks one sleeve to use another sleeve's lot."""


class StrategyExecutionPlanError(ValueError):
    """Raised when a strategy signal cannot be promoted to an execution plan."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class StrategySleeveMode(StrEnum):
    SIGNAL_ONLY = "signal_only"
    ALLOCATED = "allocated"


class StrategySleeveStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    QUARANTINED_HOLD = "quarantined_hold"
    FLATTENED = "flattened"
    TRANSFERRED = "transferred"
    MANUALLY_ACCEPTED = "manually_accepted"
    DEMOTED_COMPLETE = "demoted_complete"


class SignalStatus(StrEnum):
    GENERATED = "generated"
    DATA_UNAVAILABLE = "data_unavailable"
    INVALID = "invalid"


class StrategyExecutionStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    MISSED_WINDOW = "missed_window"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StrategyConfig(BaseModel):
    """Versioned strategy configuration used as the input to a sleeve."""

    TRADING_LOGIC_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "strategy_id",
            "universe_id",
            "symbols",
            "factor_ids",
            "weights",
            "lookback",
            "top_n",
            "rebalance_frequency",
            "max_weight_per_symbol",
            "min_order_value",
            "data_provider",
            "execution_timing",
        }
    )
    EDITABLE_IN_PLACE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "description", "tags", "archived", "metadata"}
    )

    strategy_config_id: str
    version: int = Field(default=1, ge=1)
    name: str
    description: str = ""
    strategy_id: str
    universe_id: str | None = None
    symbols: list[str] = Field(default_factory=list)
    factor_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    rebalance_frequency: str = "daily"
    max_weight_per_symbol: float = Field(default=1.0, gt=0)
    min_order_value: float = Field(default=0.0, ge=0)
    data_provider: str = "futu"
    execution_timing: str = "next_open"
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    archived: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(cls, **data: Any) -> StrategyConfig:
        payload = dict(data)
        payload.setdefault("strategy_config_id", f"strategy-config-{uuid.uuid4().hex[:12]}")
        payload.setdefault("version", 1)
        return cls.model_validate(payload)

    def new_version(self, **updates: Any) -> StrategyConfig:
        payload = self.model_dump(mode="json")
        payload.update(updates)
        payload["version"] = self.version + 1
        payload["created_at"] = self.created_at
        payload["updated_at"] = _utc_now_iso()
        return StrategyConfig.model_validate(payload)


class StrategySleeve(BaseModel):
    """An isolated strategy cash segment under the persistent paper account."""

    sleeve_id: str
    account_id: str = DEFAULT_ACCOUNT_ID
    strategy_config_id: str
    strategy_config_version: int = Field(ge=1)
    mode: StrategySleeveMode
    status: StrategySleeveStatus = StrategySleeveStatus.RUNNING
    initial_allocated_cash: float = Field(default=0.0, ge=0)
    cash: float = Field(default=0.0, ge=0)
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    paused_at: str | None = None
    stopped_at: str | None = None
    stop_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        config: StrategyConfig,
        mode: StrategySleeveMode,
        account_id: str = DEFAULT_ACCOUNT_ID,
        sleeve_id: str | None = None,
        allocated_cash: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> StrategySleeve:
        if mode == StrategySleeveMode.SIGNAL_ONLY and allocated_cash:
            raise CashAllocationError("signal_only sleeves cannot receive allocated cash")
        if mode == StrategySleeveMode.ALLOCATED and allocated_cash <= 0:
            raise CashAllocationError("allocated sleeves require positive allocated_cash")
        cash = float(allocated_cash) if mode == StrategySleeveMode.ALLOCATED else 0.0
        return cls(
            sleeve_id=sleeve_id or f"sleeve-{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            strategy_config_id=config.strategy_config_id,
            strategy_config_version=config.version,
            mode=mode,
            initial_allocated_cash=cash,
            cash=cash,
            metadata=metadata or {},
        )


class SleeveLot(BaseModel):
    """A position lot owned by exactly one sleeve."""

    model_config = ConfigDict(allow_inf_nan=False, validate_assignment=True)

    lot_id: str
    account_id: str = DEFAULT_ACCOUNT_ID
    sleeve_id: str
    symbol: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0)
    opened_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    source: str

    @classmethod
    def create(
        cls,
        *,
        sleeve_id: str,
        symbol: str,
        quantity: float,
        avg_cost: float,
        source: str,
        account_id: str = DEFAULT_ACCOUNT_ID,
        lot_id: str | None = None,
    ) -> SleeveLot:
        return cls(
            lot_id=lot_id or f"lot-{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            sleeve_id=sleeve_id,
            symbol=symbol.upper(),
            quantity=float(quantity),
            avg_cost=float(avg_cost),
            source=source,
        )


class SleeveLotBook:
    """In-memory lot book enforcing sleeve-level sell isolation."""

    def __init__(self, lots: list[SleeveLot] | None = None) -> None:
        self._lots: dict[tuple[str, str], SleeveLot] = {}
        for lot in lots or []:
            self._lots[(lot.sleeve_id, lot.symbol.upper())] = lot

    def lots(self) -> list[SleeveLot]:
        return sorted(self._lots.values(), key=lambda lot: (lot.sleeve_id, lot.symbol))

    def lot(self, sleeve_id: str, symbol: str) -> SleeveLot:
        key = (sleeve_id, symbol.upper())
        if key not in self._lots:
            raise InsufficientSleeveLotQuantity(
                f"sleeve {sleeve_id!r} has no lot for {symbol.upper()}"
            )
        return self._lots[key]

    def quantity(self, sleeve_id: str, symbol: str) -> float:
        lot = self._lots.get((sleeve_id, symbol.upper()))
        return lot.quantity if lot else 0.0

    def aggregate_quantity(self, symbol: str) -> float:
        normalized = symbol.upper()
        return sum(lot.quantity for lot in self._lots.values() if lot.symbol == normalized)

    def buy(
        self,
        *,
        account_id: str,
        sleeve_id: str,
        symbol: str,
        quantity: float,
        price: float,
        source: str,
    ) -> SleeveLot:
        normalized = symbol.upper()
        key = (sleeve_id, normalized)
        if key not in self._lots:
            self._validate_positive_finite(quantity, "quantity")
            self._validate_positive_finite(price, "price")
            lot = SleeveLot.create(
                account_id=account_id,
                sleeve_id=sleeve_id,
                symbol=normalized,
                quantity=quantity,
                avg_cost=price,
                source=source,
            )
            self._lots[key] = lot
            return lot
        lot = self._lots[key]
        total_quantity = lot.quantity + quantity
        self._validate_positive_finite(quantity, "quantity")
        self._validate_positive_finite(price, "price")
        self._validate_positive_finite(total_quantity, "total_quantity")
        next_avg_cost = ((lot.quantity * lot.avg_cost) + (quantity * price)) / total_quantity
        self._validate_non_negative_finite(next_avg_cost, "avg_cost")
        lot.avg_cost = next_avg_cost
        lot.quantity = total_quantity
        lot.updated_at = _utc_now_iso()
        return lot

    def sell(self, *, sleeve_id: str, symbol: str, quantity: float) -> SleeveLot | None:
        normalized = symbol.upper()
        key = (sleeve_id, normalized)
        lot = self._lots.get(key)
        if lot is None or lot.quantity + 1e-9 < quantity:
            available = 0.0 if lot is None else lot.quantity
            raise InsufficientSleeveLotQuantity(
                f"sleeve {sleeve_id!r} has {available:.4f} {normalized}, "
                f"cannot sell {quantity:.4f}"
            )
        self._validate_positive_finite(quantity, "quantity")
        remaining_quantity = lot.quantity - quantity
        if remaining_quantity <= 1e-9:
            self._lots.pop(key, None)
            return None
        lot.quantity = remaining_quantity
        lot.updated_at = _utc_now_iso()
        return lot

    @staticmethod
    def _validate_positive_finite(value: float, name: str) -> None:
        if not isfinite(float(value)) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")

    @staticmethod
    def _validate_non_negative_finite(value: float, name: str) -> None:
        if not isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be non-negative and finite")


class StrategySignal(BaseModel):
    """Immutable signal observation for a strategy sleeve."""

    signal_id: str
    sleeve_id: str
    strategy_config_id: str
    strategy_config_version: int
    signal_date: str
    generated_at: str = Field(default_factory=_utc_now_iso)
    data_provider: str
    data_as_of: str | None = None
    target_weights: dict[str, float] = Field(default_factory=dict)
    proposed_orders: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: SignalStatus = SignalStatus.GENERATED
    execution_blocked_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        sleeve: StrategySleeve,
        signal_date: str,
        data_provider: str,
        data_as_of: str | None = None,
        target_weights: dict[str, float] | None = None,
        proposed_orders: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        status: SignalStatus = SignalStatus.GENERATED,
        execution_blocked_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StrategySignal:
        blocked_reason = execution_blocked_reason
        if sleeve.status != StrategySleeveStatus.RUNNING and blocked_reason is None:
            blocked_reason = f"sleeve_{sleeve.status.value}"
        return cls(
            signal_id=f"signal-{uuid.uuid4().hex[:12]}",
            sleeve_id=sleeve.sleeve_id,
            strategy_config_id=sleeve.strategy_config_id,
            strategy_config_version=sleeve.strategy_config_version,
            signal_date=signal_date,
            data_provider=data_provider,
            data_as_of=data_as_of,
            target_weights=target_weights or {},
            proposed_orders=proposed_orders or [],
            warnings=warnings or [],
            status=status,
            execution_blocked_reason=blocked_reason,
            metadata=metadata or {},
        )


class StrategyExecutionOrder(BaseModel):
    """A single proposed order captured for later sleeve execution."""

    symbol: str
    side: str
    target_weight: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    notional_delta: float | None = None
    reference_price: float | None = None
    estimated_quantity: float | None = None
    reason: str | None = None
    account_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_proposed_order(cls, order: dict[str, Any]) -> StrategyExecutionOrder:
        payload = dict(order)
        if "symbol" in payload:
            payload["symbol"] = str(payload["symbol"]).upper().strip()
        return cls.model_validate(payload)


class StrategyExecutionFill(BaseModel):
    """A fill event belonging to one strategy execution plan."""

    fill_id: str
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    gross_value: float = Field(ge=0)
    price_kind: str
    filled_at: str = Field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        price_kind: str,
        gross_value: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyExecutionFill:
        return cls(
            fill_id=f"strategy-fill-{uuid.uuid4().hex[:12]}",
            symbol=symbol.upper(),
            side=side,
            quantity=float(quantity),
            price=float(price),
            gross_value=float(gross_value if gross_value is not None else quantity * price),
            price_kind=price_kind,
            metadata=metadata or {},
        )


class StrategyExecutionPlan(BaseModel):
    """Durable pending execution plan created from one generated signal."""

    execution_id: str
    sleeve_id: str
    account_id: str
    signal_id: str
    strategy_config_id: str
    strategy_config_version: int = Field(ge=1)
    execution_window: str = "next_open"
    target_date: str | None = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    status: StrategyExecutionStatus = StrategyExecutionStatus.PENDING
    blocked_reason: str | None = None
    orders: list[StrategyExecutionOrder] = Field(default_factory=list)
    fills: list[StrategyExecutionFill] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        account: PaperAccount,
        sleeve: StrategySleeve,
        signal: StrategySignal,
        execution_window: str = "next_open",
        target_date: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyExecutionPlan:
        return cls(
            execution_id=f"strategy-exec-{uuid.uuid4().hex[:12]}",
            sleeve_id=sleeve.sleeve_id,
            account_id=account.account_id,
            signal_id=signal.signal_id,
            strategy_config_id=signal.strategy_config_id,
            strategy_config_version=signal.strategy_config_version,
            execution_window=execution_window,
            target_date=target_date,
            orders=[
                StrategyExecutionOrder.from_proposed_order(order)
                for order in signal.proposed_orders
            ],
            warnings=list(signal.warnings),
            metadata=metadata or {},
        )


class PaperStrategySleeveService:
    """Small accounting service for MVP-1 sleeve setup, with no auto execution."""

    def __init__(self, storage) -> None:
        self.storage = storage

    def build_sleeve(
        self,
        *,
        config: StrategyConfig,
        mode: StrategySleeveMode,
        account_id: str = DEFAULT_ACCOUNT_ID,
        allocated_cash: float = 0.0,
        metadata: dict[str, Any] | None = None,
        sleeve_id: str | None = None,
    ) -> StrategySleeve:
        return StrategySleeve.create(
            config=config,
            mode=mode,
            account_id=account_id,
            allocated_cash=allocated_cash,
            metadata=metadata,
            sleeve_id=sleeve_id,
        )

    def create_sleeve(
        self,
        account: PaperAccount,
        *,
        config: StrategyConfig,
        mode: StrategySleeveMode,
        allocated_cash: float = 0.0,
        metadata: dict[str, Any] | None = None,
        sleeve_id: str | None = None,
    ) -> StrategySleeve:
        self._ensure_manual_cash_book(account)
        sleeve = self.build_sleeve(
            config=config,
            mode=mode,
            account_id=account.account_id,
            allocated_cash=allocated_cash,
            metadata=metadata,
            sleeve_id=sleeve_id,
        )
        if mode == StrategySleeveMode.ALLOCATED:
            self._allocate_cash(account, sleeve)
        return sleeve

    def pause_sleeve(self, sleeve: StrategySleeve) -> StrategySleeve:
        if sleeve.status not in {
            StrategySleeveStatus.RUNNING,
            StrategySleeveStatus.PAUSED,
        }:
            raise ValueError("only running sleeves can be paused")
        sleeve.status = StrategySleeveStatus.PAUSED
        sleeve.paused_at = _utc_now_iso()
        sleeve.updated_at = sleeve.paused_at
        self.storage.save_sleeve(sleeve)
        return sleeve

    def resume_sleeve(self, sleeve: StrategySleeve) -> StrategySleeve:
        if sleeve.status != StrategySleeveStatus.PAUSED:
            raise ValueError("only paused sleeves can be resumed")
        sleeve.status = StrategySleeveStatus.RUNNING
        sleeve.paused_at = None
        sleeve.updated_at = _utc_now_iso()
        self.storage.save_sleeve(sleeve)
        return sleeve

    def stop_sleeve(
        self,
        sleeve: StrategySleeve,
        *,
        reason: str | None = None,
    ) -> StrategySleeve:
        sleeve.status = StrategySleeveStatus.STOPPED
        sleeve.stopped_at = _utc_now_iso()
        sleeve.updated_at = sleeve.stopped_at
        sleeve.stop_reason = reason
        self.storage.save_sleeve(sleeve)
        return sleeve

    def quarantine_sleeve(
        self,
        sleeve: StrategySleeve,
        *,
        reason: str,
    ) -> StrategySleeve:
        if sleeve.status == StrategySleeveStatus.DEMOTED_COMPLETE:
            raise ValueError("completed demotions cannot be quarantined")
        now = _utc_now_iso()
        sleeve.status = StrategySleeveStatus.QUARANTINED_HOLD
        sleeve.stopped_at = sleeve.stopped_at or now
        sleeve.updated_at = now
        sleeve.stop_reason = reason
        sleeve.metadata["quarantine_reason"] = reason
        sleeve.metadata["quarantined_at"] = now
        self.storage.save_sleeve(sleeve)
        return sleeve

    def complete_demote(
        self,
        sleeve: StrategySleeve,
        *,
        outcome: StrategySleeveStatus,
    ) -> StrategySleeve:
        if sleeve.status != StrategySleeveStatus.QUARANTINED_HOLD:
            raise ValueError("only quarantined sleeves can complete demote")
        if outcome not in {
            StrategySleeveStatus.FLATTENED,
            StrategySleeveStatus.TRANSFERRED,
            StrategySleeveStatus.MANUALLY_ACCEPTED,
        }:
            raise ValueError("invalid demote outcome")
        now = _utc_now_iso()
        sleeve.metadata["demote_outcome"] = outcome.value
        sleeve.metadata["demote_outcome_at"] = now
        sleeve.status = StrategySleeveStatus.DEMOTED_COMPLETE
        sleeve.updated_at = now
        self.storage.save_sleeve(sleeve)
        return sleeve

    def create_execution_plan(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        signal: StrategySignal,
        execution_window: str = "next_open",
        target_date: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyExecutionPlan:
        if sleeve.mode == StrategySleeveMode.SIGNAL_ONLY:
            raise StrategyExecutionPlanError("signal_only_no_execution")
        if sleeve.status != StrategySleeveStatus.RUNNING:
            raise StrategyExecutionPlanError(f"sleeve_{sleeve.status.value}")
        if sleeve.account_id != account.account_id:
            raise StrategyExecutionPlanError("account_sleeve_mismatch")
        if signal.sleeve_id != sleeve.sleeve_id:
            raise StrategyExecutionPlanError("signal_sleeve_mismatch")
        if signal.strategy_config_id != sleeve.strategy_config_id:
            raise StrategyExecutionPlanError("signal_config_mismatch")
        if signal.status != SignalStatus.GENERATED:
            raise StrategyExecutionPlanError("signal_not_generated")
        if signal.execution_blocked_reason:
            raise StrategyExecutionPlanError(signal.execution_blocked_reason)
        if account.kill_switch:
            raise StrategyExecutionPlanError("account_frozen")
        if execution_window != "next_open":
            raise StrategyExecutionPlanError("unsupported_execution_window")
        if not signal.proposed_orders:
            raise StrategyExecutionPlanError("no_proposed_orders")
        plan_metadata = dict(metadata or {})
        if sleeve.metadata.get("automation_managed") is True:
            from quant_system.execution.factor_automation_safety import (
                FactorAutomationLimitError,
                validate_auto_execution_orders,
            )

            reference_prices = {
                str(order.get("symbol", "")).upper(): float(
                    order.get("reference_price", 0.0)
                )
                for order in signal.proposed_orders
                if order.get("symbol") and order.get("reference_price")
            }
            account_prices = {
                symbol: reference_prices.get(symbol, position.avg_cost)
                for symbol, position in account.positions.items()
            }
            aggregate_symbol_values = {
                symbol: position.market_value(account_prices[symbol])
                for symbol, position in account.positions.items()
            }
            lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
            sleeve_equity = sleeve.cash + sum(
                lot.quantity
                * reference_prices.get(lot.symbol.upper(), lot.avg_cost)
                for lot in lots
            )
            raw_context = plan_metadata.get("paper_execution_policy_context", {})
            policy_context = raw_context if isinstance(raw_context, dict) else {}
            try:
                policy_decision = validate_auto_execution_orders(
                    orders=signal.proposed_orders,
                    sleeve_equity=sleeve_equity,
                    nav=account.equity(account_prices),
                    aggregate_symbol_values=aggregate_symbol_values,
                    source=str(sleeve.metadata.get("automation_source", "d33")),
                    workspace_id=str(
                        sleeve.metadata.get("workspace_id", "local-default")
                    ),
                    account_id=account.account_id,
                    sleeve_id=sleeve.sleeve_id,
                    emergency_stop=policy_context.get("emergency_stop") is True,
                    paper_execution_enabled=(
                        policy_context.get("paper_execution_enabled", True) is True
                    ),
                    mandate_active=policy_context.get("mandate_active") is True,
                    mandate_paper_execution_allowed=(
                        policy_context.get("mandate_paper_execution_allowed") is True
                    ),
                )
            except FactorAutomationLimitError as exc:
                raise StrategyExecutionPlanError(
                    f"automation_{exc.code}"
                ) from exc
            plan_metadata["paper_execution_policy_decision"] = (
                policy_decision.to_dict()
            )
        existing = self.storage.latest_execution_for_signal(
            sleeve.sleeve_id,
            signal.signal_id,
        )
        if existing is not None:
            raise StrategyExecutionPlanError("execution_already_exists")
        plan = StrategyExecutionPlan.create(
            account=account,
            sleeve=sleeve,
            signal=signal,
            execution_window=execution_window,
            target_date=target_date or date.today().isoformat(),
            metadata=plan_metadata,
        )
        self.storage.append_execution(plan)
        return plan

    @staticmethod
    def _ensure_manual_cash_book(account: PaperAccount) -> None:
        if not account.sleeve_cash:
            account.sleeve_cash[MANUAL_SLEEVE_ID] = float(account.cash)
            return
        allocated_cash = sum(
            cash
            for sleeve_id, cash in account.sleeve_cash.items()
            if sleeve_id != MANUAL_SLEEVE_ID
        )
        account.sleeve_cash[MANUAL_SLEEVE_ID] = max(account.cash - allocated_cash, 0.0)

    @staticmethod
    def _allocate_cash(account: PaperAccount, sleeve: StrategySleeve) -> None:
        manual_cash = account.sleeve_cash.get(MANUAL_SLEEVE_ID, account.cash)
        if sleeve.cash > manual_cash + 1e-9:
            raise CashAllocationError(
                f"cannot allocate {sleeve.cash:.2f}; manual cash available is "
                f"{manual_cash:.2f}"
            )
        account.sleeve_cash[MANUAL_SLEEVE_ID] = manual_cash - sleeve.cash
        account.sleeve_cash[sleeve.sleeve_id] = (
            account.sleeve_cash.get(sleeve.sleeve_id, 0.0) + sleeve.cash
        )
        account.record_event(
            kind="sleeve_cash_allocated",
            source=f"strategy:{sleeve.sleeve_id}",
            note=(
                f"allocated {sleeve.cash:.2f} {account.base_currency} "
                f"to sleeve {sleeve.sleeve_id}"
            ),
        )
