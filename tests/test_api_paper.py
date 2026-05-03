import pandas as pd
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, Settings
from quant_system.data.schema import normalize_ohlcv_dataframe


def _fake_tiingo_frame() -> pd.DataFrame:
    rows = []
    base_dates = [
        pd.Timestamp("2024-01-02", tz="UTC"),
        pd.Timestamp("2024-01-03", tz="UTC"),
        pd.Timestamp("2024-01-04", tz="UTC"),
        pd.Timestamp("2024-01-05", tz="UTC"),
        pd.Timestamp("2024-01-08", tz="UTC"),
        pd.Timestamp("2024-01-09", tz="UTC"),
    ]
    for index, timestamp in enumerate(base_dates):
        rows.extend(
            [
                {
                    "symbol": "SPY",
                    "timestamp": timestamp,
                    "open": 470.0 + index,
                    "high": 471.0 + index,
                    "low": 469.0 + index,
                    "close": 470.8 + index,
                    "volume": 1000 + (index * 10),
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                },
                {
                    "symbol": "QQQ",
                    "timestamp": timestamp,
                    "open": 400.0 + (index * 2),
                    "high": 401.0 + (index * 2),
                    "low": 399.0 + (index * 2),
                    "close": 400.9 + (index * 2),
                    "volume": 2000 + (index * 20),
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                },
            ]
        )
    return normalize_ohlcv_dataframe(
        pd.DataFrame(rows),
        provider="tiingo",
        interval="1d",
    )


def test_paper_run_rejects_disabling_global_kill_switch(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "enable_kill_switch": False,
        },
    )

    assert response.status_code == 409
    assert "kill switch" in response.json()["detail"].lower()
    assert response.json()["safety"]["kill_switch"] is True


def test_paper_run_list_and_detail_with_kill_switch_on(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "enable_kill_switch": True,
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    list_response = client.get("/api/paper")
    assert list_response.status_code == 200
    assert run_id in {item["id"] for item in list_response.json()["paper_runs"]}

    detail_response = client.get(f"/api/paper/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["orders"]
    assert detail["risk_breaches"]
    assert isinstance(detail["trades"], list)


def test_paper_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/paper/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["kill_switch"] is True


def test_paper_list_returns_latest_run_first(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    first = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "provider": "sample",
            "enable_kill_switch": True,
        },
    )
    second = client.post(
        "/api/paper/run",
        json={
            "symbols": ["QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "provider": "sample",
            "enable_kill_switch": True,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get("/api/paper")

    assert response.status_code == 200
    payload = response.json()
    assert payload["paper_runs"][0]["id"] == second.json()["run_id"]


def test_paper_run_uses_tiingo_when_requested(tmp_path, monkeypatch) -> None:
    settings = Settings(
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr("test-tiingo-token"))
    )

    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        return _fake_tiingo_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.TiingoEODProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/paper/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-09",
            "provider": "tiingo",
            "enable_kill_switch": True,
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tiingo"
    assert payload["signal_count"] > 0
