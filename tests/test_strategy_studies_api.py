from threading import Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quant_system.api.dependencies import require_mutation_security
from quant_system.api.routes import strategy_studies as route
from quant_system.api.safety.local_session import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    exchange_bootstrap_token,
    issue_bootstrap_token,
)
from quant_system.config.settings import load_settings


@pytest.fixture
def app(tmp_path, monkeypatch):
    settings = load_settings().model_copy(deep=True)
    settings.data.data_dir = tmp_path
    settings.local_mutation.enabled = True
    settings.api_cors_origins = ["http://127.0.0.1:3001"]
    monkeypatch.setattr(route, "_STUDY_LOCK", Lock())
    monkeypatch.setattr(route, "_ACTIVE_DISCOVERY", None)
    app = FastAPI()
    app.state.services = {"settings": settings, "output_dir": tmp_path, "bind_address": "127.0.0.1"}
    app.include_router(route.router, prefix="/api")
    return app


def test_get_is_observational_and_schema_filters_private_process_fields(app, monkeypatch, tmp_path):
    monkeypatch.setattr(route, "run_studies", lambda *a, **k: pytest.fail("GET started research"))
    client = TestClient(app)
    result = client.get("/api/strategy-studies")
    assert result.status_code == 200
    assert result.json()["status"] == "not_started"
    assert result.json()["profiles"]
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(
        route,
        "read_studies",
        lambda settings: {
            "status": "partial",
            "pid": 123,
            "source": {"provider": "futu"},
            "discovery": {"status": "failed", "error": "provider_or_runtime_error"},
        },
    )
    payload = client.get("/api/strategy-studies").json()
    assert "pid" not in payload
    assert payload["discovery"]["status"] == "failed"
    assert payload["source"]["provider"] == "futu"


@pytest.mark.parametrize("body, expected", [({}, False), ({"include_discovery": True}, True)])
def test_post_schedules_exact_explicit_mode_and_releases_slot(app, monkeypatch, body, expected):
    app.dependency_overrides[require_mutation_security] = lambda: None
    calls = []
    monkeypatch.setattr(route, "run_studies", lambda settings, **kwargs: calls.append(kwargs))
    response = TestClient(app).post("/api/strategy-studies/refresh", json=body)
    assert response.status_code == 202
    assert response.json()["status"] == "updating"
    assert calls == [{"include_discovery": expected}]
    assert not route._STUDY_LOCK.locked()
    assert route._ACTIVE_DISCOVERY is None


def test_active_same_request_reuses_slot_and_cannot_upgrade_to_model(app, monkeypatch):
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(route, "run_studies", lambda *a, **k: pytest.fail("duplicate research"))
    route._STUDY_LOCK.acquire()
    monkeypatch.setattr(route, "_ACTIVE_DISCOVERY", False)
    client = TestClient(app)
    assert client.get("/api/strategy-studies").json()["status"] == "updating"
    assert client.post("/api/strategy-studies/refresh", json={}).status_code == 202
    assert (
        client.post("/api/strategy-studies/refresh", json={"include_discovery": True}).status_code
        == 409
    )
    route._STUDY_LOCK.release()


def test_external_running_report_is_not_queued_again(app, monkeypatch):
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(
        route,
        "read_studies",
        lambda settings: {
            "status": "updating",
            "run_id": "existing-study",
            "progress": "正在计算动量",
        },
    )
    monkeypatch.setattr(route, "run_studies", lambda *a, **k: pytest.fail("duplicate CLI run"))
    client = TestClient(app)
    result = client.post("/api/strategy-studies/refresh", json={})
    assert result.status_code == 202 and result.json()["run_id"] == "existing-study"
    assert result.json()["progress"] == "正在计算动量"
    assert (
        client.post("/api/strategy-studies/refresh", json={"include_discovery": True}).status_code
        == 409
    )
    assert not route._STUDY_LOCK.locked()


