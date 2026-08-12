from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from quant_system.brief import rollup_repository
from quant_system.brief.rollup_repository import (
    BriefRollupDatabaseUnavailable,
    BriefRollupNotFound,
    BriefRollupRepository,
)
from quant_system.config.settings import Settings
from quant_system.storage.database import DatabaseUnavailable

ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"

ISSUE_ROW = (
    "11111111-1111-1111-1111-111111111111",
    "brf_w_2026w33_abcd",
    "weekly",
    "2026-W33",
    date(2026, 8, 10),
    date(2026, 8, 16),
    "zh",
    "published",
)
SNAPSHOT_ROW = (
    "22222222-2222-2222-2222-222222222222",
    2,
    {"title": "第 33 周周报", "main_storyline": "主线"},
    {"captured_at": "2026-08-16T08:30:00Z"},
)


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[Any, ...] | None]] = []
        self._fetchone_results: list[Any] = []
        self._fetchall_results: list[Any] = []
        self._raise_on_execute: Exception | None = None

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def transaction(self) -> FakeConnection:
        return self

    def queue_fetchone(self, *rows: Any) -> None:
        self._fetchone_results.extend(rows)

    def queue_fetchall(self, rows: list[Any]) -> None:
        self._fetchall_results = list(rows)

    def raise_on_execute(self, exc: Exception) -> None:
        self._raise_on_execute = exc

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
    ) -> FakeConnection:
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        self.executions.append((sql, params))
        return self

    def fetchone(self) -> Any:
        if not self._fetchone_results:
            return None
        return self._fetchone_results.pop(0)

    def fetchall(self) -> list[Any]:
        return list(self._fetchall_results)


class FakeDatabase:
    def __init__(
        self,
        connection: FakeConnection | None = None,
        *,
        connect_error: Exception | None = None,
    ) -> None:
        self.connection = connection or FakeConnection()
        self._connect_error = connect_error

    def connect(self) -> FakeConnection:
        if self._connect_error is not None:
            raise self._connect_error
        return self.connection


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def _repository(monkeypatch: pytest.MonkeyPatch, database: object) -> BriefRollupRepository:
    monkeypatch.setattr(rollup_repository, "get_database", lambda _settings: database)
    return BriefRollupRepository(Settings())


def _create_kwargs() -> dict[str, Any]:
    return {
        "kind": "weekly",
        "period_key": "2026-W33",
        "period_start": date(2026, 8, 10),
        "period_end": date(2026, 8, 16),
        "locale": "zh",
        "public_id": "brf_w_2026w33_abcd",
        "payload": {"title": "第 33 周周报", "main_storyline": "主线"},
        "source_watermark": {"captured_at": "2026-08-16T08:30:00Z"},
    }


def test_create_snapshot_requires_database(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, None)

    with pytest.raises(BriefRollupDatabaseUnavailable):
        repository.create_snapshot(**_create_kwargs())


def test_get_latest_by_public_id_requires_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(monkeypatch, None)

    with pytest.raises(BriefRollupDatabaseUnavailable):
        repository.get_latest_by_public_id("brf_w_2026w33_abcd")


def test_list_rollups_requires_database(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, None)

    with pytest.raises(BriefRollupDatabaseUnavailable):
        repository.list_rollups(kind="weekly", locale="zh")


