from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import (
    CandidateAdmissionSettings,
    DatabaseSettings,
    Settings,
)
from quant_system.hermes.candidate_admission_authority import (
    AcceptCandidateAdmissionRequest,
    CandidateAdmissionAuthority,
    CandidateAdmissionConflict,
    OpenCandidateAdmissionRequest,
    candidate_admission_runtime_security_is_ready,
    candidate_admission_schema_is_ready_on_connection,
    canonical_candidate_action_digest,
)
from quant_system.hermes.candidate_evidence_v3 import (
    candidate_evidence_runtime_security_is_ready,
    candidate_evidence_schema_is_ready_on_connection,
)
from quant_system.hermes.command_ledger import HermesCommandLedger
from quant_system.hermes.dark_identity_profile import (
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisioner,
    ManagedSessionProvisionReceipt,
)
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

MIGRATIONS = (
    "003_app_users_brief_ai_reports.sql",
    "004_paper_account_tables.sql",
    "005_hermes_command_ledger.sql",
    "006_hermes_workflow_binding.sql",
    "007_hermes_session_registry.sql",
    "008_l2a_conversation_turn_claim.sql",
    "010_agent_v0_2_runtime_security.sql",
    "011_hermes_session_action_idempotency.sql",
    "012_agent_v0_2_release_authority.sql",
    "013_managed_hermes_session_provisioning.sql",
    "014_agent_v02_connector_liveness.sql",
    "015_managed_session_provision_authority.sql",
    "016_agent_v02_candidate_admission.sql",
    "017_agent_v02_vertical_a_authority.sql",
    "018_agent_v02_paper_gate_bridge.sql",
    "019_agent_v02_candidate_evidence_v3.sql",
    "020_agent_v02_release_authority_hardening.sql",
    "021_agent_v02_paper_run_attestation.sql",
    "022_agent_v02_resolved_fork_lineage.sql",
    "023_agent_v02_resolved_run_tip.sql",
    "024_agent_v02_run_control_outcome.sql",
    "025_agent_v02_release_session_binding.sql",
    "026_agent_v02_paper_research_claim_lineage.sql",
)
WORKSPACE = "workspace-root"
PLATFORM = "1" * 64
HQA = "2" * 64
HERMES = "3" * 64
SCHEMA_DIGEST = "4" * 64
PREFLIGHT = "5" * 64
ORDERS = "6" * 64
FINAL = "7" * 64
EVIDENCE_SET = "evidence_candidate_accept"
EVIDENCE_SET_DIGEST = "e" * 64
RUNTIME_LOGIN = "aqp_candidate_runtime_test"
RUNTIME_PASSWORD = "candidate-runtime-test-only"


class _ReadyProvisionPort:
    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=True,
            recovered=False,
        )

    def fork_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise AssertionError("root test Session must not fork")


def _settings() -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(url).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("QS_TEST_DATABASE_URL must point at a throwaway test database")
    maintenance = conninfo_to_dict(url)
    maintenance["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance), autocommit=True) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database_name,),
            ).fetchone()
            is None
        ):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        ),
        candidate_admission=CandidateAdmissionSettings(
            enabled=True,
            ttl_seconds=120,
        ),
    )


