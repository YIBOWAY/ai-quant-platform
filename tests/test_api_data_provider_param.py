import pandas as pd
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, Settings
from quant_system.data.schema import normalize_ohlcv_dataframe


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


def test_ohlcv_provider_param_uses_tiingo_when_requested(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
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


def test_ohlcv_provider_param_reports_missing_tiingo_token(tmp_path) -> None:
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

    assert response.status_code == 200
    assert response.json()["source"].startswith("sample (tiingo: missing token)")
