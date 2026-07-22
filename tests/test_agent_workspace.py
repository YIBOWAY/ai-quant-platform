"""V4 AgentWorkspace + crash-safe submission saga (isolated PostgreSQL)."""

from __future__ import annotations

import hashlib
import os
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import (
    ActorRef,
    PlatformAgentWorkspace,
    build_platform_agent_workspace,
)
from quant_system.hermes.agent_workspace_actions import (
    ConversationTurn,
    CreateManagedSession,
    ForkIntoManagedSession,
    WorkspaceRef,
    action_to_document,
    canonical_action_digest,
    hqa_payload_to_platform_payload_ref,
    parse_user_action_v1,
    session_ref,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID, HermesCommandLedger
from quant_system.hermes.dark_identity_profile import PROVIDER_POLICY_DIGEST
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    get_workspace_session,
    register_workspace_session,
)
from quant_system.hermes.submission_saga import (
    authorities_ready,
    derive_managed_hermes_session_id,
    derive_managed_platform_session_id,
    submit_action,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
WORKSPACE_ID = "ws-v4-agent-workspace"
RUNTIME_LOGIN = "aqp_agent_workspace_runtime_test"
RUNTIME_PASSWORD = "agent-workspace-runtime-test-only"


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
        )
    maintenance_params = dict(params)
    maintenance_params["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance_params), autocommit=True) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (dbname,),
            ).fetchone()
            is None
        ):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def _postgres_settings() -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    _ensure_test_database(url)
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _reset_authorities(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_workflow_bindings "
            "DISABLE TRIGGER USER"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events DISABLE TRIGGER USER"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links DISABLE TRIGGER USER"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_workspace_sessions DISABLE TRIGGER USER"
        )
        conn.execute(
            """
            TRUNCATE TABLE
                quant_system.hermes_command_workflow_bindings,
                quant_system.hermes_run_links,
                quant_system.hermes_outbox,
                quant_system.hermes_command_events,
                quant_system.hermes_commands,
                quant_system.hermes_workspace_sessions
            RESTART IDENTITY
            """
        )
        for trigger_name in (
            "trg_hermes_workflow_binding_validate",
            "trg_hermes_workflow_binding_append_only",
            "trg_hermes_workflow_binding_append_only_truncate",
        ):
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                f"ENABLE ALWAYS TRIGGER {trigger_name}"
            )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only_truncate"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only_truncate"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_workspace_sessions "
            "ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability"
        )


def _count_rows(database: db.Database) -> tuple[int, int]:
    with database.connect() as conn:
        commands = conn.execute(
            "SELECT count(*) FROM quant_system.hermes_commands"
        ).fetchone()
        sessions = conn.execute(
            "SELECT count(*) FROM quant_system.hermes_workspace_sessions"
        ).fetchone()
    assert commands is not None and sessions is not None
    return int(commands[0]), int(sessions[0])


def _create_action(client_action_id: str = "act-create-1") -> CreateManagedSession:
    return CreateManagedSession(
        client_action_id=client_action_id,
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
        payload_ttl_days=7,
    )


def _prepare(settings: Settings) -> db.Database:
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_authorities(database)
    assert settings.database.url is not None
    admin_url = settings.database.url.get_secret_value()
    with database.connect() as conn:
        if conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_LOGIN,)
        ).fetchone() is not None:
            conn.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(RUNTIME_LOGIN))
            )
            conn.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(RUNTIME_LOGIN))
            )
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}"
            ).format(
                sql.Identifier(RUNTIME_LOGIN),
                sql.Literal(RUNTIME_PASSWORD),
            )
        )
        conn.execute(
            sql.SQL("GRANT quant_runtime TO {}").format(
                sql.Identifier(RUNTIME_LOGIN)
            )
        )
    runtime_params = conninfo_to_dict(admin_url)
    runtime_params["user"] = RUNTIME_LOGIN
    runtime_params["password"] = RUNTIME_PASSWORD
    settings.database.url = SecretStr(make_conninfo(**runtime_params))
    db.reset_database_cache()
    return database


