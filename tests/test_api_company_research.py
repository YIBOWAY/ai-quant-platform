from fastapi.testclient import TestClient

from quant_system.api.dependencies import require_mutation_security
from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.research import company_research as service
from quant_system.research import data_source_checks


def client(tmp_path):
    settings = Settings()
    settings.data.data_dir = tmp_path / "data"
    settings.database.enabled = False
    settings.hermes_gateway.enabled = False
    app = create_app(settings=settings, output_dir=tmp_path / "runs")
    return TestClient(app), app, settings


def test_get_and_compare_do_not_collect_or_create_cache(tmp_path, monkeypatch):
    c, _, settings = client(tmp_path)

    def forbidden(*_, **__):
        raise AssertionError("read must not collect")

    monkeypatch.setattr(service, "collect_company", forbidden)
    response = c.get("/api/company-research", params={"symbol": "NVDA"})
    assert response.status_code == 200
    assert response.json()["status"] == "not_loaded"
    assert response.json()["symbol"] == "NVDA.US"
    response = c.get("/api/company-research/compare", params={"symbols": "NVDA,AAPL"})
    assert [x["symbol"] for x in response.json()["items"]] == ["NVDA.US", "AAPL.US"]
    assert not (settings.data.data_dir / "company_research").exists()


def test_invalid_symbol_and_unbounded_compare_rejected(tmp_path):
    c, _, _ = client(tmp_path)
    assert c.get("/api/company-research", params={"symbol": "../../secret"}).status_code == 422
    assert (
        c.get("/api/company-research/compare", params={"symbols": "A,B,C,D,E"}).status_code == 422
    )


def test_refresh_requires_owner_security_before_collection(tmp_path, monkeypatch):
    c, _, _ = client(tmp_path)
    monkeypatch.setattr(
        service, "begin_refresh", lambda *_: (_ for _ in ()).throw(AssertionError())
    )
    assert c.post("/api/company-research/refresh", json={"symbol": "NVDA"}).status_code in {
        401,
        403,
    }


def test_authorized_refresh_has_durable_result_not_only_ack(tmp_path, monkeypatch):
    c, app, settings = client(tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None

    def collect(_settings, symbol, **_):
        return {
            **service._empty(symbol),
            "status": "partial",
            "updated_at": service._now(),
            "headline": "真实采集替身仅用于密封测试",
            "summary": ["无交易副作用"],
        }

    monkeypatch.setattr(service, "collect_company", collect)
    response = c.post("/api/company-research/refresh", json={"symbol": "NVDA"})
    assert response.status_code == 202
    stored = c.get("/api/company-research", params={"symbol": "NVDA"}).json()
    assert stored["status"] == "partial" and len(stored["snapshot_id"]) == 64
    assert stored["pit_backtest_ready"] is False
    assert not list(settings.data.data_dir.rglob("*execution*"))


def test_sources_install_state_is_not_permission_proof(tmp_path, monkeypatch):
    c, _, _ = client(tmp_path)
    monkeypatch.setattr(data_source_checks, "_installed", lambda: (True, "longbridge 0.28.5"))
    response = c.get("/api/data-sources").json()
    assert response["status"] == "not_checked"
    assert response["sources"][1]["status"] == "installed"
    assert response["checks"] == []


def test_backup_route_uses_only_explicit_longbridge_chain(tmp_path, monkeypatch):
    from quant_system.api.routes import company_research as route
    from quant_system.data.backup_bars import BackupChainResult
    from quant_system.data.price_history import HistoricalPriceSnapshot

    c, _, _ = client(tmp_path)

    def read(**kwargs):
        assert kwargs["backup_providers"] == ("longbridge",)
        return BackupChainResult(
            HistoricalPriceSnapshot(
                provider="longbridge", source="longbridge", interval="1d",
                adjustment="forward", start="2026-01-02", end="2026-01-05",
                fetched_at="2026-01-06T00:00:00+00:00", symbols=["SPY"],
                series=[{"symbol": "SPY", "rows": [{"date": "2026-01-02", "close": 100}]}],
            ),
            fallbacks=[{"provider": "futu", "code": "opend_unavailable"}],
        )

    monkeypatch.setattr(route, "read_daily_bars_with_backup", read)
    result = c.get(
        "/api/market-data/daily-backup",
        params={"symbols": "SPY", "start": "2026-01-02", "end": "2026-01-05"},
    ).json()
    assert result["served_by"] == "longbridge"
    assert result["fallbacks"][0]["provider"] == "futu"
    assert result["series"][0]["rows"][0]["close"] == 100
