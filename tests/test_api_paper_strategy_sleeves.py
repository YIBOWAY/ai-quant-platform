from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote
from tests.test_paper_strategy_signals import (
    FakeOHLCVProvider,
    make_config,
    make_ohlcv_frame,
    make_sleeve,
    patch_provider,
)


class InlinePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}

    def get_prices(self, symbols, **_kwargs):
        return {
            symbol.upper(): PricedQuote(
                symbol=symbol.upper(),
                price=self.prices[symbol.upper()],
                price_kind="futu_snapshot",
                as_of="2026-06-29T13:30:00Z",
                source="inline",
            )
            for symbol in symbols
            if symbol.upper() in self.prices
        }


@pytest.fixture
def stub_prices(monkeypatch) -> dict[str, float]:
    prices = {"AAPL": 200.0, "MSFT": 100.0, "SPY": 470.0, "QQQ": 400.0}

    def fake_get_price(self, symbol, **_kwargs):
        symbol = symbol.upper().strip()
        return PricedQuote(
            symbol=symbol,
            price=prices[symbol],
            price_kind="futu_snapshot",
            as_of="2024-01-02T00:00:00Z",
            source="stub",
        )

    def fake_get_prices(self, symbols, **_kwargs):
        return {
            symbol.upper().strip(): fake_get_price(self, symbol)
            for symbol in symbols
            if symbol.upper().strip() in prices
        }

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        fake_get_price,
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_prices",
        fake_get_prices,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_snapshot._resolve_futu_account_quotes",
        lambda account, *, settings: {
            symbol: fake_get_price(None, symbol)
            for symbol in account.positions
            if symbol in prices
        },
    )
    return prices


def _config_payload(**overrides):
    payload = {
        "name": "Sleeve Top-N",
        "description": "API test config",
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
        "tags": ["api-test"],
        "metadata": {"source": "pytest"},
    }
    payload.update(overrides)
    return payload


def _create_config(client: TestClient) -> dict:
    response = client.post("/api/paper/strategy-configs", json=_config_payload())
    assert response.status_code == 200
    return response.json()["config"]


def _file_tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    return {
        str(path.relative_to(root)): (
            ("file", path.read_bytes(), path.stat().st_mtime_ns)
            if path.is_file()
            else ("dir", path.stat().st_mtime_ns)
        )
        for path in sorted(root.rglob("*"))
    }


def _save_orphaned_pending_sleeve(storage: PaperStrategySleeveStorage):
    config = make_config()
    storage.save_strategy_config(config)
    account = PaperAccount.open_new(initial_cash=100_000.0)
    pending_sleeve = PaperStrategySleeveService(storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    return pending_sleeve, storage.save_pending_sleeve(pending_sleeve)


def test_strategy_config_api_creates_lists_and_versions(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    created = _create_config(client)
    listed = client.get("/api/paper/strategy-configs")
    versioned = client.post(
        f"/api/paper/strategy-configs/{created['strategy_config_id']}/versions",
        json=_config_payload(top_n=2, description="new logic version"),
    )

    assert created["version"] == 1
    assert listed.status_code == 200
    assert listed.json()["configs"][0]["strategy_config_id"] == created["strategy_config_id"]
    assert versioned.status_code == 200
    assert versioned.json()["config"]["version"] == 2
    assert versioned.json()["config"]["top_n"] == 2


def test_strategy_config_api_rejects_duplicate_active_names(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    _create_config(client)

    duplicate = client.post(
        "/api/paper/strategy-configs",
        json=_config_payload(name=" sleeve top-n "),
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "strategy_config_name_conflict"


def test_strategy_config_version_conflict_returns_409(tmp_path, monkeypatch) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    created = _create_config(client)

    def fail_save_strategy_config(self, config):  # noqa: ARG001
        raise FileExistsError("strategy config version already exists")

    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "save_strategy_config",
        fail_save_strategy_config,
    )

    response = client.post(
        f"/api/paper/strategy-configs/{created['strategy_config_id']}/versions",
        json=_config_payload(top_n=2),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "strategy_config_conflict"


def test_strategy_sleeve_api_creates_signal_only_without_cash_mutation(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)

    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "signal_only",
        },
    )

    assert created.status_code == 200
    payload = created.json()
    sleeve = payload["sleeve"]
    assert sleeve["mode"] == "signal_only"
    assert sleeve["status"] == "running"
    assert sleeve["cash"] == 0.0
    assert payload["account"]["cash"] == 1_000_000.0

    listed = client.get("/api/paper/strategy-sleeves").json()
    assert [item["sleeve_id"] for item in listed["sleeves"]] == [sleeve["sleeve_id"]]

    detail = client.get(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}").json()
    assert detail["sleeve"]["sleeve_id"] == sleeve["sleeve_id"]
    assert detail["lots"] == []
    assert detail["signals"] == []


def test_strategy_sleeve_api_allocates_cash_inside_account_lock(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)

    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": 1,
            "mode": "allocated",
            "allocated_cash": 250_000.0,
        },
    )

    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    assert sleeve["cash"] == pytest.approx(250_000.0)
    assert sleeve["initial_allocated_cash"] == pytest.approx(250_000.0)

    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert account.cash == pytest.approx(1_000_000.0)
    assert account.sleeve_cash["manual"] == pytest.approx(750_000.0)
    assert account.sleeve_cash[sleeve["sleeve_id"]] == pytest.approx(250_000.0)
    assert account.ledger[-1].kind == "sleeve_cash_allocated"


