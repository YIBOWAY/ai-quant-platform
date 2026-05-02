from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError


class _FakeContext:
    def __init__(self, responses: list[tuple[int, pd.DataFrame, object | None]]) -> None:
        self._responses = list(responses)
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def request_history_kline(self, code: str, **kwargs):
        self.calls.append({"code": code, **kwargs})
        if not self._responses:
            raise AssertionError("unexpected request_history_kline call")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


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