def test_canonical_action_digest_is_stable_and_order_independent() -> None:
    action = _create_action()
    first = canonical_action_digest(action)
    second = canonical_action_digest(parse_user_action_v1(action_to_document(action)))
    assert first == second
    assert len(first) == 64
    # Key order must not matter for digest of equivalent document.
    doc = action_to_document(action)
    shuffled = {
        "payload_ttl_days": doc["payload_ttl_days"],
        "schema_version": doc["schema_version"],
        "kind": doc["kind"],
        "workspace": doc["workspace"],
        "client_action_id": doc["client_action_id"],
        "provider_policy_digest": doc["provider_policy_digest"],
    }
    assert canonical_action_digest(parse_user_action_v1(shuffled)) == first


def test_mutation_disabled_create_fork_turn_zero_writes() -> None:
    settings = _postgres_settings()
    database = _prepare(settings)
    ready = authorities_ready(settings)
    assert ready["ready"] is True
    assert ready["mutation_enabled"] is False

    workspace = build_platform_agent_workspace(settings, mutation_enabled=False)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))
    before = _count_rows(database)

    create_receipt = workspace.act(actor, _create_action("act-off-create"))
    assert create_receipt.status == "unavailable"
    assert create_receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert create_receipt.recovery_action == "retry_read_or_reconcile_original_action"
    assert create_receipt.to_public_dict()["mutation_enabled"] is False

    # Seed an external session via registry (not through act) to probe turn/fork gates.
    external, _ = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="ext-discord-1",
            hermes_session_id="hermes-ext-1",
            workspace_id=WORKSPACE_ID,
            kind="observed_external_session",
            source_channel="discord",
        ),
    )
    after_seed = _count_rows(database)
    assert after_seed == (before[0], before[1] + 1)

    fork = ForkIntoManagedSession(
        client_action_id="act-off-fork",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        source_session_ref=session_ref(external.platform_session_id),
        source_channel="discord",
        fork_point="msg:100",
        new_provider_policy_digest=DIGEST_B,
        payload_ttl_days=7,
    )
    fork_receipt = workspace.act(actor, fork)
    assert fork_receipt.status == "unavailable"
    assert fork_receipt.reason_code == "authenticated_mutation_bff_unavailable"

    payload_digest = DIGEST_C
    turn = ConversationTurn(
        client_action_id="act-off-turn",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        managed_session_ref=session_ref(external.platform_session_id),
        payload_ref=f"payload:sha256:{payload_digest}",
        payload_digest=payload_digest,
    )
    turn_receipt = workspace.act(actor, turn)
    assert turn_receipt.status == "unavailable"

    after = _count_rows(database)
    assert after == after_seed  # zero command writes; session count unchanged by act


def test_mutation_enabled_create_is_idempotent_by_digest() -> None:
    settings = _postgres_settings()
    database = _prepare(settings)
    workspace = build_platform_agent_workspace(settings, mutation_enabled=True)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))
    action = _create_action("act-create-idem")
    digest = canonical_action_digest(action)

    first = workspace.act(actor, action)
    assert first.status == "accepted"
    assert first.action_digest == digest
    assert first.command_id is None
    assert first.platform_session_id == derive_managed_platform_session_id(digest)
    assert first.hermes_session_id == derive_managed_hermes_session_id(digest)
    assert first.recovery_action is None

    second = workspace.act(actor, action)
    assert second.status == "accepted"
    assert second.command_id is None
    assert second.platform_session_id == first.platform_session_id
    assert second.hermes_session_id == first.hermes_session_id

    commands, sessions = _count_rows(database)
    assert commands == 0
    assert sessions == 1

    # Browser cannot manufacture a second valid create digest by selecting TTL.
    rejected_action = CreateManagedSession(
        client_action_id="act-create-idem",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
        payload_ttl_days=14,
    )
    rejected = workspace.act(actor, rejected_action)
    assert rejected.status == "unavailable"
    assert rejected.reason_code == "server_managed_session_policy_required"
    commands2, sessions2 = _count_rows(database)
    assert (commands2, sessions2) == (0, 1)

    record = get_workspace_session(
        settings, platform_session_id=first.platform_session_id  # type: ignore[arg-type]
    )
    assert record.kind == "web_managed_session"
    assert record.provider_policy_digest == PROVIDER_POLICY_DIGEST
    assert record.payload_ttl_days == 7
    assert record.creation_client_action_id == action.client_action_id
    assert record.creation_action_digest == digest
    assert record.web_writable is True


