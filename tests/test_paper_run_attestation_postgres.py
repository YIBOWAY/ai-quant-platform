from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_run_attestation import (
    AttestPaperRun,
    PaperRunAttestationAuthority,
    PaperRunAttestationUnavailable,
    paper_run_attestation_runtime_security_is_ready_on_connection,
    paper_run_attestation_schema_is_ready_on_connection,
)
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

MIGRATION = "021_agent_v02_paper_run_attestation.sql"
CLAIM_LINEAGE_MIGRATION = "026_agent_v02_paper_research_claim_lineage.sql"


@pytest.fixture
def attestation_database() -> Iterator[tuple[Settings, db.Database, db.Database, str]]:
    base_url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(
        base_url,
        purpose="paper21",
    ) as isolated_url:
        admin_database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(admin_database)
        suffix = uuid4().hex[:12]
        login = f"aqp_paper_attest_{suffix}"
        password = f"paper-attest-{suffix}"
        with psycopg.connect(isolated_url) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(login)))
        runtime_params = conninfo_to_dict(isolated_url)
        runtime_params["user"] = login
        runtime_params["password"] = password
        runtime_url = make_conninfo(**runtime_params)
        runtime_database = db.Database(runtime_url, connect_timeout=2)
        settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=runtime_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            )
        )
        try:
            yield settings, admin_database, runtime_database, isolated_url
        finally:
            with psycopg.connect(isolated_url, autocommit=True) as conn:
                conn.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE usename = %s
                      AND pid <> pg_backend_pid()
                    """,
                    (login,),
                )
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))


def _managed_session(
    database: db.Database,
    *,
    workspace_id: str,
) -> tuple[str, str]:
    suffix = uuid4().hex
    platform_session_id = f"paper-session-{suffix}"
    creation_digest = hashlib.sha256(f"{workspace_id}:{platform_session_id}".encode()).hexdigest()
    hermes_session_id = f"web_{creation_digest[:40]}"
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO quant_system.hermes_workspace_sessions (
                platform_session_id,
                hermes_session_id,
                workspace_id,
                owner_user_id,
                kind,
                provider_policy_digest,
                writer,
                payload_ttl_days,
                creation_client_action_id,
                creation_action_digest,
                provision_state,
                provisioning_receipt_digest,
                provisioned_at
            )
            VALUES (
                %s, %s, %s, %s, 'web_managed_session', %s,
                'web_control_plane', 7, %s, %s, 'ready', %s,
                clock_timestamp()
            )
            """,
            (
                platform_session_id,
                hermes_session_id,
                workspace_id,
                ROOT_USER_ID,
                "a" * 64,
                f"create-{suffix}",
                creation_digest,
                "b" * 64,
            ),
        )
    return platform_session_id, hermes_session_id


