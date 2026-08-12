from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def _ensure_rollup_repository_module() -> Any:
    """Return the rollup archive module, installing a contract-faithful stand-in
    when agent A's ``rollup_repository.py`` has not landed yet. The endpoints
    import it lazily per request, so tests only need the names to exist.
    """
    try:
        from quant_system.brief import rollup_repository as module

        return module
    except ModuleNotFoundError:
        pass

    module = types.ModuleType("quant_system.brief.rollup_repository")

    @dataclass(frozen=True)
    class BriefRollupIssue:
        rollup_id: str
        public_id: str
        kind: str
        period_key: str
        period_start: date
        period_end: date
        locale: str
        status: str

    @dataclass(frozen=True)
    class BriefRollupSnapshot:
        snapshot_id: str
        version: int
        payload: dict[str, Any]
        source_watermark: dict[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class BriefRollupEnvelope:
        issue: BriefRollupIssue
        snapshot: BriefRollupSnapshot
        warnings: list[str] = field(default_factory=list)

    @dataclass(frozen=True)
    class BriefRollupListItem:
        public_id: str
        kind: str
        period_key: str
        period_start: date
        period_end: date
        locale: str
        status: str
        title: str
        snippet: str

    class BriefRollupDatabaseUnavailable(RuntimeError):
        pass

    class BriefRollupNotFound(LookupError):
        pass

    class BriefRollupRepository:
        def __init__(self, settings: Any) -> None:
            self._settings = settings

    names = {
        "BriefRollupIssue": BriefRollupIssue,
        "BriefRollupSnapshot": BriefRollupSnapshot,
        "BriefRollupEnvelope": BriefRollupEnvelope,
        "BriefRollupListItem": BriefRollupListItem,
        "BriefRollupDatabaseUnavailable": BriefRollupDatabaseUnavailable,
        "BriefRollupNotFound": BriefRollupNotFound,
        "BriefRollupRepository": BriefRollupRepository,
    }
    for name, value in names.items():
        setattr(module, name, value)
    module.__all__ = list(names)
    sys.modules["quant_system.brief.rollup_repository"] = module
    return module


rollup_repository = _ensure_rollup_repository_module()


def _list_item() -> Any:
    return rollup_repository.BriefRollupListItem(
        public_id="brw_20260810_x1y2z3",
        kind="weekly",
        period_key="2026-W33",
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 16),
        locale="zh",
        status="published",
        title="本周主线",
        snippet="主线摘要。",
    )


def _envelope() -> Any:
    return rollup_repository.BriefRollupEnvelope(
        issue=rollup_repository.BriefRollupIssue(
            rollup_id="rollup-1",
            public_id="brw_20260810_x1y2z3",
            kind="weekly",
            period_key="2026-W33",
            period_start=date(2026, 8, 10),
            period_end=date(2026, 8, 16),
            locale="zh",
            status="published",
        ),
        snapshot=rollup_repository.BriefRollupSnapshot(
            snapshot_id="snapshot-1",
            version=2,
            payload={"schema_version": "brief_rollup_v1", "title": "本周主线"},
            source_watermark={"facts_digest": "abc"},
        ),
        warnings=["w-a"],
    )


def _patch_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list[Any] | None = None,
    envelope: Any = None,
    error: Exception | None = None,
) -> None:
    class _FakeService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def list_rollups(self, *, kind: str, locale: str, limit: int = 30) -> list[Any]:
            if error is not None:
                raise error
            return list(items or [])

        def get_rollup(self, public_id: str) -> Any:
            if error is not None:
                raise error
            return envelope

    monkeypatch.setattr(
        "quant_system.api.routes.brief.BriefRollupService", _FakeService
    )


def test_list_rollups_returns_items_and_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_service(monkeypatch, items=[_list_item()])
    client = TestClient(create_app())

    response = client.get(
        "/api/brief/rollups", params={"kind": "weekly", "locale": "zh", "limit": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "weekly"
    assert body["locale"] == "zh"
    assert body["total"] == 1
    assert body["items"] == [
        {
            "public_id": "brw_20260810_x1y2z3",
            "kind": "weekly",
            "period_key": "2026-W33",
            "period_start": "2026-08-10",
            "period_end": "2026-08-16",
            "locale": "zh",
            "status": "published",
            "title": "本周主线",
            "snippet": "主线摘要。",
        }
    ]


def test_list_rollups_rejects_invalid_kind_and_oversized_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_service(monkeypatch, items=[])
    client = TestClient(create_app())

    bad_kind = client.get("/api/brief/rollups", params={"kind": "daily"})
    assert bad_kind.status_code == 422

    bad_limit = client.get("/api/brief/rollups", params={"limit": 101})
    assert bad_limit.status_code == 422


def test_list_rollups_database_unavailable_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_service(
        monkeypatch,
        error=rollup_repository.BriefRollupDatabaseUnavailable("down"),
    )
    client = TestClient(create_app())

    response = client.get("/api/brief/rollups")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_rollup_unavailable"


def test_get_rollup_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_service(monkeypatch, envelope=_envelope())
    client = TestClient(create_app())

    response = client.get("/api/brief/rollups/brw_20260810_x1y2z3")

    assert response.status_code == 200
    body = response.json()
    assert body["issue"] == {
        "rollup_id": "rollup-1",
        "public_id": "brw_20260810_x1y2z3",
        "kind": "weekly",
        "period_key": "2026-W33",
        "period_start": "2026-08-10",
        "period_end": "2026-08-16",
        "locale": "zh",
        "status": "published",
    }
    assert body["snapshot"] == {
        "snapshot_id": "snapshot-1",
        "version": 2,
        "payload": {"schema_version": "brief_rollup_v1", "title": "本周主线"},
        "source_watermark": {"facts_digest": "abc"},
    }
    assert body["warnings"] == ["w-a"]


def test_get_rollup_not_found_is_404_with_public_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_service(
        monkeypatch,
        error=rollup_repository.BriefRollupNotFound("brw_20990101_missing"),
    )
    client = TestClient(create_app())

    response = client.get("/api/brief/rollups/brw_20990101_missing")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "brief_rollup_not_found"
    assert detail["public_id"] == "brw_20990101_missing"


def test_get_rollup_database_unavailable_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_service(
        monkeypatch,
        error=rollup_repository.BriefRollupDatabaseUnavailable("down"),
    )
    client = TestClient(create_app())

    response = client.get("/api/brief/rollups/brw_20260810_x1y2z3")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_rollup_unavailable"
