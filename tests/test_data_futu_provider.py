from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError


class _FakeContext:
    def __init__(
        self,
        responses: list[tuple[int, pd.DataFrame, object | None]] | None = None,
        *,
        expirations: tuple[int, pd.DataFrame | str] | None = None,
        chain: tuple[int, pd.DataFrame | str] | None = None,
        snapshots: tuple[int, pd.DataFrame | str] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._expirations = expirations
        self._chain = chain
        self._snapshots = snapshots
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        if not self._responses:
            raise AssertionError("unexpected request_history_kline call")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True

    def get_option_expiration_date(self, code: str):
        self.calls.append({"method": "get_option_expiration_date", "code": code})
        if self._expirations is None:
            raise AssertionError("unexpected get_option_expiration_date call")
        return self._expirations

    def get_option_chain(self, code: str, **kwargs):
        self.calls.append({"method": "get_option_chain", "code": code, **kwargs})
        if self._chain is None:
            raise AssertionError("unexpected get_option_chain call")
        return self._chain

    def get_market_snapshot(self, symbols: list[str]):
        self.calls.append({"method": "get_market_snapshot", "symbols": symbols})
        if self._snapshots is None:
            raise AssertionError("unexpected get_market_snapshot call")
        return self._snapshots


def _sdk() -> SimpleNamespace:
    return SimpleNamespace(
        RET_OK=0,
        KLType=SimpleNamespace(
            K_DAY="K_DAY",
            K_60M="K_60M",
            K_30M="K_30M",
            K_15M="K_15M",
            K_5M="K_5M",
            K_1M="K_1M",
        ),
        AuType=SimpleNamespace(QFQ="QFQ"),
        Session=SimpleNamespace(NONE="NONE", ALL="ALL"),
        OptionType=SimpleNamespace(ALL="ALL", CALL="CALL", PUT="PUT"),
    )


def test_futu_provider_normalizes_plain_and_prefixed_symbols() -> None:
    assert FutuMarketDataProvider.normalize_symbol("aapl") == ("AAPL", "US.AAPL")
    assert FutuMarketDataProvider.normalize_symbol("US.NVDA") == ("NVDA", "US.NVDA")


def test_futu_provider_rejects_non_us_symbol_format() -> None:
    with pytest.raises(FutuProviderError, match="expects plain US tickers"):
        FutuMarketDataProvider.normalize_symbol("HK.00700")


def test_futu_provider_converts_history_kline_to_canonical_schema() -> None:
    data = pd.DataFrame(
        [
            {
                "time_key": "2024-01-02 00:00:00",
                "open": 185.22,
                "high": 186.50,
                "low": 181.99,
                "close": 183.73,
                "volume": 82488674,
            }
        ]
    )
    fake_context = _FakeContext([(0, data, None)])
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "AAPL"
    assert frame.loc[0, "provider"] == "futu"
    assert frame.loc[0, "interval"] == "1d"
    assert frame.loc[0, "close"] == 183.73
    assert fake_context.calls[0]["code"] == "US.AAPL"
    assert fake_context.calls[0]["session"] == "NONE"
    assert fake_context.closed is True


def test_futu_provider_uses_all_session_for_intraday_requests() -> None:
    data = pd.DataFrame(
        [
            {
                "time_key": "2024-01-02 09:30:00",
                "open": 185.22,
                "high": 186.50,
                "low": 181.99,
                "close": 183.73,
                "volume": 82488674,
            }
        ]
    )
    fake_context = _FakeContext([(0, data, None)])
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02", interval="1h")

    assert fake_context.calls[0]["session"] == "ALL"
    assert fake_context.calls[0]["ktype"] == "K_60M"


def test_futu_provider_reports_invalid_symbol_error() -> None:
    fake_context = _FakeContext([(1, "security not found", None)])
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    with pytest.raises(FutuProviderError, match="invalid Futu symbol"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")


def test_futu_provider_reports_no_data() -> None:
    fake_context = _FakeContext([(0, pd.DataFrame(), None)])
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    with pytest.raises(FutuProviderError, match="no OHLCV data returned"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")


def test_futu_provider_reports_unavailable_opend() -> None:
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: (_ for _ in ()).throw(OSError("connection refused")),
        sdk_loader=_sdk,
    )

    with pytest.raises(FutuProviderError, match="unable to connect to OpenD"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")


def test_futu_provider_rejects_unsupported_interval() -> None:
    fake_context = _FakeContext([])
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    with pytest.raises(FutuProviderError, match="unsupported Futu interval"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02", interval="2h")


def test_futu_provider_fetches_option_expirations() -> None:
    expirations = pd.DataFrame(
        [
            {
                "strike_time": "2026-05-08",
                "option_expiry_date_distance": 6,
                "expiration_cycle": "WEEK",
            }
        ]
    )
    fake_context = _FakeContext([], expirations=(0, expirations))
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: fake_context,
        sdk_loader=_sdk,
    )

    frame = provider.fetch_option_expirations("AAPL")

    assert frame.loc[0, "underlying"] == "US.AAPL"
    assert frame.loc[0, "strike_time"] == "2026-05-08"
    assert fake_context.closed is True


def test_futu_provider_fetches_option_quotes_with_missing_fields() -> None:
    chain = pd.DataFrame(
        [
            {
                "code": "US.AAPL260508P200000",
                "name": "AAPL 260508 200.00P",
                "stock_owner": "US.AAPL",
                "option_type": "PUT",
                "strike_price": 200.0,
                "strike_time": "2026-05-08",
            }
        ]
    )
    snapshots = pd.DataFrame(
        [
            {
                "code": "US.AAPL260508P200000",
                "update_time": "2026-05-01 15:19:50",
                "last_price": 1.2,
                "bid_price": 1.1,
                "ask_price": 1.3,
                "volume": 5,
            }
        ]
    )
    contexts = [
        _FakeContext([], chain=(0, chain)),
        _FakeContext([], snapshots=(0, snapshots)),
    ]
    provider = FutuMarketDataProvider(
        context_factory=lambda host, port: contexts.pop(0),
        sdk_loader=_sdk,
    )

    frame = provider.fetch_option_quotes("AAPL", expiration="2026-05-08", option_type="PUT")

    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "US.AAPL260508P200000"
    assert frame.loc[0, "option_type"] == "PUT"
    assert frame.loc[0, "strike"] == 200.0
    assert frame.loc[0, "bid"] == 1.1
    assert frame.loc[0, "ask"] == 1.3
    assert pd.isna(frame.loc[0, "implied_volatility"])
