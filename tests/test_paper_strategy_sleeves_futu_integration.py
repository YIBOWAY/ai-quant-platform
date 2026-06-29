from __future__ import annotations

import os
from datetime import date

import pytest

from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_signal_service import PaperStrategySignalService
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PaperPriceSource
from tests.test_paper_strategy_signals import make_config, make_sleeve

pytestmark = pytest.mark.futu_opend

if os.getenv("QS_TEST_FUTU_OPEND") != "1":
    pytest.skip(
        "set QS_TEST_FUTU_OPEND=1 to run read-only local Futu/OpenD integration tests",
        allow_module_level=True,
    )


def test_real_futu_opend_generates_strategy_sleeve_signal(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_FUTU_ENABLED", "true")
    settings = reload_settings()
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config(
        symbols=["AAPL", "MSFT"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=5,
        top_n=1,
        data_provider="futu",
    )
    sleeve = make_sleeve(config, mode=StrategySleeveMode.SIGNAL_ONLY)
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)

    signal = PaperStrategySignalService(
        storage=storage,
        settings=settings,
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=PaperAccount.open_new(),
        history_days=120,
    )

    assert signal.status == SignalStatus.GENERATED
    assert signal.data_provider == "futu"
    assert signal.data_as_of
    assert signal.target_weights
    assert storage.load_signals(sleeve.sleeve_id) == [signal]


def test_real_futu_opend_supports_next_open_execution_processor(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_FUTU_ENABLED", "true")
    settings = reload_settings()
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account = PaperAccount.open_new(initial_cash=100_000.0)
    config = make_config(
        symbols=["AAPL"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=5,
        top_n=1,
        data_provider="futu",
        max_weight_per_symbol=1.0,
    )
    storage.save_strategy_config(config)
    sleeve_service = PaperStrategySleeveService(storage)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=5_000.0,
    )
    storage.save_sleeve(sleeve)

    price_source = PaperPriceSource(settings)
    quote = price_source.get_price("AAPL")
    notional = min(quote.price, sleeve.cash / 2)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date=date.today().isoformat(),
        data_provider="futu",
        data_as_of=quote.as_of,
        target_weights={"AAPL": 0.5},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 0.5,
                "current_value": 0.0,
                "target_value": notional,
                "notional_delta": notional,
                "reference_price": quote.price,
                "estimated_quantity": notional / quote.price,
                "reason": "read_only_futu_execution_check",
                "account_id": account.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date=date.today().isoformat(),
    )

    executed = PaperStrategyExecutionService(
        storage=storage,
        price_source=price_source,
    ).execute_plan(account, sleeve=sleeve, plan=plan)

    assert executed.status == StrategyExecutionStatus.FILLED
    assert executed.fills[0].symbol == "AAPL"
    assert executed.fills[0].quantity > 0
    assert executed.fills[0].price > 0
    assert executed.fills[0].price_kind in {"futu_snapshot", "last_close"}
    assert "sample" not in quote.source.lower()
    assert account.ledger[-1].kind == "sleeve_execution_fill"
    assert account.ledger[-1].source == f"strategy:{sleeve.sleeve_id}"
    assert storage.load_executions(sleeve.sleeve_id)[0].status == "filled"
