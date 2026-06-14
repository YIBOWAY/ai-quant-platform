from __future__ import annotations

import uuid
from collections.abc import Mapping

import pandas as pd

from quant_system.execution.broker import BrokerAdapter
from quant_system.execution.models import (
    ExecutionFill,
    ManagedOrder,
    OrderEvent,
    OrderRequest,
    OrderStatus,
)
from quant_system.risk.engine import RiskEngine
from quant_system.risk.models import RiskBreach, RiskContext


class OrderManager:
    def __init__(
        self,
        *,
        risk_engine: RiskEngine,
        broker: BrokerAdapter,
        id_prefix: str | None = None,
    ) -> None:
        self.risk_engine = risk_engine
        self.broker = broker
        self.orders: dict[str, ManagedOrder] = {}
        self.order_event_log: list[OrderEvent] = []
        self.trade_log: list[ExecutionFill] = []
        self.risk_breach_log: list[RiskBreach] = []
        self._order_counter = 0
        # A per-manager prefix keeps order ids unique across managers. The paper
        # account builds a fresh OrderManager per request, so a plain counter
        # would otherwise restart at 000001 and collide between orders.
        self._id_prefix = id_prefix or f"paper-order-{uuid.uuid4().hex[:8]}"

    def create_and_submit(
        self,
        request: OrderRequest,
        context: RiskContext,
    ) -> ManagedOrder:
        self._order_counter += 1
        order = ManagedOrder(
            order_id=f"{self._id_prefix}-{self._order_counter:06d}",
            created_at=request.timestamp,
            symbol=request.normalized_symbol(),
            side=request.side,
            quantity=request.quantity,
            limit_price=request.limit_price,
            reason=request.reason,
        )
        self.orders[order.order_id] = order
        self._log_event(order, request.timestamp, OrderStatus.CREATED, "order created")

        decision = self.risk_engine.check_order(request, context)
        if not decision.approved:
            for breach in decision.breaches:
                breach.order_id = order.order_id
            self.risk_breach_log.extend(decision.breaches)
            order.status = OrderStatus.REJECTED
            order.rejected_reason = decision.reason
            self._log_event(order, request.timestamp, OrderStatus.REJECTED, decision.reason)
            return order

        order.status = OrderStatus.SUBMITTED
        self.broker.submit_order(order)
        self._log_event(order, request.timestamp, OrderStatus.SUBMITTED, "order submitted")
        return order

    def process_market_data(
        self,
        *,
        timestamp: pd.Timestamp,
        prices: Mapping[str, float],
    ) -> list[ExecutionFill]:
        before = {
            order_id: order.status
            for order_id, order in getattr(self.broker, "open_orders", {}).items()
        }
        fills = self.broker.process_market_data(timestamp=timestamp, prices=prices)
        self.trade_log.extend(fills)
        for order_id, previous_status in before.items():
            order = self.orders[order_id]
            if order.status != previous_status:
                self._log_event(order, timestamp, order.status, "broker status update")
        return fills

    def cancel_order(self, order_id: str, *, reason: str = "") -> ManagedOrder:
        order = self.broker.cancel_order(
            order_id,
            timestamp=pd.Timestamp.utcnow(),
            reason=reason,
        )
        self._log_event(order, pd.Timestamp.utcnow(), OrderStatus.CANCELLED, reason)
        return order

    def check_post_trade_risk(self, context: RiskContext) -> list[RiskBreach]:
        decision = self.risk_engine.check_portfolio(context)
        self.risk_breach_log.extend(decision.breaches)
        return decision.breaches

    def _log_event(
        self,
        order: ManagedOrder,
        timestamp: pd.Timestamp,
        status: OrderStatus,
        message: str,
    ) -> None:
        self.order_event_log.append(
            OrderEvent(
                timestamp=timestamp,
                order_id=order.order_id,
                symbol=order.symbol,
                status=status,
                message=message,
            )
        )
