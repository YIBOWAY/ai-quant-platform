from __future__ import annotations

import contextlib
import json
import threading
import time
from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import SecretStr

import quant_system.execution.account_storage as account_storage_module
from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_service import (
    AccountFrozenError,
    PaperAccountService,
)
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.models import ExecutionFill, OrderSide
from quant_system.execution.price_source import (
    PaperPriceSource,
    PricedQuote,
    PriceUnavailableError,
)


def _fill(symbol: str, side: OrderSide, qty: float, price: float, commission: float = 0.0):
    return ExecutionFill(
        fill_id=f"f-{symbol}-{side}",
        order_id=f"o-{symbol}",
        timestamp=pd.Timestamp("2024-01-02", tz="UTC"),
        symbol=symbol,
        side=side,
        quantity=qty,
        fill_price=price,
        gross_value=qty * price,
        commission=commission,
    )


class _StubPriceSource:
    """Deterministic price source for tests (no network/OpenD)."""

    def __init__(self, prices: dict[str, float], kind: str = "futu_snapshot") -> None:
        self._prices = {k.upper(): v for k, v in prices.items()}
        self._kind = kind

    def get_price(self, symbol: str, **_kwargs) -> PricedQuote:
        symbol = symbol.upper()
        if symbol not in self._prices:
            from quant_system.execution.price_source import PriceUnavailableError

            raise PriceUnavailableError(symbol)
        return PricedQuote(
            symbol=symbol,
            price=self._prices[symbol],
            price_kind=self._kind,
            as_of="2024-01-02T00:00:00Z",
            source="stub",
        )

    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:
        out = {}
        for s in symbols:
            with contextlib.suppress(Exception):
                out[s.upper()] = self.get_price(s)
        return out

    def get_price_range(self, symbol: str, **_kwargs):
        return None


class _HistoricalRangePriceSource(_StubPriceSource):
    def __init__(self, prices: dict[str, float], *, low: float, high: float) -> None:
        super().__init__(prices)
        self.low = low
        self.high = high
        self.requests: list[tuple[str, str, str]] = []

    def get_price_range(self, symbol: str, *, start: str, end: str):
        symbol = symbol.upper()
        self.requests.append((symbol, start, end))
        return type(
            "HistoricalRange",
            (),
            {
                "symbol": symbol,
                "low": self.low,
                "high": self.high,
                "close": self._prices[symbol],
                "price_kind": "historical_range",
                "source": "stub",
            },
        )()


class _PartialPriceSource(_StubPriceSource):
    """Price source that can omit symbols from bulk quote resolution."""

    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:
        return {
            symbol.upper(): quote
            for symbol in symbols
            if symbol.upper() in self._prices
            for quote in [self.get_price(symbol)]
        }


def test_open_new_account_defaults_to_one_million() -> None:
    account = PaperAccount.open_new()
    assert account.cash == 1_000_000.0
    assert account.initial_cash == 1_000_000.0
    assert account.positions == {}
    assert account.ledger[0].kind == "deposit"


def test_apply_buy_then_sell_tracks_avg_cost_and_realized_pnl() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)

    account.apply_fill(_fill("AAPL", OrderSide.BUY, 100, 100.0), source="manual")
    assert account.position_quantity("AAPL") == 100
    assert account.cash == pytest.approx(90_000.0)
    assert account.positions["AAPL"].avg_cost == pytest.approx(100.0)

    # Second buy at a higher price rolls the average cost.
    account.apply_fill(_fill("AAPL", OrderSide.BUY, 100, 120.0), source="manual")
    assert account.position_quantity("AAPL") == 200
    assert account.positions["AAPL"].avg_cost == pytest.approx(110.0)

    # Sell half at 130 -> realised pnl = 100 * (130 - 110) = 2000.
    account.apply_fill(_fill("AAPL", OrderSide.SELL, 100, 130.0), source="manual")
    assert account.position_quantity("AAPL") == 100
    assert account.realized_pnl == pytest.approx(2_000.0)
    # avg_cost of remaining shares is unchanged by a sell.
    assert account.positions["AAPL"].avg_cost == pytest.approx(110.0)


def test_source_breakdown_merges_manual_and_strategy() -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    account.apply_fill(_fill("MSFT", OrderSide.BUY, 60, 100.0), source="manual")
    account.apply_fill(
        _fill("MSFT", OrderSide.BUY, 40, 100.0), source="strategy:cross_sectional_top_n"
    )
    breakdown = account.positions["MSFT"].source_breakdown()
    assert breakdown["manual"] == pytest.approx(0.6)
    assert breakdown["strategy:cross_sectional_top_n"] == pytest.approx(0.4)