def test_strategy_sleeve_api_does_not_save_sleeve_when_account_save_fails(
    tmp_path, monkeypatch
) -> None:
    client = TestClient(create_app(output_dir=tmp_path), raise_server_exceptions=False)
    config = _create_config(client)

    def fail_save_account(*_args, **_kwargs):
        raise OSError("account disk write failed")

    monkeypatch.setattr("quant_system.api.routes.paper._save_account", fail_save_account)

    response = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "mode": "allocated",
            "allocated_cash": 250_000.0,
        },
    )

    assert response.status_code == 500
    assert client.get("/api/paper/strategy-sleeves").json()["sleeves"] == []
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert account.sleeve_cash == {"manual": 1_000_000.0}


def test_strategy_sleeve_processor_recovers_pending_sleeve_after_finalize_failure(
    tmp_path, monkeypatch
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    original_finalize = PaperStrategySleeveStorage.finalize_pending_sleeve

    def fail_finalize(self, sleeve_id):  # noqa: ARG001
        raise OSError("sleeve finalization failed")

    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "finalize_pending_sleeve",
        fail_finalize,
    )

    response = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "mode": "allocated",
            "allocated_cash": 250_000.0,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "strategy_sleeve_storage_pending"
    assert "explicit strategy mutation" in response.json()["detail"]["message"]
    assert "paper strategies recover-pending" in response.json()["detail"]["message"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    pending = storage.list_pending_sleeves()
    assert len(pending) == 1
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert account.sleeve_cash["manual"] == pytest.approx(750_000.0)
    assert account.sleeve_cash[pending[0].sleeve_id] == pytest.approx(250_000.0)

    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "finalize_pending_sleeve",
        original_finalize,
    )
    observed = client.get("/api/paper/strategy-sleeves").json()["sleeves"]
    assert observed == []
    assert len(storage.list_pending_sleeves()) == 1

    recovered = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"limit": 1},
    )

    assert recovered.status_code == 200
    listed = client.get("/api/paper/strategy-sleeves").json()["sleeves"]
    assert [sleeve["sleeve_id"] for sleeve in listed] == [pending[0].sleeve_id]
    assert storage.list_pending_sleeves() == []


def test_strategy_sleeve_api_rejects_over_allocation_without_mutation(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)

    rejected = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "mode": "allocated",
            "allocated_cash": 1_500_000.0,
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "cash_allocation_error"
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert account.sleeve_cash == {"manual": 1_000_000.0}


