from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

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
    CandidateAdmissionReceipt,
    CandidateAdmissionUnavailable,
    OpenCandidateAdmissionRequest,
    canonical_candidate_action_digest,
)
from quant_system.hermes.command_ledger import (
    ROOT_USER_ID,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
)
from quant_system.hermes.dark_identity_profile import (
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_authority import (
    CreatePublicCutoverRequest,
    CreateReleaseStampRequest,
    ReleaseAuthority,
    ReleaseAuthorityConflict,
    ReleaseAuthorityUnavailable,
    canonical_release_action_digest,
    release_authority_runtime_security_ready,
    release_authority_schema_is_ready_on_connection,
)
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

WORKSPACE = "workspace-root"
PLATFORM = "1" * 64
HQA = "2" * 64
HERMES = "3" * 64
SCHEMA_DIGEST = "4" * 64
PREFLIGHT = "5" * 64
ORDERS = "6" * 64
FINAL_EVIDENCE = "7" * 64
CAPABILITY_NAMES = (
    "idempotency",
    "event_replay",
    "approval_cas",
    "idempotent_stop",
    "restart_reconcile",
    "run_evidence",
)


@pytest.fixture
def hardening_database() -> Iterator[tuple[Settings, db.Database, str]]:
    base_url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(
        base_url,
        purpose="release20",
    ) as isolated_url:
        settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=isolated_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            ),
            candidate_admission=CandidateAdmissionSettings(
                enabled=True,
                ttl_seconds=120,
            ),
        )
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database)
        observed_at = datetime.now(UTC)
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO quant_system.paper_accounts (
                    account_id, owner_user_id, base_currency, initial_cash,
                    cash, realized_pnl, kill_switch, version, raw,
                    created_at, updated_at
                )
                VALUES (
                    'default', %s, 'USD', 1000, 1000,
                    0, TRUE, 1,
                    '{"account_id":"default","kill_switch":true}'::jsonb,
                    %s, %s
                )
                """,
                (ROOT_USER_ID, observed_at, observed_at),
            )
        yield settings, database, isolated_url


def _open_request(
    workspace_id: str,
    *,
    generation: str = "default",
) -> OpenCandidateAdmissionRequest:
    payload = {
        "baseline_order_snapshot_digest": ORDERS,
        "database_schema_fingerprint": SCHEMA_DIGEST,
        "hermes_runtime_digest": HERMES,
        "hqa_runtime_digest": HQA,
        "note": "collect exact release candidate evidence",
        "platform_runtime_digest": PLATFORM,
        "preflight_evidence_digest": PREFLIGHT,
        "route": "/hermes",
        "ttl_seconds": 120,
        "workspace_id": workspace_id,
    }
    return OpenCandidateAdmissionRequest(
        workspace_id=workspace_id,
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA_DIGEST,
        preflight_evidence_digest=PREFLIGHT,
        baseline_order_snapshot_digest=ORDERS,
        ttl_seconds=120,
        note=str(payload["note"]),
        client_action_id=f"open-{workspace_id}-{generation}",
        action_digest=canonical_candidate_action_digest(
            "candidate.open",
            payload,
        ),
    )


def _accept_request(
    opened: CandidateAdmissionReceipt,
    *,
    evidence_set_id: str,
    evidence_set_digest: str,
) -> AcceptCandidateAdmissionRequest:
    payload = {
        "admission_id": opened.admission_id,
        "expected_admission_digest": opened.admission_digest,
        "evidence_set_digest": evidence_set_digest,
        "evidence_set_id": evidence_set_id,
        "final_evidence_digest": FINAL_EVIDENCE,
        "final_order_snapshot_digest": ORDERS,
        "note": "exact evidence and paper authority epoch sealed",
        "workspace_id": opened.workspace_id,
    }
    return AcceptCandidateAdmissionRequest(
        workspace_id=opened.workspace_id,
        admission_id=opened.admission_id,
        expected_admission_digest=opened.admission_digest,
        final_evidence_digest=FINAL_EVIDENCE,
        evidence_set_id=evidence_set_id,
        evidence_set_digest=evidence_set_digest,
        final_order_snapshot_digest=ORDERS,
        note=str(payload["note"]),
        client_action_id=f"accept-{opened.admission_id}",
        action_digest=canonical_candidate_action_digest(
            "candidate.accept",
            payload,
        ),
    )


def _seed_exact_fork_lineage(
    conn: psycopg.Connection,
    *,
    workspace_id: str,
    admission_id: str,
    token: str,
) -> dict[str, str]:
    source_platform_session_id = f"source-{token[:16]}"
    source_hermes_session_id = f"discord-source-{token[:16]}"
    child_platform_session_id = f"child-{token[:16]}"
    fork_point = "message:1"
    creation_digest = hashlib.sha256(
        f"{workspace_id}:{child_platform_session_id}".encode()
    ).hexdigest()
    child_hermes_session_id = f"web_{creation_digest[:40]}"

    conn.execute(
        """
        INSERT INTO quant_system.hermes_workspace_sessions (
            platform_session_id,
            hermes_session_id,
            workspace_id,
            owner_user_id,
            kind,
            source_channel,
            writer,
            provision_state
        )
        VALUES (
            %s, %s, %s, %s, 'observed_external_session',
            'discord', 'external_channel', 'observed'
        )
        """,
        (
            source_platform_session_id,
            source_hermes_session_id,
            workspace_id,
            ROOT_USER_ID,
        ),
    )
    conn.execute(
        """
        INSERT INTO quant_system.hermes_workspace_sessions (
            platform_session_id,
            hermes_session_id,
            workspace_id,
            owner_user_id,
            kind,
            source_channel,
            parent_platform_session_id,
            fork_point,
            provider_policy_digest,
            writer,
            payload_ttl_days,
            creation_client_action_id,
            creation_action_digest,
            provision_state,
            provisioning_receipt_digest,
            provisioned_at,
            resolved_source_session_id
        )
        VALUES (
            %s, %s, %s, %s, 'web_managed_session',
            'discord', %s, %s, %s, 'web_control_plane', 7,
            %s, %s, 'ready', %s, clock_timestamp(), %s
        )
        """,
        (
            child_platform_session_id,
            child_hermes_session_id,
            workspace_id,
            ROOT_USER_ID,
            source_platform_session_id,
            fork_point,
            "a" * 64,
            f"create-{token[:16]}",
            creation_digest,
            hashlib.sha256(f"receipt:{token}".encode()).hexdigest(),
            source_hermes_session_id,
        ),
    )
    bound_admission = conn.execute(
        """
        SELECT candidate_admission_id
        FROM quant_system.hermes_workspace_sessions
        WHERE platform_session_id = %s
        """,
        (child_platform_session_id,),
    ).fetchone()
    assert bound_admission == (admission_id,)

    return {
        "source_platform_session_id": source_platform_session_id,
        "source_hermes_session_id": source_hermes_session_id,
        "child_platform_session_id": child_platform_session_id,
        "child_hermes_session_id": child_hermes_session_id,
        "resolved_source_session_id": source_hermes_session_id,
        "fork_point": fork_point,
    }


def _seed_open_candidate_with_evidence(
    settings: Settings,
    database: db.Database,
    *,
    workspace_id: str = WORKSPACE,
    generation: str = "default",
) -> tuple[
    CandidateAdmissionAuthority,
    CandidateAdmissionReceipt,
    AcceptCandidateAdmissionRequest,
]:
    authority = CandidateAdmissionAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    token = hashlib.sha256(
        f"{workspace_id}\0{generation}".encode()
    ).hexdigest()
    opened = authority.open(
        _open_request(workspace_id, generation=generation),
        admission_id=f"candidate-{token[:16]}",
    )
    evidence_digest = hashlib.sha256(
        f"evidence\0{workspace_id}\0{generation}".encode()
    ).hexdigest()
    evidence_set_id = f"evidence-{token[:16]}"
    with database.connect() as conn, conn.transaction():
        fork_flow = _seed_exact_fork_lineage(
            conn,
            workspace_id=workspace_id,
            admission_id=opened.admission_id,
            token=token,
        )
        facts = json.dumps(
            {
                "contract": "agent-v0.2-candidate-evidence-facts/v1",
                "flows": {"exact_message_fork": fork_flow},
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        conn.execute(
            """
            ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
            DISABLE TRIGGER trg_agent_v02_candidate_evidence_set_guard
            """
        )
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_candidate_evidence_sets (
                evidence_set_id,
                owner_user_id,
                workspace_id,
                admission_id,
                admission_digest,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest,
                final_order_snapshot_digest,
                facts,
                facts_digest
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s::jsonb, %s
            )
            """,
            (
                evidence_set_id,
                ROOT_USER_ID,
                workspace_id,
                opened.admission_id,
                opened.admission_digest,
                PLATFORM,
                HQA,
                HERMES,
                SCHEMA_DIGEST,
                ORDERS,
                ORDERS,
                facts,
                evidence_digest,
            ),
        )
        conn.execute(
            """
            ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
            ENABLE ALWAYS TRIGGER
                trg_agent_v02_candidate_evidence_set_guard
            """
        )
    return (
        authority,
        opened,
        _accept_request(
            opened,
            evidence_set_id=evidence_set_id,
            evidence_set_digest=evidence_digest,
        ),
    )