def test_real_owner_and_csrf_checks_block_research_before_work(app, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(route, "run_studies", lambda settings, **kw: calls.append(kw))
    client = TestClient(app, base_url="http://127.0.0.1:3001")
    headers = {"Origin": "http://127.0.0.1:3001", "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/strategy-studies/refresh", json={}, headers=headers).status_code == 401
    issued = exchange_bootstrap_token(tmp_path, issue_bootstrap_token(tmp_path))
    client.cookies.set(SESSION_COOKIE_NAME, issued.session_cookie_value)
    assert client.post("/api/strategy-studies/refresh", json={}, headers=headers).status_code == 403
    assert (
        client.post(
            "/api/strategy-studies/refresh",
            json={},
            headers={
                **headers,
                CSRF_HEADER_NAME: "invalid",
            },
        ).status_code
        == 403
    )
    assert calls == []
    result = client.post(
        "/api/strategy-studies/refresh",
        json={},
        headers={
            **headers,
            CSRF_HEADER_NAME: issued.session.csrf_token,
        },
    )
    assert result.status_code == 202
    assert calls == [{"include_discovery": False}]


def test_ambiguous_or_extra_request_fields_cannot_enable_discovery(app, monkeypatch):
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(route, "run_studies", lambda *a, **k: pytest.fail("invalid request ran"))
    client = TestClient(app)
    assert (
        client.post(
            "/api/strategy-studies/refresh", json={"include_discovery": "false"}
        ).status_code
        == 422
    )
    assert client.post("/api/strategy-studies/refresh", json={"model": "other"}).status_code == 422


def test_unexpected_background_failure_releases_slot(app, monkeypatch):
    app.dependency_overrides[require_mutation_security] = lambda: None

    def fail(*args, **kwargs):
        raise RuntimeError("sealed failure")

    monkeypatch.setattr(route, "run_studies", fail)
    with pytest.raises(RuntimeError, match="sealed failure"):
        TestClient(app).post("/api/strategy-studies/refresh", json={})
    assert not route._STUDY_LOCK.locked()
    assert route._ACTIVE_DISCOVERY is None


def test_exact_study_profile_get_preserves_signal_and_trade_history(app, monkeypatch):
    calls = []

    def read(settings, run_id, profile_id, *, signal_date=None):
        calls.append((run_id, profile_id, signal_date))
        return {
            "run_id": run_id,
            "profile_id": profile_id,
            "profile": {"id": profile_id},
            "status": "available",
            "signal_dates": ["2021-01-29", "2021-02-26"],
            "selected_signal_date": signal_date,
            "signals": [
                {
                    "signal_date": signal_date,
                    "scores": [{"symbol": "AAA", "score": 2}],
                    "targets": {"AAA": 1},
                }
            ],
            "trades": [{"date": "2021-02-01", "symbol": "AAA", "side": "buy"}],
            "reconciliation": {"status": "matched", "cash": 100},
            "pid": 123,
        }

    monkeypatch.setattr(route, "read_study_profile", read)
    monkeypatch.setattr(route, "run_studies", lambda *a, **k: pytest.fail("GET started work"))
    client = TestClient(app)
    result = client.get(
        "/api/strategy-studies/study-saved/profiles/stocks_momentum_12_2?signal_date=2021-01-29"
    )
    assert result.status_code == 200
    payload = result.json()
    assert calls == [("study-saved", "stocks_momentum_12_2", "2021-01-29")]
    assert payload["signals"][0]["scores"][0]["score"] == 2
    assert len(payload["signal_dates"]) == 2 and payload["trades"]
    assert payload["reconciliation"]["status"] == "matched"
    assert "pid" not in payload
    assert (
        client.get(
            "/api/strategy-studies/study-saved/profiles/test?signal_date=nonsense"
        ).status_code
        == 422
    )


def test_exact_run_and_missing_profile_are_observational(app, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/strategy-studies/study-missing").status_code == 404
    assert client.get("/api/strategy-studies/study-missing/profiles/test").status_code == 404
    assert client.get("/api/strategy-studies/invalid-id").status_code == 422
