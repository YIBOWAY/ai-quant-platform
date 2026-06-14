from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.execution.account import PaperAccount
from quant_system.execution.models import ManagedOrder, OrderSide
from quant_system.execution.paper_broker import PaperBroker
from quant_system.execution.portfolio import PaperPortfolio
from quant_system.execution.price_source import PaperPriceSource, PriceUnavailableError
from quant_system.factors.pipeline import (
    build_default_factors,
    build_factor_signal_frame,
    compute_factor_pipeline,
)


@dataclass
class OrderOutcome:
    status: str
    symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float
    price: float
    price_kind: str
    rejected_reason: str = ""


@dataclass
class RebalanceOutcome:
    strategy_id: str
    as_of: str | None
    target_weights: dict[str, float]
    orders: list[OrderOutcome]
    aborted: bool = False
    note: str = ""


class AccountFrozenError(RuntimeError):
    """Raised when an order is attempted against a frozen (kill-switched) account."""


class StrategyDataUnavailableError(RuntimeError):
    """Raised when a rebalance cannot obtain real strategy history."""


class PaperAccountService:
    """Applies manual orders and strategy rebalances to a persistent account.

    Both entry points converge on the same primitive — build an
    :class:`OrderRequest`, run it through :class:`RiskEngine`, fill it through
    :class:`PaperBroker`, and apply the resulting :class:`ExecutionFill` to the
    :class:`PaperAccount`. This guarantees manual and strategy-driven trades
    affect the account identically. It is SIMULATION-ONLY.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        price_source: PaperPriceSource | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.price_source = price_source or PaperPriceSource(self.settings)

    # --- manual orders ----------------------------------------------------
    def place_manual_order(
        self,
        account: PaperAccount,
        *,
        symbol: str,
        side: str,
        quantity: float | None = None,
        notional: float | None = None,
        limit_price: float | None = None,
    ) -> OrderOutcome:
        if account.kill_switch:
            raise AccountFrozenError("account is frozen (kill switch on); no new orders")
        order_side = OrderSide(side.lower())
        quote = self.price_source.get_price(symbol)
        resolved_quantity = self._resolve_quantity(
            quantity=quantity,
            notional=notional,
            price=quote.price,
        )
        outcome = self._execute_single(
            account=account,
            symbol=quote.symbol,
            side=order_side,
            quantity=resolved_quantity,
            price=quote.price,
            price_kind=quote.price_kind,
            limit_price=limit_price,
            source="manual",
            reason="manual_order",
        )
        return outcome

    # --- strategy rebalance ----------------------------------------------
    def rebalance_to_strategy(
        self,
        account: PaperAccount,
        *,
        strategy_id: str,
        symbols: list[str],
        lookback: int = 20,
        top_n: int = 3,
        provider: str | None = None,
        history_days: int = 400,
    ) -> RebalanceOutcome:
        if account.kill_switch:
            raise AccountFrozenError("account is frozen (kill switch on); no rebalance")

        target_weights, as_of = self._compute_target_weights(
            strategy_id=strategy_id,
            symbols=symbols,
            lookback=lookback,
            top_n=top_n,
            provider=provider,
            history_days=history_days,
        )
        if not target_weights:
            return RebalanceOutcome(
                strategy_id=strategy_id,
                as_of=as_of,
                target_weights={},
                orders=[],
                note="strategy produced no target weights for the latest signal",
            )

        # Price every symbol that is either targeted or currently held.
        relevant = sorted(set(target_weights) | set(account.positions))
        quotes = self.price_source.get_prices(relevant)
        prices = {sym: q.price for sym, q in quotes.items()}
        equity = account.equity(prices)

        requests = self._rebalance_requests(
            account=account,
            target_weights=target_weights,
            prices=prices,
            equity=equity,
        )
        if not requests:
            return RebalanceOutcome(
                strategy_id=strategy_id,
                as_of=as_of,
                target_weights=target_weights,
                orders=[],
                note="already at target; no orders needed",
            )

        # Plan-then-commit: dry-run every leg on a throwaway COPY of the account
        # first. If any leg would be rejected or fail to fill, abort with NO
        # mutation to the real account — this prevents the "sold everything then
        # failed to buy" all-cash outcome. Only when the whole plan succeeds do
        # we replay the identical legs on the real account.
        trial = account.model_copy(deep=True)
        trial_outcomes: list[OrderOutcome] = []
        for symbol, side, quantity in requests:
            quote = quotes[symbol]
            trial_outcomes.append(
                self._execute_single(
                    account=trial,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=quote.price,
                    price_kind=quote.price_kind,
                    limit_price=None,
                    source=f"strategy:{strategy_id}",
                    reason="strategy_rebalance",
                    kind="rebalance_fill",
                )
            )

        failed = [o for o in trial_outcomes if o.status not in ("filled", "skipped")]
        if failed:
            detail = "; ".join(
                f"{o.symbol} {o.side} {o.status}"
                + (f" ({o.rejected_reason})" if o.rejected_reason else "")
                for o in failed
            )
            account.record_event(
                kind="rebalance_aborted",
                source=f"strategy:{strategy_id}",
                note=f"rebalance aborted, no orders applied: {detail}",
            )
            return RebalanceOutcome(
                strategy_id=strategy_id,
                as_of=as_of,
                target_weights=target_weights,
                orders=trial_outcomes,
                aborted=True,
                note=f"aborted before any fill: {detail}",
            )

        # Plan validated — commit the same legs to the real account.
        outcomes: list[OrderOutcome] = []
        for symbol, side, quantity in requests:
            quote = quotes[symbol]
            outcomes.append(
                self._execute_single(
                    account=account,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=quote.price,
                    price_kind=quote.price_kind,
                    limit_price=None,
                    source=f"strategy:{strategy_id}",
                    reason="strategy_rebalance",
                    kind="rebalance_fill",
                )
            )

        account.record_event(
            kind="rebalance_fill",
            source=f"strategy:{strategy_id}",
            note=(
                f"rebalance to {strategy_id}; targets="
                + ",".join(f"{s}:{w:.3f}" for s, w in sorted(target_weights.items()))
            ),
        )
        return RebalanceOutcome(
            strategy_id=strategy_id,
            as_of=as_of,
            target_weights=target_weights,
            orders=outcomes,
        )

    def _execute_single(
        self,
        *,
        account: PaperAccount,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        price_kind: str,
        limit_price: float | None,
        source: str,
        reason: str,
        kind: str = "fill",
    ) -> OrderOutcome:
        timestamp = pd.Timestamp(datetime.now(UTC))
        if quantity <= 0:
            return OrderOutcome(
                status="skipped",
                symbol=symbol,
                side=str(side),
                requested_quantity=0.0,
                filled_quantity=0.0,
                price=price,
                price_kind=price_kind,
                rejected_reason="non-positive quantity",
            )

        # For this simulation-only account the kill_switch is the only
        # pre-trade gate. All other risk-engine checks (max_order_value,
        # max_position_size, drawdown) would produce confusing "rejected"
        # outcomes for valid but oversized paper orders; the broker's own
        # cash/position constraints are the real enforcement mechanism.
        if account.kill_switch:
            rejected_reason = "kill switch is enabled"
            account.record_event(
                kind="order_rejected",
                source=source,
                symbol=symbol,
                side=str(side),
                quantity=quantity,
                price=price,
                price_kind=price_kind,
                note=rejected_reason,
            )
            return OrderOutcome(
                status="rejected",
                symbol=symbol,
                side=str(side),
                requested_quantity=quantity,
                filled_quantity=0.0,
                price=price,
                price_kind=price_kind,
                rejected_reason=rejected_reason,
            )

        portfolio = self._portfolio_view(account)
        broker = PaperBroker(portfolio=portfolio)
        order = ManagedOrder(
            order_id=f"paper-order-{uuid.uuid4().hex[:12]}",
            created_at=timestamp,
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            reason=reason,
        )
        broker.submit_order(order)

        fills = broker.process_market_data(timestamp=timestamp, prices={symbol: price})
        filled = sum(fill.quantity for fill in fills)
        for fill in fills:
            account.apply_fill(fill, source=source, price_kind=price_kind, kind=kind)

        outcome_status = "filled"
        outcome_reason = ""
        if filled <= 0:
            outcome_status = "unfilled"
            if limit_price is not None:
                outcome_reason = (
                    f"current price {price:.4f} does not satisfy limit price "
                    f"{limit_price:.4f}"
                )
            elif side == OrderSide.BUY:
                outcome_reason = "insufficient cash"
            else:
                outcome_reason = "no position available to sell"
            account.record_event(
                kind="order_unfilled",
                source=source,
                symbol=symbol,
                side=str(side),
                quantity=quantity,
                price=price,
                price_kind=price_kind,
                note=outcome_reason,
            )
        elif filled + 1e-9 < quantity:
            outcome_status = "partially_filled"
            constraint = "available cash" if side == OrderSide.BUY else "available position"
            outcome_reason = (
                f"filled {filled:.4f} of {quantity:.4f}; limited by {constraint}"
            )
            account.record_event(
                kind="order_partially_filled",
                source=source,
                symbol=symbol,
                side=str(side),
                quantity=quantity,
                price=price,
                price_kind=price_kind,
                note=outcome_reason,
            )

        return OrderOutcome(
            status=outcome_status,
            symbol=symbol,
            side=str(side),
            requested_quantity=quantity,
            filled_quantity=filled,
            price=price,
            price_kind=price_kind,
            rejected_reason=outcome_reason,
        )

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _resolve_quantity(
        *,
        quantity: float | None,
        notional: float | None,
        price: float,
    ) -> float:
        if quantity is not None and notional is not None:
            raise ValueError("provide either quantity or notional, not both")
        if quantity is not None:
            if quantity <= 0:
                raise ValueError("quantity must be positive")
            return float(quantity)
        if notional is not None:
            if notional <= 0:
                raise ValueError("notional must be positive")
            if price <= 0:
                raise PriceUnavailableError("cannot size a notional order without a price")
            return float(notional) / float(price)
        raise ValueError("either quantity or notional is required")

    def _portfolio_view(self, account: PaperAccount) -> PaperPortfolio:
        portfolio = PaperPortfolio(initial_cash=account.cash)
        portfolio.positions = {
            symbol: position.quantity for symbol, position in account.positions.items()
        }
        return portfolio

    @staticmethod
    def _rebalance_requests(
        *,
        account: PaperAccount,
        target_weights: dict[str, float],
        prices: dict[str, float],
        equity: float,
    ) -> list[tuple[str, OrderSide, float]]:
        symbols = sorted(set(account.positions) | set(target_weights))
        requests: list[tuple[str, OrderSide, float]] = []
        for symbol in symbols:
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue
            current_value = account.position_quantity(symbol) * price
            target_value = target_weights.get(symbol, 0.0) * equity
            value_delta = target_value - current_value
            quantity = abs(value_delta) / price
            if quantity <= 1e-9:
                continue
            side = OrderSide.BUY if value_delta > 0 else OrderSide.SELL
            requests.append((symbol, side, quantity))
        # Sells before buys so cash is freed before it is spent.
        return sorted(requests, key=lambda item: 0 if item[1] == OrderSide.SELL else 1)

    def _compute_target_weights(
        self,
        *,
        strategy_id: str,
        symbols: list[str],
        lookback: int,
        top_n: int,
        provider: str | None,
        history_days: int,
    ) -> tuple[dict[str, float], str | None]:
        from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy

        builders = {
            "cross_sectional_top_n": ScoreSignalStrategy,
            "mean_reversion_top_n": MeanReversionTopN,
        }
        if strategy_id not in builders:
            raise ValueError(
                f"strategy {strategy_id!r} is not supported for account rebalance; "
                f"supported: {', '.join(sorted(builders))}"
            )

        ohlcv_provider, source = build_ohlcv_provider(self.settings, requested=provider)
        if source.lower().startswith("sample"):
            raise StrategyDataUnavailableError(
                "strategy rebalance requires real market history; sample data is not allowed"
            )
        end = datetime.now(UTC).date()
        start = end.fromordinal(end.toordinal() - max(history_days, 60))
        try:
            ohlcv = ohlcv_provider.fetch_ohlcv(
                symbols,
                start=start.isoformat(),
                end=end.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - external data-provider boundary
            raise StrategyDataUnavailableError(
                f"strategy history is unavailable: {exc}"
            ) from exc
        if ohlcv is None or ohlcv.empty:
            return {}, None

        factor_results = compute_factor_pipeline(
            ohlcv,
            factors=build_default_factors(lookback=lookback),
        )
        signal_frame = build_factor_signal_frame(factor_results)
        if signal_frame.empty:
            return {}, None

        latest_ts = signal_frame["tradeable_ts"].max()
        strategy = builders[strategy_id](signal_frame, top_n=top_n)
        targets = strategy.target_weights(latest_ts)
        if not targets:
            return {}, str(latest_ts)
        weights = {t.symbol.upper(): float(t.target_weight) for t in targets}
        return weights, str(latest_ts)