def _release_request(workspace_id: str) -> CreateReleaseStampRequest:
    payload = {
        "workspace_id": workspace_id,
        "route": "/hermes",
        "platform_runtime_digest": PLATFORM,
        "hqa_runtime_digest": HQA,
        "hermes_runtime_digest": HERMES,
        "evidence_digest": FINAL_EVIDENCE,
        "note": "operator reviewed the exact accepted candidate",
    }
    return CreateReleaseStampRequest(
        **payload,
        client_action_id=f"release-{workspace_id}",
        action_digest=canonical_release_action_digest(
            "release.open",
            payload,
        ),
    )


def _cutover_request(
    workspace_id: str,
    *,
    stamp_id: str,
    release_digest: str,
) -> CreatePublicCutoverRequest:
    payload = {
        "workspace_id": workspace_id,
        "stamp_id": stamp_id,
        "expected_release_digest": release_digest,
        "route": "/hermes",
        "note": "operator opened the exact accepted release",
    }
    return CreatePublicCutoverRequest(
        **payload,
        client_action_id=f"cutover-{workspace_id}",
        action_digest=canonical_release_action_digest(
            "public_cutover.open",
            payload,
        ),
    )


def _insert_paper_account(
    conn: psycopg.Connection,
    *,
    account_id: str,
) -> None:
    observed_at = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO quant_system.paper_accounts (
            account_id,
            owner_user_id,
            base_currency,
            initial_cash,
            cash,
            realized_pnl,
            kill_switch,
            version,
            raw,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, 'USD', 1000, 1000, 0, TRUE, 1,
            '{}'::jsonb, %s, %s
        )
        """,
        (account_id, ROOT_USER_ID, observed_at, observed_at),
    )


@contextmanager
def _runtime_login_url(
    admin_url: str,
    database: db.Database,
) -> Iterator[str]:
    role_name = f"aqp_release20_{uuid4().hex[:12]}"
    password = f"release20-{uuid4().hex}"
    with database.connect() as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE NOREPLICATION INHERIT PASSWORD {}"
            ).format(
                sql.Identifier(role_name),
                sql.Literal(password),
            )
        )
        conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(role_name)))
    parameters = conninfo_to_dict(admin_url)
    parameters["user"] = role_name
    parameters["password"] = password
    try:
        yield make_conninfo(**parameters)
    finally:
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def _capabilities(
    observed_at: datetime,
) -> HermesDurableCapabilityObservation:
    return HermesDurableCapabilityObservation(
        runtime_digest=HERMES,
        observed_at=observed_at,
        payload={
            "contract_version": 1,
            "features": {
                "session_resources": True,
                "run_submission": True,
                "run_events_sse": True,
                "run_events_snapshot": True,
                "run_status": True,
                "run_approval_response": True,
                "run_stop": True,
                "managed_run_sessions": True,
            },
            "managed_session_contract": {
                "history_authority": "hermes_session_db",
                "fork_mode": "preserve_source_exact_message_cursor",
            },
            "durable": {
                name: {
                    "supported": True,
                    "grounded": True,
                    "evidence": f"store.transactional_probe:{name}",
                }
                for name in CAPABILITY_NAMES
            },
        },
    )


def test_020_is_replay_safe_ready_and_refuses_future_schema_downgrade(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    _settings, database, _url = hardening_database
    db.run_migrations(
        database,
        only=("020_agent_v02_release_authority_hardening.sql",),
    )
    with database.connect() as conn:
        assert release_authority_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            UPDATE quant_system.agent_v02_release_hardening_meta
            SET schema_version = 2
            WHERE singleton IS TRUE
            """
        )

    with pytest.raises(
        psycopg.errors.RaiseException,
        match="newer than this binary supports",
    ):
        db.run_migrations(
            database,
            only=("020_agent_v02_release_authority_hardening.sql",),
        )

    with database.connect() as conn:
        assert conn.execute(
            """
            SELECT schema_version
            FROM quant_system.agent_v02_release_hardening_meta
            WHERE singleton IS TRUE
            """
        ).fetchone() == (2,)


