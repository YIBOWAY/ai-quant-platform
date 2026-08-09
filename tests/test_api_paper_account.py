from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import (
    DatabaseSettings,
    PaperAccountSettings,
    SafetySettings,
    Settings,
)
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.price_source import PricedQuote


@pytest.fixture
def stub_prices(monkeypatch) -> dict[str, float]:
    """Patch PaperPriceSource so account endpoints never touch OpenD/network."""
    prices = {"AAPL": 200.0, "MSFT": 100.0, "SPY": 470.0, "QQQ": 400.0}

    def fake_get_price(self, symbol, **_kwargs):
        symbol = symbol.upper().strip()
        if symbol not in prices:
            from quant_system.execution.price_source import PriceUnavailableError

            raise PriceUnavailableError(symbol)
        return PricedQuote(
            symbol=symbol,
            price=prices[symbol],
            price_kind="futu_snapshot",
            as_of="2024-01-02T00:00:00Z",
            source="stub",
        )

    def fake_get_prices(self, symbols, **_kwargs):
        out = {}
        for s in symbols:
            with contextlib.suppress(Exception):
                out[s.upper().strip()] = fake_get_price(self, s)
        return out

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price", fake_get_price
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_prices", fake_get_prices
    )
    return prices


def test_account_opens_with_one_million(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account")

    assert response.status_code == 200
    account = response.json()
    assert account["initial_cash"] == 1_000_000.0
    assert account["cash"] == 1_000_000.0
    assert account["equity"] == 1_000_000.0
    assert account["positions"] == []
    assert account["kill_switch"] is False


def test_manual_order_updates_account_and_position_map(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    order = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 100},
    )
    assert order.status_code == 200
    payload = order.json()
    assert payload["order"]["status"] == "filled"
    assert payload["order"]["price_kind"] == "futu_snapshot"

    account = payload["account"]
    assert account["cash"] == pytest.approx(1_000_000.0 - 20_000.0)
    assert len(account["positions"]) == 1
    pos = account["positions"][0]
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] == pytest.approx(100)
    assert pos["source_breakdown"]["manual"] == pytest.approx(1.0)
    assert pos["price_kind"] == "futu_snapshot"
    assert pos["price_as_of"] == "2024-01-02T00:00:00Z"

    # Account persists across requests.
    again = client.get("/api/paper/account").json()
    assert again["positions"][0]["symbol"] == "AAPL"


def test_notional_order_sizes_by_price(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    order = client.post(
        "/api/paper/account/orders",
        json={"symbol": "MSFT", "side": "buy", "notional": 5_000},
    )
    assert order.status_code == 200
    assert order.json()["order"]["filled_quantity"] == pytest.approx(50)


def test_order_rejects_both_quantity_and_notional(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    order = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1, "notional": 100},
    )
    assert order.status_code == 422  # pydantic model validator


def test_kill_switch_freezes_account(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    toggled = client.post("/api/paper/account/kill-switch", json={"enabled": True})
    assert toggled.status_code == 200
    assert toggled.json()["kill_switch"] is True

    blocked = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )
    assert blocked.status_code == 409


def test_account_reset_archives_and_restores(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 10})
    reset = client.post("/api/paper/account/reset", json={"initial_cash": 1_000_000.0})

    assert reset.status_code == 200
    assert reset.json()["positions"] == []
    assert reset.json()["cash"] == 1_000_000.0


def test_ledger_records_orders_newest_first(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 5})
    client.post("/api/paper/account/orders", json={"symbol": "MSFT", "side": "buy", "quantity": 5})

    ledger = client.get("/api/paper/account/ledger").json()
    assert ledger["total"] >= 3  # open deposit + 2 fills
    # newest first: MSFT fill should precede AAPL fill
    symbols = [e.get("symbol") for e in ledger["entries"] if e.get("kind") == "fill"]
    assert symbols[0] == "MSFT"


def test_account_activity_groups_tabs_from_ledger(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    filled = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5},
    )
    assert filled.status_code == 200
    queued = client.post(
        "/api/paper/account/orders",
        json={"symbol": "MSFT", "side": "buy", "quantity": 3, "limit_price": 50.0},
    )
    assert queued.status_code == 200
    queued_order_id = queued.json()["order"]["order_id"]

    activity = client.get("/api/paper/account/activity").json()
    assert activity["account"]["positions"][0]["symbol"] == "AAPL"
    assert activity["pending_order_total"] == 1
    assert activity["pending_orders"][0]["order_id"] == queued_order_id
    assert activity["order_history_total"] >= 1
    assert activity["order_history"][0]["status"] == "filled"
    assert activity["order_history"][0]["symbol"] == "AAPL"
    assert activity["balance_history_total"] >= 2
    assert activity["balance_history"][0]["cash_after"] == pytest.approx(999_000.0)
    assert activity["trade_log_total"] >= activity["balance_history_total"]

    cancelled = client.post(f"/api/paper/account/orders/{queued_order_id}/cancel")
    assert cancelled.status_code == 200
    after_cancel = client.get("/api/paper/account/activity").json()
    assert after_cancel["pending_order_total"] == 0
    assert after_cancel["order_history"][0]["status"] == "cancelled"
    assert after_cancel["order_history"][0]["order_id"] == queued_order_id


