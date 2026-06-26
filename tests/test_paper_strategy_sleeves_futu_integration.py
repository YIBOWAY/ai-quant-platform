from __future__ import annotations

import os

import pytest

from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_signal_service import PaperStrategySignalService
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategySleeveMode,
)
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
