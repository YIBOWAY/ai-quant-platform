from __future__ import annotations

import json

import pandas as pd
import pytest

from quant_system.api.schemas.paper import (
    StrategyConfigResponse,
    StrategySleeveResponse,
)
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    CashAllocationError,
    InsufficientSleeveLotQuantity,
    PaperStrategySleeveService,
    SignalStatus,
    SleeveLot,
    SleeveLotBook,
    StrategyConfig,
    StrategySignal,
    StrategySleeveMode,
    StrategySleeveStatus,
)


def _config(**overrides) -> StrategyConfig:
    data = {
        "name": "Top-N momentum",
        "description": "test config",
        "strategy_id": "cross_sectional_top_n",
        "universe_id": "custom",
        "symbols": ["AAPL", "MSFT"],
        "factor_ids": ["momentum"],
        "weights": {"momentum": 1.0},
        "lookback": 20,
        "top_n": 1,
        "rebalance_frequency": "daily",
        "max_weight_per_symbol": 0.5,
        "min_order_value": 100.0,
        "data_provider": "futu",
        "execution_timing": "next_open",
    }
    data.update(overrides)
    return StrategyConfig.create(**data)


def test_strategy_config_versions_are_immutable_files(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    config_v1 = _config(top_n=1)
    config_v2 = config_v1.new_version(top_n=2)

    storage.save_strategy_config(config_v1)
    storage.save_strategy_config(config_v2)

    config_dir = storage.strategy_config_dir(config_v1.strategy_config_id)
    assert (config_dir / "config.v1.json").exists()
    assert (config_dir / "config.v2.json").exists()
    metadata = json.loads((config_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["latest_version"] == 2

    reloaded_v1 = storage.load_strategy_config(config_v1.strategy_config_id, version=1)
    reloaded_latest = storage.load_strategy_config(config_v1.strategy_config_id)
    assert reloaded_v1.top_n == 1
    assert reloaded_latest.top_n == 2
    assert "top_n" in StrategyConfig.TRADING_LOGIC_FIELDS
    assert "description" not in StrategyConfig.TRADING_LOGIC_FIELDS


def test_sleeve_creation_modes_handle_account_cash_without_execution(tmp_path) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage = PaperStrategySleeveStorage(tmp_path)
    service = PaperStrategySleeveService(storage)
    config = _config()
    storage.save_strategy_config(config)

    signal_only = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.SIGNAL_ONLY,
    )
    assert signal_only.cash == 0.0
    assert account.cash == pytest.approx(100_000.0)
    assert account.sleeve_cash["manual"] == pytest.approx(100_000.0)

    allocated = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )

    assert allocated.initial_allocated_cash == pytest.approx(25_000.0)
    assert allocated.cash == pytest.approx(25_000.0)
    assert account.cash == pytest.approx(100_000.0)
    assert account.sleeve_cash["manual"] == pytest.approx(75_000.0)
    assert account.sleeve_cash[allocated.sleeve_id] == pytest.approx(25_000.0)
    assert account.ledger[-1].kind == "sleeve_cash_allocated"
    assert account.ledger[-1].source == f"strategy:{allocated.sleeve_id}"

    with pytest.raises(CashAllocationError):
        service.create_sleeve(
            account,
            config=config,
            mode=StrategySleeveMode.ALLOCATED,
            allocated_cash=80_000.0,
        )


def test_sleeve_lot_book_keeps_same_symbol_lots_isolated() -> None:
    book = SleeveLotBook(
        [
            SleeveLot.create(
                account_id="default",
                sleeve_id="manual",
                symbol="AAPL",
                quantity=10,
                avg_cost=100.0,
                source="manual",
            ),
            SleeveLot.create(
                account_id="default",
                sleeve_id="sleeve-abc",
                symbol="AAPL",
                quantity=5,
                avg_cost=120.0,
                source="strategy:sleeve-abc",
            ),
        ]
    )

    with pytest.raises(InsufficientSleeveLotQuantity):
        book.sell(sleeve_id="sleeve-missing", symbol="AAPL", quantity=1)
    with pytest.raises(InsufficientSleeveLotQuantity):
        book.sell(sleeve_id="manual", symbol="AAPL", quantity=12)

    book.sell(sleeve_id="manual", symbol="AAPL", quantity=4)
    book.buy(
        account_id="default",
        sleeve_id="sleeve-abc",
        symbol="AAPL",
        quantity=5,
        price=140.0,
        source="strategy:sleeve-abc",
    )

    assert book.quantity("manual", "AAPL") == pytest.approx(6)
    assert book.quantity("sleeve-abc", "AAPL") == pytest.approx(10)
    assert book.lot("sleeve-abc", "AAPL").avg_cost == pytest.approx(130.0)
    assert book.aggregate_quantity("AAPL") == pytest.approx(16)


def test_sleeve_storage_round_trips_sleeves_lots_and_signals(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    config = _config()
    storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(storage).create_sleeve(
        PaperAccount.open_new(initial_cash=50_000.0),
        config=config,
        mode=StrategySleeveMode.SIGNAL_ONLY,
    )
    lot = SleeveLot.create(
        account_id="default",
        sleeve_id=sleeve.sleeve_id,
        symbol="MSFT",
        quantity=3,
        avg_cost=100.0,
        source=f"strategy:{sleeve.sleeve_id}",
    )
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-25",
        data_provider="futu",
        data_as_of="2026-06-25T20:00:00Z",
        target_weights={"MSFT": 1.0},
        proposed_orders=[],
        warnings=["observation only"],
        status=SignalStatus.GENERATED,
    )

    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(sleeve.sleeve_id, [lot])
    storage.append_signal(signal)

    reloaded_sleeve = storage.load_sleeve(sleeve.sleeve_id)
    reloaded_lots = storage.load_sleeve_lots(sleeve.sleeve_id)
    reloaded_signals = storage.load_signals(sleeve.sleeve_id)
    lot_frame = pd.read_parquet(storage.sleeve_lots_path(sleeve.sleeve_id))

    assert reloaded_sleeve.status == StrategySleeveStatus.RUNNING
    assert reloaded_lots[0].symbol == "MSFT"
    assert reloaded_signals[0].signal_id == signal.signal_id
    assert list(lot_frame["symbol"]) == ["MSFT"]


def test_paper_strategy_sleeve_api_schemas_accept_domain_models() -> None:
    config = _config()
    sleeve = PaperStrategySleeveService(PaperStrategySleeveStorage(".")).build_sleeve(
        config=config,
        mode=StrategySleeveMode.SIGNAL_ONLY,
    )

    assert StrategyConfigResponse.model_validate(config.model_dump(mode="json")).version == 1
    assert (
        StrategySleeveResponse.model_validate(sleeve.model_dump(mode="json")).mode
        == "signal_only"
    )