def test_post_release_managed_session_binds_accepted_candidate(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, admin_url = hardening_database
    candidate_authority, opened, accept_request = (
        _seed_open_candidate_with_evidence(settings, database)
    )
    accepted = candidate_authority.accept(accept_request)
    assert accepted.status == "accepted"

    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-session-binding-stamp",
    )
    release_authority.create_public_cutover(
        _cutover_request(
            WORKSPACE,
            stamp_id=stamp.resource_id,
            release_digest=stamp.resource_digest,
        ),
        now=datetime.now(UTC) + timedelta(seconds=2),
        cutover_id="release-session-binding-cutover",
    )

    creation_digest = hashlib.sha256(b"post-release-session").hexdigest()
    with _runtime_login_url(admin_url, database) as runtime_url:
        runtime_settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=runtime_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            ),
            candidate_admission=CandidateAdmissionSettings(
                enabled=True,
                ttl_seconds=120,
            ),
        )
        db.reset_database_cache()
        session, created = register_workspace_session(
            runtime_settings,
            RegisterWorkspaceSession(
                platform_session_id="wm_post_release_binding",
                hermes_session_id=f"web_{creation_digest[:40]}",
                workspace_id=WORKSPACE,
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=STORE_TTL_DAYS,
                creation_client_action_id="post-release-session-create",
                creation_action_digest=creation_digest,
            ),
        )

    assert created is True
    assert session.candidate_admission_id == opened.admission_id
    command = HermesCommandLedger(settings).create_command(
        platform_session_id=session.platform_session_id,
        client_request_id="post-release-session-turn",
        kind="conversation_turn",
        canonical_request_digest="c" * 64,
        payload_ref=f"platform-payload://sha256/{'d' * 64}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    ).command
    with database.connect() as conn:
        release_command_binding = conn.execute(
            """
            SELECT candidate_admission_id
            FROM quant_system.hermes_commands
            WHERE command_id = %s
            """,
            (command.command_id,),
        ).fetchone()
    assert release_command_binding == (None,)
    db.reset_database_cache()


def test_public_cutover_refuses_an_open_replacement_candidate(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _admin_url = hardening_database
    candidate_authority, _first, first_accept = (
        _seed_open_candidate_with_evidence(
            settings,
            database,
            generation="first",
        )
    )
    assert candidate_authority.accept(first_accept).status == "accepted"

    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-before-replacement-candidate",
    )
    replacement = candidate_authority.open(
        _open_request(WORKSPACE, generation="replacement"),
        admission_id="candidate-replacement-open",
    )
    assert replacement.status == "open"

    with pytest.raises(
        ReleaseAuthorityConflict,
        match="zero open candidate admissions",
    ):
        release_authority.create_public_cutover(
            _cutover_request(
                WORKSPACE,
                stamp_id=stamp.resource_id,
                release_digest=stamp.resource_digest,
            ),
            now=datetime.now(UTC) + timedelta(seconds=2),
            cutover_id="cutover-must-not-split",
        )

    assert release_authority.open_public_cutover(WORKSPACE) is None
    assert candidate_authority.active(WORKSPACE) is not None


def test_candidate_open_and_public_cutover_race_has_exactly_one_winner(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _admin_url = hardening_database
    candidate_authority, _first, first_accept = (
        _seed_open_candidate_with_evidence(
            settings,
            database,
            generation="race-first",
        )
    )
    assert candidate_authority.accept(first_accept).status == "accepted"
    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-admission-race",
    )
    ready = Barrier(2)

    def open_candidate() -> bool:
        ready.wait(timeout=3)
        try:
            candidate_authority.open(
                _open_request(WORKSPACE, generation="race-replacement"),
                admission_id="candidate-admission-race",
            )
        except CandidateAdmissionConflict:
            return False
        return True

    def open_cutover() -> bool:
        ready.wait(timeout=3)
        try:
            release_authority.create_public_cutover(
                _cutover_request(
                    WORKSPACE,
                    stamp_id=stamp.resource_id,
                    release_digest=stamp.resource_digest,
                ),
                now=datetime.now(UTC) + timedelta(seconds=2),
                cutover_id="cutover-admission-race",
            )
        except ReleaseAuthorityConflict:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        candidate_result = executor.submit(open_candidate)
        cutover_result = executor.submit(open_cutover)
        outcomes = (
            candidate_result.result(timeout=10),
            cutover_result.result(timeout=10),
        )

    assert sum(outcomes) == 1
    assert not (
        candidate_authority.active(WORKSPACE) is not None
        and release_authority.open_public_cutover(WORKSPACE) is not None
    )


def test_release_close_serializes_with_conversation_turn_insert(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _admin_url = hardening_database
    candidate_authority, _opened, accept_request = (
        _seed_open_candidate_with_evidence(settings, database)
    )
    assert candidate_authority.accept(accept_request).status == "accepted"

    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-close-race-stamp",
    )
    cutover = release_authority.create_public_cutover(
        _cutover_request(
            WORKSPACE,
            stamp_id=stamp.resource_id,
            release_digest=stamp.resource_digest,
        ),
        now=datetime.now(UTC) + timedelta(seconds=2),
        cutover_id="release-close-race-cutover",
    )

    creation_digest = hashlib.sha256(b"release-close-race-session").hexdigest()
    session, _created = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id="wm_release_close_race",
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id=WORKSPACE,
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id="release-close-race-session-create",
            creation_action_digest=creation_digest,
        ),
    )

    insert_started = Event()

    def insert_turn() -> str:
        insert_started.set()
        try:
            HermesCommandLedger(settings).create_command(
                platform_session_id=session.platform_session_id,
                client_request_id="release-close-race-turn",
                kind="conversation_turn",
                canonical_request_digest="f" * 64,
                payload_ref=f"platform-payload://sha256/{'a' * 64}",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
            )
        except HermesCommandLedgerUnavailable as exc:
            return str(exc)
        return "accepted"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.connect() as close_conn, close_conn.transaction():
            close_conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"quant_system:agent_v02_release:{WORKSPACE}",),
            )
            close_conn.execute(
                """
                UPDATE quant_system.agent_v02_public_cutovers
                SET status = 'closed',
                    closed_at = clock_timestamp(),
                    close_reason = 'concurrent rollback drill'
                WHERE cutover_id = %s
                  AND cutover_digest = %s
                  AND status = 'open'
                """,
                (cutover.resource_id, cutover.resource_digest),
            )
            future = executor.submit(insert_turn)
            assert insert_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.25)
        outcome = future.result(timeout=5)

    assert "exact release" in outcome or "not writable" in outcome
    with database.connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)
            FROM quant_system.hermes_commands
            WHERE client_request_id = 'release-close-race-turn'
            """
        ).fetchone() == (0,)


def test_release_command_trigger_rejects_session_from_prior_accepted_candidate(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _url = hardening_database
    candidate_authority, first, first_accept = (
        _seed_open_candidate_with_evidence(
            settings,
            database,
            generation="first",
        )
    )
    assert candidate_authority.accept(first_accept).status == "accepted"
    with database.connect() as conn:
        stale_session_row = conn.execute(
            """
            SELECT platform_session_id
            FROM quant_system.hermes_workspace_sessions
            WHERE candidate_admission_id = %s
              AND kind = 'web_managed_session'
            LIMIT 1
            """,
            (first.admission_id,),
        ).fetchone()
    assert stale_session_row is not None
    stale_session_id = str(stale_session_row[0])

    candidate_authority, second, second_accept = (
        _seed_open_candidate_with_evidence(
            settings,
            database,
            generation="second",
        )
    )
    assert candidate_authority.accept(second_accept).status == "accepted"

    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-second-candidate-stamp",
    )
    release_authority.create_public_cutover(
        _cutover_request(
            WORKSPACE,
            stamp_id=stamp.resource_id,
            release_digest=stamp.resource_digest,
        ),
        now=datetime.now(UTC) + timedelta(seconds=2),
        cutover_id="release-second-candidate-cutover",
    )
    active_stamp = release_authority.active_release_stamp(WORKSPACE)
    assert active_stamp is not None
    assert active_stamp.candidate_admission_id == second.admission_id

    with pytest.raises(
        HermesCommandLedgerUnavailable,
        match="exact release session",
    ):
        HermesCommandLedger(settings).create_command(
            platform_session_id=stale_session_id,
            client_request_id="stale-candidate-release-turn",
            kind="conversation_turn",
            canonical_request_digest="d" * 64,
            payload_ref=f"platform-payload://sha256/{'e' * 64}",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
        )


def test_every_paper_authority_insert_update_delete_advances_the_epoch(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    _settings, database, _url = hardening_database
    with database.connect() as conn, conn.transaction():
        _insert_paper_account(
            conn,
            account_id="paper-before-workspace-epoch",
        )
        owner_row = conn.execute(
            """
            SELECT authority_epoch
            FROM quant_system.agent_v02_paper_authority_owner_epochs
            WHERE owner_user_id = %s
            """,
            (ROOT_USER_ID,),
        ).fetchone()
        assert owner_row is not None
        first = conn.execute(
            """
            SELECT quant_system.ensure_agent_v02_paper_authority_epoch(
                %s,
                %s
            )
            """,
            (ROOT_USER_ID, WORKSPACE),
        ).fetchone()
        assert first is not None
        previous = int(first[0])
        assert previous == int(owner_row[0])

        def mutate(statement: str, parameters: tuple[object, ...]) -> None:
            nonlocal previous
            conn.execute(statement, parameters)
            row = conn.execute(
                """
                SELECT authority_epoch
                FROM quant_system.agent_v02_paper_authority_epochs
                WHERE owner_user_id = %s
                  AND workspace_id = %s
                """,
                (ROOT_USER_ID, WORKSPACE),
            ).fetchone()
            assert row is not None
            current = int(row[0])
            assert current > previous
            previous = current

        observed_at = datetime.now(UTC)
        mutate(
            """
            INSERT INTO quant_system.paper_accounts (
                account_id, owner_user_id, base_currency, initial_cash,
                cash, realized_pnl, kill_switch, version, raw,
                created_at, updated_at
            )
            VALUES (
                %s, %s, 'USD', 1000, 1000, 0, TRUE, 1,
                '{}'::jsonb, %s, %s
            )
            """,
            ("paper-epoch-test", ROOT_USER_ID, observed_at, observed_at),
        )
        mutate(
            """
            UPDATE quant_system.paper_accounts
            SET cash = cash
            WHERE account_id = %s
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            INSERT INTO quant_system.paper_account_ledger (
                account_id, entry_id, seq, timestamp, kind, source,
                commission, realized_pnl_delta, cash_after
            )
            VALUES (%s, 'entry-1', 1, %s, 'seed', 'test', 0, 0, 1000)
            """,
            ("paper-epoch-test", observed_at),
        )
        mutate(
            """
            UPDATE quant_system.paper_account_ledger
            SET note = 'still zero'
            WHERE account_id = %s AND entry_id = 'entry-1'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            DELETE FROM quant_system.paper_account_ledger
            WHERE account_id = %s AND entry_id = 'entry-1'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            INSERT INTO quant_system.paper_pending_orders (
                account_id, order_id, payload
            )
            VALUES (%s, 'order-1', '{}'::jsonb)
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            UPDATE quant_system.paper_pending_orders
            SET payload = '{"status":"still-pending"}'::jsonb
            WHERE account_id = %s AND order_id = 'order-1'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            DELETE FROM quant_system.paper_pending_orders
            WHERE account_id = %s AND order_id = 'order-1'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            INSERT INTO quant_system.paper_positions_current (
                account_id, symbol, quantity, avg_cost, updated_at
            )
            VALUES (%s, 'TEST', 0, 0, %s)
            """,
            ("paper-epoch-test", observed_at),
        )
        mutate(
            """
            UPDATE quant_system.paper_positions_current
            SET quantity = quantity
            WHERE account_id = %s AND symbol = 'TEST'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            """
            DELETE FROM quant_system.paper_positions_current
            WHERE account_id = %s AND symbol = 'TEST'
            """,
            ("paper-epoch-test",),
        )
        mutate(
            "DELETE FROM quant_system.paper_accounts WHERE account_id = %s",
            ("paper-epoch-test",),
        )