def test_manual_sleeve_cash_tracks_manual_and_legacy_strategy_fills() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    account.sleeve_cash = {"manual": 75_000.0, "sleeve-abc": 25_000.0}

    account.apply_fill(_fill("AAPL", OrderSide.BUY, 10, 100.0), source="manual")
    account.apply_fill(
        _fill("MSFT", OrderSide.BUY, 5, 200.0),
        source="strategy:cross_sectional_top_n",
        kind="rebalance_fill",
    )
    account.apply_fill(
        _fill("NVDA", OrderSide.BUY, 2, 500.0),
        source="strategy:sleeve-abc",
        kind="sleeve_execution_fill",
    )

    assert account.cash == pytest.approx(97_000.0)
    assert account.sleeve_cash["manual"] == pytest.approx(73_000.0)
    assert account.sleeve_cash["sleeve-abc"] == pytest.approx(25_000.0)


def test_stale_manual_sleeve_cash_is_recomputed_on_load() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    payload = account.model_dump(mode="json")
    payload["cash"] = 120_000.0
    payload["sleeve_cash"] = {"manual": 50_000.0, "sleeve-abc": 25_000.0}

    restored = PaperAccount.model_validate(payload)

    assert restored.sleeve_cash["manual"] == pytest.approx(95_000.0)
    assert restored.sleeve_cash["sleeve-abc"] == pytest.approx(25_000.0)


def test_manual_order_via_service_updates_account() -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 200.0}))

    outcome = service.place_manual_order(account, symbol="AAPL", side="buy", quantity=10)

    assert outcome.status == "filled"
    assert outcome.filled_quantity == pytest.approx(10)
    assert outcome.price_kind == "futu_snapshot"
    assert account.position_quantity("AAPL") == pytest.approx(10)
    assert account.cash == pytest.approx(1_000_000.0 - 2_000.0)


def test_manual_order_notional_is_converted_to_quantity() -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"NVDA": 500.0}))

    outcome = service.place_manual_order(account, symbol="NVDA", side="buy", notional=10_000)

    assert outcome.filled_quantity == pytest.approx(20)
    assert account.position_quantity("NVDA") == pytest.approx(20)


def test_unfavorable_limit_order_is_queued() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 200.0}))

    outcome = service.place_manual_order(
        account,
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=1.0,
    )

    assert outcome.status == "pending"
    assert "does not satisfy limit price" in outcome.rejected_reason
    assert "queued" in outcome.rejected_reason
    assert len(account.pending_orders) == 1
    assert account.pending_orders[0].symbol == "AAPL"


def test_pending_buy_limit_order_reserves_cash() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    service = PaperAccountService(
        price_source=_StubPriceSource({"AAPL": 200.0, "MSFT": 500.0})
    )

    pending = service.place_manual_order(
        account,
        symbol="AAPL",
        side="buy",
        quantity=8,
        limit_price=100.0,
    )
    market = service.place_manual_order(account, symbol="MSFT", side="buy", quantity=1)

    assert pending.status == "pending"
    assert account.pending_orders[0].reserved_cash == pytest.approx(800.0)
    assert account.reserved_cash() == pytest.approx(800.0)
    assert account.available_cash() == pytest.approx(0.0)
    assert market.status == "partially_filled"
    assert market.filled_quantity == pytest.approx(0.4)
    assert account.cash == pytest.approx(800.0)

    service.price_source = _StubPriceSource({"AAPL": 90.0})
    outcomes = service.process_pending_orders(account)

    assert outcomes[0].status == "filled"
    assert outcomes[0].filled_quantity == pytest.approx(8)
    assert account.pending_orders == []
    assert account.cash == pytest.approx(80.0)


def test_pending_buy_limit_order_uses_historical_range_backfill() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    price_source = _HistoricalRangePriceSource({"AAPL": 200.0}, low=140.0, high=210.0)
    service = PaperAccountService(price_source=price_source)

    pending = service.place_manual_order(
        account,
        symbol="AAPL",
        side="buy",
        quantity=2,
        limit_price=150.0,
    )
    assert pending.status == "pending"
    account.pending_orders[0].created_at = "2024-01-02T20:00:00+00:00"
    account.pending_orders[0].last_checked_at = "2024-01-02T20:00:00+00:00"

    outcomes = service.process_pending_orders(account)

    assert outcomes[0].status == "filled"
    assert outcomes[0].price == pytest.approx(150.0)
    assert outcomes[0].price_kind == "historical_range"
    assert account.pending_orders == []
    assert account.position_quantity("AAPL") == pytest.approx(2.0)
    assert account.cash == pytest.approx(700.0)
    assert price_source.requests[0][0] == "AAPL"
    assert price_source.requests[0][1] == "2024-01-03"