def test_account_equity_curve_does_not_open_missing_account(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account/equity-curve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_exists"] is False
    assert payload["points"] == []
    assert PaperAccountStorage(tmp_path / "api_runs").load() is None


def test_account_snapshot_does_not_open_missing_account(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_exists"] is False
    assert payload["account"] is None
    assert PaperAccountStorage(tmp_path / "api_runs").load() is None


def test_account_snapshot_reads_existing_account(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 3},
    )

    response = client.get("/api/paper/account/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_exists"] is True
    account = payload["account"]
    assert account["account_id"] == "default"
    assert account["positions"][0]["symbol"] == "AAPL"
    assert account["positions"][0]["quantity"] == pytest.approx(3)


def test_account_repository_factory_selects_configured_mode(tmp_path) -> None:
    from quant_system.execution.account_dual_write_repository import (
        DualWritePaperAccountRepository,
    )
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )

    file_repository = build_paper_account_repository(
        tmp_path,
        settings=Settings(paper_account=PaperAccountSettings(db_mode="file")),
    )
    mirror_repository = build_paper_account_repository(
        tmp_path,
        settings=Settings(paper_account=PaperAccountSettings(db_mode="mirror")),
    )
    canonical_repository = build_paper_account_repository(
        tmp_path,
        settings=Settings(paper_account=PaperAccountSettings(db_mode="canonical")),
    )

    assert isinstance(file_repository, PaperAccountStorage)
    assert isinstance(mirror_repository, DualWritePaperAccountRepository)
    assert isinstance(canonical_repository, PostgresPaperAccountRepository)
    assert not isinstance(canonical_repository, PaperAccountStorage)
    assert canonical_repository.source == "api_canonical"


def test_paper_account_canonical_mode_rejects_mutation_when_db_unavailable(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    class UnavailablePostgres(PostgresPaperAccountRepository):
        def available_for_mutation(self) -> bool:
            return False

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        UnavailablePostgres,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(enabled=False, url=None),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "paper_account_database_unavailable"

    reset_response = client.post(
        "/api/paper/account/reset",
        json={"initial_cash": 1000.0},
    )
    assert reset_response.status_code == 503
    assert reset_response.json()["detail"]["code"] == "paper_account_database_unavailable"


def test_paper_account_canonical_mode_maps_midflight_save_failure_to_503(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account import PaperAccount
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    class FlakyPostgres(PostgresPaperAccountRepository):
        def available_for_mutation(self) -> bool:
            return True

        def load_or_open(self, *, initial_cash: float = 1_000_000.0):
            return PaperAccount.open_new(
                account_id=self.account_id,
                initial_cash=initial_cash,
            )

        def save(self, account, **_kwargs):
            raise RuntimeError(
                "PostgreSQL database is unavailable for paper account canonical save"
            )

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        FlakyPostgres,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(enabled=True, url="postgresql://user:pass@localhost:5432/tmp"),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "paper_account_database_unavailable"


def test_paper_account_canonical_get_open_maps_db_failure_to_503(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    class FailingLoadOpen(PostgresPaperAccountRepository):
        def load_or_open(self, *, initial_cash: float = 1_000_000.0):
            raise RuntimeError("PostgreSQL database is unavailable for paper account load")

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        FailingLoadOpen,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(enabled=False, url=None),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    response = client.get("/api/paper/account")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "paper_account_database_unavailable"


def test_paper_account_canonical_get_missing_requires_explicit_bootstrap(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )
    from quant_system.execution.account_repository import (
        PaperAccountBootstrapRequired,
    )

    class MissingCanonical(PostgresPaperAccountRepository):
        @contextlib.contextmanager
        def mutation_lock(self, **_kwargs):
            yield

        def load_or_open(self, *, initial_cash: float = 1_000_000.0):
            del initial_cash
            raise PaperAccountBootstrapRequired(self.account_id)

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        MissingCanonical,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://user:pass@localhost:5432/tmp",
        ),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/paper/account")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paper_account_bootstrap_required"


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/paper/account",
        "/api/paper/account/activity",
        "/api/paper/account/ledger",
    ],
)
def test_paper_account_canonical_get_maps_corrupt_raw_to_stable_503(
    tmp_path,
    monkeypatch,
    endpoint,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )
    from quant_system.execution.account_repository import PaperAccountStorageCorrupt

    class CorruptCanonical(PostgresPaperAccountRepository):
        @contextlib.contextmanager
        def mutation_lock(self, **_kwargs):
            yield

        def load_or_open(self, *, initial_cash: float = 1_000_000.0):
            del initial_cash
            raise PaperAccountStorageCorrupt(self.account_id)

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        CorruptCanonical,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://user:pass@localhost:5432/tmp",
        ),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(endpoint)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "paper_account_storage_corrupt"