def test_strategy_sleeve_api_lifecycle_transitions(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    sleeve = client.post(
        "/api/paper/strategy-sleeves",
        json={"strategy_config_id": config["strategy_config_id"], "mode": "signal_only"},
    ).json()["sleeve"]

    paused = client.post(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/pause")
    resumed = client.post(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/resume")
    stopped = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/stop",
        json={"reason": "finished observation"},
    )

    assert paused.status_code == 200
    assert paused.json()["sleeve"]["status"] == "paused"
    assert paused.json()["sleeve"]["paused_at"] is not None
    assert resumed.status_code == 200
    assert resumed.json()["sleeve"]["status"] == "running"
    assert stopped.status_code == 200
    assert stopped.json()["sleeve"]["status"] == "stopped"
    assert stopped.json()["sleeve"]["stop_reason"] == "finished observation"


def test_strategy_sleeve_signal_api_generates_and_persists_daily_signal(
    tmp_path, monkeypatch
) -> None:
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]

    response = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/signals",
        json={"signal_date": "2024-03-20", "history_days": 90},
    )

    assert response.status_code == 200
    signal = response.json()["signal"]
    assert signal["status"] == "generated"
    assert signal["data_provider"] == "futu"
    assert signal["target_weights"] == {
        "AAPL": pytest.approx(_config_payload()["max_weight_per_symbol"])
    }
    assert signal["proposed_orders"][0]["symbol"] == "AAPL"
    assert signal["proposed_orders"][0]["side"] == "buy"

    detail = client.get(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}").json()
    assert [item["signal_id"] for item in detail["signals"]] == [signal["signal_id"]]
    account = client.get("/api/paper/account").json()
    assert account["cash"] == pytest.approx(1_000_000.0)
    assert account["positions"] == []
    assert account["pending_orders"] == []


def test_strategy_sleeve_execution_api_creates_pending_plan_without_account_mutation(
    tmp_path,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)

    response = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={
            "signal_id": signal.signal_id,
            "execution_window": "next_open",
            "target_date": "2026-06-29",
        },
    )

    assert response.status_code == 200
    execution = response.json()["execution"]
    assert execution["status"] == "pending"
    assert execution["signal_id"] == signal.signal_id
    assert execution["execution_window"] == "next_open"
    assert execution["target_date"] == "2026-06-29"
    assert execution["orders"][0]["symbol"] == "AAPL"
    assert execution["fills"] == []

    detail = client.get(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}").json()
    assert [item["execution_id"] for item in detail["executions"]] == [
        execution["execution_id"]
    ]
    account = client.get("/api/paper/account").json()
    assert account["cash"] == pytest.approx(1_000_000.0)
    assert account["positions"] == []
    assert account["pending_orders"] == []


def test_strategy_sleeve_execution_api_processes_pending_plan(
    tmp_path,
    stub_prices,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    pending = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={
            "signal_id": signal.signal_id,
            "execution_window": "next_open",
            "target_date": "2026-06-29",
        },
    ).json()["execution"]

    response = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"execution_window": "next_open", "target_date": "2026-06-29"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["filled_count"] == 1
    assert payload["blocked_count"] == 0
    assert payload["executions"][0]["execution_id"] == pending["execution_id"]
    assert payload["executions"][0]["status"] == "filled"
    assert payload["account"]["cash"] == pytest.approx(950_000.0)
    assert payload["account"]["positions"][0]["symbol"] == "AAPL"
    assert payload["account"]["positions"][0]["quantity"] == pytest.approx(250.0)
    assert payload["account"]["positions"][0]["source_breakdown"] == {
        f"strategy:{sleeve['sleeve_id']}": pytest.approx(1.0)
    }
    assert storage.load_sleeve(sleeve["sleeve_id"]).cash == pytest.approx(0.0)
    assert storage.execution_journal_committed_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()
    assert not storage.execution_journal_pending_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()


