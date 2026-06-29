from __future__ import annotations

import pandas as pd
import pytest

from quant_system.execution.account import PaperAccount
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionError,
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    SleeveLot,
    StrategyConfig,
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}

    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:
        return {
            symbol.upper(): PricedQuote(
                symbol=symbol.upper(),
                price=self.prices[symbol.upper()],
                price_kind="futu_snapshot",
                as_of="2026-06-29T13:30:00Z",
                source="fake",
            )
            for symbol in symbols
            if symbol.upper() in self.prices
        }


class UnavailablePriceSource:
    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:  # noqa: ARG002
        raise PriceUnavailableError("no real price available")


def _config() -> StrategyConfig:
    return StrategyConfig.create(
        name="Top-N momentum",
        description="execution test",
        strategy_id="cross_sectional_top_n",
        universe_id="custom",
        symbols=["AAPL"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=20,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=1.0,
        min_order_value=100.0,
        data_provider="futu",
        execution_timing="next_open",
    )


def _fill(symbol: str, side: OrderSide, quantity: float, price: float) -> ExecutionFill:
    return ExecutionFill(
        fill_id=f"fill-{symbol}-{side}-{quantity}",
        order_id="seed",
        timestamp=pd.Timestamp("2026-06-26T13:30:00Z"),
        symbol=symbol,
        side=side,
        quantity=quantity,
        fill_price=price,
        gross_value=quantity * price,
    )


def test_next_open_execution_fills_buy_and_updates_sleeve_account_and_lots(
    tmp_path,
) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve_service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    storage.save_sleeve(sleeve)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 25_000.0,
                "target_weight": 1.0,
                "reference_price": 100.0,
                "estimated_quantity": 250.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    executed = PaperStrategyExecutionService(
        storage=storage,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).execute_plan(account, sleeve=sleeve, plan=plan)

    assert executed.status == StrategyExecutionStatus.FILLED
    assert executed.fills[0].symbol == "AAPL"
    assert executed.fills[0].quantity == pytest.approx(250.0)
    assert executed.fills[0].price == pytest.approx(100.0)
    assert sleeve.cash == pytest.approx(0.0)
    assert account.sleeve_cash[sleeve.sleeve_id] == pytest.approx(0.0)
    assert account.cash == pytest.approx(75_000.0)
    assert account.positions["AAPL"].quantity == pytest.approx(250.0)
    assert account.positions["AAPL"].source_quantity[
        f"strategy:{sleeve.sleeve_id}"
    ] == pytest.approx(250.0)
    lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    assert lots[0].quantity == pytest.approx(250.0)
    assert lots[0].avg_cost == pytest.approx(100.0)
    assert storage.load_executions(sleeve.sleeve_id)[0].status == "filled"
    assert account.ledger[-1].kind == "sleeve_execution_fill"


def test_next_open_execution_sell_reduces_only_the_sleeve_lot_source(tmp_path) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve_service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000.0,
    )
    sleeve.cash = 9_500.0
    account.sleeve_cash[sleeve.sleeve_id] = sleeve.cash
    account.apply_fill(_fill("AAPL", OrderSide.BUY, 10.0, 100.0), source="manual")
    account.apply_fill(
        _fill("AAPL", OrderSide.BUY, 5.0, 100.0),
        source=f"strategy:{sleeve.sleeve_id}",
    )
    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                account_id=account.account_id,
                sleeve_id=sleeve.sleeve_id,
                symbol="AAPL",
                quantity=5.0,
                avg_cost=100.0,
                source=f"strategy:{sleeve.sleeve_id}",
            )
        ],
    )
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "sell",
                "notional_delta": -200.0,
                "target_weight": 0.0,
                "reference_price": 100.0,
                "estimated_quantity": 2.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    PaperStrategyExecutionService(
        storage=storage,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).execute_plan(account, sleeve=sleeve, plan=plan)

    position = account.positions["AAPL"]
    assert position.quantity == pytest.approx(13.0)
    assert position.source_quantity["manual"] == pytest.approx(10.0)
    assert position.source_quantity[f"strategy:{sleeve.sleeve_id}"] == pytest.approx(
        3.0
    )
    assert storage.load_sleeve_lots(sleeve.sleeve_id)[0].quantity == pytest.approx(3.0)
    assert sleeve.cash == pytest.approx(9_700.0)
    assert account.sleeve_cash[sleeve.sleeve_id] == pytest.approx(9_700.0)


def test_next_open_execution_blocks_insufficient_sleeve_cash_without_mutation(
    tmp_path,
) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve_service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000.0,
    )
    storage.save_sleeve(sleeve)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 20_000.0,
                "target_weight": 1.0,
                "reference_price": 100.0,
                "estimated_quantity": 200.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    with pytest.raises(PaperStrategyExecutionError, match="insufficient_sleeve_cash"):
        PaperStrategyExecutionService(
            storage=storage,
            price_source=FakePriceSource({"AAPL": 100.0}),
        ).execute_plan(account, sleeve=sleeve, plan=plan)

    reloaded = storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.BLOCKED
    assert reloaded.blocked_reason == "insufficient_sleeve_cash"
    assert sleeve.cash == pytest.approx(10_000.0)
    assert account.cash == pytest.approx(100_000.0)
    assert account.positions == {}
    assert storage.load_sleeve_lots(sleeve.sleeve_id) == []


def test_next_open_execution_blocks_price_source_failures_without_mutation(
    tmp_path,
) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve_service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000.0,
    )
    storage.save_sleeve(sleeve)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 5_000.0,
                "target_weight": 1.0,
                "reference_price": 100.0,
                "estimated_quantity": 50.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    with pytest.raises(PaperStrategyExecutionError, match="price_unavailable"):
        PaperStrategyExecutionService(
            storage=storage,
            price_source=UnavailablePriceSource(),
        ).execute_plan(account, sleeve=sleeve, plan=plan)

    reloaded = storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.BLOCKED
    assert reloaded.blocked_reason == "price_unavailable"
    assert sleeve.cash == pytest.approx(10_000.0)
    assert account.cash == pytest.approx(100_000.0)
    assert account.positions == {}
    assert storage.load_sleeve_lots(sleeve.sleeve_id) == []


def test_next_open_execution_does_not_reprocess_filled_plan(tmp_path) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve_service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    storage.save_sleeve(sleeve)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 25_000.0,
                "target_weight": 1.0,
                "reference_price": 100.0,
                "estimated_quantity": 250.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    processor = PaperStrategyExecutionService(
        storage=storage,
        price_source=FakePriceSource({"AAPL": 100.0}),
    )
    processor.execute_plan(account, sleeve=sleeve, plan=plan)

    with pytest.raises(PaperStrategyExecutionError, match="execution_not_pending"):
        processor.execute_plan(account, sleeve=sleeve, plan=plan)

    reloaded = storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.FILLED
    assert account.cash == pytest.approx(75_000.0)
    assert account.positions["AAPL"].quantity == pytest.approx(250.0)
