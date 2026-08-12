from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class BriefRollupIssue:
    rollup_id: str
    public_id: str
    kind: str  # 'weekly' | 'monthly'
    period_key: str  # '2026-W33' | '2026-08'
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
    title: str | None  # payload ->> 'title'
    snippet: str | None  # left(payload ->> 'main_storyline', 120)


class BriefRollupDatabaseUnavailable(RuntimeError):
    """Raised when durable brief rollup storage cannot be used."""


class BriefRollupNotFound(LookupError):
    """Raised when a durable brief rollup issue does not exist."""


class BriefRollupRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_snapshot(
        self,
        *,
        kind: str,
        period_key: str,
        period_start: date,
        period_end: date,
        locale: str,
        public_id: str,
        payload: dict[str, Any],
        source_watermark: dict[str, Any] | None = None,
    ) -> BriefRollupEnvelope:
        database = self._require_database()
        try:
            with database.connect() as conn, conn.transaction():
                issue_row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.brief_rollup_issues (
                        rollup_id,
                        public_id,
                        owner_user_id,
                        kind,
                        period_key,
                        period_start,
                        period_end,
                        locale,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'published')
                    ON CONFLICT (owner_user_id, kind, period_key, locale)
                    DO UPDATE
                    SET updated_at = now()
                    RETURNING rollup_id::text,
                              public_id,
                              kind,
                              period_key,
                              period_start,
                              period_end,
                              locale,
                              status
                    """,
                    (
                        uuid4(),
                        public_id,
                        ROOT_USER_ID,
                        kind,
                        period_key,
                        period_start,
                        period_end,
                        locale,
                    ),
                ).fetchone()
                if issue_row is None:
                    raise BriefRollupDatabaseUnavailable("brief rollup issue upsert failed")

                issue = _issue_from_row(issue_row)
                version = conn.execute(
                    f"""
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM {SCHEMA}.brief_rollup_snapshots
                    WHERE rollup_id = %s
                    """,
                    (issue.rollup_id,),
                ).fetchone()[0]
                snapshot_row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.brief_rollup_snapshots (
                        snapshot_id,
                        rollup_id,
                        version,
                        payload,
                        source_watermark
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING snapshot_id::text,
                              version,
                              payload,
                              source_watermark
                    """,
                    (
                        uuid4(),
                        issue.rollup_id,
                        version,
                        Jsonb(payload),
                        Jsonb(source_watermark or {}),
                    ),
                ).fetchone()
                if snapshot_row is None:
                    raise BriefRollupDatabaseUnavailable(
                        "brief rollup snapshot insert failed"
                    )

                snapshot = _snapshot_from_row(snapshot_row)
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.brief_rollup_issues
                    SET latest_snapshot_id = %s,
                        updated_at = now()
                    WHERE rollup_id = %s
                    """,
                    (snapshot.snapshot_id, issue.rollup_id),
                )
                return BriefRollupEnvelope(issue=issue, snapshot=snapshot)
        except DatabaseUnavailable as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc

    def get_latest_by_public_id(self, public_id: str) -> BriefRollupEnvelope:
        database = self._require_database()
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT i.rollup_id::text,
                           i.public_id,
                           i.kind,
                           i.period_key,
                           i.period_start,
                           i.period_end,
                           i.locale,
                           i.status,
                           s.snapshot_id::text,
                           s.version,
                           s.payload,
                           s.source_watermark
                    FROM {SCHEMA}.brief_rollup_issues AS i
                    JOIN {SCHEMA}.brief_rollup_snapshots AS s
                      ON s.rollup_id = i.rollup_id
                     AND s.snapshot_id = i.latest_snapshot_id
                    WHERE i.public_id = %s
                    """,
                    (public_id,),
                ).fetchone()
        except DatabaseUnavailable as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc

        if row is None:
            raise BriefRollupNotFound(public_id)
        return BriefRollupEnvelope(
            issue=_issue_from_row(row[:8]),
            snapshot=_snapshot_from_row(row[8:]),
        )

    def list_rollups(
        self,
        *,
        kind: str,
        locale: str,
        limit: int = 30,
    ) -> list[BriefRollupListItem]:
        database = self._require_database()
        safe_limit = max(0, min(int(limit), 100))
        try:
            with database.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT i.public_id,
                           i.kind,
                           i.period_key,
                           i.period_start,
                           i.period_end,
                           i.locale,
                           i.status,
                           s.payload ->> 'title' AS title,
                           left(s.payload ->> 'main_storyline', 120) AS snippet
                    FROM {SCHEMA}.brief_rollup_issues AS i
                    LEFT JOIN {SCHEMA}.brief_rollup_snapshots AS s
                      ON s.rollup_id = i.rollup_id
                     AND s.snapshot_id = i.latest_snapshot_id
                    WHERE i.owner_user_id = %s
                      AND i.kind = %s
                      AND i.locale = %s
                    ORDER BY i.period_start DESC, i.rollup_id DESC
                    LIMIT %s
                    """,
                    (ROOT_USER_ID, kind, locale, safe_limit),
                ).fetchall()
        except DatabaseUnavailable as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefRollupDatabaseUnavailable(str(exc)) from exc
        return [
            BriefRollupListItem(
                public_id=str(row[0]),
                kind=str(row[1]),
                period_key=str(row[2]),
                period_start=row[3],
                period_end=row[4],
                locale=str(row[5]),
                status=str(row[6]),
                title=str(row[7]) if row[7] is not None else None,
                snippet=str(row[8]) if row[8] is not None else None,
            )
            for row in rows
        ]

    def _require_database(self) -> Database:
        database = get_database(self._settings)
        if database is None:
            raise BriefRollupDatabaseUnavailable("brief rollup database is disabled")
        return database


def _issue_from_row(row: tuple[Any, ...]) -> BriefRollupIssue:
    return BriefRollupIssue(
        rollup_id=str(row[0]),
        public_id=str(row[1]),
        kind=str(row[2]),
        period_key=str(row[3]),
        period_start=row[4],
        period_end=row[5],
        locale=str(row[6]),
        status=str(row[7]),
    )


def _snapshot_from_row(row: tuple[Any, ...]) -> BriefRollupSnapshot:
    return BriefRollupSnapshot(
        snapshot_id=str(row[0]),
        version=int(row[1]),
        payload=dict(row[2]),
        source_watermark=dict(row[3] or {}),
    )
