from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from quant_system.execution.models import ExecutionFill, OrderSide

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
    realized_pnl: float = 0.0
    kill_switch: bool = False
    positions: dict[str, AccountPosition] = Field(default_factory=dict)
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
        )
        account._append_ledger(
            kind="deposit",
            source="system",
            note=f"open account with {initial_cash:.2f} {base_currency}",
        )
        return account

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
        realized_delta = 0.0

        if fill.side == OrderSide.BUY:
            total_basis = position.quantity * position.avg_cost
            total_basis += fill.gross_value + fill.commission
            new_quantity = position.quantity + fill.quantity
            position.avg_cost = total_basis / new_quantity if new_quantity > 0 else 0.0
            position.quantity = new_quantity
            position.source_quantity[source] = (
                position.source_quantity.get(source, 0.0) + fill.quantity
            )
            self.cash -= fill.gross_value + fill.commission
        else:  # SELL
            realized_delta = fill.quantity * (fill.fill_price - position.avg_cost)
            realized_delta -= fill.commission
            self.realized_pnl += realized_delta
            position.quantity -= fill.quantity
            self.cash += fill.gross_value - fill.commission
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
