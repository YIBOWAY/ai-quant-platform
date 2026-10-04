import json

import pandas as pd
import pytest

from quant_system.config.settings import load_settings
from quant_system.research import evaluation_service as service


@pytest.fixture
def settings(tmp_path):
    value = load_settings()
    value.data.data_dir = tmp_path
    return value


def test_read_is_observational_and_empty(settings, monkeypatch):
    monkeypatch.setattr(
        service, "build_ohlcv_provider", lambda *a, **k: pytest.fail("GET fetched data")
    )
    assert service.read_evaluation(settings)["status"] == "not_started"
    assert not service._root(settings).exists()


def test_compiled_candidate_uses_symbol_history_and_rejects_code():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"], utc=True
            ),
            "symbol": ["QQQ", "QQQ", "SPY", "SPY"],
            "close": [10.0, 12.0, 20.0, 18.0],
        }
    )
    result = service.candidate_feature(frame, "$close/Ref($close,1)-1")
    assert result.loc[(pd.Timestamp("2024-01-02", tz="UTC"), "QQQ")] == pytest.approx(0.2)
    assert result.loc[(pd.Timestamp("2024-01-02", tz="UTC"), "SPY")] == pytest.approx(-0.1)
    with pytest.raises(ValueError):
        service.candidate_feature(frame, "__import__('os').system('anything')")


def test_source_changed_is_not_current_result(settings, monkeypatch):
    previous = {
        **service._empty(),
        "status": "ready",
        "source_digest": "old",
        "reference": {"rows": []},
    }
    service._write(service._latest(settings, None), previous)
    before = service._latest(settings, None).read_bytes()
    monkeypatch.setattr(service, "source_digest", lambda: "new")
    result = service.read_evaluation(settings)
    assert result["status"] == "stale"
    assert result["reference"] == previous["reference"]
    assert service._latest(settings, None).read_bytes() == before


def test_interrupted_run_is_not_success_and_get_does_not_write(settings, monkeypatch):
    service._write(
        service._latest(settings, None), {**service._empty(), "status": "updating", "pid": 12345}
    )
    before = service._latest(settings, None).read_bytes()

    def missing(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(service.os, "kill", missing)
    assert service.read_evaluation(settings)["status"] == "failed"
    assert service._latest(settings, None).read_bytes() == before


def test_persisted_reference_survives_qlib_failure(settings, monkeypatch):
    from quant_system.research import reference_backtests

    prices = pd.DataFrame(
        {"symbol": ["QQQ"], "timestamp": pd.to_datetime(["2024-01-01"], utc=True)}
    )
    features = pd.DataFrame(
        {"momentum": [1.0]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01", tz="UTC"), "QQQ")], names=["datetime", "instrument"]
        ),
    )
    monkeypatch.setattr(service, "source_digest", lambda: "code")
    monkeypatch.setattr(
        service,
        "prepare_prices",
        lambda *a: (prices, {"data_end": "2024-01-01", "prices_sha256": "price"}),
    )
    monkeypatch.setattr(reference_backtests, "compute_reference_features", lambda *a: features)
    monkeypatch.setattr(
        reference_backtests,
        "build_reference_backtests",
        lambda *a, **k: {"rows": [{"key": "factor:momentum", "metrics": {"sharpe": 0.3}}]},
    )

    def fail(directory):
        raise RuntimeError("container_failed")

    monkeypatch.setattr(service, "_run_qlib", fail)
    result = service.refresh_evaluation(settings)
    assert result["status"] == "partial"
    assert result["reference"]["rows"][0]["metrics"]["sharpe"] == 0.3
    assert result["rolling"] is None
    report = service._root(settings) / "runs" / result["run_id"] / "report.json"
    assert json.loads(report.read_text())["error"]
    assert not (settings.data.data_dir / "api_runs").exists()


def test_view_does_not_send_full_model_arrays():
    value = {
        "predictions": [1, 2],
        "daily_returns": [0.1],
        "metrics": {"sharpe": 1.23},
        "curve": [{"date": str(n), "equity": n + 1} for n in range(900)],
    }
    shown = service._view(value)
    assert "predictions" not in shown and "daily_returns" not in shown
    assert shown["metrics"] == value["metrics"]
    assert len(shown["curve"]) <= 401
    assert shown["curve"][-1] == value["curve"][-1]


@pytest.mark.parametrize("raw", [[], None, {"status": "imaginary"}])
def test_invalid_cache_is_failure_without_repair(settings, raw):
    path = service._latest(settings, None)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    assert service.read_evaluation(settings)["status"] == "failed"
    assert path.read_bytes() == before


def test_candidate_configuration_is_checked_on_read(settings, monkeypatch):
    key = "research:artifact-existing"
    old = {"source_digest": "old-candidate", "expression": "$close", "universe": ["QQQ"]}
    service._write(
        service._latest(settings, key),
        {
            **service._empty(key),
            "status": "ready",
            "source_digest": "code",
            "source": {"candidate": old},
        },
    )
    monkeypatch.setattr(service, "source_digest", lambda: "code")
    monkeypatch.setattr(service, "_candidate", lambda *a: {**old, "expression": "Ref($close,1)"})
    assert service.read_evaluation(settings, key)["status"] == "stale"


def test_other_key_is_busy_not_false_acceptance(settings, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from quant_system.api.dependencies import require_mutation_security
    from quant_system.api.routes import research_evaluation as route

    app = FastAPI()
    app.state.services = {"settings": settings}
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(route, "_ACTIVE_KEY", "research:artifact-first")
    monkeypatch.setattr(
        route, "refresh_evaluation", lambda *a: pytest.fail("unexpected evaluation")
    )
    route._RESEARCH_LOCK.acquire()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/research-evaluation/refresh", json={"key": "research:artifact-second"}
        )
        assert response.status_code == 409
        assert (
            client.get("/api/research-evaluation?key=research:artifact-second").json()["status"]
            == "not_started"
        )
        assert (
            client.get("/api/research-evaluation?key=research:artifact-first").json()["status"]
            == "updating"
        )
    finally:
        route._RESEARCH_LOCK.release()
