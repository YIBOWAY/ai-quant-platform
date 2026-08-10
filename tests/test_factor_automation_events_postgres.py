from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from quant_system.storage import database as db
from quant_system.storage.database import list_migration_files
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"
THROUGH_029 = tuple(
    name
    for name in list_migration_files()
    if name[:3].isdigit() and int(name[:3]) <= 29
)


def _base_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(value).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("PostgreSQL migration tests require a throwaway base database")
    return value


@contextmanager
def _database(purpose: str):
    with isolated_test_database_url(_base_url(), purpose=purpose) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=THROUGH_029)
        yield database


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _append(
    conn: psycopg.Connection,
    *,
    event_id: str,
    event_type: str,
    automation_id: str = "auto-1",
    sleeve_id: str | None = None,
):
    return conn.execute(
        """
        SELECT *
        FROM quant_system.append_factor_automation_event(
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            event_id,
            ROOT_USER_ID,
            "ws-local-main",
            event_type,
            automation_id,
            f"candidate-{automation_id}",
            _digest(f"candidate-{automation_id}"),
            f"factor-{automation_id}",
            _digest(f"manifest-{automation_id}"),
            _digest("policy"),
            _digest("intake"),
            _digest("gate1"),
            _digest("gate2"),
            _digest("gate3"),
            "a" * 40,
            sleeve_id,
            event_type,
            Jsonb({"source": "test"}),
        ),
    ).fetchone()


def test_029_replay_quota_and_append_only_guards() -> None:
    with _database("factorautomation") as database, database.connect() as conn:
        first = _append(
            conn,
            event_id="promotion-1",
            event_type="promotion_committed",
        )
        replay = _append(
            conn,
            event_id="promotion-1",
            event_type="promotion_committed",
        )
        assert first is not None and first[2] is False
        assert replay == (first[0], first[1], True)

        with pytest.raises(psycopg.errors.RaiseException, match="daily quota"):
            _append(
                conn,
                event_id="promotion-2",
                event_type="promotion_committed",
                automation_id="auto-2",
            )

        _append(
            conn,
            event_id="sleeve-1",
            event_type="sleeve_created",
            sleeve_id="sleeve-auto-1",
        )
        for index in range(5):
            _append(
                conn,
                event_id=f"demote-{index}",
                event_type="demote_started",
                sleeve_id="sleeve-auto-1",
            )
        with pytest.raises(psycopg.errors.RaiseException, match="demote daily quota"):
            _append(
                conn,
                event_id="demote-6",
                event_type="demote_started",
                sleeve_id="sleeve-auto-1",
            )

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "UPDATE quant_system.factor_automation_events SET details='{}'::jsonb"
            )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "DELETE FROM quant_system.factor_automation_events WHERE event_id='promotion-1'"
            )


def test_029_rejects_missing_promotion_and_sleeve_lineage() -> None:
    with _database("factorlineage") as database, database.connect() as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="promotion lineage"):
            _append(
                conn,
                event_id="sleeve-without-promotion",
                event_type="sleeve_created",
                sleeve_id="sleeve-orphan",
            )

        _append(
            conn,
            event_id="promotion-1",
            event_type="promotion_committed",
        )
        with pytest.raises(psycopg.errors.RaiseException, match="sleeve lineage"):
            _append(
                conn,
                event_id="demote-without-sleeve",
                event_type="demote_started",
                sleeve_id="sleeve-orphan",
            )
