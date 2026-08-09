from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.dark_identity_profile import PROVIDER_POLICY_DIGEST
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisioner,
    ManagedSessionProvisionError,
    ManagedSessionProvisionReceipt,
)
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    get_workspace_session,
    register_workspace_session,
    require_web_writable_session,
)
from quant_system.storage import database as db
from tests.postgres_reset import truncate_with_fk_dependents

pytestmark = pytest.mark.pg

ACTION_DIGEST = "a" * 64
SESSION_ID = f"web_{ACTION_DIGEST[:40]}"
FORK_ACTION_DIGEST = "b" * 64
FORK_SESSION_ID = f"web_{FORK_ACTION_DIGEST[:40]}"


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


def _settings() -> Settings:
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


def _reset_sessions(database: db.Database) -> None:
    truncate_with_fk_dependents(
        database,
        ("quant_system.hermes_workspace_sessions",),
        restart_identity=False,
    )


@dataclass
class RecordingPort:
    ensure_calls: list[tuple[str, str]] = field(default_factory=list)

    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        self.ensure_calls.append((session_id, action_digest))
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=True,
            recovered=False,
        )

    def fork_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise AssertionError("root provisioning must not fork")


@dataclass
class ForkRecordingPort:
    calls: list[tuple[str, str, str, str]] = field(default_factory=list)
    receipt_source_override: str | None = None

    def ensure_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise AssertionError("fork provisioning must not ensure a root")

    def fork_session(
        self,
        *,
        source_session_id: str,
        session_id: str,
        fork_point: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        self.calls.append((source_session_id, session_id, fork_point, action_digest))
        receipt_source = self.receipt_source_override or source_session_id
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=True,
            recovered=False,
            source_session_id=receipt_source,
            resolved_source_session_id=receipt_source,
            fork_point=fork_point,
            preserve_source=True,
        )


@dataclass
class AckLossPort:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        self.calls.append((session_id, action_digest))
        if len(self.calls) == 1:
            raise ManagedSessionProvisionError(
                "session_cli_timeout",
                retryable=True,
            )
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=False,
            recovered=True,
        )

    def fork_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise AssertionError("root provisioning must not fork")


class SimulatedWorkerCrash(BaseException):
    pass


class CrashingPort:
    def ensure_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise SimulatedWorkerCrash

    def fork_session(self, **_kwargs) -> ManagedSessionProvisionReceipt:
        raise AssertionError("root provisioning must not fork")


