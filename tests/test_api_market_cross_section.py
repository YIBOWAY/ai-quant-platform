from __future__ import annotations

from fastapi.testclient import TestClient

from quant_system.api.routes.market_cross_section import (
    get_market_cross_section_reader,
)
from quant_system.api.server import create_app
from quant_system.data.price_history import HistoricalPriceReadError


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "provider": "futu",
        "as_of": "2026-03-30",
        "timezone": "America/New_York",
        "fetched_at": "2026-03-30T09:30:00+00:00",
        "provenance": "futu",
        "basket": "ai_watch",
        "basket_label": {"en": "AI / semis watch", "zh": "AI / 半导体关注"},
        "methodology": {},
        "rows": [],
    }


def test_cross_section_forces_futu_and_passes_basket(tmp_path) -> None:
    calls = []

    def fake_reader(*, settings, basket=None, symbols=None, today=None):
        calls.append((basket, symbols))
        return _payload()

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_market_cross_section_reader] = lambda: fake_reader
    client = TestClient(app)

    response = client.get("/api/market-cross-section?provider=futu&basket=us_sectors")

    assert response.status_code == 200
    assert response.json()["provider"] == "futu"
    assert calls == [("us_sectors", None)]


def test_cross_section_rejects_non_futu_provider(tmp_path) -> None:
    app = create_app(output_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/market-cross-section?provider=sample")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "market_cross_section_requires_futu"


def test_cross_section_invalid_basket_is_400(tmp_path) -> None:
    def fail(*, settings, basket=None, symbols=None, today=None):
        raise HistoricalPriceReadError(
            code="market_cross_section_invalid_request",
            message="unknown basket 'nope'",
            provider="futu",
        )

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_market_cross_section_reader] = lambda: fail
    client = TestClient(app)

    response = client.get("/api/market-cross-section?basket=nope")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "market_cross_section_invalid_request"


def test_cross_section_provider_failure_is_503_without_sample(tmp_path) -> None:
    def fail(*, settings, basket=None, symbols=None, today=None):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_error",
            provider="futu",
            provider_code="opend_unavailable",
            message="Futu OpenD is unavailable",
        )

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_market_cross_section_reader] = lambda: fail
    client = TestClient(app)

    response = client.get("/api/market-cross-section")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "market_cross_section_provider_unavailable"
    assert "sample" not in response.text.lower()