def test_mirror_mode_order_response_stays_file_canonical_when_postgres_fails(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory

    failures: list[str] = []

    class FailingPostgresRepository:
        def __init__(
            self,
            *,
            settings,
            account_id: str = "default",
            source: str = "api_dual_write",
        ) -> None:
            self.settings = settings
            self.account_id = account_id
            self.source = source

        def save(self, account, **_kwargs):
            failures.append(account.account_id)
            raise RuntimeError("mirror database unavailable")

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        FailingPostgresRepository,
        raising=False,
    )
    settings = Settings(
        database=DatabaseSettings(enabled=False, url=None),
        paper_account=PaperAccountSettings(db_mode="mirror"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"order", "account", "safety"}
    assert payload["account"]["storage_mode"] == "mirror"
    assert payload["account"]["stale"] is True
    assert set(payload["account"]["warnings"]) >= {
        "paper_account_db_mirror_unavailable",
        "paper_account_reconciliation_unavailable",
    }
    assert payload["account"]["reconciliation"]["status"] == "unavailable"
    assert payload["account"]["positions"][0]["quantity"] == pytest.approx(2)
    assert failures == ["default", "default"]

    persisted = PaperAccountStorage(tmp_path / "api_runs").load()
    assert persisted is not None
    assert persisted.positions["AAPL"].quantity == pytest.approx(2)


def test_account_equity_curve_replays_ledger_and_current_mark(
    tmp_path,
    stub_prices,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 100},
    )
    stub_prices["AAPL"] = 210.0

    response = client.get("/api/paper/account/equity-curve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_exists"] is True
    assert payload["account_id"] == "default"
    assert payload["total"] == 3
    assert [point["source"] for point in payload["points"]] == [
        "ledger",
        "ledger",
        "current_quote",
    ]
    deposit, fill, current = payload["points"]
    assert deposit["event_kind"] == "deposit"
    assert deposit["equity"] == pytest.approx(1_000_000.0)
    assert fill["event_kind"] == "fill"
    assert fill["symbol"] == "AAPL"
    assert fill["quantity"] == pytest.approx(100.0)
    assert fill["market_value"] == pytest.approx(20_000.0)
    assert fill["equity"] == pytest.approx(1_000_000.0)
    assert current["event_kind"] == "current"
    assert current["price_source"]["kind"] == "futu_snapshot"
    assert current["market_value"] == pytest.approx(21_000.0)
    assert current["equity"] == pytest.approx(1_001_000.0)


def test_rebalance_applies_strategy_targets_to_account(tmp_path, stub_prices, monkeypatch) -> None:
    # Stub the strategy target computation so the rebalance is deterministic and
    # offline (no factor pipeline / provider needed).
    def fake_targets(self, **_kwargs):
        return {"AAPL": 0.5, "MSFT": 0.5}, "2024-01-02T00:00:00Z"

    monkeypatch.setattr(
        "quant_system.execution.account_service.PaperAccountService._compute_target_weights",
        fake_targets,
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["AAPL", "MSFT"], "top_n": 2},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["rebalance"]["target_weights"] == {"AAPL": 0.5, "MSFT": 0.5}
    account = payload["account"]
    held = {p["symbol"] for p in account["positions"]}
    assert held == {"AAPL", "MSFT"}
    # Each leg ~ 50% of 1,000,000 = 500,000; AAPL@200 -> 2500 sh, MSFT@100 -> 5000 sh
    by_symbol = {p["symbol"]: p for p in account["positions"]}
    assert by_symbol["AAPL"]["quantity"] == pytest.approx(2500, rel=1e-3)
    assert by_symbol["MSFT"]["quantity"] == pytest.approx(5000, rel=1e-3)
    assert by_symbol["AAPL"]["source_breakdown"]["strategy:cross_sectional_top_n"] == pytest.approx(
        1.0
    )

    repeat = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["AAPL", "MSFT"], "top_n": 2},
    )
    assert repeat.status_code == 200


def test_paper_run_still_works_alongside_account(tmp_path, stub_prices) -> None:
    """The legacy historical-replay endpoint must remain functional."""
    settings = Settings(safety=SafetySettings(kill_switch=False))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    run = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "enable_kill_switch": False,
            "lookback": 3,
            "top_n": 1,
        },
    )
    assert run.status_code == 200
    assert "run_id" in run.json()


def test_order_ids_are_unique_across_requests(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 1})
    client.post("/api/paper/account/orders", json={"symbol": "MSFT", "side": "buy", "quantity": 1})
    ledger = client.get("/api/paper/account/ledger").json()
    fill_ids = [e["note"] for e in ledger["entries"] if e["kind"] == "fill"]
    assert len(fill_ids) == 2
    assert len(set(fill_ids)) == 2  # no reuse


def test_limit_price_queues_unfavorable_fill_and_later_fills(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    # AAPL stub price is 200; a $150 limit buy should wait for a later check.
    blocked = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 150.0},
    ).json()
    assert blocked["order"]["status"] == "pending"
    assert blocked["order"]["filled_quantity"] == 0
    assert "queued" in blocked["order"]["rejected_reason"]
    assert blocked["account"]["positions"] == []
    assert len(blocked["account"]["pending_orders"]) == 1
    pending_order = blocked["account"]["pending_orders"][0]
    assert pending_order["symbol"] == "AAPL"
    assert pending_order["reserved_cash"] == pytest.approx(750.0)
    assert pending_order["reserved_quantity"] == pytest.approx(0.0)
    assert blocked["account"]["reserved_cash"] == pytest.approx(750.0)
    assert blocked["account"]["available_cash"] == pytest.approx(999_250.0)

    persisted = client.get("/api/paper/account").json()
    assert len(persisted["pending_orders"]) == 1
    assert persisted["available_cash"] == pytest.approx(999_250.0)

    stub_prices["AAPL"] = 140.0
    processed = client.post("/api/paper/account/orders/process").json()
    assert processed["orders"][0]["status"] == "filled"
    assert processed["account"]["pending_orders"] == []
    assert processed["account"]["reserved_cash"] == pytest.approx(0.0)
    assert processed["account"]["positions"][0]["symbol"] == "AAPL"
    assert processed["account"]["positions"][0]["quantity"] == pytest.approx(5)

    # A generous limit fills.
    ok = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 500.0},
    ).json()
    assert ok["order"]["status"] == "filled"