def test_fork_creates_managed_without_mutating_external() -> None:
    settings = _postgres_settings()
    database = _prepare(settings)
    workspace = build_platform_agent_workspace(settings, mutation_enabled=True)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))

    external, _ = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="ext-discord-fork",
            hermes_session_id="hermes-ext-fork",
            workspace_id=WORKSPACE_ID,
            kind="observed_external_session",
            source_channel="discord",
        ),
    )
    before = get_workspace_session(
        settings, platform_session_id=external.platform_session_id
    )

    fork = ForkIntoManagedSession(
        client_action_id="act-fork-1",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        source_session_ref=session_ref(external.platform_session_id),
        source_channel="discord",
        fork_point="cursor:42",
        new_provider_policy_digest=PROVIDER_POLICY_DIGEST,
        payload_ttl_days=7,
    )
    receipt = workspace.act(actor, fork)
    assert receipt.status == "accepted"
    assert receipt.command_id is None
    assert receipt.platform_session_id is not None
    assert receipt.platform_session_id != external.platform_session_id

    after_external = get_workspace_session(
        settings, platform_session_id=external.platform_session_id
    )
    assert after_external.kind == before.kind
    assert after_external.hermes_session_id == before.hermes_session_id
    assert after_external.updated_at == before.updated_at
    assert after_external.provider_policy_digest is None

    managed = get_workspace_session(
        settings, platform_session_id=receipt.platform_session_id
    )
    assert managed.kind == "web_managed_session"
    assert managed.parent_platform_session_id == external.platform_session_id
    assert managed.fork_point == "cursor:42"
    assert managed.source_channel == "discord"
    assert managed.provider_policy_digest == PROVIDER_POLICY_DIGEST
    assert managed.payload_ttl_days == 7

    # Idempotent fork retry
    again = workspace.act(actor, fork)
    assert again.status == "accepted"
    assert again.command_id is None
    assert again.platform_session_id == receipt.platform_session_id

    conflicting_fork = ForkIntoManagedSession(
        client_action_id=fork.client_action_id,
        workspace=fork.workspace,
        source_session_ref=fork.source_session_ref,
        source_channel=fork.source_channel,
        fork_point="cursor:43",
        new_provider_policy_digest=fork.new_provider_policy_digest,
        payload_ttl_days=fork.payload_ttl_days,
    )
    conflict = workspace.act(actor, conflicting_fork)
    assert conflict.status == "conflict"
    assert conflict.reason_code == "idempotency_digest_conflict"
    assert conflict.command_id is None
    commands, sessions = _count_rows(database)
    assert commands == 0
    assert sessions == 2