def test_create_snapshot_upserts_issue_and_appends_versioned_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.queue_fetchone(ISSUE_ROW, (2,), SNAPSHOT_ROW)
    repository = _repository(monkeypatch, fake)
    kwargs = _create_kwargs()

    envelope = repository.create_snapshot(**kwargs)

    assert envelope.issue.rollup_id == ISSUE_ROW[0]
    assert envelope.issue.public_id == "brf_w_2026w33_abcd"
    assert envelope.issue.kind == "weekly"
    assert envelope.issue.period_key == "2026-W33"
    assert envelope.issue.period_start == date(2026, 8, 10)
    assert envelope.issue.period_end == date(2026, 8, 16)
    assert envelope.issue.locale == "zh"
    assert envelope.issue.status == "published"
    assert envelope.snapshot.snapshot_id == SNAPSHOT_ROW[0]
    assert envelope.snapshot.version == 2
    assert envelope.snapshot.payload == SNAPSHOT_ROW[2]
    assert envelope.snapshot.source_watermark == SNAPSHOT_ROW[3]
    assert envelope.warnings == []

    executions = fake.connection.executions
    assert len(executions) == 4

    issue_sql, issue_params = executions[0]
    issue_compact = _compact(issue_sql)
    assert "INSERT INTO quant_system.brief_rollup_issues" in issue_compact
    assert "ON CONFLICT (owner_user_id, kind, period_key, locale)" in issue_compact
    assert "DO UPDATE SET updated_at = now()" in issue_compact
    assert isinstance(issue_params[0], UUID)
    assert issue_params[1] == "brf_w_2026w33_abcd"
    assert str(issue_params[2]) == ROOT_USER_ID
    assert issue_params[3] == "weekly"
    assert issue_params[4] == "2026-W33"
    assert issue_params[5] == date(2026, 8, 10)
    assert issue_params[6] == date(2026, 8, 16)
    assert issue_params[7] == "zh"

    version_sql, version_params = executions[1]
    version_compact = _compact(version_sql)
    assert "SELECT COALESCE(MAX(version), 0) + 1" in version_compact
    assert "FROM quant_system.brief_rollup_snapshots" in version_compact
    assert "WHERE rollup_id = %s" in version_compact
    assert version_params == (ISSUE_ROW[0],)

    snapshot_sql, snapshot_params = executions[2]
    snapshot_compact = _compact(snapshot_sql)
    assert "INSERT INTO quant_system.brief_rollup_snapshots" in snapshot_compact
    assert isinstance(snapshot_params[0], UUID)
    assert snapshot_params[1] == ISSUE_ROW[0]
    assert snapshot_params[2] == 2
    assert isinstance(snapshot_params[3], Jsonb)
    assert snapshot_params[3].obj == kwargs["payload"]
    assert isinstance(snapshot_params[4], Jsonb)
    assert snapshot_params[4].obj == kwargs["source_watermark"]

    update_sql, update_params = executions[3]
    update_compact = _compact(update_sql)
    assert "UPDATE quant_system.brief_rollup_issues" in update_compact
    assert "SET latest_snapshot_id = %s" in update_compact
    assert "WHERE rollup_id = %s" in update_compact
    assert update_params == (SNAPSHOT_ROW[0], ISSUE_ROW[0])


def test_create_snapshot_defaults_empty_source_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.queue_fetchone(ISSUE_ROW, (1,), SNAPSHOT_ROW)
    repository = _repository(monkeypatch, fake)
    kwargs = _create_kwargs()
    del kwargs["source_watermark"]

    envelope = repository.create_snapshot(**kwargs)

    assert envelope.snapshot.version == 2  # envelope mirrors the RETURNING row
    snapshot_params = fake.connection.executions[2][1]
    assert snapshot_params[2] == 1
    assert isinstance(snapshot_params[4], Jsonb)
    assert snapshot_params[4].obj == {}


def test_create_snapshot_wraps_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        monkeypatch,
        FakeDatabase(connect_error=DatabaseUnavailable("database is down")),
    )

    with pytest.raises(BriefRollupDatabaseUnavailable, match="database is down"):
        repository.create_snapshot(**_create_kwargs())


def test_create_snapshot_wraps_psycopg_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.raise_on_execute(psycopg.OperationalError("boom"))
    repository = _repository(monkeypatch, fake)

    with pytest.raises(BriefRollupDatabaseUnavailable, match="boom"):
        repository.create_snapshot(**_create_kwargs())


def test_create_snapshot_fails_when_issue_upsert_returns_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    repository = _repository(monkeypatch, fake)

    with pytest.raises(BriefRollupDatabaseUnavailable, match="upsert failed"):
        repository.create_snapshot(**_create_kwargs())


