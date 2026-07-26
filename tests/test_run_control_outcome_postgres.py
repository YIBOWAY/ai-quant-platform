from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.run_control_outcome_authority import (
    run_control_outcome_schema_is_ready_on_connection,
)
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

MIGRATION = "024_agent_v02_run_control_outcome.sql"


def _receipt(
    *,
    kind: str,
    digest: str,
    run_id: str,
    status: str,
    reason: str | None,
    external_status: str | None,
    replay: bool = False,
) -> dict[str, object]:
    return {
        "action_digest": digest,
        "action_kind": kind,
        "contract": "agent-v0.2-run-control-outcome/v1",
        "external_idempotent_replay": replay,
        "external_status": external_status,
        "outcome_status": status,
        "reason_code": reason,
        "target_run_id": run_id,
    }


def _insert_control(
    conn,
    *,
    kind: str,
    digest: str,
) -> str:
    command_id = uuid4()
    conn.execute(
        """
        INSERT INTO quant_system.hermes_commands (
            command_id,
            owner_user_id,
            platform_session_id,
            client_request_id,
            kind,
            canonical_request_digest,
            payload_ref
        )
        VALUES (%s, %s, 'awctl_workspace-root', %s, %s, %s, %s)
        """,
        (
            command_id,
            ROOT_USER_ID,
            f"control-{command_id}",
            kind,
            digest,
            f"platform-payload://sha256/{digest}",
        ),
    )
    conn.execute(
        """
        INSERT INTO quant_system.hermes_command_events (
            command_id,
            command_version,
            event_type,
            actor,
            to_state,
            canonical_request_digest,
            attempt_count
        )
        VALUES (%s, 1, 'command_created', 'bff', 'queued', %s, 0)
        """,
        (command_id, digest),
    )
    conn.execute(
        """
        INSERT INTO quant_system.hermes_outbox (
            command_id,
            command_version,
            topic
        )
        VALUES (%s, 1, 'hermes.command.queued')
        """,
        (command_id,),
    )
    return str(command_id)


def _finalize(
    conn,
    *,
    command_id: str,
    kind: str,
    digest: str,
    run_id: str,
    status: str,
    reason: str | None,
    external_status: str | None,
    replay: bool = False,
) -> tuple[object, ...]:
    receipt = _receipt(
        kind=kind,
        digest=digest,
        run_id=run_id,
        status=status,
        reason=reason,
        external_status=external_status,
        replay=replay,
    )
    row = conn.execute(
        """
        SELECT *
        FROM quant_system.finalize_agent_v02_run_control(
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s::jsonb
        )
        """,
        (
            ROOT_USER_ID,
            command_id,
            digest,
            kind,
            run_id,
            status,
            reason,
            external_status,
            replay,
            json.dumps(receipt, sort_keys=True),
        ),
    ).fetchone()
    assert row is not None
    return row


def test_024_triple_replay_and_control_crash_recovery_are_durable() -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")

    with isolated_test_database_url(base_url, purpose="control24") as url:
        database = db.Database(url, connect_timeout=2)
        sql_dir = Path(__file__).resolve().parents[1] / "scripts" / "sql"
        predecessors = tuple(
            path.name
            for path in sorted(sql_dir.glob("*.sql"))
            if path.name < MIGRATION
        )
        db.run_migrations(database, only=predecessors)
        for _ in range(3):
            db.run_migrations(database, only=(MIGRATION,))

        approval_digest = "a" * 64
        stop_digest = "b" * 64
        with database.connect() as conn:
            approval_id = _insert_control(
                conn,
                kind="hermes_command_approval_decide",
                digest=approval_digest,
            )
            stop_id = _insert_control(
                conn,
                kind="run_stop_request",
                digest=stop_digest,
            )

            # Crash after external POST but before local finalize leaves the
            # exact identity retryable; it is not claimable transport work.
            queued = conn.execute(
                """
                SELECT state, version
                FROM quant_system.hermes_commands
                WHERE command_id = %s
                """,
                (approval_id,),
            ).fetchone()
            assert queued == ("queued", 1)
            claimable = conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_commands
                WHERE command_id IN (%s, %s)
                  AND (
                    kind = 'conversation_turn'
                    OR EXISTS (
                        SELECT 1
                        FROM quant_system.hermes_command_workflow_bindings
                        WHERE command_id =
                            hermes_commands.command_id
                    )
                  )
                """,
                (approval_id, stop_id),
            ).fetchone()
            assert claimable == (0,)

            conn.execute("SET LOCAL ROLE quant_runtime")
            unknown = _finalize(
                conn,
                command_id=approval_id,
                kind="hermes_command_approval_decide",
                digest=approval_digest,
                run_id="run-approval",
                status="outcome_unknown",
                reason="transport_error",
                external_status=None,
            )
            assert unknown[:2] == ("outcome_unknown", 2)
            success = _finalize(
                conn,
                command_id=approval_id,
                kind="hermes_command_approval_decide",
                digest=approval_digest,
                run_id="run-approval",
                status="succeeded",
                reason=None,
                external_status="committed",
                replay=True,
            )
            assert success[:2] == ("succeeded", 3)
            terminal_replay = _finalize(
                conn,
                command_id=approval_id,
                kind="hermes_command_approval_decide",
                digest=approval_digest,
                run_id="run-approval",
                status="succeeded",
                reason=None,
                external_status="committed",
                replay=True,
            )
            assert terminal_replay[:2] == ("succeeded", 3)
            assert terminal_replay[3] is True

            stopped = _finalize(
                conn,
                command_id=stop_id,
                kind="run_stop_request",
                digest=stop_digest,
                run_id="run-stop",
                status="succeeded",
                reason=None,
                external_status="stopped",
            )
            assert stopped[:2] == ("succeeded", 2)
            conn.execute("RESET ROLE")

            states = conn.execute(
                """
                SELECT command_id::text, state
                FROM quant_system.hermes_commands
                WHERE command_id IN (%s, %s)
                ORDER BY command_id
                """,
                (approval_id, stop_id),
            ).fetchall()
            assert {tuple(row) for row in states} == {
                (approval_id, "succeeded"),
                (stop_id, "succeeded"),
            }
            events = conn.execute(
                """
                SELECT event_type, event_data->>'target_run_id'
                FROM quant_system.hermes_command_events
                WHERE command_id = %s
                  AND event_type LIKE 'run_control.%%'
                ORDER BY command_version
                """,
                (approval_id,),
            ).fetchall()
            assert events == [
                ("run_control.outcome_unknown", "run-approval"),
                ("run_control.succeeded", "run-approval"),
            ]
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_outbox
                WHERE command_id IN (%s, %s)
                  AND consumed_by = 'run_control_bff'
                  AND consumed_at IS NOT NULL
                """,
                (approval_id, stop_id),
            ).fetchone() == (2,)
            assert run_control_outcome_schema_is_ready_on_connection(conn)
