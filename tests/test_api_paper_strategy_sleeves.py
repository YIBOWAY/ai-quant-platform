from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.price_source import PricedQuote


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


def test_strategy_sleeve_api_rolls_back_account_when_sleeve_save_fails(
    tmp_path, monkeypatch
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    config = _create_config(client)

    def fail_save_sleeve(self, sleeve):  # noqa: ARG001
        raise OSError("sleeve disk write failed")

    monkeypatch.setattr(PaperStrategySleeveStorage, "save_sleeve", fail_save_sleeve)

    response = client.post(
        "/api/paper/strategy-sleeves",
        json={
            "strategy_config_id": config["strategy_config_id"],
            "mode": "allocated",
            "allocated_cash": 250_000.0,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "strategy_sleeve_storage_error"
    assert client.get("/api/paper/strategy-sleeves").json()["sleeves"] == []
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert account.sleeve_cash == {"manual": 1_000_000.0}
    assert [entry.kind for entry in account.ledger] == ["deposit"]


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
