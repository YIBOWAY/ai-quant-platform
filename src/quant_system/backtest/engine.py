from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict

from quant_system.backtest.broker import BrokerSimulator
from quant_system.backtest.metrics import PerformanceMetrics, calculate_performance_metrics
from quant_system.backtest.models import BacktestConfig, Fill, Order
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.backtest.strategy import ScoreSignalStrategy


class BacktestResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    equity_curve: pd.DataFrame
    trade_blotter: pd.DataFrame
    orders: pd.DataFrame
    positions: pd.DataFrame
    metrics: PerformanceMetrics


class BacktestEngine:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.order_generator = OrderGenerator(config)
        self.broker = BrokerSimulator(config)

    def run(self, ohlcv: pd.DataFrame, strategy: ScoreSignalStrategy) -> BacktestResult:
        frame = self._prepare_ohlcv(ohlcv)
        portfolio = Portfolio(initial_cash=self.config.initial_cash)
        order_records: list[dict[str, object]] = []
        fill_records: list[dict[str, object]] = []
        equity_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []

        for timestamp, bars in frame.groupby("timestamp", sort=True):
            open_prices = dict(zip(bars["symbol"], bars["open"], strict=True))
            close_prices = dict(zip(bars["symbol"], bars["close"], strict=True))
            targets = strategy.target_weights(timestamp)
            orders: list[Order] = []
            fills: list[Fill] = []
            if targets is not None:
                orders = self.order_generator.generate_orders(
                    timestamp=timestamp,
                    targets=targets,
                    portfolio=portfolio,
                    prices=open_prices,
                )
                fills = self.broker.execute_orders(orders, open_prices, portfolio)

            order_records.extend(self._order_records(orders))
            fill_records.extend(self._fill_records(fills))
            equity_records.append(self._equity_record(timestamp, portfolio, close_prices, fills))
            position_records.extend(
                self._position_records(timestamp, portfolio, close_prices)
            )

        equity_curve = pd.DataFrame(
            equity_records,
            columns=["timestamp", "cash", "market_value", "equity", "period_turnover"],
        )
        trade_blotter = pd.DataFrame(
            fill_records,
            columns=[
                "fill_id",
                "order_id",
                "timestamp",
                "symbol",
                "side",
                "quantity",
                "requested_price",
                "fill_price",
                "gross_value",
                "commission",
                "slippage_bps",
                "status",
            ],
        )
        orders_frame = pd.DataFrame(
            order_records,
            columns=["order_id", "timestamp", "symbol", "side", "quantity", "reason"],
        )
        positions_frame = pd.DataFrame(
            position_records,
            columns=["timestamp", "symbol", "quantity", "close_price", "market_value"],
        )
        metrics = calculate_performance_metrics(
            equity_curve,
            trade_blotter,
            initial_cash=self.config.initial_cash,
            annualization_factor=self.config.annualization_factor,
        )
        return BacktestResult(
            equity_curve=equity_curve,
            trade_blotter=trade_blotter,
            orders=orders_frame,
            positions=positions_frame,
            metrics=metrics,
        )

    def _prepare_ohlcv(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        required = {"symbol", "timestamp", "open", "close"}
        missing = required.difference(ohlcv.columns)
        if missing:
            raise ValueError(f"missing required OHLCV columns: {', '.join(sorted(missing))}")
        frame = ohlcv.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        return frame.dropna(subset=["open", "close"]).sort_values(
            ["timestamp", "symbol"],
            ignore_index=True,
        )

    def _equity_record(
        self,
        timestamp: pd.Timestamp,
        portfolio: Portfolio,
        close_prices: Mapping[str, float],
        fills: list[Fill],
    ) -> dict[str, object]:
        gross_traded = sum(fill.gross_value for fill in fills)
        turnover = gross_traded / self.config.initial_cash if self.config.initial_cash else 0.0
        market_value = portfolio.market_value(close_prices)
        return {
            "timestamp": timestamp,
            "cash": portfolio.cash,
            "market_value": market_value,
            "equity": portfolio.cash + market_value,
            "period_turnover": turnover,
        }

    def _position_records(
        self,
        timestamp: pd.Timestamp,
        portfolio: Portfolio,
        close_prices: Mapping[str, float],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for symbol, quantity in sorted(portfolio.positions.items()):
            close_price = float(close_prices.get(symbol, 0.0))
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "quantity": quantity,
                    "close_price": close_price,
                    "market_value": quantity * close_price,
                }
            )
        return rows

    def _order_records(self, orders: list[Order]) -> list[dict[str, object]]:
        return [
            {
                "order_id": order.order_id,
                "timestamp": order.timestamp,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": order.quantity,
                "reason": order.reason,
            }
            for order in orders
        ]

    def _fill_records(self, fills: list[Fill]) -> list[dict[str, object]]:
        return [
            {
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "timestamp": fill.timestamp,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "requested_price": fill.requested_price,
                "fill_price": fill.fill_price,
                "gross_value": fill.gross_value,
                "commission": fill.commission,
                "slippage_bps": fill.slippage_bps,
                "status": fill.status.value,
            }
            for fill in fills
        ]