def _prepare() -> tuple[Settings, db.Database]:
    settings = _settings()
    url = os.environ.get("QS_TEST_DATABASE_URL")
    assert url is not None
    parameters = conninfo_to_dict(url)
    database_name = parameters.get("dbname", "")
    maintenance = dict(parameters)
    maintenance["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance), autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database, only=MIGRATIONS)
    return settings, database


def _open_request(
    *,
    action_id: str = "candidate-open-1",
) -> OpenCandidateAdmissionRequest:
    payload = {
        "baseline_order_snapshot_digest": ORDERS,
        "database_schema_fingerprint": SCHEMA_DIGEST,
        "hermes_runtime_digest": HERMES,
        "hqa_runtime_digest": HQA,
        "note": "collect exact local browser evidence",
        "platform_runtime_digest": PLATFORM,
        "preflight_evidence_digest": PREFLIGHT,
        "route": "/hermes",
        "ttl_seconds": 120,
        "workspace_id": WORKSPACE,
    }
    return OpenCandidateAdmissionRequest(
        workspace_id=WORKSPACE,
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA_DIGEST,
        preflight_evidence_digest=PREFLIGHT,
        baseline_order_snapshot_digest=ORDERS,
        ttl_seconds=120,
        note="collect exact local browser evidence",
        client_action_id=action_id,
        action_digest=canonical_candidate_action_digest(
            "candidate.open",
            payload,
        ),
    )


def test_candidate_is_db_clocked_idempotent_and_server_binds_chat() -> None:
    settings, database = _prepare()
    authority = CandidateAdmissionAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )

    first = authority.open(
        _open_request(),
        admission_id="candidate_test_1",
    )
    replay = authority.open(
        _open_request(),
        admission_id="candidate_ignored_on_replay",
    )
    assert first.status == "open"
    assert replay.idempotent_replay is True
    assert replay.admission_id == first.admission_id
    current = authority.active(WORKSPACE)
    assert current is not None
    assert current.expires_at > current.opened_at
    assert (current.expires_at - current.opened_at).total_seconds() == 120

    with pytest.raises(CandidateAdmissionConflict):
        authority.open(
            _open_request(action_id="candidate-open-2"),
            admission_id="candidate_test_2",
        )

    creation_digest = "8" * 64
    session, created = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="wm_candidate_test",
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id=WORKSPACE,
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id="candidate-session-create",
            creation_action_digest=creation_digest,
        ),
    )
    assert created is True
    assert session.candidate_admission_id == first.admission_id
    ledger = HermesCommandLedger(
        settings,
        claim_candidate_admission_id=first.admission_id,
    )
    created_command = ledger.create_command(
        platform_session_id=session.platform_session_id,
        client_request_id="candidate-turn-1",
        kind="conversation_turn",
        canonical_request_digest="9" * 64,
        payload_ref=f"platform-payload://sha256/{'a' * 64}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    )
    with database.connect() as conn:
        bound = conn.execute(
            """
            SELECT
                session_row.candidate_admission_id,
                command_row.candidate_admission_id
            FROM quant_system.hermes_workspace_sessions AS session_row
            JOIN quant_system.hermes_commands AS command_row
              ON command_row.platform_session_id =
                 session_row.platform_session_id
            WHERE command_row.command_id = %s
            """,
            (created_command.command.command_id,),
        ).fetchone()
    assert bound == (first.admission_id, first.admission_id)

    claimed = ledger.claim_next_command(
        worker_id="candidate-worker",
        now=datetime.now(UTC),
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    assert claimed.command_id == created_command.command.command_id


def test_candidate_never_claims_a_web_command_from_another_workspace() -> None:
    settings, database = _prepare()
    authority = CandidateAdmissionAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    opened = authority.open(
        _open_request(action_id="candidate-workspace-open"),
        admission_id="candidate_workspace_test",
    )
    creation_digest = "a" * 64
    session, created = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="wm_candidate_wrong_workspace",
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id="ws-local-main",
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id="candidate-wrong-workspace-session",
            creation_action_digest=creation_digest,
        ),
    )
    assert created is True
    ledger = HermesCommandLedger(
        settings,
        claim_candidate_admission_id=opened.admission_id,
    )
    command = ledger.create_command(
        platform_session_id=session.platform_session_id,
        client_request_id="candidate-wrong-workspace-turn",
        kind="conversation_turn",
        canonical_request_digest="b" * 64,
        payload_ref=f"platform-payload://sha256/{'c' * 64}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    ).command

    with database.connect() as conn:
        bound = conn.execute(
            """
            SELECT
                session_row.candidate_admission_id,
                command_row.candidate_admission_id
            FROM quant_system.hermes_workspace_sessions AS session_row
            JOIN quant_system.hermes_commands AS command_row
              ON command_row.platform_session_id =
                 session_row.platform_session_id
            WHERE command_row.command_id = %s
            """,
            (command.command_id,),
        ).fetchone()

    assert bound == (None, None)
    assert (
        ledger.claim_next_command(
            worker_id="candidate-wrong-workspace-worker",
            now=datetime.now(UTC),
            lease_duration=timedelta(seconds=30),
        )
        is None
    )


def test_accept_requires_no_nonterminal_candidate_command() -> None:
    settings, database = _prepare()
    authority = CandidateAdmissionAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    opened = authority.open(
        _open_request(),
        admission_id="candidate_accept_test",
    )
    creation_digest = "b" * 64
    register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="wm_candidate_accept",
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id=WORKSPACE,
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id="candidate-accept-session",
            creation_action_digest=creation_digest,
        ),
    )
    ledger = HermesCommandLedger(settings)
    command = ledger.create_command(
        platform_session_id="wm_candidate_accept",
        client_request_id="candidate-accept-turn",
        kind="conversation_turn",
        canonical_request_digest="c" * 64,
        payload_ref=f"platform-payload://sha256/{'d' * 64}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    ).command
    provisioned = ManagedSessionProvisioner(
        settings=settings,
        port=_ReadyProvisionPort(),
        lease_seconds=30,
    ).provision_next(
        worker_id="candidate-test-provisioner",
        now=datetime.now(UTC),
    )
    assert provisioned.outcome == "ready"
    payload = {
        "admission_id": opened.admission_id,
        "expected_admission_digest": opened.admission_digest,
        "evidence_set_digest": EVIDENCE_SET_DIGEST,
        "evidence_set_id": EVIDENCE_SET,
        "final_evidence_digest": FINAL,
        "final_order_snapshot_digest": ORDERS,
        "note": "all exact candidate captures sealed",
        "workspace_id": WORKSPACE,
    }
    request = AcceptCandidateAdmissionRequest(
        workspace_id=WORKSPACE,
        admission_id=opened.admission_id,
        expected_admission_digest=opened.admission_digest,
        final_evidence_digest=FINAL,
        evidence_set_id=EVIDENCE_SET,
        evidence_set_digest=EVIDENCE_SET_DIGEST,
        final_order_snapshot_digest=ORDERS,
        note="all exact candidate captures sealed",
        client_action_id="candidate-accept-1",
        action_digest=canonical_candidate_action_digest(
            "candidate.accept",
            payload,
        ),
    )
    with pytest.raises(
        CandidateAdmissionConflict,
        match="zero nonterminal candidate commands",
    ):
        authority.accept(request)

    ledger.cancel_queued_command(
        command_id=UUID(str(command.command_id)),
        expected_version=command.version,
    )
    with pytest.raises(
        CandidateAdmissionConflict,
        match="exact verified v3 evidence set",
    ):
        authority.accept(request)


def test_candidate_authority_requires_constrained_runtime_role() -> None:
    admin_settings, database = _prepare()
    admin_secret = admin_settings.database.url
    assert admin_secret is not None
    admin_url = admin_secret.get_secret_value()
    with database.connect() as conn:
        if (
            conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (RUNTIME_LOGIN,),
            ).fetchone()
            is not None
        ):
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(RUNTIME_LOGIN)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(RUNTIME_LOGIN)))
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(
                sql.Identifier(RUNTIME_LOGIN),
                sql.Literal(RUNTIME_PASSWORD),
            )
        )
        conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(RUNTIME_LOGIN)))
    db.run_migrations(
        database,
        only=(
            "016_agent_v02_candidate_admission.sql",
            "019_agent_v02_candidate_evidence_v3.sql",
            "025_agent_v02_release_session_binding.sql",
        ),
    )
    runtime_parameters = conninfo_to_dict(admin_url)
    runtime_parameters["user"] = RUNTIME_LOGIN
    runtime_parameters["password"] = RUNTIME_PASSWORD
    runtime_settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url=make_conninfo(**runtime_parameters),
            auto_migrate=False,
            connect_timeout_seconds=1,
        ),
        candidate_admission=CandidateAdmissionSettings(enabled=True),
    )
    try:
        db.reset_database_cache()
        assert candidate_admission_runtime_security_is_ready(runtime_settings) is True
        assert candidate_evidence_runtime_security_is_ready(runtime_settings) is True
    finally:
        db.reset_database_cache()
        cleanup = db.Database(admin_url, connect_timeout=1)
        with cleanup.connect() as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(RUNTIME_LOGIN)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(RUNTIME_LOGIN)))
        db.reset_database_cache()


