from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from quant_system.data.providers import twelvedata
from quant_system.data.providers.twelvedata import (
    TwelveDataDailyProvider,
    TwelveDataProviderError,
)

# Recorded response shapes from the 2026-08-11 live probe (sanitized: no keys,
# values rounded). Twelve Data answers daily bars newest-first by default.
EWH_OK_PAYLOAD = {
    "meta": {
        "symbol": "EWH",
        "interval": "1day",
        "currency": "USD",
        "exchange_timezone": "America/New_York",
        "exchange": "NYSE Arca",
        "mic_code": "ARCX",
        "type": "ETF",
    },
    "values": [
        {
            "datetime": "2026-08-07",
            "open": "22.50000",
            "high": "22.62000",
            "low": "22.41000",
            "close": "22.60000",
            "volume": "1500000",
        },
        {
            "datetime": "2026-08-10",
            "open": "22.70000",
            "high": "22.90000",
            "low": "22.68000",
            "close": "22.80000",
            "volume": "1700000",
        },
    ],
    "status": "ok",
}

PLAN_GATED_PAYLOAD = {
    "code": 404,
    "message": "**symbol** not found: HSI. Please specify it correctly...",
    "status": "error",
}

RATE_LIMIT_PAYLOAD = {
    "code": 429,
    "message": "You have run out of API credits for the current minute.",
    "status": "error",
}


def _provider(request_json) -> TwelveDataDailyProvider:
    return TwelveDataDailyProvider(api_key="test-key", request_json=request_json)


def test_twelvedata_provider_converts_response_to_canonical_ohlcv() -> None:
    calls: list[str] = []

    def fake_request_json(url: str, headers: dict[str, str]):
        calls.append(url)
        assert "symbol=EWH" in url
        assert "interval=1day" in url
        assert "apikey=test-key" in url
        return EWH_OK_PAYLOAD, {"api-credits-used": "1", "api-credits-left": "799"}

    provider = _provider(fake_request_json)
    frame = provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")

    assert len(calls) == 1
    assert len(frame) == 2
    assert set(frame["symbol"]) == {"EWH"}
    assert set(frame["provider"]) == {"twelvedata"}
    assert set(frame["interval"]) == {"1d"}
    assert set(frame["price_adjustment"]) == {"splits"}
    assert frame.loc[0, "close"] == 22.6
    # knowledge_ts (download time) must be strictly later than event_ts so PIT
    # replays never see EOD bars before they could have been observed.
    assert (frame["knowledge_ts"] > frame["event_ts"]).all()
    assert provider.last_api_credits_used == 1
    assert provider.last_api_credits_left == 799


def test_twelvedata_provider_normalizes_symbols_like_futu() -> None:
    assert TwelveDataDailyProvider.normalize_symbol("ewh") == "EWH"
    assert TwelveDataDailyProvider.normalize_symbol("US.EWH") == "EWH"
    assert TwelveDataDailyProvider.normalize_symbol("  ewj ") == "EWJ"
    for bad in ("HK.800000", "JP..N225", "BRK.B", "", "  ", "EW H"):
        with pytest.raises(TwelveDataProviderError) as excinfo:
            TwelveDataDailyProvider.normalize_symbol(bad)
        assert excinfo.value.code == "invalid_symbol"


def test_twelvedata_provider_detects_payload_error_under_http_200() -> None:
    def fake_request_json(url: str, headers: dict[str, str]):
        # Plan-gated symbols arrive as an in-band 404 error body.
        return PLAN_GATED_PAYLOAD, {}

    provider = _provider(fake_request_json)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")
    assert excinfo.value.code == "symbol_not_found_or_plan_gated"