def test_historical_range_window_uses_complete_days_only() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 100.0}))
    service.place_manual_order(
        account,
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=90.0,
    )
    account.pending_orders[0].created_at = "2024-01-02T20:00:00+00:00"
    account.pending_orders[0].last_checked_at = "2024-01-02T20:00:00+00:00"

    window = PaperAccountService._historical_range_window(
        account.pending_orders[0],
        previous_checked_at=account.pending_orders[0].last_checked_at,
        checked_at=datetime(2024, 1, 5, 10, tzinfo=UTC),
    )

    assert window == ("2024-01-03", "2024-01-04")


def test_pending_sell_limit_order_reserves_position_quantity() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 100.0}))
    service.place_manual_order(account, symbol="AAPL", side="buy", quantity=1)

    service.price_source = _StubPriceSource({"AAPL": 50.0})
    pending = service.place_manual_order(
        account,
        symbol="AAPL",
        side="sell",
        quantity=1,
        limit_price=200.0,
    )
    duplicate = service.place_manual_order(account, symbol="AAPL", side="sell", quantity=1)

    assert pending.status == "pending"
    assert account.pending_orders[0].reserved_quantity == pytest.approx(1.0)
    assert account.reserved_quantity("AAPL") == pytest.approx(1.0)
    assert account.available_quantity("AAPL") == pytest.approx(0.0)
    assert duplicate.status == "unfilled"
    assert "no position available to sell" in duplicate.rejected_reason
    assert account.position_quantity("AAPL") == pytest.approx(1.0)

    service.price_source = _StubPriceSource({"AAPL": 250.0})
    outcomes = service.process_pending_orders(account)

    assert outcomes[0].status == "filled"
    assert account.pending_orders == []
    assert account.position_quantity("AAPL") == pytest.approx(0.0)
    assert account.cash == pytest.approx(1_150.0)


def test_manual_sell_over_position_reports_partial_fill() -> None:
    account = PaperAccount.open_new(initial_cash=1_000.0)
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 100.0}))
    service.place_manual_order(account, symbol="AAPL", side="buy", quantity=1)

    outcome = service.place_manual_order(account, symbol="AAPL", side="sell", quantity=2)

    assert outcome.status == "partially_filled"
    assert outcome.filled_quantity == pytest.approx(1)
    assert "filled 1.0000 of 2.0000" in outcome.rejected_reason
    assert account.position_quantity("AAPL") == 0


def test_price_source_never_uses_synthetic_sample_for_account_orders(tmp_path) -> None:
    settings = Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=tmp_path / "parquet",
            duckdb_path=tmp_path / "quant_system.duckdb",
        ),
        api_keys=ApiKeySettings(tiingo_api_token=None),
        futu=FutuSettings(enabled=False),
    )

    with pytest.raises(PriceUnavailableError):
        PaperPriceSource(settings).get_price("AAPL")


def test_price_source_uses_only_real_rows_from_local_cache(tmp_path) -> None:
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1),
                "close": 199.0,
                "provider": "sample",
            },
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "close": 201.0,
                "provider": "tiingo",
            },
        ]
    ).to_parquet(parquet_dir / "ohlcv.parquet", index=False)
    settings = Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=parquet_dir,
            duckdb_path=tmp_path / "quant_system.duckdb",
        ),
        api_keys=ApiKeySettings(tiingo_api_token=None),
        futu=FutuSettings(enabled=False),
    )

    quote = PaperPriceSource(settings).get_price("AAPL")

    assert quote.price == pytest.approx(201.0)
    assert quote.price_kind == "last_close"
    assert quote.source == "local:tiingo"


