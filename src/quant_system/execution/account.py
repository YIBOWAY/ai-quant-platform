from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.trading_kernel import roll_position_on_fill

DEFAULT_ACCOUNT_ID = "default"
DEFAULT_INITIAL_CASH = 1_000_000.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AccountPosition(BaseModel):
    """A single open position with an average cost basis.

    ``avg_cost`` is the per-share cost basis including commission paid on the
    buys that built the position, so realised P&L on a sell is simply
    ``quantity * (fill_price - avg_cost) - sell_commission``.
    """

    symbol: str
    quantity: float = 0.0
    avg_cost: float = 0.0
    # Fraction of the current quantity attributable to each fill source, e.g.
    # {"manual": 0.6, "strategy:cross_sectional_top_n": 0.4}. Tracked on a
    # quantity-weighted basis so the Position Map can attribute exposure.
    source_quantity: dict[str, float] = Field(default_factory=dict)

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.quantity * (price - self.avg_cost)

    def source_breakdown(self) -> dict[str, float]:
        total = sum(self.source_quantity.values())
        if total <= 0:
            return {}
        return {source: qty / total for source, qty in self.source_quantity.items()}


class LedgerEntry(BaseModel):
    """An append-only event in the account ledger (the source of truth)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    entry_id: str
    timestamp: str
    kind: str  # deposit | fill | rebalance_fill | reset | fee
    source: str = "system"  # manual | strategy:<id> | system
    symbol: str | None = None
    side: str | None = None
    quantity: float | None = None
    price: float | None = None
    gross_value: float | None = None
    commission: float = 0.0
    price_kind: str | None = None  # futu_snapshot | last_close
    realized_pnl_delta: float = 0.0
    cash_after: float = 0.0
    note: str = ""


class PendingAccountOrder(BaseModel):
    """A manual paper limit order waiting for a future price check."""

    order_id: str
    created_at: str
    symbol: str
    side: str
    quantity: float
    limit_price: float
    reserved_cash: float = 0.0
    reserved_quantity: float = 0.0
    source: str = "manual"
    reason: str = "manual_order"
    last_checked_price: float | None = None
    last_checked_price_kind: str | None = None
    last_checked_at: str | None = None


class PaperAccount(BaseModel):
    """A single persistent, mutable paper account.

    The ``ledger`` is the authoritative event stream; ``cash`` / ``positions``
    / ``realized_pnl`` are the materialised view kept in sync as fills are
    applied. This is a SIMULATION-ONLY account: it never touches a real broker,
    wallet, or order submission path.
    """

    account_id: str = DEFAULT_ACCOUNT_ID
    base_currency: str = "USD"
    initial_cash: float = DEFAULT_INITIAL_CASH
    cash: float = DEFAULT_INITIAL_CASH
    # Total account cash remains in ``cash`` for legacy/manual/rebalance paths.
    # ``sleeve_cash`` is the internal allocation book for Paper Strategy Sleeves:
    # manual cash plus per-sleeve allocated cash must come from the same account.
    sleeve_cash: dict[str, float] = Field(default_factory=dict)
    realized_pnl: float = 0.0
    kill_switch: bool = False
    positions: dict[str, AccountPosition] = Field(default_factory=dict)
    pending_orders: list[PendingAccountOrder] = Field(default_factory=list)
    ledger: list[LedgerEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    # --- construction -----------------------------------------------------
    @classmethod
    def open_new(
        cls,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        initial_cash: float = DEFAULT_INITIAL_CASH,
        base_currency: str = "USD",
    ) -> PaperAccount:
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        account = cls(
            account_id=account_id,
            base_currency=base_currency,
            initial_cash=float(initial_cash),
            cash=float(initial_cash),
            sleeve_cash={"manual": float(initial_cash)},
        )
        account._append_ledger(
            kind="deposit",
            source="system",
            note=f"open account with {initial_cash:.2f} {base_currency}",
        )
        return account

    @model_validator(mode="after")
    def _ensure_manual_sleeve_cash(self) -> PaperAccount:
        if not self.sleeve_cash:
            self.sleeve_cash = {"manual": float(self.cash)}
        else:
            self.sleeve_cash = {
                str(sleeve_id): float(cash)
                for sleeve_id, cash in self.sleeve_cash.items()
            }
            allocated_cash = sum(
                cash
                for sleeve_id, cash in self.sleeve_cash.items()
                if sleeve_id != "manual"
            )
            self.sleeve_cash["manual"] = max(float(self.cash) - allocated_cash, 0.0)
        return self

    # --- read views -------------------------------------------------------
    def position_quantity(self, symbol: str) -> float:
        position = self.positions.get(symbol.upper())
        return position.quantity if position else 0.0

    def market_value(self, prices: Mapping[str, float]) -> float:
        normalized = {symbol.upper(): float(price) for symbol, price in prices.items()}
        return sum(
            position.market_value(normalized.get(symbol, position.avg_cost))
            for symbol, position in self.positions.items()
        )

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def unrealized_pnl(self, prices: Mapping[str, float]) -> float:
        normalized = {symbol.upper(): float(price) for symbol, price in prices.items()}
        return sum(
            position.unrealized_pnl(normalized.get(symbol, position.avg_cost))
            for symbol, position in self.positions.items()
        )

    def reserved_cash(self, *, exclude_order_id: str | None = None) -> float:
        return sum(
            max(order.reserved_cash, 0.0)
            for order in self.pending_orders
            if order.order_id != exclude_order_id
        )

    def available_cash(self, *, exclude_order_id: str | None = None) -> float:
        return max(self.cash - self.reserved_cash(exclude_order_id=exclude_order_id), 0.0)

    def reserved_quantity(
        self, symbol: str, *, exclude_order_id: str | None = None
    ) -> float:
        normalized = symbol.upper()
        return sum(
            max(order.reserved_quantity, 0.0)
            for order in self.pending_orders
            if order.order_id != exclude_order_id and order.symbol.upper() == normalized
        )

    def available_quantity(
        self, symbol: str, *, exclude_order_id: str | None = None
    ) -> float:
        return max(
            self.position_quantity(symbol)
            - self.reserved_quantity(symbol, exclude_order_id=exclude_order_id),
            0.0,
        )

    # --- mutations --------------------------------------------------------
    def apply_fill(
        self,
        fill: ExecutionFill,
        *,
        source: str = "manual",
        price_kind: str | None = None,
        kind: str = "fill",
    ) -> LedgerEntry:
        """Apply an ExecutionFill to cash/positions/realized_pnl and log it.

        Buys add to the position and roll the average cost (commission folded
        into basis). Sells realise P&L against ``avg_cost`` and leave the basis
        of the remaining shares unchanged.
        """

        symbol = fill.symbol.upper()
        position = self.positions.get(symbol, AccountPosition(symbol=symbol))

        # Numeric position/cash/avg_cost roll comes from the shared pure kernel;
        # the ledger, source-quantity, and realized-P&L side effects stay here.
        new_quantity, new_avg_cost, realized_delta, cash_delta = roll_position_on_fill(
            side=fill.side,
            position_quantity=position.quantity,
            position_avg_cost=position.avg_cost,
            fill_quantity=fill.quantity,
            fill_price=fill.fill_price,
            gross_value=fill.gross_value,
            commission=fill.commission,
        )
        position.avg_cost = new_avg_cost
        position.quantity = new_quantity
        self.cash += cash_delta
        self._sync_manual_sleeve_cash(
            cash_delta,
            source=source,
            kind=kind,
        )
        if fill.side == OrderSide.BUY:
            position.source_quantity[source] = (
                position.source_quantity.get(source, 0.0) + fill.quantity
            )
        else:  # SELL
            self.realized_pnl += realized_delta
            self._reduce_source_quantity(position, fill.quantity)

        if abs(position.quantity) < 1e-9:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = position

        return self._append_ledger(
            kind=kind,
            source=source,
            symbol=symbol,
            side=str(fill.side),
            quantity=fill.quantity,
            price=fill.fill_price,
            gross_value=fill.gross_value,
            commission=fill.commission,
            price_kind=price_kind,
            realized_pnl_delta=realized_delta,
            note=fill.order_id,
        )

    @staticmethod
    def _reduce_source_quantity(position: AccountPosition, sold_quantity: float) -> None:
        total = sum(position.source_quantity.values())
        if total <= 0:
            return
        # Reduce each source proportionally to its share of the position.
        remaining = sold_quantity
        for source in list(position.source_quantity):
            share = position.source_quantity[source] / total
            reduction = min(position.source_quantity[source], share * sold_quantity)
            position.source_quantity[source] -= reduction
            remaining -= reduction
            if position.source_quantity[source] <= 1e-9:
                position.source_quantity.pop(source, None)
        # Drop residual rounding so an emptied position has no source dust.
        if position.quantity <= 1e-9:
            position.source_quantity.clear()

    def _sync_manual_sleeve_cash(self, cash_delta: float, *, source: str, kind: str) -> None:
        if not self._cash_delta_belongs_to_manual_sleeve(source=source, kind=kind):
            return
        manual_cash = self.sleeve_cash.get("manual", 0.0) + cash_delta
        self.sleeve_cash["manual"] = 0.0 if abs(manual_cash) < 1e-9 else manual_cash

    def _cash_delta_belongs_to_manual_sleeve(self, *, source: str, kind: str) -> bool:
        if kind == "sleeve_execution_fill":
            return False
        if source.startswith("strategy:"):
            sleeve_id = source.removeprefix("strategy:")
            return sleeve_id not in self.sleeve_cash
        return True

    def record_event(
        self,
        *,
        kind: str,
        source: str = "system",
        symbol: str | None = None,
        side: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        price_kind: str | None = None,
        note: str = "",
    ) -> LedgerEntry:
        return self._append_ledger(
            kind=kind,
            source=source,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            price_kind=price_kind,
            note=note,
        )

    def _append_ledger(
        self,
        *,
        kind: str,
        source: str = "system",
        symbol: str | None = None,
        side: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        gross_value: float | None = None,
        commission: float = 0.0,
        price_kind: str | None = None,
        realized_pnl_delta: float = 0.0,
        note: str = "",
    ) -> LedgerEntry:
        entry = LedgerEntry(
            entry_id=f"ledger-{uuid.uuid4().hex[:12]}",
            timestamp=_utc_now_iso(),
            kind=kind,
            source=source,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            gross_value=gross_value,
            commission=commission,
            price_kind=price_kind,
            realized_pnl_delta=realized_pnl_delta,
            cash_after=self.cash,
            note=note,
        )
        self.ledger.append(entry)
        self.updated_at = entry.timestamp
        return entry