def test_twelvedata_provider_retries_rate_limit_then_raises() -> None:
    sleeps: list[float] = []
    calls = 0

    def fake_request_json(url: str, headers: dict[str, str]):
        nonlocal calls
        calls += 1
        raise TwelveDataProviderError("rate_limited", "credits exhausted", retry_after_seconds=2.0)

    provider = TwelveDataDailyProvider(
        api_key="test-key",
        request_json=fake_request_json,
        rate_limit_max_retries=1,
        sleep_func=sleeps.append,
    )
    with pytest.raises(TwelveDataProviderError) as excinfo:
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")
    assert excinfo.value.code == "rate_limited"
    assert calls == 2
    assert sleeps == [2.0]


def test_twelvedata_provider_retry_recovers() -> None:
    calls = 0

    def fake_request_json(url: str, headers: dict[str, str]):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TwelveDataProviderError("rate_limited", "slow down")
        return EWH_OK_PAYLOAD, {}

    provider = TwelveDataDailyProvider(
        api_key="test-key",
        request_json=fake_request_json,
        sleep_func=lambda _seconds: None,
    )
    frame = provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")
    assert len(frame) == 2
    assert calls == 2


def test_twelvedata_provider_rejects_meta_symbol_mismatch() -> None:
    payload = dict(EWH_OK_PAYLOAD)
    payload["meta"] = dict(EWH_OK_PAYLOAD["meta"], symbol="SPY")

    def fake_request_json(url: str, headers: dict[str, str]):
        return payload, {}

    provider = _provider(fake_request_json)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")
    assert excinfo.value.code == "payload_error"


def test_twelvedata_provider_empty_values_is_no_data() -> None:
    def fake_request_json(url: str, headers: dict[str, str]):
        return {"meta": {"symbol": "EWH"}, "values": [], "status": "ok"}, {}

    provider = _provider(fake_request_json)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")
    assert excinfo.value.code == "no_data"


def test_twelvedata_provider_requires_api_key() -> None:
    provider = TwelveDataDailyProvider(api_key=None)
    with pytest.raises(ValueError, match="Twelve Data API key is required"):
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10")


def test_twelvedata_provider_rejects_intraday_interval() -> None:
    provider = _provider(lambda url, headers: (EWH_OK_PAYLOAD, {}))
    with pytest.raises(ValueError, match="only supports daily"):
        provider.fetch_ohlcv(["EWH"], start="2026-08-07", end="2026-08-10", interval="1h")


class _FakeHTTPResponse:
    def __init__(self, payload: object, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def test_default_request_json_maps_http_404_to_plan_gate(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(json.dumps(PLAN_GATED_PAYLOAD).encode("utf-8")),
        )

    monkeypatch.setattr(twelvedata, "urlopen", fake_urlopen)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        twelvedata._default_request_json("https://api.twelvedata.com/time_series?x=1", {})
    assert excinfo.value.code == "symbol_not_found_or_plan_gated"


def test_default_request_json_maps_http_429_with_retry_after(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            io.BytesIO(b"rate limited"),
        )

    monkeypatch.setattr(twelvedata, "urlopen", fake_urlopen)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        twelvedata._default_request_json("https://api.twelvedata.com/time_series?x=1", {})
    assert excinfo.value.code == "rate_limited"
    assert excinfo.value.retry_after_seconds == 7.0


def test_default_request_json_detects_in_band_error_under_http_200(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeHTTPResponse(RATE_LIMIT_PAYLOAD)

    monkeypatch.setattr(twelvedata, "urlopen", fake_urlopen)
    with pytest.raises(TwelveDataProviderError) as excinfo:
        twelvedata._default_request_json("https://api.twelvedata.com/time_series?x=1", {})
    assert excinfo.value.code == "rate_limited"


def test_default_request_json_returns_payload_and_headers(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeHTTPResponse(EWH_OK_PAYLOAD, {"api-credits-left": "799"})

    monkeypatch.setattr(twelvedata, "urlopen", fake_urlopen)
    payload, headers = twelvedata._default_request_json(
        "https://api.twelvedata.com/time_series?x=1", {}
    )
    assert payload["status"] == "ok"
    assert headers["api-credits-left"] == "799"
