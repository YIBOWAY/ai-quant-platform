from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.brief.models import BriefIssue, BriefIssueEnvelope, BriefSnapshot
from quant_system.config.settings import Settings
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class BriefDatabaseUnavailable(RuntimeError):
    """Raised when durable brief archive storage cannot be used."""


class BriefNotFound(LookupError):
    """Raised when a durable brief archive issue does not exist."""


class BriefRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_snapshot(
        self,
        *,
        issue_date: date,
        locale: str,
        public_id: str,
        payload: dict[str, Any],
        source_watermark: dict[str, Any] | None = None,
    ) -> BriefIssueEnvelope:
        database = self._require_database()
        try:
            with database.connect() as conn, conn.transaction():
                issue_row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.brief_issues (
                        issue_id,
                        public_id,
                        owner_user_id,
                        issue_date,
                        locale,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, 'published')
                    ON CONFLICT (owner_user_id, issue_date, locale)
                    DO UPDATE
                    SET updated_at = now()
                    RETURNING issue_id::text,
                              public_id,
                              issue_date,
                              locale,
                              status
                    """,
                    (uuid4(), public_id, ROOT_USER_ID, issue_date, locale),
                ).fetchone()
                if issue_row is None:
                    raise BriefDatabaseUnavailable("brief issue upsert failed")

                issue = _issue_from_row(issue_row)
                version = conn.execute(
                    f"""
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM {SCHEMA}.brief_snapshots
                    WHERE issue_id = %s
                    """,
                    (issue.issue_id,),
                ).fetchone()[0]
                snapshot_row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.brief_snapshots (
                        snapshot_id,
                        issue_id,
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
                        issue.issue_id,
                        version,
                        Jsonb(payload),
                        Jsonb(source_watermark or {}),
                    ),
                ).fetchone()
                if snapshot_row is None:
                    raise BriefDatabaseUnavailable("brief snapshot insert failed")

                snapshot = _snapshot_from_row(snapshot_row)
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.brief_issues
                    SET latest_snapshot_id = %s,
                        updated_at = now()
                    WHERE issue_id = %s
                    """,
                    (snapshot.snapshot_id, issue.issue_id),
                )
                return BriefIssueEnvelope(issue=issue, snapshot=snapshot)
        except DatabaseUnavailable as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc

    def get_latest_by_public_id(self, public_id: str) -> BriefIssueEnvelope:
        database = self._require_database()
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT i.issue_id::text,
                           i.public_id,
                           i.issue_date,
                           i.locale,
                           i.status,
                           s.snapshot_id::text,
                           s.version,
                           s.payload,
                           s.source_watermark
                    FROM {SCHEMA}.brief_issues AS i
                    JOIN {SCHEMA}.brief_snapshots AS s
                      ON s.issue_id = i.issue_id
                     AND s.snapshot_id = i.latest_snapshot_id
                    WHERE i.public_id = %s
                    """,
                    (public_id,),
                ).fetchone()
        except DatabaseUnavailable as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc

        if row is None:
            raise BriefNotFound(public_id)
        return BriefIssueEnvelope(
            issue=_issue_from_row(row[:5]),
            snapshot=_snapshot_from_row(row[5:]),
        )

    def get_latest(
        self,
        *,
        locale: str,
        issue_date: date | None = None,
    ) -> BriefIssueEnvelope:
        database = self._require_database()
        params: list[Any] = [ROOT_USER_ID, locale]
        date_filter = ""
        if issue_date is not None:
            date_filter = "AND i.issue_date = %s"
            params.append(issue_date)
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT i.issue_id::text,
                           i.public_id,
                           i.issue_date,
                           i.locale,
                           i.status,
                           s.snapshot_id::text,
                           s.version,
                           s.payload,
                           s.source_watermark
                    FROM {SCHEMA}.brief_issues AS i
                    JOIN {SCHEMA}.brief_snapshots AS s
                      ON s.issue_id = i.issue_id
                     AND s.snapshot_id = i.latest_snapshot_id
                    WHERE i.owner_user_id = %s
                      AND i.locale = %s
                      {date_filter}
                    ORDER BY i.issue_date DESC, i.updated_at DESC
                    LIMIT 1
                    """,
                    tuple(params),
                ).fetchone()
        except DatabaseUnavailable as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise BriefDatabaseUnavailable(str(exc)) from exc

        if row is None:
            raise BriefNotFound("latest")
        return BriefIssueEnvelope(
            issue=_issue_from_row(row[:5]),
            snapshot=_snapshot_from_row(row[5:]),
        )

    def _require_database(self) -> Database:
        database = get_database(self._settings)
        if database is None:
            raise BriefDatabaseUnavailable("brief archive database is disabled")
        return database


def _issue_from_row(row: tuple[Any, ...]) -> BriefIssue:
    return BriefIssue(
        issue_id=str(row[0]),
        public_id=str(row[1]),
        issue_date=row[2],
        locale=str(row[3]),
        status=str(row[4]),
    )


def _snapshot_from_row(row: tuple[Any, ...]) -> BriefSnapshot:
    return BriefSnapshot(
        snapshot_id=str(row[0]),
        version=int(row[1]),
        payload=dict(row[2]),
        source_watermark=dict(row[3] or {}),
    )
