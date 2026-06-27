from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

import pandas as pd

from quant_system.execution.account import PaperAccount
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLotBook,
    StrategyExecutionFill,
    StrategyExecutionOrder,
    StrategyExecutionPlan,
    StrategyExecutionStatus,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.execution.price_source import PricedQuote

EPSILON = 1e-9


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PaperStrategyExecutionError(ValueError):
    """Raised when a pending strategy execution cannot be processed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class _ExecutionStep(NamedTuple):
    order: StrategyExecutionOrder
    side: OrderSide
    symbol: str
    quantity: float
    price: float
    gross_value: float
    quote: PricedQuote


class PaperStrategyExecutionService:
    """Process Paper Strategy Sleeve execution plans against paper prices."""

    def __init__(self, *, storage, price_source) -> None:
        self.storage = storage
        self.price_source = price_source

    def execute_plan(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
    ) -> StrategyExecutionPlan:
        try:
            self._validate_execution_context(account, sleeve=sleeve, plan=plan)
            quotes = self._load_quotes(plan)
            steps = self._build_steps(plan, quotes)
            self._preflight(account, sleeve=sleeve, steps=steps)
        except PaperStrategyExecutionError as exc:
            if plan.status == StrategyExecutionStatus.PENDING:
                self._block_plan(plan, exc.code)
            raise

        lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
        lot_book = SleeveLotBook([lot.model_copy(deep=True) for lot in lots])
        fills: list[StrategyExecutionFill] = []
        source = f"strategy:{sleeve.sleeve_id}"

        for step in self._ordered_steps(steps):
            account_fill = self._account_fill(plan, step)
            if step.side == OrderSide.SELL:
                before_sources = self._position_sources(account, step.symbol)
                lot_book.sell(
                    sleeve_id=sleeve.sleeve_id,
                    symbol=step.symbol,
                    quantity=step.quantity,
                )
                account.apply_fill(
                    account_fill,
                    source=source,
                    price_kind=step.quote.price_kind,
                    kind="sleeve_execution_fill",
                )
                self._set_sleeve_source_after_sell(
                    account,
                    symbol=step.symbol,
                    source=source,
                    before_sources=before_sources,
                    quantity=step.quantity,
                )
                sleeve.cash += step.gross_value
            else:
                account.apply_fill(
                    account_fill,
                    source=source,
                    price_kind=step.quote.price_kind,
                    kind="sleeve_execution_fill",
                )
                lot_book.buy(
                    account_id=account.account_id,
                    sleeve_id=sleeve.sleeve_id,
                    symbol=step.symbol,
                    quantity=step.quantity,
                    price=step.price,
                    source=source,
                )
                sleeve.cash -= step.gross_value

            fills.append(
                StrategyExecutionFill.create(
                    symbol=step.symbol,
                    side=str(step.side),
                    quantity=step.quantity,
                    price=step.price,
                    price_kind=step.quote.price_kind,
                    gross_value=step.gross_value,
                )
            )

        sleeve.cash = max(sleeve.cash, 0.0)
        account.sleeve_cash[sleeve.sleeve_id] = sleeve.cash
        sleeve.updated_at = _utc_now_iso()
        plan.fills = fills
        plan.status = StrategyExecutionStatus.FILLED
        plan.updated_at = _utc_now_iso()
        self.storage.save_sleeve(sleeve)
        self.storage.save_sleeve_lots(sleeve.sleeve_id, lot_book.lots())
        self._replace_execution(plan)
        return plan

    def pending_plans(
        self,
        *,
        sleeve_id: str | None = None,
        execution_window: str = "next_open",
        target_date: str | None = None,
        limit: int = 50,
    ) -> list[tuple[StrategySleeve, StrategyExecutionPlan]]:
        sleeves = (
            [self.storage.load_sleeve(sleeve_id)]
            if sleeve_id is not None
            else self.storage.list_sleeves()
        )
        plans: list[tuple[StrategySleeve, StrategyExecutionPlan]] = []
        for sleeve in sleeves:
            for plan in self.storage.load_executions(sleeve.sleeve_id):
                if plan.status != StrategyExecutionStatus.PENDING:
                    continue
                if plan.execution_window != execution_window:
                    continue
                if target_date is not None and plan.target_date != target_date:
                    continue
                plans.append((sleeve, plan))
                if len(plans) >= limit:
                    return plans
        return plans

    def _validate_execution_context(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        plan: StrategyExecutionPlan,
    ) -> None:
        if plan.status != StrategyExecutionStatus.PENDING:
            raise PaperStrategyExecutionError("execution_not_pending")
        if plan.execution_window != "next_open":
            raise PaperStrategyExecutionError("unsupported_execution_window")
        if sleeve.mode != StrategySleeveMode.ALLOCATED:
            raise PaperStrategyExecutionError("signal_only_no_execution")
        if sleeve.status == StrategySleeveStatus.PAUSED:
            raise PaperStrategyExecutionError("sleeve_paused")
        if sleeve.status == StrategySleeveStatus.STOPPED:
            raise PaperStrategyExecutionError("sleeve_stopped")
        if account.kill_switch:
            raise PaperStrategyExecutionError("account_frozen")
        if sleeve.account_id != account.account_id or plan.account_id != account.account_id:
            raise PaperStrategyExecutionError("account_sleeve_mismatch")
        if plan.sleeve_id != sleeve.sleeve_id:
            raise PaperStrategyExecutionError("execution_sleeve_mismatch")
        if not plan.orders:
            raise PaperStrategyExecutionError("no_executable_orders")

    def _load_quotes(self, plan: StrategyExecutionPlan) -> dict[str, PricedQuote]:
        symbols = sorted({order.symbol.upper() for order in plan.orders})
        quotes = self.price_source.get_prices(symbols)
        missing = [symbol for symbol in symbols if symbol not in quotes]
        if missing:
            raise PaperStrategyExecutionError("price_unavailable")
        for symbol, quote in quotes.items():
            if quote.price <= 0:
                raise PaperStrategyExecutionError("price_unavailable")
            quotes[symbol] = quote.model_copy(update={"symbol": symbol.upper()})
        return quotes

    def _build_steps(
        self,
        plan: StrategyExecutionPlan,
        quotes: dict[str, PricedQuote],
    ) -> list[_ExecutionStep]:
        steps = []
        for order in plan.orders:
            symbol = order.symbol.upper()
            try:
                side = OrderSide(order.side)
            except ValueError as exc:
                raise PaperStrategyExecutionError("invalid_order_side") from exc
            quote = quotes[symbol]
            quantity = self._execution_quantity(order, quote.price)
            if quantity <= EPSILON:
                continue
            gross_value = quantity * quote.price
            steps.append(
                _ExecutionStep(
                    order=order,
                    side=side,
                    symbol=symbol,
                    quantity=quantity,
                    price=quote.price,
                    gross_value=gross_value,
                    quote=quote,
                )
            )
        if not steps:
            raise PaperStrategyExecutionError("no_executable_orders")
        return steps

    @staticmethod
    def _execution_quantity(order: StrategyExecutionOrder, price: float) -> float:
        if order.notional_delta is not None:
            return abs(order.notional_delta) / price
        if order.estimated_quantity is not None:
            return abs(order.estimated_quantity)
        return 0.0

    def _preflight(
        self,
        account: PaperAccount,
        *,
        sleeve: StrategySleeve,
        steps: list[_ExecutionStep],
    ) -> None:
        lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
        lot_book = SleeveLotBook([lot.model_copy(deep=True) for lot in lots])
        sleeve_cash = sleeve.cash
        source = f"strategy:{sleeve.sleeve_id}"
        for step in self._ordered_steps(steps):
            if step.side == OrderSide.SELL:
                if self._account_source_quantity(account, step.symbol, source) < (
                    step.quantity - EPSILON
                ):
                    raise PaperStrategyExecutionError(
                        "insufficient_account_source_quantity"
                    )
                try:
                    lot_book.sell(
                        sleeve_id=sleeve.sleeve_id,
                        symbol=step.symbol,
                        quantity=step.quantity,
                    )
                except ValueError as exc:
                    raise PaperStrategyExecutionError(
                        "insufficient_sleeve_lot_quantity"
                    ) from exc
                sleeve_cash += step.gross_value
            elif step.gross_value > sleeve_cash + EPSILON:
                raise PaperStrategyExecutionError("insufficient_sleeve_cash")
            else:
                sleeve_cash -= step.gross_value

    @staticmethod
    def _ordered_steps(steps: list[_ExecutionStep]) -> list[_ExecutionStep]:
        return sorted(steps, key=lambda step: 0 if step.side == OrderSide.SELL else 1)

    @staticmethod
    def _account_fill(plan: StrategyExecutionPlan, step: _ExecutionStep) -> ExecutionFill:
        return ExecutionFill(
            fill_id=f"fill-{plan.execution_id}-{step.symbol}-{step.side}",
            order_id=plan.execution_id,
            timestamp=pd.Timestamp(step.quote.as_of),
            symbol=step.symbol,
            side=step.side,
            quantity=step.quantity,
            fill_price=step.price,
            gross_value=step.gross_value,
        )

    @staticmethod
    def _position_sources(account: PaperAccount, symbol: str) -> dict[str, float]:
        position = account.positions.get(symbol.upper())
        if position is None:
            return {}
        return dict(position.source_quantity)

    @staticmethod
    def _account_source_quantity(
        account: PaperAccount,
        symbol: str,
        source: str,
    ) -> float:
        position = account.positions.get(symbol.upper())
        if position is None:
            return 0.0
        return position.source_quantity.get(source, 0.0)

    @staticmethod
    def _set_sleeve_source_after_sell(
        account: PaperAccount,
        *,
        symbol: str,
        source: str,
        before_sources: dict[str, float],
        quantity: float,
    ) -> None:
        position = account.positions.get(symbol.upper())
        if position is None:
            return
        updated = dict(before_sources)
        updated[source] = updated.get(source, 0.0) - quantity
        position.source_quantity = {
            item_source: item_quantity
            for item_source, item_quantity in updated.items()
            if item_quantity > EPSILON
        }

    def _block_plan(self, plan: StrategyExecutionPlan, reason: str) -> None:
        plan.status = StrategyExecutionStatus.BLOCKED
        plan.blocked_reason = reason
        plan.updated_at = _utc_now_iso()
        self._replace_execution(plan)

    def _replace_execution(self, plan: StrategyExecutionPlan) -> None:
        executions = self.storage.load_executions(plan.sleeve_id)
        replaced = False
        for index, existing in enumerate(executions):
            if existing.execution_id == plan.execution_id:
                executions[index] = plan
                replaced = True
                break
        if not replaced:
            executions.append(plan)
        self.storage.save_executions(plan.sleeve_id, executions)