def _command(
    database: db.Database,
    *,
    platform_session_id: str,
    hermes_session_id: str,
    resolved_hermes_session_id: str | None = None,
    hermes_run_id: str,
    state: str,
) -> UUID:
    command_id = uuid4()
    digest = hashlib.sha256(str(command_id).encode()).hexdigest()
    values: dict[str, object] = {
        "command_id": command_id,
        "owner_user_id": ROOT_USER_ID,
        "platform_session_id": platform_session_id,
        "client_request_id": f"request-{command_id}",
        "canonical_request_digest": digest,
        "payload_ref": f"platform-payload://sha256/{digest}",
        "provider_policy_digest": "a" * 64,
        "state": state,
        "attempt_count": 1,
        "dispatch_started_at": "2026-07-24T00:00:00Z",
        "hermes_session_id": (hermes_session_id if state in {"delivered", "succeeded"} else None),
        "resolved_hermes_session_id": (
            resolved_hermes_session_id or hermes_session_id
            if state in {"delivered", "succeeded"}
            else None
        ),
        "hermes_run_id": (hermes_run_id if state in {"delivered", "succeeded"} else None),
        "lease_owner": "paper-worker" if state == "leased" else None,
        "lease_token": uuid4() if state == "leased" else None,
        "lease_until": ("2099-07-24T00:00:00Z" if state == "leased" else None),
    }
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO quant_system.hermes_commands (
                command_id,
                owner_user_id,
                platform_session_id,
                client_request_id,
                kind,
                canonical_request_digest,
                payload_ref,
                provider_policy_digest,
                state,
                version,
                attempt_count,
                dispatch_started_at,
                hermes_session_id,
                resolved_hermes_session_id,
                hermes_run_id,
                lease_owner,
                lease_token,
                lease_until
            )
            VALUES (
                %(command_id)s,
                %(owner_user_id)s,
                %(platform_session_id)s,
                %(client_request_id)s,
                'conversation_turn',
                %(canonical_request_digest)s,
                %(payload_ref)s,
                %(provider_policy_digest)s,
                %(state)s,
                1,
                %(attempt_count)s,
                %(dispatch_started_at)s,
                %(hermes_session_id)s,
                %(resolved_hermes_session_id)s,
                %(hermes_run_id)s,
                %(lease_owner)s,
                %(lease_token)s,
                %(lease_until)s
            )
            """,
            values,
        )
    return command_id


def _insert_gate1(
    conn: psycopg.Connection,
    *,
    gate_id: str,
    workspace_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    command_id: UUID,
    hermes_run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO quant_system.agent_v02_paper_gate_challenges (
            gate_id,
            owner_user_id,
            workspace_id,
            gate_kind,
            task_ref,
            expected_task_version,
            attempt_ref,
            hqa_gate_ref,
            platform_session_id,
            hermes_session_id,
            command_id,
            hermes_run_id,
            source_file_ref,
            universe,
            reviewed_source_sha256
        )
        VALUES (
            %s, %s, %s, 'gate1', 'task:paper-attestation', 1,
            'attempt:paper-attestation-1', 'gate:paper-attestation',
            %s, %s, %s, %s, '/tmp/paper-attestation.py', 'US', %s
        )
        """,
        (
            gate_id,
            ROOT_USER_ID,
            workspace_id,
            platform_session_id,
            hermes_session_id,
            command_id,
            hermes_run_id,
            "1" * 64,
        ),
    )


def test_fresh_migration_ladder_replay_and_exact_current_command_binding(
    attestation_database: tuple[Settings, db.Database, db.Database, str],
) -> None:
    settings, admin_database, runtime_database, _url = attestation_database
    db.run_migrations(
        admin_database,
        only=(MIGRATION, CLAIM_LINEAGE_MIGRATION),
    )
    with runtime_database.connect() as conn:
        assert paper_run_attestation_schema_is_ready_on_connection(conn)
        assert paper_run_attestation_runtime_security_is_ready_on_connection(conn)

    workspace = "paper-attestation"
    session_id, hermes_session_id = _managed_session(
        admin_database,
        workspace_id=workspace,
    )
    leased_command = _command(
        admin_database,
        platform_session_id=session_id,
        hermes_session_id=hermes_session_id,
        hermes_run_id="leased-has-no-run",
        state="leased",
    )
    with (
        admin_database.connect() as conn,
        pytest.raises(psycopg.errors.RaiseException, match="exact delivered"),
    ):
        _insert_gate1(
            conn,
            gate_id="paper-gate-leased",
            workspace_id=workspace,
            platform_session_id=session_id,
            hermes_session_id=hermes_session_id,
            command_id=leased_command,
            hermes_run_id="leased-has-no-run",
        )

    other_workspace = "paper-attestation-other"
    other_session_id, other_hermes_session_id = _managed_session(
        admin_database,
        workspace_id=other_workspace,
    )
    delivered_command = _command(
        admin_database,
        platform_session_id=session_id,
        hermes_session_id=hermes_session_id,
        hermes_run_id="delivered-paper-run",
        state="delivered",
    )
    with (
        admin_database.connect() as conn,
        pytest.raises(psycopg.errors.RaiseException, match="exact delivered"),
    ):
        _insert_gate1(
            conn,
            gate_id="paper-gate-wrong-scope",
            workspace_id=other_workspace,
            platform_session_id=other_session_id,
            hermes_session_id=other_hermes_session_id,
            command_id=delivered_command,
            hermes_run_id="delivered-paper-run",
        )

    with admin_database.connect() as conn:
        _insert_gate1(
            conn,
            gate_id="paper-gate-exact",
            workspace_id=workspace,
            platform_session_id=session_id,
            hermes_session_id=hermes_session_id,
            command_id=delivered_command,
            hermes_run_id="delivered-paper-run",
        )

    receipt = PaperRunAttestationAuthority(
        settings,
        database=runtime_database,
    ).attest(
        AttestPaperRun(
            mode="invocation",
            workspace_id=workspace,
            platform_session_id=session_id,
            hermes_session_id=hermes_session_id,
            command_id=str(delivered_command),
            hermes_run_id="delivered-paper-run",
        )
    )
    assert receipt["command_state"] == "delivered"
    assert receipt["attestation_ref"] == (f"paper-run-attestation:{receipt['evidence_digest']}")