def test_pending_order_processor_does_not_open_missing_account(tmp_path, stub_prices) -> None:
    from quant_system.api.routes.paper import process_pending_account_orders_once

    outcomes = process_pending_account_orders_once(
        tmp_path / "api_runs",
        Settings(),
    )

    assert outcomes == []
    assert PaperAccountStorage(tmp_path / "api_runs").load() is None


def test_pending_order_processor_fills_existing_pending_order(tmp_path, stub_prices) -> None:
    from quant_system.api.routes.paper import process_pending_account_orders_once

    client = TestClient(create_app(output_dir=tmp_path))
    queued = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 150.0},
    ).json()
    assert queued["order"]["status"] == "pending"

    stub_prices["AAPL"] = 140.0
    outcomes = process_pending_account_orders_once(
        tmp_path / "api_runs",
        Settings(),
    )

    assert [outcome.status for outcome in outcomes] == ["filled"]
    account = client.get("/api/paper/account").json()
    assert account["pending_orders"] == []
    assert account["positions"][0]["symbol"] == "AAPL"
    assert account["positions"][0]["quantity"] == pytest.approx(5)


def test_api_startup_schedules_pending_order_processor_when_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    settings = Settings(
        paper_account=PaperAccountSettings(
            auto_process_pending_orders_enabled=True,
            auto_process_interval_seconds=5.0,
        )
    )
    scheduled: list[tuple[Settings, object]] = []
    joined: list[float] = []

    class FakeStopEvent:
        def __init__(self) -> None:
            self.set_called = False

        def set(self) -> None:
            self.set_called = True

    class FakeThread:
        def join(self, timeout=None) -> None:
            joined.append(timeout)

    stop_event = FakeStopEvent()

    def fake_start(active_settings, api_runs_dir):
        scheduled.append((active_settings, api_runs_dir))
        return stop_event, FakeThread()

    monkeypatch.setattr(
        api_server,
        "_start_paper_account_pending_order_processor",
        fake_start,
    )

    with TestClient(create_app(settings=settings, output_dir=tmp_path)):
        pass

    assert len(scheduled) == 1
    assert scheduled[0][0] is settings
    assert stop_event.set_called is True
    assert joined == [1.0]


def test_pending_limit_order_can_be_cancelled(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    queued = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 150.0},
    ).json()
    order_id = queued["order"]["order_id"]

    cancelled = client.post(f"/api/paper/account/orders/{order_id}/cancel")

    assert cancelled.status_code == 200
    payload = cancelled.json()
    assert payload["order"]["status"] == "cancelled"
    assert payload["order"]["order_id"] == order_id
    assert payload["account"]["positions"] == []
    assert payload["account"]["pending_orders"] == []

    ledger = client.get("/api/paper/account/ledger").json()
    assert ledger["entries"][0]["kind"] == "order_cancelled"
    assert ledger["entries"][0]["symbol"] == "AAPL"
    assert order_id in ledger["entries"][0]["note"]

    missing = client.post(f"/api/paper/account/orders/{order_id}/cancel")
    assert missing.status_code == 404


def test_manual_order_reports_partial_fill(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )

    response = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "sell", "quantity": 2},
    ).json()

    assert response["order"]["status"] == "partially_filled"
    assert response["order"]["filled_quantity"] == pytest.approx(1)
    assert response["account"]["positions"] == []


def test_persistent_account_rebalance_rejects_sample_history(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/rebalance",
        json={
            "strategy_id": "cross_sectional_top_n",
            "symbols": ["AAPL"],
            "top_n": 1,
            "provider": "sample",
        },
    )

    assert response.status_code == 422