def test_strategy_sleeve_detail_is_observational_before_explicit_journal_recovery(
    tmp_path,
    stub_prices,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    pending = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={
            "signal_id": signal.signal_id,
            "execution_window": "next_open",
            "target_date": "2026-06-29",
        },
    ).json()["execution"]
    stale_account = account_storage.load()
    assert stale_account is not None
    interrupted_account = stale_account.model_copy(deep=True)
    PaperStrategyExecutionService(
        storage=storage,
        price_source=InlinePriceSource({"AAPL": 200.0}),
    ).execute_plan(
        interrupted_account,
        sleeve=storage.load_sleeve(sleeve["sleeve_id"]),
        plan=storage.load_executions(sleeve["sleeve_id"])[0],
    )
    assert account_storage.load().positions == {}
    before = _file_tree_snapshot(tmp_path)

    detail = client.get(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}")

    assert detail.status_code == 200
    assert detail.json()["executions"][0]["status"] == "filled"
    assert _file_tree_snapshot(tmp_path) == before
    assert storage.execution_journal_pending_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()
    assert not storage.execution_journal_committed_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()
    stale_after_detail = account_storage.load()
    assert stale_after_detail is not None
    assert stale_after_detail.cash == pytest.approx(1_000_000.0)
    assert stale_after_detail.positions == {}

    recovered = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"limit": 1},
    )

    assert recovered.status_code == 200
    reloaded_account = account_storage.load()
    assert reloaded_account is not None
    assert reloaded_account.cash == pytest.approx(950_000.0)
    assert reloaded_account.positions["AAPL"].quantity == pytest.approx(250.0)
    assert storage.execution_journal_committed_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()
    assert not storage.execution_journal_pending_path(
        sleeve["sleeve_id"],
        pending["execution_id"],
    ).exists()