def test_candidate_readiness_rejects_pre_025_trigger_body() -> None:
    _settings_value, database = _prepare()
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True

    db.run_migrations(
        database,
        only=("016_agent_v02_candidate_admission.sql",),
    )
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is False

    db.run_migrations(
        database,
        only=("025_agent_v02_release_session_binding.sql",),
    )
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is False

    db.run_migrations(
        database,
        only=(
            "019_agent_v02_candidate_evidence_v3.sql",
            "020_agent_v02_release_authority_hardening.sql",
            "025_agent_v02_release_session_binding.sql",
        ),
    )
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True


def test_candidate_readiness_rejects_tampered_025_function_body() -> None:
    _settings_value, database = _prepare()
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION
                quant_system.bind_agent_v02_candidate_command()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            AS $$
            BEGIN
                RETURN NEW;
            END;
            $$
            """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_candidate_readiness_rejects_wrong_trigger_target() -> None:
    _settings_value, database = _prepare()
    with database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            DROP TRIGGER trg_hermes_command_candidate_binding
            ON quant_system.hermes_commands
            """
        )
        conn.execute(
            """
            CREATE TRIGGER trg_hermes_command_candidate_binding
            BEFORE INSERT OR UPDATE
            ON quant_system.hermes_workspace_sessions
            FOR EACH ROW
            EXECUTE FUNCTION quant_system.bind_agent_v02_candidate_command()
            """
        )
        conn.execute(
            """
            ALTER TABLE quant_system.hermes_workspace_sessions
            ENABLE ALWAYS TRIGGER trg_hermes_command_candidate_binding
            """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_candidate_evidence_readiness_rejects_policy_drift() -> None:
    _settings_value, database = _prepare()
    with database.connect() as conn:
        assert candidate_evidence_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            DROP POLICY v4r_root_scope
            ON quant_system.agent_v02_candidate_evidence_sets
            """
        )
        conn.execute(
            """
            CREATE POLICY v4r_root_scope
            ON quant_system.agent_v02_candidate_evidence_sets
            FOR ALL TO quant_runtime, quant_readonly
            USING (true)
            WITH CHECK (true)
            """
        )
        assert candidate_evidence_schema_is_ready_on_connection(conn) is False