def test_account_rebalance_rejects_strategy_without_account_support(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/rebalance",
        json={
            "strategy_id": "reversal_momentum",
            "symbols": ["AAPL"],
            "top_n": 1,
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "unsupported_account_rebalance_strategy"
    assert "does not support account rebalance" in detail["message"]


def test_concurrent_orders_do_not_lose_updates(tmp_path, stub_prices) -> None:
    import threading

    client = TestClient(create_app(output_dir=tmp_path))
    responses = []
    errors = []

    def buy() -> None:
        try:
            responses.append(
                client.post(
                    "/api/paper/account/orders",
                    json={"symbol": "MSFT", "side": "buy", "quantity": 1},
                )
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=buy) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(responses) == 12
    assert all(response.status_code == 200 for response in responses)
    account = client.get("/api/paper/account").json()
    msft = [p for p in account["positions"] if p["symbol"] == "MSFT"]
    assert msft and msft[0]["quantity"] == pytest.approx(12)


def test_rapid_resets_archive_each_account(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    for _ in range(3):
        client.post(
            "/api/paper/account/orders",
            json={"symbol": "AAPL", "side": "buy", "quantity": 1},
        )
        client.post("/api/paper/account/reset", json={"initial_cash": 1_000_000})
    archive = list((tmp_path / "api_runs" / "paper_account" / "default" / "archive").glob("*.json"))
    assert len(archive) == 3


def test_positions_snapshot_has_valuation_columns(tmp_path, stub_prices) -> None:
    import pandas as pd

    client = TestClient(create_app(output_dir=tmp_path))
    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 10})
    snap = tmp_path / "api_runs" / "paper_account" / "default" / "positions_snapshot.parquet"
    cols = set(pd.read_parquet(snap).columns)
    assert {
        "last_price",
        "market_value",
        "weight",
        "unrealized_pnl",
        "source_breakdown",
        "price_kind",
        "price_as_of",
    } <= cols


def test_account_reports_price_source_per_position(tmp_path, stub_prices, monkeypatch) -> None:
    from quant_system.execution.price_source import PricedQuote

    def mixed_price(self, symbol, **_kwargs):
        symbol = symbol.upper().strip()
        return PricedQuote(
            symbol=symbol,
            price=stub_prices[symbol],
            price_kind="futu_snapshot" if symbol == "AAPL" else "last_close",
            as_of="2024-01-02T00:00:00Z",
            source="stub",
        )

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        mixed_price,
    )
    client = TestClient(create_app(output_dir=tmp_path))
    client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 1})
    response = client.post(
        "/api/paper/account/orders",
        json={"symbol": "MSFT", "side": "buy", "quantity": 1},
    ).json()["account"]

    assert response["price_source"] == {"kind": "mixed", "as_of": None}
    kinds = {position["symbol"]: position["price_kind"] for position in response["positions"]}
    assert kinds == {"AAPL": "futu_snapshot", "MSFT": "last_close"}


def test_rebalance_aborts_without_mutation_when_a_leg_is_rejected(
    tmp_path, stub_prices, monkeypatch
) -> None:
    monkeypatch.setattr(
        "quant_system.execution.account_service.PaperAccountService._compute_target_weights",
        lambda self, **kw: ({"MSFT": 1.0}, "2024-01-02T00:00:00Z"),
    )
    client = TestClient(create_app(output_dir=tmp_path))
    client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "notional": 500000},
    )
    before = client.get("/api/paper/account").json()
    before_aapl = next(p for p in before["positions"] if p["symbol"] == "AAPL")["quantity"]

    # Trigger abort by making MSFT price unavailable so get_prices() omits it,
    # leaving 0 prices for the buy leg → quantity stays in requests but price
    # lookup returns None → _rebalance_requests skips (price is None).
    # More reliably: patch _execute_single on the service to return rejected
    # for any BUY on the trial copy, verifying abort-then-restore.
    from quant_system.execution.account_service import OrderOutcome, PaperAccountService

    original_execute = PaperAccountService._execute_single

    call_count = {"n": 0}

    def reject_second_call(self, *, account, symbol, side, **kwargs):
        call_count["n"] += 1
        # The trial run calls _execute_single for each leg; reject the first BUY.
        from quant_system.execution.models import OrderSide

        if side == OrderSide.BUY and call_count["n"] <= 2:
            return OrderOutcome(
                status="rejected",
                symbol=symbol,
                side=str(side),
                requested_quantity=kwargs.get("quantity", 0),
                filled_quantity=0.0,
                price=kwargs.get("price", 0.0),
                price_kind=kwargs.get("price_kind", "stub"),
                rejected_reason="forced reject for test",
            )
        return original_execute(self, account=account, symbol=symbol, side=side, **kwargs)

    monkeypatch.setattr(PaperAccountService, "_execute_single", reject_second_call)
    resp = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["MSFT"], "top_n": 1},
    ).json()

    assert resp["rebalance"]["aborted"] is True
    after = client.get("/api/paper/account").json()
    after_aapl = next(p for p in after["positions"] if p["symbol"] == "AAPL")["quantity"]
    # The original AAPL position is preserved — NOT sold into all-cash.
    assert after_aapl == pytest.approx(before_aapl)


def test_rebalance_reports_unavailable_prices_without_server_error(
    tmp_path, stub_prices, monkeypatch
) -> None:
    from quant_system.execution.price_source import PriceUnavailableError

    monkeypatch.setattr(
        "quant_system.execution.account_service.PaperAccountService._compute_target_weights",
        lambda self, **kw: ({"AAPL": 1.0}, "2024-01-02T00:00:00Z"),
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_prices",
        lambda self, symbols, **kw: (_ for _ in ()).throw(
            PriceUnavailableError("no real quote available")
        ),
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/account/rebalance",
        json={"strategy_id": "cross_sectional_top_n", "symbols": ["AAPL"], "top_n": 1},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "price_unavailable"
    assert "no real quote available" in detail["message"]


def test_account_equity_curve_keeps_pre_window_anchor(tmp_path, stub_prices, monkeypatch) -> None:
    """Quiet weeks still show a two-point figure via the last pre-window ledger mark."""
    from datetime import UTC, datetime

    from quant_system.api.routes import paper as paper_routes

    client = TestClient(create_app(output_dir=tmp_path))
    client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 1},
    )

    old_now = datetime(2026, 7, 2, 20, 31, 34, tzinfo=UTC)
    old_now_iso = old_now.isoformat()
    now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)

    # Age ledger timestamps so they fall outside the default 7-day window.
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = storage.load()
    assert account is not None
    aged = []
    for entry in account.ledger:
        data = entry.model_dump(mode="python")
        data["timestamp"] = old_now_iso
        aged.append(type(entry)(**data))
    account.ledger = aged
    storage.save(account, prices={"AAPL": 210.0})

    real_datetime = paper_routes.datetime

    class _FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(paper_routes, "datetime", _FrozenDateTime)
    stub_prices["AAPL"] = 210.0

    response = client.get("/api/paper/account/equity-curve?days=7")
    assert response.status_code == 200
    payload = response.json()
    sources = [point["source"] for point in payload["points"]]
    assert sources[0] == "ledger"
    assert sources[-1] == "current_quote"
    assert payload["total"] >= 2


