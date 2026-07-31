from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import (
    ThreadPoolExecutor,
)
from concurrent.futures import (
    TimeoutError as FutureTimeoutError,
)
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from quant_system.config.settings import (
    CandidateAdmissionSettings,
    DatabaseSettings,
    PaperAccountSettings,
    Settings,
)
from quant_system.execution.account import DEFAULT_ACCOUNT_ID
from quant_system.hermes.candidate_admission_authority import (
    CandidateAdmissionAuthority,
    candidate_admission_schema_is_ready_on_connection,
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
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.storage import database as db
from quant_system.storage.database import list_migration_files
from tests import (
    test_agent_v02_migrations_025_026_postgres as migration_test_support,
)
from tests import test_release_authority_hardening as release_test_support
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

MIGRATION_028 = "028_agent_v02_candidate_paper_epoch_fence.sql"
THROUGH_027 = tuple(
    name
    for name in list_migration_files()
    if name[:3].isdigit() and int(name[:3]) <= 27
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
def _database(
    *,
    purpose: str,
    apply_028: bool,
) -> Iterator[tuple[Settings, db.Database]]:
    with isolated_test_database_url(_base_url(), purpose=purpose) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=THROUGH_027)
        if apply_028:
            db.run_migrations(database, only=(MIGRATION_028,))
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
        db.reset_database_cache()
        try:
            yield settings, database
        finally:
            db.reset_database_cache()


def _insert_frozen_root_account(
    database: db.Database,
    *,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> str:
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
                %s, %s, 'USD', 1000, 1000, 0, TRUE, 1,
                jsonb_build_object(
                    'account_id', %s::TEXT,
                    'kill_switch', TRUE
                ),
                %s, %s
            )
            """,
            (
                account_id,
                ROOT_USER_ID,
                account_id,
                observed_at,
                observed_at,
            ),
        )
    return account_id


def _insert_managed_session(
    database: db.Database,
    *,
    workspace_id: str,
    label: str,
) -> tuple[str, str | None]:
    token = uuid4().hex
    platform_session_id = f"wm-{label}-{token}"
    creation_digest = hashlib.sha256(platform_session_id.encode()).hexdigest()
    session, created = register_workspace_session(
        Settings(
            database=DatabaseSettings(
                enabled=True,
                url=database._url,  # noqa: SLF001 - isolated test seam
                auto_migrate=False,
                connect_timeout_seconds=2,
            )
        ),
        RegisterWorkspaceSession(
            platform_session_id=platform_session_id,
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id=workspace_id,
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id=f"create-{label}-{token}",
            creation_action_digest=creation_digest,
        ),
    )
    assert created is True
    return session.platform_session_id, session.candidate_admission_id


def test_028_metadata_replay_and_runtime_readiness() -> None:
    with _database(purpose="paperfencemeta", apply_028=False) as (
        _settings,
        database,
    ):
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )

        db.run_migrations(database, only=(MIGRATION_028,))
        db.run_migrations(database, only=(MIGRATION_028,))

        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT schema_version
                FROM quant_system.agent_v02_candidate_paper_fence_meta
                WHERE singleton IS TRUE
                """
            ).fetchone() == (1,)
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is True
            )
            assert conn.execute(
                """
                SELECT count(*)
                FROM pg_trigger AS trigger_record
                JOIN pg_class AS relation
                  ON relation.oid = trigger_record.tgrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'quant_system'
                  AND trigger_record.tgname IN (
                      'trg_hermes_session_candidate_binding',
                      'trg_hermes_command_candidate_binding'
                  )
                  AND trigger_record.tgenabled = 'A'
                  AND trigger_record.tgtype = 23
                  AND NOT trigger_record.tgisinternal
                """
            ).fetchone() == (2,)