def test_strategy_sleeve_execution_api_defaults_to_due_target_date(
    tmp_path,
    stub_prices,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()

    def create_pending(target_date: str) -> dict:
        created = client.post(
            "/api/paper/strategy-sleeves",
            json={
                "strategy_config_id": config["strategy_config_id"],
                "strategy_config_version": config["version"],
                "mode": "allocated",
                "allocated_cash": 50_000.0,
            },
        )
        assert created.status_code == 200
        sleeve = created.json()["sleeve"]
        domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
        signal = StrategySignal.create(
            sleeve=domain_sleeve,
            signal_date="2026-06-26",
            data_provider="futu",
            data_as_of="2026-06-26T20:00:00Z",
            target_weights={"AAPL": 1.0},
            proposed_orders=[
                {
                    "symbol": "AAPL",
                    "side": "buy",
                    "target_weight": 1.0,
                    "current_value": 0.0,
                    "target_value": 50_000.0,
                    "notional_delta": 50_000.0,
                    "reference_price": 200.0,
                    "estimated_quantity": 250.0,
                    "reason": "advisory_only_no_execution",
                    "account_id": domain_sleeve.account_id,
                }
            ],
            status=SignalStatus.GENERATED,
        )
        storage.append_signal(signal)
        response = client.post(
            f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
            json={
                "signal_id": signal.signal_id,
                "execution_window": "next_open",
                "target_date": target_date,
            },
        )
        assert response.status_code == 200
        return response.json()["execution"]

    due_execution = create_pending(today)
    future_execution = create_pending(future)

    response = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"execution_window": "next_open"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["executions"][0]["execution_id"] == due_execution["execution_id"]
    assert storage.load_executions(future_execution["sleeve_id"])[0].status == "pending"


def test_strategy_sleeve_ops_status_reports_due_pending_executions(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    today = date.today().isoformat()
    pending = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={
            "signal_id": signal.signal_id,
            "execution_window": "next_open",
            "target_date": today,
        },
    )
    assert pending.status_code == 200

    response = client.get("/api/paper/strategy-sleeves/ops/status")

    assert response.status_code == 200
    status = response.json()["status"]
    assert status["target_date"] == today
    assert status["sleeve_count"] == 1
    assert status["running_sleeve_count"] == 1
    assert status["pending_execution_count"] == 1
    assert status["pending_due_count"] == 1
    assert status["filled_count"] == 0
    assert status["blocked_count"] == 0
    assert status["recovery_required_count"] == 0
    assert status["pending_journal_count"] == 0


def test_strategy_sleeve_ops_status_does_not_reconcile_or_write_pending_state(
    tmp_path,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    _pending_sleeve, pending_path = _save_orphaned_pending_sleeve(storage)
    before = _file_tree_snapshot(tmp_path)

    response = client.get("/api/paper/strategy-sleeves/ops/status")

    assert response.status_code == 200
    assert response.json()["status"]["pending_sleeve_count"] == 1
    assert pending_path.exists()
    assert _file_tree_snapshot(tmp_path) == before


def test_strategy_sleeve_list_does_not_reconcile_or_write_pending_state(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    _pending_sleeve, pending_path = _save_orphaned_pending_sleeve(storage)
    before = _file_tree_snapshot(tmp_path)

    response = client.get("/api/paper/strategy-sleeves")

    assert response.status_code == 200
    assert response.json()["sleeves"] == []
    assert pending_path.exists()
    assert _file_tree_snapshot(tmp_path) == before


def test_strategy_sleeve_detail_does_not_reconcile_or_write_pending_state(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    pending_sleeve, pending_path = _save_orphaned_pending_sleeve(storage)
    before = _file_tree_snapshot(tmp_path)

    response = client.get(
        f"/api/paper/strategy-sleeves/{pending_sleeve.sleeve_id}"
    )

    assert response.status_code == 404
    assert pending_path.exists()
    assert _file_tree_snapshot(tmp_path) == before


def test_strategy_sleeve_ops_status_counts_corrupt_journal_without_renaming_it(
    tmp_path,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    journal_path = storage.execution_journal_pending_path(
        "sleeve-corrupt",
        "exec-corrupt",
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_bytes(b"{not-json")
    before = _file_tree_snapshot(tmp_path)

    response = client.get("/api/paper/strategy-sleeves/ops/status")

    assert response.status_code == 200
    assert response.json()["status"]["pending_journal_count"] == 1
    assert journal_path.read_bytes() == b"{not-json"
    assert _file_tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("db_mode", ["file", "mirror", "canonical"])
@pytest.mark.parametrize("surface", ["list", "detail", "ops-status"])
def test_strategy_sleeve_gets_do_not_open_account_repository(
    tmp_path,
    monkeypatch,
    db_mode,
    surface,
) -> None:
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", db_mode)
    reload_settings()

    def fail_postgres_repository(*_args, **_kwargs):
        raise AssertionError("read-only strategy GET opened the account repository")

    monkeypatch.setattr(
        "quant_system.execution.account_repository_factory.PostgresPaperAccountRepository",
        fail_postgres_repository,
    )
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(storage).create_sleeve(
        PaperAccount.open_new(initial_cash=100_000.0),
        config=config,
        mode=StrategySleeveMode.SIGNAL_ONLY,
    )
    storage.save_sleeve(sleeve)
    client = TestClient(create_app(output_dir=tmp_path))
    before = _file_tree_snapshot(tmp_path)
    path = {
        "list": "/api/paper/strategy-sleeves",
        "detail": f"/api/paper/strategy-sleeves/{sleeve.sleeve_id}",
        "ops-status": "/api/paper/strategy-sleeves/ops/status",
    }[surface]

    response = client.get(path)

    assert response.status_code == 200
    assert _file_tree_snapshot(tmp_path) == before
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    reload_settings()


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/paper/strategy-configs", 200),
        ("/api/paper/strategy-sleeves", 200),
        ("/api/paper/strategy-sleeves/ops/status", 200),
        ("/api/paper/strategy-sleeves/missing-sleeve", 404),
    ],
)
def test_strategy_read_surfaces_do_not_materialize_missing_storage(
    tmp_path,
    path,
    expected_status,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(path)

    assert response.status_code == expected_status
    assert not (tmp_path / "api_runs" / "paper_account").exists()
    assert not (tmp_path / "api_runs" / "paper_strategy_sleeves").exists()


def test_strategy_sleeve_ops_status_rejects_invalid_target_date(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/paper/strategy-sleeves/ops/status",
        params={"target_date": "2026/06/29"},
    )

    assert response.status_code == 422


def test_strategy_sleeve_execution_api_created_without_target_date_is_due_today(
    tmp_path,
    stub_prices,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    pending = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={"signal_id": signal.signal_id, "execution_window": "next_open"},
    )
    assert pending.status_code == 200
    execution = pending.json()["execution"]
    assert execution["target_date"] == date.today().isoformat()

    response = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"execution_window": "next_open"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["executions"][0]["execution_id"] == execution["execution_id"]
    assert payload["executions"][0]["status"] == "filled"


def test_strategy_sleeve_execution_api_rejects_invalid_target_date(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    create_response = client.post(
        "/api/paper/strategy-sleeves/sleeve-test/executions",
        json={
            "signal_id": "signal-test",
            "execution_window": "next_open",
            "target_date": "2026/06/29",
        },
    )
    process_response = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"execution_window": "next_open", "target_date": "2026/06/29"},
    )

    assert create_response.status_code == 422
    assert process_response.status_code == 422


def test_strategy_sleeve_signal_api_rejects_stopped_sleeves(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    sleeve = client.post(
        "/api/paper/strategy-sleeves",
        json={"strategy_config_id": config["strategy_config_id"], "mode": "signal_only"},
    ).json()["sleeve"]
    client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/stop",
        json={"reason": "done"},
    )

    response = client.post(f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/signals")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "strategy_sleeve_stopped"


def test_strategy_sleeve_signal_api_does_not_create_account_file(
    tmp_path, monkeypatch
) -> None:
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve = make_sleeve(config, mode=StrategySleeveMode.SIGNAL_ONLY)
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        f"/api/paper/strategy-sleeves/{sleeve.sleeve_id}/signals",
        json={"signal_date": "2024-03-20", "history_days": 90},
    )

    assert response.status_code == 200
    assert response.json()["signal"]["status"] == "generated"
    assert PaperAccountStorage(tmp_path / "api_runs").account_path.exists() is False


def test_legacy_account_rebalance_route_is_not_strategy_sleeve_entrypoint(
    tmp_path, stub_prices, monkeypatch
) -> None:
    def fake_targets(self, **_kwargs):
        return {"MSFT": 1.0}, "2024-01-02T00:00:00Z"

    monkeypatch.setattr(
        "quant_system.execution.account_service.PaperAccountService._compute_target_weights",
        fake_targets,
    )
    client = TestClient(create_app(output_dir=tmp_path))
    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 10})
    before = client.get("/api/paper/account").json()
    assert before["positions"][0]["symbol"] == "AAPL"

    response = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["MSFT"], "top_n": 1},
    )

    assert response.status_code == 200
    positions = response.json()["account"]["positions"]
    assert {position["symbol"] for position in positions} == {"MSFT"}
    assert client.get("/api/paper/strategy-sleeves").json()["sleeves"] == []