def test_account_performance_rejects_unknown_range(tmp_path, stub_prices) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/paper/account/performance",
        params={"range": "1y", "granularity": "1d", "benchmarks": "SPY,QQQ"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("range_key", "now", "expected_start", "expected_end"),
    [
        (
            "1m",
            datetime(2026, 3, 31, 21, 0, tzinfo=UTC),
            "2026-02-28",
            "2026-03-31",
        ),
        (
            "3m",
            datetime(2026, 7, 31, 21, 0, tzinfo=UTC),
            "2026-04-30",
            "2026-07-31",
        ),
    ],
)
def test_account_performance_uses_calendar_month_boundaries(
    tmp_path,
    monkeypatch,
    range_key,
    now,
    expected_start,
    expected_end,
) -> None:
    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [{"date": kwargs["end"], "close": 100.0}]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at=now.isoformat(),
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": 1,
                    "first_date": rows[0]["date"],
                    "last_date": rows[0]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: now,
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/paper/account/performance",
        params={"range": range_key, "granularity": "1d", "benchmarks": "SPY,QQQ"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["range"] == range_key
    assert payload["requested_start"] == expected_start
    assert payload["requested_end"] == expected_end


def test_account_performance_aligns_paper_spy_and_qqq_on_common_sessions(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    assert client.get("/api/paper/account").status_code == 200
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = storage.load()
    assert account is not None
    opened_at = "2026-07-20T20:00:00+00:00"
    account.created_at = opened_at
    account.updated_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    storage.save(account)

    closes = {
        "SPY": [
            ("2026-07-22", 620.0),
            ("2026-07-23", 626.2),
            ("2026-07-24", 623.1),
            ("2026-07-27", 632.4),
        ],
        "QQQ": [
            ("2026-07-22", 550.0),
            ("2026-07-23", 555.5),
            ("2026-07-24", 561.0),
            ("2026-07-27", 566.5),
        ],
    }

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [
            {"date": session_date, "close": close}
            for session_date, close in closes[symbol]
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )

    response = client.get(
        "/api/paper/account/performance",
        params={"range": "7d", "granularity": "1d", "benchmarks": "SPY,QQQ"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_exists"] is True
    assert payload["range"] == "7d"
    assert payload["granularity"] == "1d"
    assert payload["requested_start"] == "2026-07-21"
    assert payload["requested_end"] == "2026-07-27"
    assert payload["actual_start"] == "2026-07-22"
    assert payload["actual_end"] == "2026-07-27"
    assert payload["coverage_complete"] is True
    series = {item["id"]: item for item in payload["series"]}
    assert set(series) == {"paper", "SPY", "QQQ"}
    assert [point["date"] for point in series["paper"]["points"]] == [
        "2026-07-22",
        "2026-07-23",
        "2026-07-24",
        "2026-07-27",
    ]
    assert [point["return_ratio"] for point in series["paper"]["points"]] == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]
    assert series["SPY"]["points"][0]["return_ratio"] == 0.0
    assert series["SPY"]["points"][-1]["return_ratio"] == pytest.approx(
        632.4 / 620.0 - 1.0
    )
    assert series["QQQ"]["points"][0]["return_ratio"] == 0.0
    assert series["QQQ"]["points"][-1]["return_ratio"] == pytest.approx(
        566.5 / 550.0 - 1.0
    )


def test_account_performance_replays_fills_commissions_and_daily_marks(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    opened_at = "2026-07-20T20:00:00+00:00"
    account.created_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    account.apply_fill(
        ExecutionFill(
            fill_id="fill-performance",
            order_id="order-performance",
            timestamp=pd.Timestamp("2026-07-23T15:00:00Z"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100.0,
            fill_price=100.0,
            gross_value=10_000.0,
            commission=10.0,
        ),
        source="manual",
        price_kind="futu_snapshot",
    )
    fill_at = "2026-07-23T15:00:00+00:00"
    account.updated_at = fill_at
    account.ledger[-1] = account.ledger[-1].model_copy(update={"timestamp": fill_at})
    PaperAccountStorage(tmp_path / "api_runs").save(account)

    closes = {
        "SPY": [620.0, 626.2, 623.1, 632.4],
        "QQQ": [550.0, 555.5, 561.0, 566.5],
        "AAPL": [100.0, 102.0, 105.0, 110.0],
    }
    sessions = ["2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27"]

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [
            {"date": session_date, "close": close}
            for session_date, close in zip(sessions, closes[symbol], strict=True)
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account/performance")

    assert response.status_code == 200
    paper = next(item for item in response.json()["series"] if item["id"] == "paper")
    assert paper["status"] == "available"
    assert paper["as_of"] == "2026-07-28T01:00:00+00:00"
    assert [point["equity"] for point in paper["points"]] == pytest.approx(
        [1_000_000.0, 1_000_190.0, 1_000_490.0, 1_000_990.0]
    )
    assert paper["points"][-1]["return_ratio"] == pytest.approx(0.00099)


def test_account_performance_neutralizes_external_cash_before_reinvestment_and_at_close(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    opened_at = "2026-07-22T13:00:00+00:00"
    account.created_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    account.apply_fill(
        ExecutionFill(
            fill_id="fill-before-deposit",
            order_id="order-before-deposit",
            timestamp=pd.Timestamp("2026-07-22T14:00:00Z"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            fill_price=100.0,
            gross_value=1_000.0,
            commission=0.0,
        ),
        source="manual",
        price_kind="futu_snapshot",
    )
    account.ledger[-1] = account.ledger[-1].model_copy(
        update={"timestamp": "2026-07-22T14:00:00+00:00"}
    )
    account.cash += 1_000.0
    account.sleeve_cash["manual"] += 1_000.0
    account.record_event(kind="deposit", note="external paper cash")
    account.ledger[-1] = account.ledger[-1].model_copy(
        update={"timestamp": "2026-07-23T13:00:00+00:00"}
    )
    account.apply_fill(
        ExecutionFill(
            fill_id="fill-after-deposit",
            order_id="order-after-deposit",
            timestamp=pd.Timestamp("2026-07-23T14:00:00Z"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            fill_price=100.0,
            gross_value=1_000.0,
            commission=0.0,
        ),
        source="manual",
        price_kind="futu_snapshot",
    )
    account.updated_at = "2026-07-23T14:00:00+00:00"
    account.ledger[-1] = account.ledger[-1].model_copy(
        update={"timestamp": account.updated_at}
    )
    account.cash += 1_000.0
    account.sleeve_cash["manual"] += 1_000.0
    account.record_event(kind="deposit", note="cash added at the completed close")
    account.updated_at = "2026-07-24T20:00:00+00:00"
    account.ledger[-1] = account.ledger[-1].model_copy(
        update={"timestamp": account.updated_at}
    )
    PaperAccountStorage(tmp_path / "api_runs").save(account)

    sessions = ["2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27"]
    closes = {
        "SPY": [100.0, 100.0, 100.0, 100.0],
        "QQQ": [100.0, 100.0, 100.0, 100.0],
        "AAPL": [100.0, 110.0, 121.0, 121.0],
    }

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [
            {"date": session_date, "close": close}
            for session_date, close in zip(sessions, closes[symbol], strict=True)
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )

    response = TestClient(create_app(output_dir=tmp_path)).get(
        "/api/paper/account/performance"
    )

    assert response.status_code == 200
    paper = next(
        item for item in response.json()["series"] if item["id"] == "paper"
    )
    assert paper["status"] == "available"
    assert [point["equity"] for point in paper["points"]] == pytest.approx(
        [1_000.0, 2_200.0, 3_420.0, 3_420.0]
    )
    assert [point["return_ratio"] for point in paper["points"]] == pytest.approx(
        [0.0, 0.1, 0.21, 0.21]
    )


def test_account_performance_keeps_qqq_when_spy_is_unavailable(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    assert client.get("/api/paper/account").status_code == 200
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = storage.load()
    assert account is not None
    opened_at = "2026-07-20T20:00:00+00:00"
    account.created_at = opened_at
    account.updated_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    storage.save(account)

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        if symbol == "SPY":
            raise HistoricalPriceReadError(
                code="historical_prices_provider_unavailable",
                message="Futu OpenD is unavailable",
                provider_code="connection_refused",
            )
        rows = [
            {"date": "2026-07-22", "close": 550.0},
            {"date": "2026-07-23", "close": 555.5},
            {"date": "2026-07-24", "close": 561.0},
            {"date": "2026-07-27", "close": 566.5},
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu_cache",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )

    response = client.get("/api/paper/account/performance")

    assert response.status_code == 200
    payload = response.json()
    series = {item["id"]: item for item in payload["series"]}
    assert series["SPY"]["status"] == "unavailable"
    assert series["SPY"]["error_code"] == "historical_prices_provider_unavailable"
    assert series["SPY"]["points"] == []
    assert series["QQQ"]["status"] == "available"
    assert series["QQQ"]["source"] == "futu_cache"
    assert series["paper"]["status"] == "available"
    assert payload["coverage_complete"] is False
    assert "SPY:historical_prices_provider_unavailable" in payload["warnings"]


def test_account_performance_fails_only_paper_when_position_history_is_missing(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    opened_at = "2026-07-20T20:00:00+00:00"
    account.created_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    account.apply_fill(
        ExecutionFill(
            fill_id="fill-missing-history",
            order_id="order-missing-history",
            timestamp=pd.Timestamp("2026-07-23T15:00:00Z"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            fill_price=100.0,
            gross_value=1_000.0,
            commission=0.0,
        ),
        source="manual",
        price_kind="futu_snapshot",
    )
    fill_at = "2026-07-23T15:00:00+00:00"
    account.updated_at = fill_at
    account.ledger[-1] = account.ledger[-1].model_copy(update={"timestamp": fill_at})
    PaperAccountStorage(tmp_path / "api_runs").save(account)

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        if symbol == "AAPL":
            raise HistoricalPriceReadError(
                code="historical_prices_provider_error",
                message="AAPL history unavailable",
                provider_code="no_data",
            )
        rows = [
            {"date": "2026-07-22", "close": 100.0},
            {"date": "2026-07-23", "close": 101.0},
            {"date": "2026-07-24", "close": 102.0},
            {"date": "2026-07-27", "close": 103.0},
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account/performance")

    assert response.status_code == 200
    payload = response.json()
    series = {item["id"]: item for item in payload["series"]}
    assert series["paper"]["status"] == "unavailable"
    assert series["paper"]["error_code"] == "paper_position_history_unavailable"
    assert series["paper"]["points"] == []
    assert series["SPY"]["status"] == "available"
    assert series["QQQ"]["status"] == "available"
    assert payload["actual_start"] == "2026-07-22"
    assert payload["actual_end"] == "2026-07-27"
    assert payload["coverage_complete"] is False
    assert "paper:paper_position_history_unavailable" in payload["warnings"]


def test_account_performance_does_not_forward_fill_a_missing_held_session(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    opened_at = "2026-07-20T20:00:00+00:00"
    account.created_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    account.apply_fill(
        ExecutionFill(
            fill_id="fill-session-gap",
            order_id="order-session-gap",
            timestamp=pd.Timestamp("2026-07-23T15:00:00Z"),
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            fill_price=100.0,
            gross_value=1_000.0,
            commission=0.0,
        ),
        source="manual",
        price_kind="futu_snapshot",
    )
    fill_at = "2026-07-23T15:00:00+00:00"
    account.updated_at = fill_at
    account.ledger[-1] = account.ledger[-1].model_copy(update={"timestamp": fill_at})
    PaperAccountStorage(tmp_path / "api_runs").save(account)

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [
            {"date": "2026-07-22", "close": 100.0},
            {"date": "2026-07-23", "close": 101.0},
            {"date": "2026-07-24", "close": 102.0},
            {"date": "2026-07-27", "close": 103.0},
        ]
        if symbol == "AAPL":
            rows = [
                {"date": "2026-07-23", "close": 100.0},
                {"date": "2026-07-27", "close": 103.0},
            ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )

    response = TestClient(create_app(output_dir=tmp_path)).get(
        "/api/paper/account/performance"
    )

    assert response.status_code == 200
    payload = response.json()
    series = {item["id"]: item for item in payload["series"]}
    assert series["paper"]["status"] == "unavailable"
    assert series["paper"]["error_code"] == "paper_position_history_unavailable"
    assert series["paper"]["points"] == []
    assert series["SPY"]["status"] == "available"
    assert series["QQQ"]["status"] == "available"
    assert payload["coverage_complete"] is False


def test_account_performance_marks_partial_when_account_starts_inside_window(
    tmp_path,
    stub_prices,
    monkeypatch,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    opened_at = "2026-07-24T15:00:00+00:00"
    account.created_at = opened_at
    account.updated_at = opened_at
    account.ledger[0] = account.ledger[0].model_copy(update={"timestamp": opened_at})
    PaperAccountStorage(tmp_path / "api_runs").save(account)

    closes = {
        "SPY": [620.0, 626.2, 623.1, 632.4],
        "QQQ": [550.0, 555.5, 561.0, 566.5],
    }
    sessions = ["2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27"]

    def fake_history(**kwargs):
        symbol = kwargs["symbols"][0]
        rows = [
            {"date": session_date, "close": close}
            for session_date, close in zip(sessions, closes[symbol], strict=True)
        ]
        return HistoricalPriceSnapshot(
            provider="futu",
            source="futu",
            interval="1d",
            adjustment="qfq",
            start=kwargs["start"],
            end=kwargs["end"],
            fetched_at="2026-07-28T01:00:00+00:00",
            symbols=[symbol],
            series=[
                {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": rows[0]["date"],
                    "last_date": rows[-1]["date"],
                    "rows": rows,
                }
            ],
        )

    monkeypatch.setattr(
        "quant_system.execution.account_performance.read_historical_prices",
        fake_history,
    )
    monkeypatch.setattr(
        "quant_system.execution.account_performance._utc_now",
        lambda: datetime(2026, 7, 28, 13, 0, tzinfo=UTC),
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/account/performance")

    assert response.status_code == 200
    payload = response.json()
    series = {item["id"]: item for item in payload["series"]}
    assert payload["actual_start"] == "2026-07-24"
    assert payload["actual_end"] == "2026-07-27"
    assert payload["coverage_complete"] is False
    assert series["paper"]["status"] == "partial"
    assert [point["date"] for point in series["paper"]["points"]] == [
        "2026-07-24",
        "2026-07-27",
    ]
    assert series["SPY"]["points"][0]["return_ratio"] == 0.0
    assert series["QQQ"]["points"][0]["return_ratio"] == 0.0
    assert "paper:partial_coverage" in payload["warnings"]
