from __future__ import annotations

from fastapi.testclient import TestClient

from quant_system.api.routes.asia_radar import get_asia_radar_reader
from quant_system.api.server import create_app
from quant_system.data.price_history import HistoricalPriceReadError


def _overview() -> dict:
    return {
        "schema_version": "1.1",
        "provider": "futu",
        "as_of": "2026-02-13",
        "timezone": "America/New_York",
        "fetched_at": "2026-02-13T09:30:00+00:00",
        "provenance": "futu",
        "methodology": {
            "week": "5 trading sessions",
            "month": "21 trading sessions",
            "ytd": "calendar year first available close through latest shared session",
            "volatility": "63-session annualized realized volatility",
            "drawdown": "calendar-year maximum drawdown through latest shared session",
            "k_shape": "daily YTD cross-sectional top-three / bottom-three baskets",
        },
        "markets": [],
        "k_shape": {"winners": [], "laggards": [], "series": []},
    }


def test_overview_endpoint_forces_futu_and_uses_reader_seam(tmp_path) -> None:
    calls = []

    def fake_reader(*, settings, today=None):
        calls.append((settings, today))
        return _overview()

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_asia_radar_reader] = lambda: fake_reader
    client = TestClient(app)

    response = client.get("/api/asia-radar/overview?provider=futu")

    assert response.status_code == 200
    assert response.json()["provider"] == "futu"
    assert response.json()["timezone"] == "America/New_York"
    assert len(calls) == 1


def test_overview_endpoint_rejects_every_non_futu_provider(tmp_path) -> None:
    app = create_app(output_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/asia-radar/overview?provider=sample")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "asia_radar_requires_futu"


def test_provider_failure_is_503_and_never_returns_sample_payload(tmp_path) -> None:
    def unavailable_reader(*, settings, today=None):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_unavailable",
            message="Futu OpenD is unavailable",
            provider_code="opend_unreachable",
        )

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_asia_radar_reader] = lambda: unavailable_reader
    client = TestClient(app)

    response = client.get("/api/asia-radar/overview")

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "asia_radar_provider_unavailable"
    assert payload["detail"]["provider"] == "futu"
    assert "sample" not in response.text.lower()
