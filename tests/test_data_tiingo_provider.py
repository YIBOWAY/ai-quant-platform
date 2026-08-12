import io
import json
from urllib.error import HTTPError

import pandas as pd
import pytest

from quant_system.data.providers import tiingo
from quant_system.data.providers.tiingo import TiingoEODProvider, TiingoProviderError


def test_tiingo_provider_converts_response_to_canonical_ohlcv() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        assert "AAPL/prices" in url
        assert headers["Authorization"] == "Token test-token"
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 187.15,
                "high": 188.44,
                "low": 183.89,
                "close": 185.64,
                "volume": 82488700,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "AAPL"
    assert frame.loc[0, "provider"] == "tiingo"
    assert frame.loc[0, "close"] == 185.64
    # knowledge_ts must be strictly later than event_ts so PIT replays do not
    # see EOD bars before they could have been observed.
    assert frame.loc[0, "knowledge_ts"] > frame.loc[0, "event_ts"]
    assert frame.loc[0, "knowledge_ts"] >= pd.Timestamp("2024-01-02", tz="UTC")


def test_tiingo_provider_prefers_adjusted_ohlcv_when_available() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": 50.0,
                "adjHigh": 55.0,
                "adjLow": 45.0,
                "adjClose": 52.5,
                "adjVolume": 2000,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 50.0
    assert frame.loc[0, "high"] == 55.0
    assert frame.loc[0, "low"] == 45.0
    assert frame.loc[0, "close"] == 52.5
    assert frame.loc[0, "volume"] == 2000
    assert frame.loc[0, "price_adjustment"] == "adjusted"


def test_tiingo_provider_falls_back_when_adjusted_values_are_missing() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": None,
                "adjHigh": None,
                "adjLow": None,
                "adjClose": None,
                "adjVolume": None,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 100.0
    assert frame.loc[0, "high"] == 110.0
    assert frame.loc[0, "low"] == 90.0
    assert frame.loc[0, "close"] == 105.0
    assert frame.loc[0, "volume"] == 1000
    assert frame.loc[0, "price_adjustment"] == "raw"


def test_tiingo_provider_marks_mixed_adjusted_and_raw_values() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": 50.0,
                "adjHigh": None,
                "adjLow": 45.0,
                "adjClose": None,
                "adjVolume": 2000,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 50.0
    assert frame.loc[0, "high"] == 110.0
    assert frame.loc[0, "low"] == 45.0
    assert frame.loc[0, "close"] == 105.0
    assert frame.loc[0, "volume"] == 2000
    assert frame.loc[0, "price_adjustment"] == "mixed"


def test_tiingo_provider_requires_api_token() -> None:
    provider = TiingoEODProvider(api_token=None)

    with pytest.raises(ValueError, match="Tiingo API token is required"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")


def test_tiingo_provider_rejects_intraday_interval() -> None:
    provider = TiingoEODProvider(api_token="test-token", get_json=lambda _url, _headers: [])

    with pytest.raises(ValueError, match="Tiingo provider only supports daily"):
        provider.fetch_ohlcv(
            ["AAPL"],
            start="2024-01-02",
            end="2024-01-02",
            interval="1h",
        )


def test_tiingo_provider_normalizes_symbols_like_futu() -> None:
    assert TiingoEODProvider.normalize_symbol("ewh") == "EWH"
    assert TiingoEODProvider.normalize_symbol("US.EWH") == "EWH"
    assert TiingoEODProvider.normalize_symbol("  ashr ") == "ASHR"
    for bad in ("", "  ", "EW H"):
        with pytest.raises(TiingoProviderError) as excinfo:
            TiingoEODProvider.normalize_symbol(bad)
        assert excinfo.value.code == "invalid_symbol"


def test_tiingo_provider_passes_through_class_share_tickers() -> None:
    # Class shares keep their dot (Tiingo spells them ``BRK.B``); the shared
    # provider always passed them through and must keep doing so.
    assert TiingoEODProvider.normalize_symbol("brk.b") == "BRK.B"
    assert TiingoEODProvider.normalize_symbol("US.BRK.B") == "BRK.B"


def test_tiingo_provider_normalize_symbol_documents_exchange_suffix_caveat() -> None:
    # Tiingo spells exchange-suffixed symbols with a dot (e.g. 600519.SS was the
    # old Chinese-stocks format). normalize_symbol passes dots through for class
    # shares (BRK.B), so non-US suffixed symbols are NOT rejected at validation
    # time — they fail downstream as TiingoProviderError('symbol_not_found').
    assert TiingoEODProvider.normalize_symbol("600519.SS") == "600519.SS"


def test_tiingo_provider_exchange_suffix_fails_as_symbol_not_found() -> None:
    def fake_get_json(_url: str, _headers: dict[str, str]) -> list[dict[str, object]]:
        raise TiingoProviderError("symbol_not_found", "Tiingo returned HTTP 404")

    provider = TiingoEODProvider(
        api_token="test-token", get_json=fake_get_json, strict_symbols=True
    )
    with pytest.raises(TiingoProviderError) as excinfo:
        provider.fetch_ohlcv(["600519.SS"], start="2024-01-02", end="2024-01-02")
    assert excinfo.value.code == "symbol_not_found"


def test_tiingo_provider_empty_payload_is_typed_no_data() -> None:
    provider = TiingoEODProvider(
        api_token="test-token",
        get_json=lambda _url, _headers: [],
        strict_symbols=True,
    )

    with pytest.raises(TiingoProviderError) as excinfo:
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")
    assert excinfo.value.code == "no_data"


def test_tiingo_provider_default_mode_tolerates_per_symbol_failures() -> None:
    # Shared-pipeline contract (pre-existing behavior): one empty/failed symbol
    # must not fail the whole batch; the remaining symbols are still served.
    good_row = {
        "date": "2024-01-02T00:00:00.000Z",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 1_000,
    }

    def fake_get_json(url: str, _headers: dict[str, str]) -> list[dict[str, object]]:
        if "DELISTED" in url:
            return []
        return [dict(good_row)]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)
    frame = provider.fetch_ohlcv(
        ["DELISTED", "EWH"], start="2024-01-02", end="2024-01-02"
    )
    assert sorted(frame["symbol"].unique()) == ["EWH"]