def test_paper_mutation_after_evidence_prevents_candidate_acceptance(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _url = hardening_database
    authority, opened, accept_request = _seed_open_candidate_with_evidence(
        settings,
        database,
    )

    with database.connect() as conn:
        _insert_paper_account(conn, account_id="paper-after-evidence")

    with pytest.raises(
        CandidateAdmissionUnavailable,
        match="database operation failed",
    ):
        authority.accept(accept_request)

    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT
                candidate.status,
                candidate.paper_authority_epoch,
                epoch.authority_epoch
            FROM quant_system.agent_v02_candidate_admissions AS candidate
            JOIN quant_system.agent_v02_paper_authority_epochs AS epoch
              ON epoch.owner_user_id = candidate.owner_user_id
             AND epoch.workspace_id = candidate.workspace_id
            WHERE candidate.admission_id = %s
            """,
            (opened.admission_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "open"
    assert int(row[1]) < int(row[2])


def test_concurrent_acceptance_waits_for_paper_mutation_and_fails_closed(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _url = hardening_database
    authority, opened, accept_request = _seed_open_candidate_with_evidence(
        settings,
        database,
    )
    attempt_started = Event()

    def attempt_acceptance() -> bool:
        attempt_started.set()
        try:
            authority.accept(accept_request)
        except CandidateAdmissionUnavailable:
            return False
        return True

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.connect() as paper_conn, paper_conn.transaction():
            _insert_paper_account(
                paper_conn,
                account_id="paper-accept-race",
            )
            acceptance = executor.submit(attempt_acceptance)
            assert attempt_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                acceptance.result(timeout=0.25)
        acceptance_succeeded = acceptance.result(timeout=5)

    assert acceptance_succeeded is False
    current = authority.current(WORKSPACE)
    assert current is not None
    assert current.admission_id == opened.admission_id
    assert current.status == "open"
    assert authority.accepted_release_binding(WORKSPACE, opened.admission_id) is None


def test_runtime_cannot_forge_release_rows_and_legitimate_path_survives(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, admin_url = hardening_database
    candidate_authority, opened, accept_request = _seed_open_candidate_with_evidence(
        settings, database
    )
    accepted = candidate_authority.accept(accept_request)
    assert accepted.status == "accepted"

    with _runtime_login_url(admin_url, database) as runtime_url:
        runtime_settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=runtime_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            ),
            candidate_admission=CandidateAdmissionSettings(
                enabled=True,
                ttl_seconds=120,
            ),
        )
        db.reset_database_cache()
        assert release_authority_runtime_security_ready(runtime_settings) is True
        runtime_database = db.Database(runtime_url, connect_timeout=2)
        runtime_candidate = CandidateAdmissionAuthority(
            runtime_settings,
            database=runtime_database,
            schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
        ).open(
            _open_request("workspace-runtime-epoch"),
            admission_id="candidate-runtime-epoch",
        )
        with runtime_database.connect() as runtime_conn:
            runtime_epoch = runtime_conn.execute(
                """
                SELECT paper_authority_epoch
                FROM quant_system.agent_v02_candidate_admissions
                WHERE admission_id = %s
                """,
                (runtime_candidate.admission_id,),
            ).fetchone()
        assert runtime_epoch is not None
        assert int(runtime_epoch[0]) > 0
        release_authority = ReleaseAuthority(
            runtime_settings,
            database=runtime_database,
            schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
        )
        stamp_receipt = release_authority.create_release_stamp(
            _release_request(WORKSPACE),
            now=datetime.now(UTC) + timedelta(seconds=1),
            stamp_id="release-stamp-1",
        )
        stamp = release_authority.active_release_stamp(WORKSPACE)
        assert stamp is not None
        assert stamp.candidate_admission_id == opened.admission_id
        assert stamp.paper_authority_epoch is not None

        with psycopg.connect(runtime_url, autocommit=True) as runtime_conn:
            with pytest.raises(
                psycopg.errors.InsufficientPrivilege,
                match="permission denied",
            ):
                runtime_conn.execute(
                    """
                    INSERT INTO quant_system.agent_v02_release_stamps (
                        stamp_id,
                        owner_user_id,
                        workspace_id,
                        route,
                        platform_runtime_digest,
                        hqa_runtime_digest,
                        hermes_runtime_digest,
                        database_schema_fingerprint,
                        evidence_digest,
                        release_digest,
                        status,
                        opened_at
                    )
                    VALUES (
                        'forged-stamp', %s, %s, '/hermes',
                        %s, %s, %s, %s, %s, %s, 'active', %s
                    )
                    """,
                    (
                        ROOT_USER_ID,
                        WORKSPACE,
                        PLATFORM,
                        HQA,
                        HERMES,
                        SCHEMA_DIGEST,
                        FINAL_EVIDENCE,
                        "c" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                    ),
                )

            with pytest.raises(
                psycopg.errors.RaiseException,
                match="exact current accepted candidate binding",
            ):
                runtime_conn.execute(
                    """
                    SELECT quant_system.insert_agent_v02_release_stamp(
                        'forged-stamp-binding', %s, '/hermes',
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        WORKSPACE,
                        PLATFORM,
                        HQA,
                        HERMES,
                        SCHEMA_DIGEST,
                        FINAL_EVIDENCE,
                        "c" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                        stamp.candidate_admission_id,
                        stamp.candidate_admission_digest,
                        "f" * 64,
                        stamp.evidence_set_id,
                        stamp.evidence_set_digest,
                        stamp.final_order_snapshot_digest,
                        stamp.paper_authority_epoch,
                    ),
                )

            with pytest.raises(
                psycopg.errors.RaiseException,
                match="digest does not match its canonical binding",
            ):
                runtime_conn.execute(
                    """
                    SELECT quant_system.insert_agent_v02_release_stamp(
                        'forged-stamp-digest', %s, '/hermes',
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        WORKSPACE,
                        PLATFORM,
                        HQA,
                        HERMES,
                        SCHEMA_DIGEST,
                        FINAL_EVIDENCE,
                        "c" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                        stamp.candidate_admission_id,
                        stamp.candidate_admission_digest,
                        stamp.candidate_acceptance_digest,
                        stamp.evidence_set_id,
                        stamp.evidence_set_digest,
                        stamp.final_order_snapshot_digest,
                        stamp.paper_authority_epoch,
                    ),
                )

            with pytest.raises(
                psycopg.errors.InsufficientPrivilege,
                match="permission denied",
            ):
                runtime_conn.execute(
                    """
                    INSERT INTO quant_system.agent_v02_public_cutovers (
                        cutover_id,
                        stamp_id,
                        owner_user_id,
                        workspace_id,
                        route,
                        release_digest,
                        cutover_digest,
                        status,
                        opened_at
                    )
                    VALUES (
                        'forged-cutover', %s, %s, %s, '/hermes',
                        %s, %s, 'open', %s
                    )
                    """,
                    (
                        stamp.stamp_id,
                        ROOT_USER_ID,
                        WORKSPACE,
                        stamp.release_digest,
                        "d" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                    ),
                )

            with pytest.raises(
                psycopg.errors.RaiseException,
                match="exact current active release stamp",
            ):
                runtime_conn.execute(
                    """
                    SELECT quant_system.insert_agent_v02_public_cutover(
                        'forged-cutover-binding', %s, %s, '/hermes',
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        stamp.stamp_id,
                        WORKSPACE,
                        stamp.release_digest,
                        "d" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                        stamp.candidate_admission_id,
                        stamp.candidate_admission_digest,
                        stamp.candidate_acceptance_digest,
                        stamp.evidence_set_id,
                        "e" * 64,
                        stamp.final_order_snapshot_digest,
                        stamp.paper_authority_epoch,
                    ),
                )

            with pytest.raises(
                psycopg.errors.RaiseException,
                match="digest does not match its canonical binding",
            ):
                runtime_conn.execute(
                    """
                    SELECT quant_system.insert_agent_v02_public_cutover(
                        'forged-cutover-digest', %s, %s, '/hermes',
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        stamp.stamp_id,
                        WORKSPACE,
                        stamp.release_digest,
                        "d" * 64,
                        datetime.now(UTC) + timedelta(seconds=2),
                        stamp.candidate_admission_id,
                        stamp.candidate_admission_digest,
                        stamp.candidate_acceptance_digest,
                        stamp.evidence_set_id,
                        stamp.evidence_set_digest,
                        stamp.final_order_snapshot_digest,
                        stamp.paper_authority_epoch,
                    ),
                )
        cutover = release_authority.create_public_cutover(
            _cutover_request(
                WORKSPACE,
                stamp_id=stamp.stamp_id,
                release_digest=stamp_receipt.resource_digest,
            ),
            now=datetime.now(UTC) + timedelta(seconds=3),
            cutover_id="public-cutover-1",
        )
        db.reset_database_cache()

    assert cutover.status == "open"


def test_paper_mutation_after_cutover_closes_effective_release_gate(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _url = hardening_database
    candidate_authority, opened, accept_request = _seed_open_candidate_with_evidence(
        settings, database
    )
    candidate_authority.accept(accept_request)
    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp_receipt = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-stamp-gate",
    )
    release_authority.create_public_cutover(
        _cutover_request(
            WORKSPACE,
            stamp_id=stamp_receipt.resource_id,
            release_digest=stamp_receipt.resource_digest,
        ),
        now=datetime.now(UTC) + timedelta(seconds=2),
        cutover_id="public-cutover-gate",
    )
    evidence_binding = candidate_authority.accepted_release_binding(
        WORKSPACE,
        opened.admission_id,
    )
    assert evidence_binding is not None
    observed_at = datetime.now(UTC)
    gate = EffectiveReleaseGate(
        authority=release_authority,
        local_flags_probe=lambda: LocalReleaseFlags(
            mutation_enabled=True,
            composer_open=True,
            hermes_gateway_enabled=True,
            kill_switch_enabled=True,
            live_trading_enabled=False,
            candidate_admission_enabled=True,
        ),
        runtime_identity_probe=lambda: RuntimeIdentityObservation(
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
        ),
        database_schema_fingerprint_probe=lambda: SCHEMA_DIGEST,
        release_evidence_probe=lambda: ReleaseEvidenceObservation(
            digest=FINAL_EVIDENCE,
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
            contract="agent-v0.2-release-evidence/v4",
            candidate_admission_id=opened.admission_id,
            candidate_admission_digest=opened.admission_digest,
            evidence_set_id=evidence_binding.evidence_set_id,
            evidence_set_digest=evidence_binding.evidence_set_digest,
            final_order_snapshot_digest=ORDERS,
        ),
        runtime_role_readiness_probe=lambda: True,
        authority_schema_readiness_probe=lambda: True,
        hermes_capability_probe=lambda: _capabilities(observed_at),
        now=lambda: observed_at,
    )
    assert gate.evaluate(WORKSPACE).ready is True

    with database.connect() as conn:
        _insert_paper_account(conn, account_id="paper-after-cutover")

    decision = gate.evaluate(WORKSPACE)
    assert decision.ready is False
    assert "accepted_candidate_binding_unavailable" in decision.blockers
    assert release_authority.active_release_stamp(WORKSPACE) is not None
    assert release_authority.open_public_cutover(WORKSPACE) is not None


def test_concurrent_cutover_and_paper_mutation_finishes_fail_closed(
    hardening_database: tuple[Settings, db.Database, str],
) -> None:
    settings, database, _url = hardening_database
    candidate_authority, opened, accept_request = _seed_open_candidate_with_evidence(
        settings, database
    )
    candidate_authority.accept(accept_request)
    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=lambda _database: SCHEMA_DIGEST,
    )
    stamp = release_authority.create_release_stamp(
        _release_request(WORKSPACE),
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id="release-stamp-race",
    )
    attempt_started = Event()

    def attempt_cutover() -> bool:
        attempt_started.set()
        try:
            release_authority.create_public_cutover(
                _cutover_request(
                    WORKSPACE,
                    stamp_id=stamp.resource_id,
                    release_digest=stamp.resource_digest,
                ),
                now=datetime.now(UTC) + timedelta(seconds=2),
                cutover_id="public-cutover-race",
            )
        except ReleaseAuthorityUnavailable:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        with database.connect() as paper_conn, paper_conn.transaction():
            _insert_paper_account(
                paper_conn,
                account_id="paper-cutover-race",
            )
            cutover = executor.submit(attempt_cutover)
            assert attempt_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                cutover.result(timeout=0.25)
        cutover_succeeded = cutover.result(timeout=5)

    assert (
        candidate_authority.accepted_release_binding(
            WORKSPACE,
            opened.admission_id,
        )
        is None
    )
    assert cutover_succeeded is False
    assert release_authority.open_public_cutover(WORKSPACE) is None
