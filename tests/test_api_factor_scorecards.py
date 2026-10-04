"""API surface for the stored factor scorecard dashboard.

The GET path is strictly observational (it never recomputes statistics) and must
answer ``unavailable`` rather than a 500 before the first run. The POST path is a
mutation-secured, single-flight refresh: one run at a time, 409 on a second
concurrent request, and an explicit rejection when owner security is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quant_system.api.dependencies import require_mutation_security
from quant_system.api.routes import factor_scorecards as route
from quant_system.api.schemas.factor_scorecards import FactorScorecardRefreshRequest
from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, DataSettings, Settings
from quant_system.factors.scorecard import SCORECARD_SCHEMA_VERSION, current_source_digest
from quant_system.factors.scorecard_service import (
    LATEST_UNREADABLE_REASON,
    refresh_factor_scorecards,
)


def _isolated_settings(tmp_path) -> Settings:
    """Keep every write (scorecards + trials tombstone) inside ``tmp_path``."""

    return Settings(
        data=DataSettings(
            data_dir=tmp_path / "data",
            parquet_dir=tmp_path / "parquet",
            duckdb_path=tmp_path / "quant_system.duckdb",
            reports_dir=tmp_path / "reports",
        ),
        api_keys=ApiKeySettings(),
    )


def test_default_refresh_requires_a_real_provider():
    assert FactorScorecardRefreshRequest().provider == "futu"


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(settings=_isolated_settings(tmp_path), output_dir=tmp_path))


def _stored_scorecard() -> dict:
    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "generated_at": "2026-09-18T00:00:00+00:00",
        "status": "ready",
        "stale": False,
        "methodology": {"price_basis": "open_to_open", "horizons": [1, 5, 21]},
        "provenance": {
            "methodology_version": "factor-eval-2",
            "source_digest": current_source_digest(),
        },
        "factors": [
            {
                "factor_id": "momentum",
                "direction": "higher_is_better",
                "horizons": {"1": {"ic": {"ic_mean": 0.0123, "nw_t": 1.9}}},
                "correlation": {"max_abs_factor_correlation": 0.31},
                "industry_neutral": {"status": "field_unavailable"},
            }
        ],
    }


def test_get_without_run_is_observational_and_not_a_server_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        route, "refresh_factor_scorecards", lambda *a, **k: pytest.fail("GET refreshed")
    )
    client = _client(tmp_path)

    response = client.get("/api/factor-scorecards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "no_scorecard_run"
    assert payload["stale"] is False
    assert not (tmp_path / "factor_scorecards").exists()


def test_get_with_run_returns_stored_scorecard_and_freshness(tmp_path) -> None:
    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_text(
        json.dumps(_stored_scorecard(), ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    client = _client(tmp_path)

    payload = client.get("/api/factor-scorecards").json()

    assert payload["status"] == "ready"
    assert payload["schema_version"] == SCORECARD_SCHEMA_VERSION
    assert payload["stale"] is False
    assert payload["factors"][0]["factor_id"] == "momentum"
    assert payload["factors"][0]["horizons"]["1"]["ic"]["nw_t"] == pytest.approx(1.9)
    assert payload["methodology"]["price_basis"] == "open_to_open"


def test_get_flags_stale_scorecard_without_rewriting_it(tmp_path) -> None:
    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    stored = _stored_scorecard()
    stored["provenance"]["source_digest"] = "0" * 64
    latest_path = base / "latest.json"
    latest_path.write_text(json.dumps(stored, allow_nan=False), encoding="utf-8")
    before = latest_path.read_bytes()
    client = _client(tmp_path)

    payload = client.get("/api/factor-scorecards").json()

    assert payload["stale"] is True
    assert payload["status"] == "ready"
    assert latest_path.read_bytes() == before


def test_get_reports_a_truncated_latest_json_as_unavailable(tmp_path) -> None:
    """A half-written deck must not turn the observational GET into a 500."""

    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_text(
        '{"schema_version": "factor_scorecard_v1", "factors": [', encoding="utf-8"
    )
    client = _client(tmp_path)

    response = client.get("/api/factor-scorecards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == LATEST_UNREADABLE_REASON
    assert payload["stale"] is False
    assert payload["factors"] == []


def test_get_reports_json_that_is_not_an_object_as_unavailable(tmp_path) -> None:
    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_text("[1, 2, 3]", encoding="utf-8")

    payload = _client(tmp_path).get("/api/factor-scorecards").json()

    assert payload["status"] == "unavailable"
    assert payload["reason"] == LATEST_UNREADABLE_REASON


def test_get_reports_byte_damaged_latest_json_as_unavailable(tmp_path) -> None:
    """Invalid UTF-8 raises UnicodeDecodeError (a ValueError, not OSError) — the
    reader must absorb it too or the observational GET answers 500."""

    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_bytes(b"\xff\xfe\x00\x01\x02")

    response = _client(tmp_path).get("/api/factor-scorecards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == LATEST_UNREADABLE_REASON


def test_get_reports_wrong_typed_members_as_unavailable(tmp_path) -> None:
    """Valid JSON whose top-level members do not match the response types must not
    reach response validation (where it would surface as a 500)."""

    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_text(
        '{"status": "ready", "provenance": "oops", "factors": "nope"}', encoding="utf-8"
    )

    response = _client(tmp_path).get("/api/factor-scorecards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == LATEST_UNREADABLE_REASON


def test_post_refresh_read_path_survives_a_truncated_latest_json(tmp_path, monkeypatch) -> None:
    """The POST read-before-schedule path shares the same tolerant reader."""

    settings = _isolated_settings(tmp_path)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(route, "refresh_factor_scorecards", lambda *a, **k: None)
    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    (base / "latest.json").write_text("{not json", encoding="utf-8")
    client = TestClient(app)

    response = client.post("/api/factor-scorecards/refresh", json={})

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "updating"
    assert payload["reason"] == LATEST_UNREADABLE_REASON
    assert not route._SCORECARD_LOCK.locked()


def test_latest_json_write_is_atomic_and_never_truncates(tmp_path, monkeypatch) -> None:
    """A crash before the rename keeps the previous deck whole and leaves no temp file."""

    settings = _isolated_settings(tmp_path)
    base = tmp_path / "factor_scorecards"
    base.mkdir(parents=True)
    latest_path = base / "latest.json"
    good = _stored_scorecard()
    latest_path.write_text(json.dumps(good, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    before = latest_path.read_bytes()

    def _interrupted_replace(self, target):
        raise RuntimeError("simulated crash before the rename")

    monkeypatch.setattr(Path, "replace", _interrupted_replace)
    with pytest.raises(RuntimeError):
        refresh_factor_scorecards(
            settings,
            {"provider": "sample", "start": "2024-01-02", "end": "2024-03-29", "lookback": 3},
            output_dir=base,
        )

    assert latest_path.read_bytes() == before
    assert json.loads(latest_path.read_text(encoding="utf-8")) == good
    assert not [entry for entry in base.iterdir() if entry.name.endswith(".tmp")]


def test_post_refresh_schedules_isolated_run_and_returns_202(tmp_path, monkeypatch) -> None:
    settings = _isolated_settings(tmp_path)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    calls: list[dict] = []
    monkeypatch.setattr(
        route,
        "refresh_factor_scorecards",
        lambda _settings, request, *, output_dir=None, **kwargs: calls.append(
            {"request": request, "output_dir": output_dir}
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/factor-scorecards/refresh",
        json={"provider": "sample", "lookback": 3, "start": "2024-01-02", "end": "2024-03-29"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "updating"
    assert payload["progress"]
    assert len(calls) == 1
    assert calls[0]["output_dir"] == tmp_path / "factor_scorecards"
    assert calls[0]["request"]["provider"] == "sample"
    assert calls[0]["request"]["lookback"] == 3
    assert calls[0]["request"]["horizons"] == [1, 5, 21]
    assert not route._SCORECARD_LOCK.locked()
    # The isolated settings carry an isolated data dir: no production data/ writes.
    assert not (settings.data.data_dir / "factor_scorecards").exists()
    assert not (tmp_path / "data").exists()


def test_post_refresh_runs_real_service_then_get_reads_latest(tmp_path) -> None:
    """Exercise the scheduling + storage wiring end to end on the sample provider."""

    settings = _isolated_settings(tmp_path)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    client = TestClient(app)

    response = client.post(
        "/api/factor-scorecards/refresh",
        json={
            "provider": "sample",
            "universe_id": "etf",
            "start": "2024-01-02",
            "end": "2024-03-29",
            "lookback": 3,
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "updating"
    latest_path = tmp_path / "factor_scorecards" / "latest.json"
    assert latest_path.exists()
    assert not [entry for entry in latest_path.parent.iterdir() if entry.name.endswith(".tmp")]

    stored = client.get("/api/factor-scorecards").json()
    assert stored["status"] in {"ready", "partial"}
    assert stored["factors"]
    assert stored["run"]["run_id"].startswith("scorecard-")
    assert stored["provenance"]["input_digest"]
    assert not route._SCORECARD_LOCK.locked()


def test_second_concurrent_refresh_is_409(tmp_path, monkeypatch) -> None:
    settings = _isolated_settings(tmp_path)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    monkeypatch.setattr(
        route, "refresh_factor_scorecards", lambda *a, **k: pytest.fail("unexpected refresh")
    )
    client = TestClient(app)

    route._SCORECARD_LOCK.acquire()
    try:
        assert client.get("/api/factor-scorecards").json()["status"] == "updating"
        response = client.post("/api/factor-scorecards/refresh", json={})
        assert response.status_code == 409
        assert "正在运行" in response.json()["detail"]
    finally:
        route._SCORECARD_LOCK.release()


def test_background_failure_retains_an_observable_error_and_releases_lock(tmp_path, monkeypatch):
    settings = _isolated_settings(tmp_path)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None

    def fail(*args, **kwargs):
        raise RuntimeError("failure details must not leak arbitrary exception text")

    monkeypatch.setattr(route, "refresh_factor_scorecards", fail)
    client = TestClient(app)
    assert client.post("/api/factor-scorecards/refresh", json={}).status_code == 202
    saved = client.get("/api/factor-scorecards").json()
    assert saved["operation"]["status"] == "failed"
    assert saved["error"] == "scorecard_refresh_failed:RuntimeError"
    assert not route._SCORECARD_LOCK.locked()


def test_refresh_requires_owner_security_before_scheduling(tmp_path, monkeypatch) -> None:
    settings = _isolated_settings(tmp_path)
    app = FastAPI()
    app.state.services = {
        "settings": settings,
        "output_dir": tmp_path,
        "bind_address": "127.0.0.1",
    }
    app.include_router(route.router, prefix="/api")
    monkeypatch.setattr(
        route, "refresh_factor_scorecards", lambda *a, **k: pytest.fail("unsecured refresh ran")
    )

    response = TestClient(app).post("/api/factor-scorecards/refresh", json={})

    assert response.status_code in {401, 403}
    assert not route._SCORECARD_LOCK.locked()