def test_invocation_attestation_binds_registry_root_and_compressed_command_tip(
    attestation_database: tuple[Settings, db.Database, db.Database, str],
) -> None:
    settings, admin_database, runtime_database, _url = attestation_database
    workspace = "paper-attestation-compressed"
    platform_session_id, conversation_root = _managed_session(
        admin_database,
        workspace_id=workspace,
    )
    resolved_tip = f"{conversation_root}_tip"
    command_id = _command(
        admin_database,
        platform_session_id=platform_session_id,
        hermes_session_id=conversation_root,
        resolved_hermes_session_id=resolved_tip,
        hermes_run_id="compressed-paper-run",
        state="delivered",
    )

    receipt = PaperRunAttestationAuthority(
        settings,
        database=runtime_database,
    ).attest(
        AttestPaperRun(
            mode="invocation",
            workspace_id=workspace,
            platform_session_id=platform_session_id,
            hermes_session_id=conversation_root,
            command_id=str(command_id),
            hermes_run_id="compressed-paper-run",
        )
    )

    assert receipt["hermes_session_id"] == conversation_root
    assert receipt["resolved_hermes_session_id"] == resolved_tip
    assert receipt["command_state"] == "delivered"


def test_021_future_version_fails_closed(
    attestation_database: tuple[Settings, db.Database, db.Database, str],
) -> None:
    _settings, admin_database, runtime_database, _url = attestation_database
    with admin_database.connect() as conn:
        conn.execute(
            """
            UPDATE quant_system.agent_v02_paper_run_attestation_meta
            SET schema_version = 2
            WHERE singleton IS TRUE
            """
        )

    with pytest.raises(
        psycopg.errors.RaiseException,
        match="newer than this binary supports",
    ):
        db.run_migrations(admin_database, only=(MIGRATION,))

    with runtime_database.connect() as conn:
        assert not paper_run_attestation_schema_is_ready_on_connection(conn)


def test_runtime_security_rejects_admin_connection(
    attestation_database: tuple[Settings, db.Database, db.Database, str],
) -> None:
    _settings, admin_database, runtime_database, isolated_url = attestation_database
    with runtime_database.connect() as conn:
        assert paper_run_attestation_runtime_security_is_ready_on_connection(conn)
    with admin_database.connect() as conn:
        assert paper_run_attestation_schema_is_ready_on_connection(conn)
        assert not paper_run_attestation_runtime_security_is_ready_on_connection(conn)

    admin_settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url=isolated_url,
            auto_migrate=False,
            connect_timeout_seconds=2,
        )
    )
    with pytest.raises(
        PaperRunAttestationUnavailable,
        match="runtime security is not ready",
    ):
        PaperRunAttestationAuthority(
            admin_settings,
            database=admin_database,
        ).attest(
            AttestPaperRun(
                mode="invocation",
                workspace_id="paper-attestation-admin",
                platform_session_id="paper-session-admin",
                hermes_session_id="web_admin",
                command_id=str(uuid4()),
                hermes_run_id="paper-run-admin",
            )
        )