def test_legacy_account_rebalance_rejects_existing_strategy_sleeve_positions(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    def fake_targets(self, **_kwargs):  # noqa: ARG001
        return {"MSFT": 1.0}, "2024-01-02T00:00:00Z"

    monkeypatch.setattr(
        "quant_system.execution.account_service.PaperAccountService._compute_target_weights",
        fake_targets,
    )
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)
    created = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "strategy_config_version": config["version"],
            "mode": "allocated",
            "allocated_cash": 50_000.0,
        },
    )
    assert created.status_code == 200
    sleeve = created.json()["sleeve"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    domain_sleeve = storage.load_sleeve(sleeve["sleeve_id"])
    signal = StrategySignal.create(
        sleeve=domain_sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        data_as_of="2026-06-26T20:00:00Z",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "target_weight": 1.0,
                "current_value": 0.0,
                "target_value": 50_000.0,
                "notional_delta": 50_000.0,
                "reference_price": 200.0,
                "estimated_quantity": 250.0,
                "reason": "advisory_only_no_execution",
                "account_id": domain_sleeve.account_id,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    storage.append_signal(signal)
    pending = client.post(
        f"/api/paper/strategy-sleeves/{sleeve['sleeve_id']}/executions",
        json={"signal_id": signal.signal_id, "execution_window": "next_open"},
    )
    assert pending.status_code == 200
    processed = client.post(
        "/api/paper/strategy-sleeves/executions/process",
        json={"execution_window": "next_open"},
    )
    assert processed.status_code == 200
    assert processed.json()["filled_count"] == 1

    response = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["MSFT"], "top_n": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "strategy_sleeve_positions_present"
    account = client.get("/api/paper/account").json()
    assert account["positions"][0]["symbol"] == "AAPL"
    assert storage.load_sleeve_lots(sleeve["sleeve_id"])[0].symbol == "AAPL"