def test_registered_root_is_not_writable_until_exact_receipt_is_durable() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)
    port = RecordingPort()

    try:
        registered, created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="wm-provision-root",
                hermes_session_id=SESSION_ID,
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="provision-root",
                creation_action_digest=ACTION_DIGEST,
            ),
        )
        assert created is True
        assert registered.provisioning_state == "pending"
        assert registered.web_writable is False

        with (
            pytest.raises(psycopg.errors.RaiseException, match="lease/CAS"),
            database.connect() as conn,
        ):
            conn.execute(
                """
                UPDATE quant_system.hermes_workspace_sessions
                SET provision_state = 'ready',
                    provision_version = provision_version + 1,
                    provisioning_receipt_digest = %s,
                    provisioned_at = %s
                WHERE platform_session_id = %s
                """,
                (
                    "f" * 64,
                    datetime.now(UTC),
                    "wm-provision-root",
                ),
            )

        result = ManagedSessionProvisioner(
            settings=settings,
            port=port,
            lease_seconds=30,
        ).provision_next(worker_id="provisioner-1", now=datetime.now(UTC))

        assert result.outcome == "ready"
        assert result.platform_session_id == "wm-provision-root"
        assert port.ensure_calls == [(SESSION_ID, ACTION_DIGEST)]
        db.reset_database_cache()
        persisted = get_workspace_session(
            settings,
            platform_session_id="wm-provision-root",
        )
        assert persisted.provisioning_state == "ready"
        assert persisted.provisioning_receipt_digest is not None
        assert (
            require_web_writable_session(
                settings,
                platform_session_id="wm-provision-root",
            ).hermes_session_id
            == SESSION_ID
        )
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_fork_binds_real_parent_session_and_exact_message_point() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)
    port = ForkRecordingPort()

    try:
        parent, _ = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="external-discord-parent",
                hermes_session_id="discord-session-real-42",
                workspace_id="workspace-root",
                kind="observed_external_session",
                source_channel="discord",
            ),
        )
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="wm-provision-fork",
                hermes_session_id=FORK_SESSION_ID,
                workspace_id="workspace-root",
                kind="web_managed_session",
                source_channel="discord",
                parent_platform_session_id=parent.platform_session_id,
                fork_point="message:42",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="provision-fork",
                creation_action_digest=FORK_ACTION_DIGEST,
            ),
        )

        result = ManagedSessionProvisioner(
            settings=settings,
            port=port,
        ).provision_next(worker_id="provisioner-fork", now=datetime.now(UTC))

        assert result.outcome == "ready"
        assert port.calls == [
            (
                "discord-session-real-42",
                FORK_SESSION_ID,
                "message:42",
                FORK_ACTION_DIGEST,
            )
        ]
        ready = get_workspace_session(
            settings,
            platform_session_id="wm-provision-fork",
        )
        assert ready.provisioning_state == "ready"
        assert ready.parent_platform_session_id == parent.platform_session_id
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_fork_rejects_self_consistent_receipt_for_the_wrong_parent() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)
    port = ForkRecordingPort(receipt_source_override="discord-session-substituted")

    try:
        parent, _ = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="external-parent-for-mismatch",
                hermes_session_id="discord-session-real-parent",
                workspace_id="workspace-root",
                kind="observed_external_session",
                source_channel="discord",
            ),
        )
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="wm-provision-fork-mismatch",
                hermes_session_id=FORK_SESSION_ID,
                workspace_id="workspace-root",
                kind="web_managed_session",
                source_channel="discord",
                parent_platform_session_id=parent.platform_session_id,
                fork_point="message:7",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="provision-fork-mismatch",
                creation_action_digest=FORK_ACTION_DIGEST,
            ),
        )

        result = ManagedSessionProvisioner(
            settings=settings,
            port=port,
        ).provision_next(worker_id="provisioner-fork-mismatch")

        assert result.outcome == "failed"
        assert result.error_code == "session_fork_receipt_mismatch"
        failed = get_workspace_session(
            settings,
            platform_session_id="wm-provision-fork-mismatch",
        )
        assert failed.provisioning_state == "failed"
        assert failed.web_writable is False
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_ack_loss_retries_same_identity_and_binds_recovery_receipt() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)
    port = AckLossPort()
    start = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)

    try:
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="wm-provision-ack-loss",
                hermes_session_id=SESSION_ID,
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="provision-ack-loss",
                creation_action_digest=ACTION_DIGEST,
            ),
        )
        provisioner = ManagedSessionProvisioner(
            settings=settings,
            port=port,
            retry_delay_seconds=2,
        )

        unknown = provisioner.provision_next(
            worker_id="provisioner-ack-loss",
            now=start,
        )
        assert unknown.outcome == "retry_scheduled"
        assert unknown.error_code == "session_cli_timeout"
        pending_retry = get_workspace_session(
            settings,
            platform_session_id="wm-provision-ack-loss",
        )
        assert pending_retry.provisioning_state == "retryable"
        assert pending_retry.web_writable is False

        not_due = provisioner.provision_next(
            worker_id="provisioner-ack-loss",
            now=start + timedelta(seconds=1),
        )
        assert not_due.outcome == "idle"

        recovered = provisioner.provision_next(
            worker_id="provisioner-ack-loss",
            now=start + timedelta(seconds=2),
        )
        assert recovered.outcome == "ready"
        assert port.calls == [
            (SESSION_ID, ACTION_DIGEST),
            (SESSION_ID, ACTION_DIGEST),
        ]
        ready = get_workspace_session(
            settings,
            platform_session_id="wm-provision-ack-loss",
        )
        assert ready.provisioning_state == "ready"
        assert ready.provisioning_attempt_count == 2
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_expired_lease_is_reclaimed_after_worker_restart() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)
    start = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)

    try:
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="wm-provision-crash",
                hermes_session_id=SESSION_ID,
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="provision-crash",
                creation_action_digest=ACTION_DIGEST,
            ),
        )
        first_process = ManagedSessionProvisioner(
            settings=settings,
            port=CrashingPort(),
            lease_seconds=30,
        )
        with pytest.raises(SimulatedWorkerCrash):
            first_process.provision_next(
                worker_id="provisioner-before-crash",
                now=start,
            )

        leased = get_workspace_session(
            settings,
            platform_session_id="wm-provision-crash",
        )
        assert leased.provisioning_state == "leased"
        assert leased.provisioning_lease_owner == "provisioner-before-crash"

        replacement_port = RecordingPort()
        replacement = ManagedSessionProvisioner(
            settings=settings,
            port=replacement_port,
            lease_seconds=30,
        )
        before_expiry = replacement.provision_next(
            worker_id="provisioner-after-crash",
            now=start + timedelta(seconds=29),
        )
        assert before_expiry.outcome == "idle"

        recovered = replacement.provision_next(
            worker_id="provisioner-after-crash",
            now=start + timedelta(seconds=30),
        )
        assert recovered.outcome == "ready"
        persisted = get_workspace_session(
            settings,
            platform_session_id="wm-provision-crash",
        )
        assert persisted.provisioning_state == "ready"
        assert persisted.provisioning_attempt_count == 2
        assert persisted.provisioning_lease_owner is None
        assert persisted.provisioning_lease_token is None
    finally:
        _reset_sessions(database)
        db.reset_database_cache()
