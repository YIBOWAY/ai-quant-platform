from __future__ import annotations

import pandas as pd

from quant_system.execution.models import OrderRequest, OrderSide
from quant_system.risk.models import RiskBreach, RiskContext, RiskDecision, RiskLimits


class RiskEngine:
    """Pre-trade risk engine independent of strategy and broker adapters."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def check_order(self, request: OrderRequest, context: RiskContext) -> RiskDecision:
        breaches: list[RiskBreach] = []
        symbol = request.normalized_symbol()
        order_price = context.price_for(symbol, request.limit_price)
        if order_price is None:
            breaches.append(
                self._breach(request, "missing_price", f"missing latest price for {symbol}")
            )
            return RiskDecision(approved=False, breaches=breaches)

        if self.limits.kill_switch:
            breaches.append(
                self._breach(request, "kill_switch", "kill switch is enabled")
            )
        if symbol in self.limits.normalized_blocked_symbols:
            breaches.append(
                self._breach(request, "blocked_symbols", f"{symbol} is blocked")
            )
        allowed = self.limits.normalized_allowed_symbols
        if allowed and symbol not in allowed:
            breaches.append(
                self._breach(request, "allowed_symbols", f"{symbol} is not in allowed symbols")
            )

        order_value = request.quantity * order_price
        if order_value > self.limits.max_order_value:
            breaches.append(
                self._breach(
                    request,
                    "max_order_value",
                    f"order value {order_value:.2f} exceeds {self.limits.max_order_value:.2f}",
                )
            )

        projected_quantity = self._projected_quantity(request, context)
        projected_position_value = abs(projected_quantity * order_price)
        max_position_value = context.equity * self.limits.max_position_size
        if projected_position_value > max_position_value:
            breaches.append(
                self._breach(
                    request,
                    "max_position_size",
                    f"projected position value {projected_position_value:.2f} exceeds "
                    f"{max_position_value:.2f}",
                )
            )

        daily_loss_limit = context.equity * self.limits.max_daily_loss
        if context.daily_pnl < 0 and abs(context.daily_pnl) > daily_loss_limit:
            breaches.append(
                self._breach(
                    request,
                    "max_daily_loss",
                    f"daily loss {context.daily_pnl:.2f} exceeds limit",
                )
            )

        if context.peak_equity > 0:
            drawdown = 1 - context.equity / context.peak_equity
            if drawdown > self.limits.max_drawdown:
                breaches.append(
                    self._breach(
                        request,
                        "max_drawdown",
                        f"drawdown {drawdown:.4f} exceeds {self.limits.max_drawdown:.4f}",
                    )
                )

        return RiskDecision(approved=not breaches, breaches=breaches)

    def check_portfolio(self, context: RiskContext) -> RiskDecision:
        breaches: list[RiskBreach] = []
        timestamp = pd.Timestamp.utcnow()

        if context.equity > 0:
            max_position_value = context.equity * self.limits.max_position_size
            for symbol, quantity in sorted(context.positions.items()):
                price = context.price_for(symbol)
                if price is None:
                    continue
                position_value = abs(float(quantity) * price)
                if position_value > max_position_value:
                    breaches.append(
                        RiskBreach(
                            timestamp=timestamp,
                            rule_name="max_position_size",
                            symbol=symbol.upper(),
                            message=(
                                f"position value {position_value:.2f} exceeds "
                                f"{max_position_value:.2f}"
                            ),
                        )
                    )

            daily_loss_limit = context.equity * self.limits.max_daily_loss
            if context.daily_pnl < 0 and abs(context.daily_pnl) > daily_loss_limit:
                breaches.append(
                    RiskBreach(
                        timestamp=timestamp,
                        rule_name="max_daily_loss",
                        symbol="PORTFOLIO",
                        message=f"daily loss {context.daily_pnl:.2f} exceeds limit",
                    )
                )

        if context.peak_equity > 0:
            drawdown = 1 - context.equity / context.peak_equity
            if drawdown > self.limits.max_drawdown:
                breaches.append(
                    RiskBreach(
                        timestamp=timestamp,
                        rule_name="max_drawdown",
                        symbol="PORTFOLIO",
                        message=(
                            f"drawdown {drawdown:.4f} exceeds "
                            f"{self.limits.max_drawdown:.4f}"
                        ),
                    )
                )

        return RiskDecision(approved=not breaches, breaches=breaches)

    def _projected_quantity(self, request: OrderRequest, context: RiskContext) -> float:
        current = context.position(request.symbol)
        if request.side == OrderSide.BUY:
            return current + request.quantity
        return current - request.quantity

    def _breach(self, request: OrderRequest, rule_name: str, message: str) -> RiskBreach:
        return RiskBreach(
            timestamp=request.timestamp,
            rule_name=rule_name,
            symbol=request.normalized_symbol(),
            message=message,
        )
