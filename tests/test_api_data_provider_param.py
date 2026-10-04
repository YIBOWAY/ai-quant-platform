import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.data.storage import LocalDataStorage


def _isolated_data_settings(tmp_path) -> DataSettings:
    return DataSettings(
        data_dir=tmp_path / "data",
        parquet_dir=tmp_path / "parquet",
        duckdb_path=tmp_path / "quant_system.duckdb",
        reports_dir=tmp_path / "reports",
    )


def _fake_tiingo_frame() -> pd.DataFrame:
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    return normalize_ohlcv_dataframe(
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "timestamp": timestamp,
                    "open": 470.0,
                    "high": 475.0,
                    "low": 468.0,
                    "close": 472.65,
                    "volume": 100,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                }
            ]
        ),
        provider="tiingo",
        interval="1d",
    )


def _fake_futu_frame() -> pd.DataFrame:
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    return normalize_ohlcv_dataframe(
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "timestamp": timestamp,
                    "open": 459.51,
                    "high": 460.98,
                    "low": 457.88,
                    "close": 459.99,
                    "volume": 123007793,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(minutes=1),
                }
            ]
        ),
        provider="futu",
        interval="1d",
    )


def test_ohlcv_provider_param_uses_futu_when_requested(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        return _fake_futu_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(
        create_app(
            settings=Settings(futu=FutuSettings(enabled=True)),
            output_dir=tmp_path,
        )
    )

    response = client.get(
        "/api/ohlcv",
        params={
            "symbol": "SPY",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "futu",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "futu"
    assert payload["rows"][0]["close"] == 459.99


def test_ohlcv_provider_param_uses_tiingo_when_requested(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
        data=_isolated_data_settings(tmp_path),
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr("test-tiingo-token")),
    )

    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        return _fake_tiingo_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.TiingoEODProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/ohlcv",
        params={
            "symbol": "SPY",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "tiingo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tiingo"
    assert payload["rows"][0]["close"] == 472.65


def test_ohlcv_provider_param_rejects_missing_tiingo_token(tmp_path) -> None:
    settings = Settings(api_keys=ApiKeySettings(tiingo_api_token=None))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/ohlcv",
        params={
            "symbol": "SPY",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "tiingo",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_unavailable"


def test_ohlcv_rejects_unknown_explicit_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/ohlcv",
        params={
            "symbol": "SPY",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "polygon",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "provider_unavailable"
    assert payload["detail"]["provider"] == "polygon"


@pytest.mark.parametrize("requested", [None, "futu", "tiingo", "polygon"])
def test_ohlcv_cannot_hide_sample_cache_as_local_for_real_requests(
    tmp_path, monkeypatch, requested
):
    cached = _fake_futu_frame()
    cached["provider"] = "sample"
    LocalDataStorage(base_dir=tmp_path).save_ohlcv(cached)

    def unavailable(*_args, **_kwargs):
        raise FutuProviderError("opend_unavailable", "real source unavailable")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv", unavailable
    )
    settings = Settings(
        data=DataSettings(default_data_provider="futu"),
        api_keys=ApiKeySettings(tiingo_api_token=None),
        futu=FutuSettings(enabled=True),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    params = {"symbol": "SPY", "start": "2024-01-02", "end": "2024-01-12"}
    if requested is not None:
        params["provider"] = requested
    response = client.get("/api/ohlcv", params=params)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_unavailable"
    assert "rows" not in response.json()


@pytest.mark.parametrize(
    "path,key,expected_status",
    [
        ("/api/ohlcv", "symbol", 400),
        ("/api/benchmark", "symbol", 400),
        ("/api/market-data/history", "ticker", 502),
    ],
)
def test_real_default_fetch_failure_never_returns_sample(
    tmp_path, monkeypatch, path, key, expected_status
):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("real source unavailable")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv", unavailable
    )
    settings = Settings(
        data=DataSettings(default_data_provider="futu"), futu=FutuSettings(enabled=True)
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    response = client.get(path, params={key: "SPY", "start": "2024-01-02", "end": "2024-01-05"})
    assert response.status_code == expected_status
    assert "rows" not in response.json()
    assert "equity_curve" not in response.json()


@pytest.mark.parametrize("metadata", ["sample", "missing-provider", "missing-interval"])
def test_symbols_do_not_present_unattributed_cache_as_real(tmp_path, metadata):
    cached = _fake_futu_frame()
    cached["symbol"] = "SAMPLE_ONLY"
    if metadata == "sample":
        cached["provider"] = "sample"
    else:
        cached = cached.drop(columns=[metadata.removeprefix("missing-")])
    path = LocalDataStorage(base_dir=tmp_path).parquet_path
    path.parent.mkdir(parents=True)
    cached.to_parquet(path, index=False)
    settings = Settings(
        data=DataSettings(default_data_provider="futu"), futu=FutuSettings(enabled=True)
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    response = client.get("/api/symbols")
    assert response.status_code == 200
    assert response.json()["source"].startswith("futu")
    assert "SAMPLE_ONLY" not in response.json()["symbols"]