def test_price_source_prefers_futu_snapshot_over_local_close(tmp_path, monkeypatch) -> None:
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "close": 201.0,
                "provider": "tiingo",
            }
        ]
    ).to_parquet(parquet_dir / "ohlcv.parquet", index=False)

    def fake_snapshots(self, symbols: list[str]) -> pd.DataFrame:  # noqa: ARG001
        assert symbols == ["US.AAPL"]
        return pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL",
                    "last": 225.5,
                    "update_time": "2026-06-12T14:30:00Z",
                }
            ]
        )

    monkeypatch.setattr(
        FutuMarketDataProvider,
        "fetch_market_snapshots",
        fake_snapshots,
    )
    settings = Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=parquet_dir,
            duckdb_path=tmp_path / "quant_system.duckdb",
        ),
        api_keys=ApiKeySettings(tiingo_api_token=None),
        futu=FutuSettings(enabled=True),
    )

    quote = PaperPriceSource(settings).get_price("AAPL")

    assert quote.price == pytest.approx(225.5)
    assert quote.price_kind == "futu_snapshot"
    assert quote.source == "futu"


def test_price_source_falls_back_to_tiingo_remote_when_local_cache_missing(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeTiingoProvider:
        def fetch_ohlcv(self, symbols: list[str], *, start: str, end: str) -> pd.DataFrame:
            assert symbols == ["AAPL"]
            assert start < end
            return pd.DataFrame(
                [
                    {
                        "symbol": "AAPL",
                        "timestamp": pd.Timestamp("2026-06-12", tz="UTC"),
                        "close": 208.25,
                    }
                ]
            )

    def fake_build_ohlcv_provider(settings: Settings, *, requested: str):  # noqa: ARG001
        assert requested == "tiingo"
        return FakeTiingoProvider(), "tiingo"

    monkeypatch.setattr(
        "quant_system.execution.price_source.build_ohlcv_provider",
        fake_build_ohlcv_provider,
    )
    settings = Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=tmp_path / "parquet",
            duckdb_path=tmp_path / "quant_system.duckdb",
        ),
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr("token")),
        futu=FutuSettings(enabled=False),
    )

    quote = PaperPriceSource(settings).get_price("AAPL")

    assert quote.price == pytest.approx(208.25)
    assert quote.price_kind == "last_close"
    assert quote.source == "tiingo"


def test_price_source_rejects_local_close_outside_cutoff_window(tmp_path) -> None:
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=31),
                "close": 201.0,
                "provider": "tiingo",
            }
        ]
    ).to_parquet(parquet_dir / "ohlcv.parquet", index=False)
    settings = Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=parquet_dir,
            duckdb_path=tmp_path / "quant_system.duckdb",
        ),
        api_keys=ApiKeySettings(tiingo_api_token=None),
        futu=FutuSettings(enabled=False),
    )

    with pytest.raises(PriceUnavailableError):
        PaperPriceSource(settings).get_price("AAPL", lookback_days=10)


def test_frozen_account_rejects_manual_order() -> None:
    account = PaperAccount.open_new()
    account.kill_switch = True
    service = PaperAccountService(price_source=_StubPriceSource({"AAPL": 100.0}))

    with pytest.raises(AccountFrozenError):
        service.place_manual_order(account, symbol="AAPL", side="buy", quantity=1)


def test_rebalance_requests_sell_before_buy_and_hit_targets() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    # Seed an existing AAPL position so a rebalance into MSFT must sell first.
    account.apply_fill(_fill("AAPL", OrderSide.BUY, 500, 100.0), source="manual")
    prices = {"AAPL": 100.0, "MSFT": 100.0}
    equity = account.equity(prices)

    requests = PaperAccountService._rebalance_requests(
        account=account,
        target_weights={"MSFT": 1.0},
        prices=prices,
        equity=equity,
    )

    # AAPL fully sold (target 0) before MSFT bought; sells come first.
    assert requests[0][0] == "AAPL"
    assert requests[0][1] == OrderSide.SELL
    assert any(sym == "MSFT" and side == OrderSide.BUY for sym, side, _ in requests)


def test_rebalance_request_builder_rejects_missing_prices() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    account.apply_fill(_fill("AAPL", OrderSide.BUY, 500, 100.0), source="manual")

    with pytest.raises(PriceUnavailableError, match="AAPL"):
        PaperAccountService._rebalance_requests(
            account=account,
            target_weights={"MSFT": 1.0},
            prices={"MSFT": 100.0},
            equity=100_000.0,
        )


def test_rebalance_request_builder_rejects_non_finite_prices() -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)

    with pytest.raises(PriceUnavailableError, match="MSFT"):
        PaperAccountService._rebalance_requests(
            account=account,
            target_weights={"MSFT": 1.0},
            prices={"MSFT": float("nan")},
            equity=100_000.0,
        )


