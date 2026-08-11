from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
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


def _market(symbol: str, market_id: str, local_index: dict) -> dict:
    return {
        "market_id": market_id,
        "name_en": market_id,
        "name_zh": market_id,
        "symbol": symbol,
        "data_status": "real",
        "market_coverage": "proxy",
        "rank": 1,
        "k_leg": "middle",
        "returns": {"week_pct": 1.0, "month_pct": 2.0, "ytd_pct": 3.0},
        "volatility_pct": 18.0,
        "max_drawdown_pct": -5.0,
        "history": [{"date": "2026-02-13", "close": 100.0, "indexed_return_pct": 0.0}],
        "meta": {
            "provider": "futu",
            "symbol": symbol,
            "currency": "USD",
            "timezone": "America/New_York",
            "as_of": "2026-02-13",
            "adjustment": "qfq",
            "provenance": "futu",
        },
        "local_index": local_index,
    }


def test_overview_response_carries_local_index_overlays(tmp_path) -> None:
    available_index = {
        "status": "available",
        "index_symbol": "HK.800000",
        "index_name_en": "Hang Seng Index",
        "index_name_zh": "恒生指数",
        "currency": "HKD",
        "timezone": "Asia/Hong_Kong",
        "as_of": "2026-02-12",
        "provider": "futu",
        "provenance": "futu_cache",
        "fetched_at": "2026-02-12T09:00:00+00:00",
        "adjustment": "qfq",
        "series": [
            {"date": "2026-02-11", "close": 21000.0, "indexed_return_pct": 0.0},
            {"date": "2026-02-12", "close": 21210.0, "indexed_return_pct": 1.0},
        ],
        "reason_code": None,
        "reason": None,
        "provider_code": None,
    }
    pending_index = {
        "status": "unavailable",
        "index_symbol": None,
        "index_name_en": "KOSPI",
        "index_name_zh": "KOSPI 指数",
        "currency": None,
        "timezone": None,
        "as_of": None,
        "provider": None,
        "provenance": None,
        "fetched_at": None,
        "adjustment": None,
        "series": [],
        "reason_code": "market_format_unsupported",
        "reason": "Futu OpenD does not support KS market codes.",
        "provider_code": None,
    }
    error_index = {
        "status": "unavailable",
        "index_symbol": "JP..N225",
        "index_name_en": "Nikkei 225",
        "index_name_zh": "日经 225 指数",
        "currency": "JPY",
        "timezone": "Asia/Tokyo",
        "as_of": None,
        "provider": "futu",
        "provenance": None,
        "fetched_at": None,
        "adjustment": None,
        "series": [],
        "reason_code": "provider_error",
        "reason": "unable to connect to OpenD at 127.0.0.1:11111",
        "provider_code": "opend_unavailable",
    }

    def fake_reader(*, settings, today=None):
        overview = _overview()
        overview["schema_version"] = "1.2"
        overview["markets"] = [
            _market("EWH", "hong-kong", available_index),
            _market("EWY", "south-korea", pending_index),
            _market("EWJ", "japan", error_index),
        ]
        return overview

    app = create_app(output_dir=tmp_path)
    app.dependency_overrides[get_asia_radar_reader] = lambda: fake_reader
    client = TestClient(app)

    response = client.get("/api/asia-radar/overview?provider=futu")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.2"
    by_symbol = {market["symbol"]: market for market in payload["markets"]}
    hong_kong = by_symbol["EWH"]["local_index"]
    assert hong_kong["status"] == "available"
    assert hong_kong["currency"] == "HKD"
    assert hong_kong["timezone"] == "Asia/Hong_Kong"
    assert hong_kong["as_of"] == "2026-02-12"
    assert hong_kong["provenance"] == "futu_cache"
    assert hong_kong["series"][-1] == {
        "date": "2026-02-12",
        "close": 21210.0,
        "indexed_return_pct": 1.0,
    }
    south_korea = by_symbol["EWY"]["local_index"]
    assert south_korea["status"] == "unavailable"
    assert south_korea["reason_code"] == "market_format_unsupported"
    assert south_korea["series"] == []
    japan = by_symbol["EWJ"]["local_index"]
    assert japan["reason_code"] == "provider_error"
    assert japan["provider_code"] == "opend_unavailable"
    assert japan["series"] == []


def test_index_lane_outage_still_returns_200_with_honest_overlays(
    tmp_path, monkeypatch
) -> None:
    # Route-level proof: with the REAL composed reader, an OpenD outage on the
    # local-index lane degrades to overlay_missing states instead of a 503.
    from quant_system.data.price_history import HistoricalPriceSnapshot
    from quant_system.factors import asia_radar

    dates = pd.bdate_range("2025-12-31", periods=64)
    series = []
    for offset, symbol in enumerate(asia_radar.ASIA_ETF_SYMBOLS):
        rows = [
            {
                "date": day.date().isoformat(),
                "close": round(100.0 + offset + index * 0.1, 6),
            }
            for index, day in enumerate(dates)
        ]
        series.append(
            {
                "symbol": symbol,
                "row_count": len(rows),
                "first_date": rows[0]["date"],
                "last_date": rows[-1]["date"],
                "rows": rows,
            }
        )
    snapshot = HistoricalPriceSnapshot(
        provider="futu",
        source="futu",
        interval="1d",
        adjustment="qfq",
        start=dates[0].date().isoformat(),
        end=dates[-1].date().isoformat(),
        fetched_at="2026-03-30T20:00:00+00:00",
        symbols=list(asia_radar.ASIA_ETF_SYMBOLS),
        series=series,
    )
    monkeypatch.setattr(
        asia_radar, "read_historical_prices", lambda **kwargs: snapshot
    )
    monkeypatch.setattr(asia_radar, "_resolve_cache", lambda **kwargs: None)

    def lane_outage(**kwargs):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_unavailable",
            message="unable to connect to OpenD at 127.0.0.1:11111",
            provider_code="opend_unavailable",
        )

    monkeypatch.setattr(asia_radar, "read_local_index_overlays", lane_outage)

    class _FrozenDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 3, 30, 21, 0, tzinfo=UTC)

    monkeypatch.setattr(asia_radar, "datetime", _FrozenDateTime)

    app = create_app(output_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/asia-radar/overview?provider=futu")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.2"
    assert len(payload["markets"]) == 12
    for market in payload["markets"]:
        assert market["local_index"]["status"] == "unavailable"
        assert market["local_index"]["reason_code"] == "overlay_missing"
        assert market["local_index"]["series"] == []