def test_readiness_rejects_and_replay_repairs_marker_acl_drift() -> None:
    with _database(purpose="paperfenceacl", apply_028=True) as (
        _settings,
        database,
    ):
        with database.connect() as conn:
            assert candidate_admission_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                GRANT UPDATE ON TABLE
                    quant_system.agent_v02_candidate_paper_fence_meta
                TO quant_runtime
                """
            )
            assert candidate_admission_schema_is_ready_on_connection(conn) is False

        db.run_migrations(database, only=(MIGRATION_028,))
        with database.connect() as conn:
            assert candidate_admission_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                GRANT SELECT ON TABLE
                    quant_system.agent_v02_candidate_paper_fence_meta
                TO quant
                """
            )
            assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_readiness_rejects_constraint_owner_and_future_version_drift() -> None:
    with _database(purpose="paperfencetamper", apply_028=True) as (
        _settings,
        database,
    ):
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.paper_accounts
                    DROP CONSTRAINT
                        ck_agent_v02_default_paper_account_raw_consistency
                """
            )
            assert candidate_admission_schema_is_ready_on_connection(conn) is False

        db.run_migrations(database, only=(MIGRATION_028,))
        with database.connect() as conn:
            assert candidate_admission_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                ALTER TABLE
                    quant_system.agent_v02_candidate_paper_fence_meta
                OWNER TO quant
                """
            )
            assert candidate_admission_schema_is_ready_on_connection(conn) is False

        db.run_migrations(database, only=(MIGRATION_028,))
        with database.connect() as conn:
            assert candidate_admission_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                UPDATE quant_system.agent_v02_candidate_paper_fence_meta
                SET schema_version = 2
                WHERE singleton IS TRUE
                """
            )
            assert candidate_admission_schema_is_ready_on_connection(conn) is False

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="newer than this binary supports",
        ):
            db.run_migrations(database, only=(MIGRATION_028,))


def test_readiness_rejects_paper_epoch_trigger_and_helper_tamper() -> None:
    with _database(purpose="paperfenceepochbind", apply_028=True) as (
        _settings,
        database,
    ), database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
                ALTER TABLE quant_system.paper_accounts
                    DISABLE TRIGGER
                        trg_agent_v02_paper_epoch_paper_accounts
                """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False
        conn.execute(
            """
                ALTER TABLE quant_system.paper_accounts
                    ENABLE ALWAYS TRIGGER
                        trg_agent_v02_paper_epoch_paper_accounts
                """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
                CREATE OR REPLACE FUNCTION
                    quant_system.bump_agent_v02_paper_authority_epoch()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                VOLATILE
                SECURITY DEFINER
                SET search_path = pg_catalog
                AS $$
                BEGIN
                    RETURN COALESCE(NEW, OLD);
                END;
                $$
                """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_readiness_rejects_current_epoch_helper_tamper() -> None:
    with _database(purpose="paperfencecurrenthelper", apply_028=True) as (
        _settings,
        database,
    ), database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION
                quant_system.current_agent_v02_paper_authority_epoch(
                    requested_owner UUID,
                    requested_workspace TEXT
                )
            RETURNS BIGINT
            LANGUAGE plpgsql
            VOLATILE
            SECURITY DEFINER
            SET search_path = pg_catalog
            AS $$
            BEGIN
                RETURN NULL;
            END;
            $$
            """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_readiness_rejects_paper_epoch_trigger_wrong_target() -> None:
    with _database(purpose="paperfencewrongtrigger", apply_028=True) as (
        _settings,
        database,
    ), database.connect() as conn:
        assert candidate_admission_schema_is_ready_on_connection(conn) is True
        conn.execute(
            """
            DROP TRIGGER
                trg_agent_v02_paper_epoch_paper_positions_current
            ON quant_system.paper_positions_current
            """
        )
        conn.execute(
            """
            CREATE TRIGGER
                trg_agent_v02_paper_epoch_paper_positions_current
            BEFORE INSERT OR UPDATE OR DELETE
            ON quant_system.paper_pending_orders
            FOR EACH ROW
            EXECUTE FUNCTION
                quant_system.bump_agent_v02_paper_authority_epoch()
            """
        )
        conn.execute(
            """
            ALTER TABLE quant_system.paper_pending_orders
                ENABLE ALWAYS TRIGGER
                    trg_agent_v02_paper_epoch_paper_positions_current
            """
        )
        assert candidate_admission_schema_is_ready_on_connection(conn) is False


def test_028_rejects_missing_027_predecessor() -> None:
    with isolated_test_database_url(
        _base_url(),
        purpose="paperfencepre27",
    ) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=THROUGH_027[:-1])

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="requires migrations 020 and 027",
        ):
            db.run_migrations(database, only=(MIGRATION_028,))


