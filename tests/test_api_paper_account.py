from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import SafetySettings, Settings
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
    assert blocked["account"]["pending_orders"][0]["symbol"] == "AAPL"

    persisted = client.get("/api/paper/account").json()
    assert len(persisted["pending_orders"]) == 1

    stub_prices["AAPL"] = 140.0
    processed = client.post("/api/paper/account/orders/process").json()
    assert processed["orders"][0]["status"] == "filled"
    assert processed["account"]["pending_orders"] == []
    assert processed["account"]["positions"][0]["symbol"] == "AAPL"
    assert processed["account"]["positions"][0]["quantity"] == pytest.approx(5)

    # A generous limit fills.
    ok = client.post(
        "/api/paper/account/orders",
        json={"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 500.0},
    ).json()
    assert ok["order"]["status"] == "filled"


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


def test_account_rebalance_rejects_strategy_without_account_support(
    tmp_path, stub_prices
) -> None:
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

    def buy() -> None:
        client.post(
            "/api/paper/account/orders",
            json={"symbol": "MSFT", "side": "buy", "quantity": 1},
        )

    threads = [threading.Thread(target=buy) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

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
    archive = list(
        (tmp_path / "api_runs" / "paper_account" / "default" / "archive").glob("*.json")
    )
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