def test_external_turn_conflicts_managed_turn_idempotent_and_conflict() -> None:
    settings = _postgres_settings()
    database = _prepare(settings)
    workspace = build_platform_agent_workspace(settings, mutation_enabled=True)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))

    external, _ = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="ext-ro",
            hermes_session_id="hermes-ext-ro",
            workspace_id=WORKSPACE_ID,
            kind="observed_external_session",
            source_channel="historical",
        ),
    )
    payload_digest = hashlib.sha256(b"turn-body-v4").hexdigest()
    external_turn = ConversationTurn(
        client_action_id="act-turn-ext",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        managed_session_ref=session_ref(external.platform_session_id),
        payload_ref=f"payload:sha256:{payload_digest}",
        payload_digest=payload_digest,
    )
    blocked = workspace.act(actor, external_turn)
    assert blocked.status == "conflict"
    assert blocked.reason_code == "external_session_not_writable"
    commands_after_block, _ = _count_rows(database)
    assert commands_after_block == 0

    create = workspace.act(actor, _create_action("act-create-for-turn"))
    assert create.status == "accepted"
    assert create.platform_session_id is not None

    turn = ConversationTurn(
        client_action_id="act-turn-1",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        managed_session_ref=session_ref(create.platform_session_id),
        payload_ref=f"payload:sha256:{payload_digest}",
        payload_digest=payload_digest,
    )
    first = workspace.act(actor, turn)
    assert first.status == "accepted"
    assert first.command_id is not None
    assert first.platform_session_id == create.platform_session_id

    # Ledger payload_ref must be platform-mapped, never HQA payload:sha256 form.
    ledger = HermesCommandLedger(settings)
    command = ledger.get_command(UUID(first.command_id))
    assert command.kind == "conversation_turn"
    assert command.payload_ref == hqa_payload_to_platform_payload_ref(payload_digest)
    assert command.canonical_request_digest == canonical_action_digest(turn)
    assert not command.payload_ref.startswith("payload:sha256:")

    second = workspace.act(actor, turn)
    assert second.status == "accepted"
    assert second.command_id == first.command_id

    other_digest = hashlib.sha256(b"different-turn").hexdigest()
    conflict_turn = ConversationTurn(
        client_action_id="act-turn-1",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        managed_session_ref=session_ref(create.platform_session_id),
        payload_ref=f"payload:sha256:{other_digest}",
        payload_digest=other_digest,
    )
    conflict = workspace.act(actor, conflict_turn)
    assert conflict.status == "conflict"
    assert conflict.reason_code == "idempotency_digest_conflict"

    commands, sessions = _count_rows(database)
    # Session creation is registry-only; only the conversation turn is work.
    assert commands == 1
    assert sessions == 2


def test_snapshot_lists_sessions_and_follow_lifecycle() -> None:
    """L2b-M1: snapshot command objects + follow event page.

    Hermetic gate is ON for act; snapshot/follow report the effective gate
    (constructor OR settings.local_mutation). Constructor default remains
    False; effective ON only when operator settings open local mutation.
    """
    settings = _postgres_settings()
    _prepare(settings)
    workspace = build_platform_agent_workspace(settings, mutation_enabled=True)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))

    create = workspace.act(actor, _create_action("act-snap-create"))
    assert create.status == "accepted"

    turn = ConversationTurn(
        client_action_id="act-snap-turn",
        workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
        managed_session_ref=session_ref(create.platform_session_id),  # type: ignore[arg-type]
        payload_ref=f"payload:sha256:{DIGEST_C}",
        payload_digest=DIGEST_C,
    )
    turn_receipt = workspace.act(actor, turn)
    assert turn_receipt.status == "accepted"
    assert turn_receipt.command_id is not None

    snap = workspace.snapshot(actor, WorkspaceRef(workspace_id=WORKSPACE_ID))
    assert snap.mutation_enabled is True
    assert snap.workspace_id == WORKSPACE_ID
    assert snap.owner_user_id == str(ROOT_USER_ID)
    assert create.platform_session_id in snap.sessions
    assert snap.authority_health["mutation"] == "enabled"
    assert snap.authority_health["command_ledger"] == "ready"
    assert snap.authority_health["session_registry"] == "ready"
    public = snap.to_public_dict()
    assert public["mutation_enabled"] is True

    page = workspace.follow(actor, WORKSPACE_ID, after=0)
    assert page.resync_required is False
    # L2b-M1: follow projects durable command_created events (not empty skeleton).
    assert page.events
    assert page.next_cursor is not None and page.next_cursor >= 1
    assert all(isinstance(event.get("event_id"), int) for event in page.events)
    assert any(event.get("type") == "command.queued" for event in page.events)
    assert page.mutation_enabled is True
    # Snapshot commands are public objects (not bare UUID strings).
    assert snap.commands
    assert isinstance(snap.commands[0], dict)
    assert "command_id" in snap.commands[0]
    assert snap.commands[0]["command_id"] == turn_receipt.command_id
    assert snap.commands[0]["state"] == "queued"
    assert snap.snapshot_workspace_cursor >= 1

    # Constructor default is OFF; snapshot reports *effective* gate
    # (constructor OR settings.local_mutation). When the operator has
    # QS_LOCAL_MUTATION_ENABLED on this machine, effective stays ON —
    # that is intentional V6 local behavior, not a public cutover.
    closed = build_platform_agent_workspace(settings)
    closed_snap = closed.snapshot(actor, WorkspaceRef(workspace_id=WORKSPACE_ID))
    assert closed.mutation_enabled is False
    ready = authorities_ready(settings)
    effective = bool(ready.get("mutation_enabled"))
    assert closed_snap.mutation_enabled is effective
    assert closed_snap.authority_health["mutation"] == (
        "enabled" if effective else "disabled"
    )