def test_rebalance_requires_prices_for_every_target_and_holding(monkeypatch) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    service = PaperAccountService(price_source=_PartialPriceSource({"AAPL": 100.0}))
    monkeypatch.setattr(
        service,
        "_compute_target_weights",
        lambda **_kwargs: ({"AAPL": 0.5, "MSFT": 0.5}, "2024-01-02T00:00:00Z"),
    )

    with pytest.raises(PriceUnavailableError, match="MSFT"):
        service.rebalance_to_strategy(
            account,
            strategy_id="cross_sectional_top_n",
            symbols=["AAPL", "MSFT"],
            top_n=2,
        )


def test_storage_mutation_lock_serializes_independent_callers(tmp_path) -> None:
    first = PaperAccountStorage(tmp_path)
    second = PaperAccountStorage(tmp_path)
    acquired: list[str] = []

    def wait_for_lock() -> None:
        with second.mutation_lock(timeout_seconds=2):
            acquired.append("second")

    with first.mutation_lock():
        thread = threading.Thread(target=wait_for_lock)
        thread.start()
        time.sleep(0.1)
        assert acquired == []

    thread.join(timeout=2)
    assert acquired == ["second"]


def test_storage_keeps_previous_account_backup_on_save(tmp_path) -> None:
    storage = PaperAccountStorage(tmp_path)
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage.save(account)

    account.record_event(kind="note", note="second save")
    storage.save(account)

    backup_payload = json.loads(storage.account_backup_path.read_text(encoding="utf-8"))
    assert backup_payload["cash"] == 100_000.0
    assert len(backup_payload["ledger"]) == 1


def test_storage_preserves_corrupt_account_file_before_reopening(tmp_path) -> None:
    storage = PaperAccountStorage(tmp_path)
    storage.account_dir.mkdir(parents=True)
    storage.account_path.write_text("{not-json", encoding="utf-8")

    account = storage.load_or_open(initial_cash=50_000.0)

    assert account.cash == 50_000.0
    assert not storage.account_path.read_text(encoding="utf-8").startswith("{not-json")
    corrupt_files = list(storage.account_dir.glob("account.corrupt-*.json"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "{not-json"


def test_storage_recovers_valid_backup_when_account_file_is_corrupt(tmp_path) -> None:
    storage = PaperAccountStorage(tmp_path)
    original = PaperAccount.open_new(initial_cash=100_000.0)
    original.record_event(kind="note", note="before corruption")
    storage.save(original)
    storage.account_backup_path.write_text(
        storage.account_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    storage.account_path.write_text("{not-json", encoding="utf-8")

    account = storage.load_or_open(initial_cash=50_000.0)

    assert account.cash == 100_000.0
    assert len(account.ledger) == 2
    assert json.loads(storage.account_path.read_text(encoding="utf-8"))["cash"] == 100_000.0
    corrupt_files = list(storage.account_dir.glob("account.corrupt-*.json"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "{not-json"


def test_storage_save_keeps_existing_account_when_atomic_replace_fails(
    tmp_path,
    monkeypatch,
) -> None:
    storage = PaperAccountStorage(tmp_path)
    account = PaperAccount.open_new(initial_cash=100_000.0)
    storage.save(account)
    original_payload = storage.account_path.read_text(encoding="utf-8")
    attempts = 0

    def fail_replace(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise PermissionError("account file is locked")

    monkeypatch.setattr(account_storage_module.os, "replace", fail_replace)
    monkeypatch.setattr(account_storage_module.time, "sleep", lambda _seconds: None)
    account.record_event(kind="note", note="should not be partially written")

    with pytest.raises(PermissionError, match="account file is locked"):
        storage.save(account)

    assert attempts == 10
    assert storage.account_path.read_text(encoding="utf-8") == original_payload


def test_storage_snapshot_without_fresh_quotes_keeps_weight_and_fill_source(tmp_path) -> None:
    account = PaperAccount.open_new(initial_cash=100_000.0)
    account.apply_fill(
        _fill("AAPL", OrderSide.BUY, 100, 100.0),
        source="strategy:cross_sectional_top_n",
        price_kind="futu_snapshot",
    )
    storage = PaperAccountStorage(tmp_path)

    storage.save(account)

    snapshot = pd.read_parquet(storage.positions_snapshot_path).iloc[0]
    assert snapshot["weight"] == pytest.approx(0.1)
    assert snapshot["price_kind"] == "futu_snapshot"