@pytest.mark.parametrize(
    "raw_payload",
    (
        '{"account_id":"not-default","kill_switch":true}',
        '{"account_id":"default","kill_switch":"true"}',
        '{"account_id":"default","kill_switch":false}',
    ),
)
def test_028_constraint_rejects_default_account_raw_drift(
    raw_payload: str,
) -> None:
    with _database(purpose="paperfenceraw", apply_028=True) as (
        _settings,
        database,
    ):
        observed_at = datetime.now(UTC)
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="ck_agent_v02_default_paper_account_raw_consistency",
        ), database.connect() as conn:
            conn.execute(
                """
                    INSERT INTO quant_system.paper_accounts (
                        account_id, owner_user_id, base_currency,
                        initial_cash, cash, realized_pnl, kill_switch,
                        version, raw, created_at, updated_at
                    )
                    VALUES (
                        %s, %s, 'USD', 1000, 1000, 0, TRUE, 1,
                        %s::jsonb,
                        %s, %s
                    )
                    """,
                (
                    DEFAULT_ACCOUNT_ID,
                    ROOT_USER_ID,
                    raw_payload,
                    observed_at,
                    observed_at,
                ),
            )


def test_active_requires_exactly_one_canonical_default_root_account() -> None:
    with _database(purpose="paperfencecanonical", apply_028=True) as (
        settings,
        database,
    ):
        authority = CandidateAdmissionAuthority(
            settings,
            database=database,
            schema_fingerprint_reader=(
                lambda _database: release_test_support.SCHEMA_DIGEST
            ),
        )
        empty_workspace = f"paper-fence-empty-{uuid4().hex}"
        authority.open(
            release_test_support._open_request(  # noqa: SLF001
                empty_workspace,
                generation="paper-fence-empty",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )
        assert authority.active(empty_workspace) is None
        with pytest.raises(Exception) as empty_session_error:
            _insert_managed_session(
                database,
                workspace_id=empty_workspace,
                label="empty-root-authority",
            )
        assert empty_session_error.value.__cause__ is not None
        assert (
            "candidate paper authority epoch is stale"
            in str(empty_session_error.value.__cause__)
        )

        _insert_frozen_root_account(database)
        _insert_frozen_root_account(
            database,
            account_id=f"paper-root-extra-{uuid4().hex}",
        )
        duplicate_workspace = f"paper-fence-duplicate-{uuid4().hex}"
        authority.open(
            release_test_support._open_request(  # noqa: SLF001
                duplicate_workspace,
                generation="paper-fence-duplicate",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )
        assert authority.active(duplicate_workspace) is None
        with pytest.raises(Exception) as duplicate_session_error:
            _insert_managed_session(
                database,
                workspace_id=duplicate_workspace,
                label="duplicate-root-authority",
            )
        assert duplicate_session_error.value.__cause__ is not None
        assert (
            "candidate paper authority epoch is stale"
            in str(duplicate_session_error.value.__cause__)
        )


def test_stale_open_candidate_rejects_new_session_and_old_session_command() -> None:
    with _database(purpose="paperfencewrites", apply_028=True) as (
        settings,
        database,
    ):
        account_id = _insert_frozen_root_account(database)
        workspace_id = f"paper-fence-{uuid4().hex}"
        authority = CandidateAdmissionAuthority(
            settings,
            database=database,
            schema_fingerprint_reader=(
                lambda _database: release_test_support.SCHEMA_DIGEST
            ),
        )
        opened = authority.open(
            release_test_support._open_request(  # noqa: SLF001
                workspace_id,
                generation="paper-fence",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )
        old_session_id, old_binding = _insert_managed_session(
            database,
            workspace_id=workspace_id,
            label="before-epoch-bump",
        )
        assert old_binding == opened.admission_id

        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.paper_accounts
                SET kill_switch = FALSE,
                    raw = raw || '{"kill_switch": false}'::jsonb,
                    updated_at = clock_timestamp()
                WHERE account_id = %s
                """,
                (account_id,),
            )

        assert authority.active(workspace_id) is None
        with pytest.raises(Exception) as session_error:
            _insert_managed_session(
                database,
                workspace_id=workspace_id,
                label="after-epoch-bump",
            )
        assert session_error.value.__cause__ is not None
        assert (
            "candidate paper authority epoch is stale"
            in str(session_error.value.__cause__)
        )

        client_request_id = f"stale-turn-{uuid4().hex}"
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="candidate paper authority epoch is stale",
        ):
            HermesCommandLedger(settings).create_command(
                platform_session_id=old_session_id,
                client_request_id=client_request_id,
                kind="conversation_turn",
                canonical_request_digest="9" * 64,
                payload_ref=f"platform-payload://sha256/{'a' * 64}",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
            )

        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_workspace_sessions
                WHERE workspace_id = %s
                  AND candidate_admission_id IS NULL
                  AND kind = 'web_managed_session'
                """,
                (workspace_id,),
            ).fetchone() == (0,)
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_commands
                WHERE client_request_id = %s
                """,
                (client_request_id,),
            ).fetchone() == (0,)


def test_pure_epoch_change_rejects_candidate_writes_while_account_stays_frozen() -> None:
    with _database(purpose="paperfencepureepoch", apply_028=True) as (
        settings,
        database,
    ):
        _insert_frozen_root_account(database)
        workspace_id = f"paper-fence-pure-epoch-{uuid4().hex}"
        authority = CandidateAdmissionAuthority(
            settings,
            database=database,
            schema_fingerprint_reader=(
                lambda _database: release_test_support.SCHEMA_DIGEST
            ),
        )
        opened = authority.open(
            release_test_support._open_request(  # noqa: SLF001
                workspace_id,
                generation="paper-fence-pure-epoch",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )
        old_session_id, old_binding = _insert_managed_session(
            database,
            workspace_id=workspace_id,
            label="before-pure-epoch-bump",
        )
        assert old_binding == opened.admission_id

        with database.connect() as conn:
            conn.execute(
                """
                SELECT quant_system.bump_agent_v02_paper_authority_owner(%s)
                """,
                (ROOT_USER_ID,),
            )
            assert conn.execute(
                """
                SELECT
                    kill_switch,
                    raw -> 'account_id' = to_jsonb(account_id),
                    raw -> 'kill_switch' = to_jsonb(kill_switch)
                FROM quant_system.paper_accounts
                WHERE account_id = %s
                """,
                (DEFAULT_ACCOUNT_ID,),
            ).fetchone() == (True, True, True)

        assert authority.active(workspace_id) is None
        with pytest.raises(Exception) as session_error:
            _insert_managed_session(
                database,
                workspace_id=workspace_id,
                label="after-pure-epoch-bump",
            )
        assert session_error.value.__cause__ is not None
        assert (
            "candidate paper authority epoch is stale"
            in str(session_error.value.__cause__)
        )

        client_request_id = f"pure-epoch-turn-{uuid4().hex}"
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="candidate paper authority epoch is stale",
        ):
            HermesCommandLedger(settings).create_command(
                platform_session_id=old_session_id,
                client_request_id=client_request_id,
                kind="conversation_turn",
                canonical_request_digest="7" * 64,
                payload_ref=f"platform-payload://sha256/{'8' * 64}",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
            )


def test_concurrent_pure_epoch_bump_serializes_candidate_session_insert() -> None:
    with _database(purpose="paperfenceepochrace", apply_028=True) as (
        settings,
        database,
    ):
        _insert_frozen_root_account(database)
        workspace_id = f"paper-fence-epoch-race-{uuid4().hex}"
        authority = CandidateAdmissionAuthority(
            settings,
            database=database,
            schema_fingerprint_reader=(
                lambda _database: release_test_support.SCHEMA_DIGEST
            ),
        )
        authority.open(
            release_test_support._open_request(  # noqa: SLF001
                workspace_id,
                generation="paper-fence-epoch-race",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )
        insert_started = Event()

        def insert_session() -> str:
            insert_started.set()
            try:
                _insert_managed_session(
                    database,
                    workspace_id=workspace_id,
                    label="concurrent-pure-epoch",
                )
            except Exception as exc:  # noqa: BLE001 - exact database cause returned
                return str(exc.__cause__ or exc)
            return "accepted"

        with ThreadPoolExecutor(max_workers=1) as executor:
            with database.connect() as mutation_conn, mutation_conn.transaction():
                mutation_conn.execute(
                    """
                    SELECT quant_system.bump_agent_v02_paper_authority_owner(%s)
                    """,
                    (ROOT_USER_ID,),
                )
                future = executor.submit(insert_session)
                assert insert_started.wait(timeout=2)
                with pytest.raises(FutureTimeoutError):
                    future.result(timeout=0.25)
            outcome = future.result(timeout=5)

        assert "candidate paper authority epoch is stale" in outcome
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_workspace_sessions
                WHERE workspace_id = %s
                  AND kind = 'web_managed_session'
                """,
                (workspace_id,),
            ).fetchone() == (0,)


def test_028_preserves_exact_accepted_release_session_binding() -> None:
    with _database(purpose="paperfencerelease", apply_028=True) as (
        settings,
        database,
    ):
        _insert_frozen_root_account(database)
        workspace_id = f"paper-fence-release-{uuid4().hex}"
        admission_id = migration_test_support._open_exact_release(  # noqa: SLF001
            settings,
            database,
            workspace_id=workspace_id,
        )

        session_id, binding = _insert_managed_session(
            database,
            workspace_id=workspace_id,
            label="accepted-release",
        )

        assert binding == admission_id
        command = HermesCommandLedger(settings).create_command(
            platform_session_id=session_id,
            client_request_id=f"released-turn-{uuid4().hex}",
            kind="conversation_turn",
            canonical_request_digest="5" * 64,
            payload_ref=f"platform-payload://sha256/{'6' * 64}",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
        )
        assert command.created is True
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT candidate_admission_id
                FROM quant_system.hermes_commands
                WHERE command_id = %s
                """,
                (command.command.command_id,),
            ).fetchone() == (None,)


def test_effective_paper_safety_is_readable_by_constrained_runtime_role() -> None:
    with _database(purpose="paperfenceruntime", apply_028=True) as (
        settings,
        database,
    ):
        _insert_frozen_root_account(database)
        workspace_id = f"paper-fence-runtime-{uuid4().hex}"
        authority = CandidateAdmissionAuthority(
            settings,
            database=database,
            schema_fingerprint_reader=(
                lambda _database: release_test_support.SCHEMA_DIGEST
            ),
        )
        authority.open(
            release_test_support._open_request(  # noqa: SLF001
                workspace_id,
                generation="paper-fence-runtime",
            ),
            admission_id=f"candidate-{uuid4().hex}",
        )

        with release_test_support._runtime_login_url(  # noqa: SLF001
            database._url,  # noqa: SLF001
            database,
        ) as runtime_url:
            runtime_settings = Settings(
                database=DatabaseSettings(
                    enabled=True,
                    url=runtime_url,
                    auto_migrate=False,
                    connect_timeout_seconds=2,
                ),
                paper_account=PaperAccountSettings(db_mode="canonical"),
            )
            db.reset_database_cache()
            observation = PaperSafetyAuthority(runtime_settings).observe(
                workspace_id
            )

        assert observation.canonical_account_count == 1
        assert observation.canonical_account_frozen is True
        assert observation.current_paper_authority_epoch is not None
        assert observation.blockers == ()
        assert observation.effective is True
