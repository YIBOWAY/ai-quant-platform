from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
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
    CandidateAdmissionReceipt,
    CandidateAdmissionUnavailable,
    OpenCandidateAdmissionRequest,
    canonical_candidate_action_digest,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
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
    ReleaseAuthorityUnavailable,
    canonical_release_action_digest,
    release_authority_runtime_security_ready,
    release_authority_schema_is_ready_on_connection,
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
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
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
        yield settings, database, isolated_url


def _open_request(workspace_id: str) -> OpenCandidateAdmissionRequest:
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
        client_action_id=f"open-{workspace_id}",
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


def _seed_open_candidate_with_evidence(
    settings: Settings,
    database: db.Database,
    *,
    workspace_id: str = WORKSPACE,
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
    token = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
    opened = authority.open(
        _open_request(workspace_id),
        admission_id=f"candidate-{token[:16]}",
    )
    evidence_digest = hashlib.sha256(f"evidence\0{workspace_id}".encode()).hexdigest()
    evidence_set_id = f"evidence-{token[:16]}"
    facts = json.dumps(
        {"contract": "agent-v0.2-candidate-evidence-facts/v1"},
        separators=(",", ":"),
        sort_keys=True,
    )
    with database.connect() as conn, conn.transaction():
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