def test_tiingo_provider_default_mode_all_empty_raises_value_error() -> None:
    # Pre-existing behavior for the all-empty batch: normalize_ohlcv_dataframe's
    # missing-columns ValueError (not a typed provider error).
    provider = TiingoEODProvider(api_token="test-token", get_json=lambda _u, _h: [])

    with pytest.raises(ValueError):
        provider.fetch_ohlcv(["DELISTED"], start="2024-01-02", end="2024-01-02")


def test_tiingo_provider_strict_mode_fails_batch_on_single_bad_symbol() -> None:
    # The disaster-recovery chain opts into strict mode because it validates the
    # returned frame against the full request — partial data must degrade the lane.
    provider = TiingoEODProvider(
        api_token="test-token",
        get_json=lambda _url, _headers: [],
        strict_symbols=True,
    )

    with pytest.raises(TiingoProviderError) as excinfo:
        provider.fetch_ohlcv(["EWH", "DELISTED"], start="2024-01-02", end="2024-01-02")
    assert excinfo.value.code == "no_data"


def test_tiingo_provider_default_mode_tolerates_invalid_symbol_in_batch() -> None:
    good_row = {
        "date": "2024-01-02T00:00:00.000Z",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 1_000,
    }
    provider = TiingoEODProvider(
        api_token="test-token",
        get_json=lambda _url, _headers: [dict(good_row)],
    )
    frame = provider.fetch_ohlcv(["EW H", "EWH"], start="2024-01-02", end="2024-01-02")
    assert sorted(frame["symbol"].unique()) == ["EWH"]


def test_tiingo_provider_row_missing_date_is_payload_error() -> None:
    provider = TiingoEODProvider(
        api_token="test-token",
        get_json=lambda _url, _headers: [{"open": 1.0}],
        strict_symbols=True,
    )

    with pytest.raises(TiingoProviderError) as excinfo:
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")
    assert excinfo.value.code == "payload_error"


def test_tiingo_provider_retries_rate_limit_then_raises() -> None:
    sleeps: list[float] = []
    calls = 0

    def fake_get_json(_url: str, _headers: dict[str, str]) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        raise TiingoProviderError("rate_limited", "slow down", retry_after_seconds=3.0)

    provider = TiingoEODProvider(
        api_token="test-token",
        get_json=fake_get_json,
        rate_limit_max_retries=1,
        sleep_func=sleeps.append,
        strict_symbols=True,
    )
    with pytest.raises(TiingoProviderError) as excinfo:
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")
    assert excinfo.value.code == "rate_limited"
    assert calls == 2
    assert sleeps == [3.0]


class _FakeHTTPResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def test_tiingo_default_get_json_detects_dict_error_body(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ARG001
        return _FakeHTTPResponse({"detail": "Not found."})

    monkeypatch.setattr(tiingo, "urlopen", fake_urlopen)
    with pytest.raises(TiingoProviderError) as excinfo:
        tiingo._default_get_json("https://api.tiingo.com/x", {})
    assert excinfo.value.code == "payload_error"
    assert "Not found." in excinfo.value.message


def test_tiingo_default_get_json_maps_http_errors(monkeypatch) -> None:
    def fake_urlopen_404(request, timeout):  # noqa: ARG001
        raise HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"detail": "no ticker"}')
        )

    monkeypatch.setattr(tiingo, "urlopen", fake_urlopen_404)
    with pytest.raises(TiingoProviderError) as excinfo:
        tiingo._default_get_json("https://api.tiingo.com/x", {})
    assert excinfo.value.code == "symbol_not_found"

    def fake_urlopen_429(request, timeout):  # noqa: ARG001
        raise HTTPError(
            request.full_url, 429, "Too Many Requests", {"Retry-After": "5"}, io.BytesIO(b"")
        )

    monkeypatch.setattr(tiingo, "urlopen", fake_urlopen_429)
    with pytest.raises(TiingoProviderError) as excinfo:
        tiingo._default_get_json("https://api.tiingo.com/x", {})
    assert excinfo.value.code == "rate_limited"
    assert excinfo.value.retry_after_seconds == 5.0
