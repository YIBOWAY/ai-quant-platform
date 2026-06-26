from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_system.config.settings import load_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_signal_service import (
    PaperStrategySignalService,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategyConfig,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)


class FakeOHLCVProvider:
    def __init__(self, frame: pd.DataFrame | None = None, exc: Exception | None = None) -> None:
        self.frame = frame
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.calls.append(
            {"symbols": list(symbols), "start": start, "end": end, "interval": interval}
        )
        if self.exc is not None:
            raise self.exc
        assert self.frame is not None
        symbols = {symbol.upper() for symbol in symbols}
        return self.frame[self.frame["symbol"].isin(symbols)].copy()


def make_ohlcv_frame() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-01", periods=80, freq="D", tz=UTC)
    for index, timestamp in enumerate(dates):
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": timestamp,
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.0 + index,
                "volume": 1_000_000 + index,
            }
        )
        rows.append(
            {
                "symbol": "MSFT",
                "timestamp": timestamp,
                "open": 200.0 - (index * 0.25),
                "high": 201.0 - (index * 0.25),
                "low": 199.0 - (index * 0.25),
                "close": 200.0 - (index * 0.25),
                "volume": 900_000 + index,
            }
        )
    return pd.DataFrame(rows)


def make_config(**overrides) -> StrategyConfig:
    payload = {
        "name": "Sleeve Top-N",
        "description": "signal service test",
        "strategy_id": "cross_sectional_top_n",
        "universe_id": "custom",
        "symbols": ["AAPL", "MSFT"],
        "factor_ids": ["momentum"],
        "weights": {"momentum": 1.0},
        "lookback": 5,
        "top_n": 1,
        "rebalance_frequency": "daily",
        "max_weight_per_symbol": 1.0,
        "min_order_value": 100.0,
        "data_provider": "futu",
        "execution_timing": "next_open",
        "metadata": {"source": "pytest"},
    }
    payload.update(overrides)
    return StrategyConfig.create(**payload)


def make_sleeve(
    config: StrategyConfig,
    *,
    mode: StrategySleeveMode = StrategySleeveMode.ALLOCATED,
    allocated_cash: float = 10_000.0,
) -> StrategySleeve:
    return StrategySleeve.create(
        config=config,
        mode=mode,
        allocated_cash=allocated_cash if mode == StrategySleeveMode.ALLOCATED else 0.0,
    )


def patch_provider(monkeypatch, provider: FakeOHLCVProvider, source: str = "futu") -> None:
    monkeypatch.setattr(
        "quant_system.execution.paper_strategy_signal_service.build_ohlcv_provider",
        lambda settings, *, requested=None: (provider, source),
    )


def test_signal_service_generates_and_persists_daily_signal(tmp_path, monkeypatch) -> None:
    provider = FakeOHLCVProvider(make_ohlcv_frame())
    patch_provider(monkeypatch, provider)
    storage = PaperStrategySleeveStorage(tmp_path)
    config = make_config()
    sleeve = make_sleeve(config)
    account = PaperAccount.open_new()
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)

    signal = PaperStrategySignalService(
        storage=storage,
        settings=load_settings(),
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2024-03-20",
        history_days=90,
    )

    assert signal.status == SignalStatus.GENERATED
    assert signal.data_provider == "futu"
    assert signal.data_as_of is not None
    assert signal.target_weights == {"AAPL": pytest.approx(1.0)}
    assert signal.proposed_orders[0]["symbol"] == "AAPL"
    assert signal.proposed_orders[0]["side"] == "buy"
    assert signal.proposed_orders[0]["estimated_quantity"] > 0
    assert storage.load_signals(sleeve.sleeve_id) == [signal]
    assert provider.calls[0]["symbols"] == ["AAPL", "MSFT"]


def test_signal_service_marks_paused_sleeve_blocked_without_plan(
    tmp_path, monkeypatch
) -> None:
    provider = FakeOHLCVProvider(make_ohlcv_frame())
    patch_provider(monkeypatch, provider)
    storage = PaperStrategySleeveStorage(tmp_path)
    config = make_config()
    sleeve = make_sleeve(config)
    sleeve.status = StrategySleeveStatus.PAUSED
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)

    signal = PaperStrategySignalService(
        storage=storage,
        settings=load_settings(),
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=PaperAccount.open_new(),
        signal_date="2024-03-20",
    )

    assert signal.status == SignalStatus.GENERATED
    assert signal.execution_blocked_reason == "sleeve_paused"
    assert signal.target_weights == {"AAPL": pytest.approx(1.0)}
    assert signal.proposed_orders == []
    assert any("sleeve is paused" in warning for warning in signal.warnings)


def test_signal_service_marks_frozen_account_blocked_without_plan(
    tmp_path, monkeypatch
) -> None:
    provider = FakeOHLCVProvider(make_ohlcv_frame())
    patch_provider(monkeypatch, provider)
    storage = PaperStrategySleeveStorage(tmp_path)
    config = make_config()
    sleeve = make_sleeve(config)
    account = PaperAccount.open_new()
    account.kill_switch = True

    signal = PaperStrategySignalService(
        storage=storage,
        settings=load_settings(),
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2024-03-20",
    )

    assert signal.status == SignalStatus.GENERATED
    assert signal.execution_blocked_reason == "account_frozen"
    assert signal.proposed_orders == []


def test_signal_service_persists_data_unavailable_instead_of_sample_fallback(
    tmp_path, monkeypatch
) -> None:
    provider = FakeOHLCVProvider(make_ohlcv_frame())
    patch_provider(monkeypatch, provider, source="sample (futu: disabled)")
    storage = PaperStrategySleeveStorage(tmp_path)
    config = make_config()
    sleeve = make_sleeve(config, mode=StrategySleeveMode.SIGNAL_ONLY)

    signal = PaperStrategySignalService(
        storage=storage,
        settings=load_settings(),
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=PaperAccount.open_new(),
        signal_date="2024-03-20",
    )

    assert signal.status == SignalStatus.DATA_UNAVAILABLE
    assert signal.data_provider == "sample (futu: disabled)"
    assert signal.target_weights == {}
    assert signal.proposed_orders == []
    assert any("sample data is not allowed" in warning for warning in signal.warnings)
    assert storage.load_signals(sleeve.sleeve_id) == [signal]


def test_signal_service_persists_data_unavailable_when_fetch_fails(
    tmp_path, monkeypatch
) -> None:
    provider = FakeOHLCVProvider(exc=RuntimeError("OpenD unavailable"))
    patch_provider(monkeypatch, provider)
    storage = PaperStrategySleeveStorage(tmp_path)
    config = make_config()
    sleeve = make_sleeve(config, mode=StrategySleeveMode.SIGNAL_ONLY)

    signal = PaperStrategySignalService(
        storage=storage,
        settings=load_settings(),
    ).generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=PaperAccount.open_new(),
        signal_date=datetime(2024, 3, 20, tzinfo=UTC).date().isoformat(),
    )

    assert signal.status == SignalStatus.DATA_UNAVAILABLE
    assert signal.data_provider == "futu"
    assert "strategy history is unavailable" in signal.warnings[0]