def test_submit_action_document_path_and_unsupported_kind() -> None:
    settings = _postgres_settings()
    _prepare(settings)
    doc = action_to_document(_create_action("act-doc-path"))
    receipt = submit_action(settings, doc, mutation_enabled=True)
    assert receipt.status == "accepted"

    research_doc = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-research-1",
        "workspace": {"workspace_id": WORKSPACE_ID},
        "managed_session_ref": session_ref(receipt.platform_session_id or "wm_x"),
        "payload_ref": f"payload:sha256:{DIGEST_C}",
        "payload_digest": DIGEST_C,
        "initial_mode": "plan_only",
    }
    # research.start is typed and digest-stable; browser/HQA prepare path stays
    # dark in V4. Hermetic mutation=True still returns an explicit research
    # submission blocker with zero PG writes beyond the earlier create.
    blocked = submit_action(settings, research_doc, mutation_enabled=True)
    assert blocked.status == "unavailable"
    assert blocked.reason_code == "research_workflow_submission_unavailable"

    # Public mutation gate still wins when OFF.
    public = submit_action(settings, research_doc, mutation_enabled=False)
    assert public.status == "unavailable"
    assert public.reason_code == "authenticated_mutation_bff_unavailable"

    # initial_mode must be plan_only (HQA contract).
    from quant_system.hermes.submission_saga import SubmissionSagaError

    bad_mode = dict(research_doc, initial_mode="plan", client_action_id="act-research-bad")
    with pytest.raises(SubmissionSagaError) as excinfo:
        submit_action(settings, bad_mode, mutation_enabled=True)
    assert excinfo.value.code == "validation"

    # V7 authority kinds fail closed until the canonical adapter is mounted.
    stop_doc = {
        "schema_version": 1,
        "kind": "run.stop.request",
        "client_action_id": "act-stop-1",
        "workspace": {"workspace_id": WORKSPACE_ID},
        "run_ref": "run:r1",
        "task_ref": None,
        "attempt_ref": None,
        "platform_job_ref": None,
    }
    stop = submit_action(settings, stop_doc, mutation_enabled=True)
    assert stop.status == "unavailable"
    assert stop.reason_code == "canonical_authority_adapter_unavailable"


def test_public_workspace_factory_defaults_mutation_off() -> None:
    settings = _postgres_settings()
    workspace = PlatformAgentWorkspace(settings)
    assert workspace.mutation_enabled is False
    built = build_platform_agent_workspace(settings)
    assert built.mutation_enabled is False