def test_get_latest_by_public_id_joins_latest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.queue_fetchone(ISSUE_ROW + SNAPSHOT_ROW)
    repository = _repository(monkeypatch, fake)

    envelope = repository.get_latest_by_public_id("brf_w_2026w33_abcd")

    assert envelope.issue.rollup_id == ISSUE_ROW[0]
    assert envelope.issue.period_key == "2026-W33"
    assert envelope.snapshot.snapshot_id == SNAPSHOT_ROW[0]
    assert envelope.snapshot.version == 2
    assert envelope.snapshot.payload == SNAPSHOT_ROW[2]
    assert envelope.snapshot.source_watermark == SNAPSHOT_ROW[3]

    sql, params = fake.connection.executions[0]
    compact = _compact(sql)
    assert "FROM quant_system.brief_rollup_issues AS i" in compact
    assert "JOIN quant_system.brief_rollup_snapshots AS s" in compact
    assert "s.rollup_id = i.rollup_id" in compact
    assert "s.snapshot_id = i.latest_snapshot_id" in compact
    assert "WHERE i.public_id = %s" in compact
    assert params == ("brf_w_2026w33_abcd",)


def test_get_latest_by_public_id_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    repository = _repository(monkeypatch, fake)

    with pytest.raises(BriefRollupNotFound, match="brf_w_missing"):
        repository.get_latest_by_public_id("brf_w_missing")


def test_get_latest_by_public_id_wraps_psycopg_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.raise_on_execute(psycopg.OperationalError("boom"))
    repository = _repository(monkeypatch, fake)

    with pytest.raises(BriefRollupDatabaseUnavailable, match="boom"):
        repository.get_latest_by_public_id("brf_w_2026w33_abcd")


def test_list_rollups_filters_orders_and_clamps_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (
            "brf_w_2026w33_abcd",
            "weekly",
            "2026-W33",
            date(2026, 8, 10),
            date(2026, 8, 16),
            "zh",
            "published",
            "第 33 周周报",
            "截断后的主线",
        ),
        (
            "brf_w_2026w32_efgh",
            "weekly",
            "2026-W32",
            date(2026, 8, 3),
            date(2026, 8, 9),
            "zh",
            "published",
            None,
            None,
        ),
    ]
    fake = FakeDatabase()
    fake.connection.queue_fetchall(rows)
    repository = _repository(monkeypatch, fake)

    items = repository.list_rollups(kind="weekly", locale="zh", limit=500)

    assert len(items) == 2
    first, second = items
    assert first.public_id == "brf_w_2026w33_abcd"
    assert first.kind == "weekly"
    assert first.period_key == "2026-W33"
    assert first.period_start == date(2026, 8, 10)
    assert first.period_end == date(2026, 8, 16)
    assert first.locale == "zh"
    assert first.status == "published"
    assert first.title == "第 33 周周报"
    assert first.snippet == "截断后的主线"
    assert second.public_id == "brf_w_2026w32_efgh"
    assert second.title is None
    assert second.snippet is None

    sql, params = fake.connection.executions[0]
    compact = _compact(sql)
    assert "FROM quant_system.brief_rollup_issues AS i" in compact
    assert "LEFT JOIN quant_system.brief_rollup_snapshots AS s" in compact
    assert "s.snapshot_id = i.latest_snapshot_id" in compact
    assert "WHERE i.owner_user_id = %s" in compact
    assert "AND i.kind = %s" in compact
    assert "AND i.locale = %s" in compact
    assert "s.payload ->> 'title'" in compact
    assert "left(s.payload ->> 'main_storyline', 120)" in compact
    assert "ORDER BY i.period_start DESC, i.rollup_id DESC" in compact
    assert "LIMIT %s" in compact
    assert str(params[0]) == ROOT_USER_ID
    assert params[1] == "weekly"
    assert params[2] == "zh"
    assert params[3] == 100


def test_list_rollups_defaults_limit_to_30(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    repository = _repository(monkeypatch, fake)

    items = repository.list_rollups(kind="monthly", locale="zh")

    assert items == []
    params = fake.connection.executions[0][1]
    assert params[1] == "monthly"
    assert params[3] == 30


def test_list_rollups_wraps_psycopg_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDatabase()
    fake.connection.raise_on_execute(psycopg.OperationalError("boom"))
    repository = _repository(monkeypatch, fake)

    with pytest.raises(BriefRollupDatabaseUnavailable, match="boom"):
        repository.list_rollups(kind="weekly", locale="zh")
