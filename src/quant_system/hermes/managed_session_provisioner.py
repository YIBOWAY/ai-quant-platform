"""Durable provisioning for exact Hermes-managed Web sessions.

The session registry reserves identity; this module is the only transition
from that reservation to ``ready``.  It leases one row, closes the database
transaction, calls HQA's loopback-only CLI, validates the exact receipt, then
CAS-binds the receipt in a new transaction.  It never creates Runs, calls a
provider, or carries a prompt/trading instruction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.run_lifecycle_port import HermesRunCliSettings
from quant_system.hermes.session_registry import (
    _SELECT_COLUMNS,
    WorkspaceSessionRecord,
    _row_to_record,
    session_registry_schema_is_ready_on_connection,
)
from quant_system.storage.database import (
    SCHEMA,
    DatabaseUnavailable,
    get_database,
)

_ACTION_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SESSION_ID_RE = re.compile(r"^web_[0-9a-f]{40}$")
_HERMES_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_FORK_POINT_RE = re.compile(r"^message:[1-9][0-9]*$")
_ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_STDIN_LIMIT = 65_536
_STDOUT_LIMIT = 1_048_576


class ManagedSessionProvisionError(RuntimeError):
    """Secret-free structured failure at the provisioning seam."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("managed Hermes Session provisioning failed")
        self.code = code if _ERROR_CODE_RE.fullmatch(code) else "session_provision_failed"
        self.retryable = retryable


@dataclass(frozen=True)
class ManagedSessionProvisionReceipt:
    session_id: str
    action_digest: str
    created: bool
    recovered: bool
    source_session_id: str | None = None
    resolved_source_session_id: str | None = None
    fork_point: str | None = None
    preserve_source: bool | None = None


class ManagedSessionProvisionPort(Protocol):
    """HQA/Hermes mutation seam; implementations must be replay-safe."""

    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt: ...

    def fork_session(
        self,
        *,
        source_session_id: str,
        session_id: str,
        fork_point: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt: ...


ProvisionOutcome = Literal[
    "idle",
    "ready",
    "retry_scheduled",
    "failed",
    "lease_lost",
    "unavailable",
]


@dataclass(frozen=True)
class ManagedSessionProvisionResult:
    outcome: ProvisionOutcome
    platform_session_id: str | None = None
    hermes_session_id: str | None = None
    error_code: str | None = None


@dataclass
class SubprocessManagedSessionProvisionPort:
    """Bounded JSON subprocess adapter for ``hqa.hermes_run_cli``."""

    cli_settings: HermesRunCliSettings
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        _validate_target_identity(
            session_id=session_id,
            action_digest=action_digest,
        )
        document = self._invoke(
            "session-ensure",
            {
                "action_digest": action_digest,
                "session_id": session_id,
            },
        )
        return _receipt_from_document(
            document,
            operation="session-ensure",
            session_id=session_id,
            action_digest=action_digest,
        )

    def fork_session(
        self,
        *,
        source_session_id: str,
        session_id: str,
        fork_point: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        _validate_target_identity(
            session_id=session_id,
            action_digest=action_digest,
        )
        if (
            not source_session_id
            or len(source_session_id) > 255
            or not source_session_id.isprintable()
            or _FORK_POINT_RE.fullmatch(fork_point) is None
        ):
            raise ManagedSessionProvisionError(
                "session_fork_request_invalid",
                retryable=False,
            )
        document = self._invoke(
            "session-fork",
            {
                "action_digest": action_digest,
                "source_session_id": source_session_id,
                "session_id": session_id,
                "fork_point": fork_point,
            },
        )
        return _receipt_from_document(
            document,
            operation="session-fork",
            session_id=session_id,
            action_digest=action_digest,
            source_session_id=source_session_id,
            fork_point=fork_point,
        )

    def _invoke(
        self,
        operation: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        if not python.is_file() or not hqa_root.is_dir():
            raise ManagedSessionProvisionError(
                "session_cli_unavailable",
                retryable=True,
            )
        document = {
            "endpoint": self.cli_settings.endpoint_document(),
            **dict(request),
        }
        try:
            raw = json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ManagedSessionProvisionError(
                "session_cli_request_invalid",
                retryable=False,
            ) from exc
        if not raw or len(raw) > _STDIN_LIMIT:
            raise ManagedSessionProvisionError(
                "session_cli_request_invalid",
                retryable=False,
            )

        env = os.environ.copy()
        root = str(hqa_root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = root if not existing else root + os.pathsep + existing
        argv = [str(python), "-m", "hqa.hermes_run_cli", operation]
        run = self.runner or subprocess.run
        try:
            completed = run(
                argv,
                input=raw,
                capture_output=True,
                timeout=self.cli_settings.timeout_seconds,
                check=False,
                cwd=root,
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ManagedSessionProvisionError(
                "session_cli_timeout",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ManagedSessionProvisionError(
                "session_cli_unavailable",
                retryable=True,
            ) from exc

        response = _parse_stdout(completed.stdout or b"")
        if completed.returncode != 0 or response.get("ok") is not True:
            error = response.get("error")
            if not isinstance(error, Mapping):
                raise ManagedSessionProvisionError(
                    "session_cli_failed",
                    retryable=True,
                )
            code = error.get("code")
            raise ManagedSessionProvisionError(
                str(code) if type(code) is str else "session_cli_failed",
                retryable=error.get("retryable") is True,
            )
        return response


@dataclass
class ManagedSessionProvisioner:
    """Lease, provision, and CAS-bind one exact managed Session per call."""

    settings: Settings
    port: ManagedSessionProvisionPort
    lease_seconds: int = 60
    retry_delay_seconds: int = 2
    max_retry_delay_seconds: int = 60
    max_attempts: int = 8

    def __post_init__(self) -> None:
        if not 1 <= self.lease_seconds <= 600:
            raise ValueError("lease_seconds must be in [1, 600]")
        if not 1 <= self.retry_delay_seconds <= self.max_retry_delay_seconds:
            raise ValueError("retry delay is invalid")
        if self.max_retry_delay_seconds > 3600:
            raise ValueError("max retry delay must be <= 3600")
        if not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be in [1, 100]")

    def provision_next(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> ManagedSessionProvisionResult:
        """Provision at most one due Session; safe to call from every worker cycle."""

        if _WORKER_ID_RE.fullmatch(worker_id) is None:
            raise ValueError("invalid provisioning worker_id")
        observed_now = _normalize_now(now)
        try:
            claimed = self._claim_next(worker_id=worker_id, now=observed_now)
        except (DatabaseUnavailable, psycopg.Error):
            return ManagedSessionProvisionResult(
                outcome="unavailable",
                error_code="session_registry_unavailable",
            )
        if claimed is None:
            return ManagedSessionProvisionResult(outcome="idle")

        try:
            receipt, expected_source_session_id = self._call_port(claimed)
            receipt_digest, resolved_source_session_id = _validate_and_digest_receipt(
                claimed,
                receipt,
                expected_source_session_id=expected_source_session_id,
            )
        except ManagedSessionProvisionError as exc:
            return self._record_failure(
                claimed,
                worker_id=worker_id,
                now=observed_now,
                error=exc,
            )
        except Exception:  # noqa: BLE001 - no external detail crosses this seam
            return self._record_failure(
                claimed,
                worker_id=worker_id,
                now=observed_now,
                error=ManagedSessionProvisionError(
                    "session_port_unhandled_error",
                    retryable=True,
                ),
            )

        try:
            ready = self._mark_ready(
                claimed,
                worker_id=worker_id,
                now=observed_now,
                receipt_digest=receipt_digest,
                resolved_source_session_id=resolved_source_session_id,
            )
        except (DatabaseUnavailable, psycopg.Error):
            return ManagedSessionProvisionResult(
                outcome="unavailable",
                platform_session_id=claimed.platform_session_id,
                hermes_session_id=claimed.hermes_session_id,
                error_code="session_registry_unavailable",
            )
        if ready is None:
            return ManagedSessionProvisionResult(
                outcome="lease_lost",
                platform_session_id=claimed.platform_session_id,
                hermes_session_id=claimed.hermes_session_id,
                error_code="session_provision_lease_lost",
            )
        return ManagedSessionProvisionResult(
            outcome="ready",
            platform_session_id=ready.platform_session_id,
            hermes_session_id=ready.hermes_session_id,
        )

    def _claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
    ) -> WorkspaceSessionRecord | None:
        database = get_database(self.settings)
        if database is None:
            raise DatabaseUnavailable("managed Session provisioning needs PostgreSQL")
        lease_token = uuid4()
        lease_until = now + timedelta(seconds=self.lease_seconds)
        with database.connect() as conn, conn.transaction():
            if not session_registry_schema_is_ready_on_connection(conn):
                raise DatabaseUnavailable("session provisioning schema is not ready")
            row = conn.execute(
                f"""
                WITH candidate AS (
                    SELECT session.platform_session_id
                    FROM {SCHEMA}.hermes_workspace_sessions AS session
                    LEFT JOIN {SCHEMA}.hermes_workspace_sessions AS parent
                      ON parent.platform_session_id =
                         session.parent_platform_session_id
                    WHERE session.owner_user_id = %s
                      AND session.kind = 'web_managed_session'
                      AND (
                            session.provision_state = 'pending'
                            OR (
                                session.provision_state = 'retryable'
                                AND session.provision_next_attempt_at <= %s
                            )
                            OR (
                                session.provision_state = 'leased'
                                AND session.provision_lease_until <= %s
                            )
                      )
                      AND (
                            session.parent_platform_session_id IS NULL
                            OR parent.kind = 'observed_external_session'
                            OR parent.provision_state = 'ready'
                      )
                    ORDER BY
                        COALESCE(
                            session.provision_next_attempt_at,
                            session.provision_lease_until,
                            session.created_at
                        ),
                        session.platform_session_id
                    FOR UPDATE OF session SKIP LOCKED
                    LIMIT 1
                )
                UPDATE {SCHEMA}.hermes_workspace_sessions AS session
                SET provision_state = 'leased',
                    provision_version = session.provision_version + 1,
                    provision_attempt_count =
                        session.provision_attempt_count + 1,
                    provision_lease_owner = %s,
                    provision_lease_token = %s,
                    provision_lease_until = %s,
                    provision_next_attempt_at = NULL,
                    provision_last_error_code = NULL,
                    provisioning_receipt_digest = NULL,
                    resolved_source_session_id = NULL,
                    provisioned_at = NULL
                FROM candidate
                WHERE session.platform_session_id =
                      candidate.platform_session_id
                RETURNING {_qualified_select_columns("session")}
                """,
                (
                    ROOT_USER_ID,
                    now,
                    now,
                    worker_id,
                    lease_token,
                    lease_until,
                ),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def _call_port(
        self,
        claimed: WorkspaceSessionRecord,
    ) -> tuple[ManagedSessionProvisionReceipt, str | None]:
        action_digest = claimed.creation_action_digest
        if action_digest is None:
            raise ManagedSessionProvisionError(
                "session_action_identity_missing",
                retryable=False,
            )
        _validate_target_identity(
            session_id=claimed.hermes_session_id,
            action_digest=action_digest,
        )
        if claimed.parent_platform_session_id is None:
            return (
                self.port.ensure_session(
                    session_id=claimed.hermes_session_id,
                    action_digest=action_digest,
                ),
                None,
            )

        if claimed.fork_point is None or _FORK_POINT_RE.fullmatch(claimed.fork_point) is None:
            raise ManagedSessionProvisionError(
                "session_fork_point_invalid",
                retryable=False,
            )
        parent = self._get_parent(claimed.parent_platform_session_id)
        return (
            self.port.fork_session(
                source_session_id=parent.hermes_session_id,
                session_id=claimed.hermes_session_id,
                fork_point=claimed.fork_point,
                action_digest=action_digest,
            ),
            parent.hermes_session_id,
        )

    def _get_parent(self, platform_session_id: str) -> WorkspaceSessionRecord:
        database = get_database(self.settings)
        if database is None:
            raise ManagedSessionProvisionError(
                "session_registry_unavailable",
                retryable=True,
            )
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE platform_session_id = %s
                      AND owner_user_id = %s
                    """,
                    (platform_session_id, ROOT_USER_ID),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ManagedSessionProvisionError(
                "session_registry_unavailable",
                retryable=True,
            ) from exc
        if row is None:
            raise ManagedSessionProvisionError(
                "session_parent_missing",
                retryable=False,
            )
        return _row_to_record(row)

    def _mark_ready(
        self,
        claimed: WorkspaceSessionRecord,
        *,
        worker_id: str,
        now: datetime,
        receipt_digest: str,
        resolved_source_session_id: str | None,
    ) -> WorkspaceSessionRecord | None:
        database = get_database(self.settings)
        if database is None:
            raise DatabaseUnavailable("managed Session provisioning needs PostgreSQL")
        with database.connect() as conn, conn.transaction():
            row = conn.execute(
                f"""
                UPDATE {SCHEMA}.hermes_workspace_sessions
                SET provision_state = 'ready',
                    provision_version = provision_version + 1,
                    provision_lease_owner = NULL,
                    provision_lease_token = NULL,
                    provision_lease_until = NULL,
                    provision_next_attempt_at = NULL,
                    provision_last_error_code = NULL,
                    provisioning_receipt_digest = %s,
                    resolved_source_session_id = %s,
                    provisioned_at = %s
                WHERE platform_session_id = %s
                  AND owner_user_id = %s
                  AND provision_state = 'leased'
                  AND provision_version = %s
                  AND provision_lease_owner = %s
                  AND provision_lease_token = %s
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    receipt_digest,
                    resolved_source_session_id,
                    now,
                    claimed.platform_session_id,
                    ROOT_USER_ID,
                    claimed.provisioning_version,
                    worker_id,
                    claimed.provisioning_lease_token,
                ),
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def _record_failure(
        self,
        claimed: WorkspaceSessionRecord,
        *,
        worker_id: str,
        now: datetime,
        error: ManagedSessionProvisionError,
    ) -> ManagedSessionProvisionResult:
        retryable = error.retryable and claimed.provisioning_attempt_count < self.max_attempts
        state = "retryable" if retryable else "failed"
        next_attempt = None
        if retryable:
            exponent = max(0, claimed.provisioning_attempt_count - 1)
            delay = min(
                self.retry_delay_seconds * (2**exponent),
                self.max_retry_delay_seconds,
            )
            next_attempt = now + timedelta(seconds=delay)
        try:
            database = get_database(self.settings)
            if database is None:
                raise DatabaseUnavailable("managed Session provisioning needs PostgreSQL")
            with database.connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_workspace_sessions
                    SET provision_state = %s,
                        provision_version = provision_version + 1,
                        provision_lease_owner = NULL,
                        provision_lease_token = NULL,
                        provision_lease_until = NULL,
                        provision_next_attempt_at = %s,
                        provision_last_error_code = %s,
                        provisioning_receipt_digest = NULL,
                        resolved_source_session_id = NULL,
                        provisioned_at = NULL
                    WHERE platform_session_id = %s
                      AND owner_user_id = %s
                      AND provision_state = 'leased'
                      AND provision_version = %s
                      AND provision_lease_owner = %s
                      AND provision_lease_token = %s
                    RETURNING platform_session_id
                    """,
                    (
                        state,
                        next_attempt,
                        error.code,
                        claimed.platform_session_id,
                        ROOT_USER_ID,
                        claimed.provisioning_version,
                        worker_id,
                        claimed.provisioning_lease_token,
                    ),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error):
            return ManagedSessionProvisionResult(
                outcome="unavailable",
                platform_session_id=claimed.platform_session_id,
                hermes_session_id=claimed.hermes_session_id,
                error_code="session_registry_unavailable",
            )
        if row is None:
            return ManagedSessionProvisionResult(
                outcome="lease_lost",
                platform_session_id=claimed.platform_session_id,
                hermes_session_id=claimed.hermes_session_id,
                error_code="session_provision_lease_lost",
            )
        return ManagedSessionProvisionResult(
            outcome="retry_scheduled" if retryable else "failed",
            platform_session_id=claimed.platform_session_id,
            hermes_session_id=claimed.hermes_session_id,
            error_code=error.code,
        )


def _qualified_select_columns(alias: str) -> str:
    return ",\n".join(
        f"{alias}.{column.strip()}" for column in _SELECT_COLUMNS.split(",") if column.strip()
    )


def _normalize_now(value: datetime | None) -> datetime:
    observed = value or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return observed.astimezone(UTC)


def _validate_target_identity(*, session_id: str, action_digest: str) -> None:
    if (
        _ACTION_DIGEST_RE.fullmatch(action_digest) is None
        or _SESSION_ID_RE.fullmatch(session_id) is None
        or session_id != f"web_{action_digest[:40]}"
    ):
        raise ManagedSessionProvisionError(
            "session_target_identity_mismatch",
            retryable=False,
        )


def _validate_and_digest_receipt(
    claimed: WorkspaceSessionRecord,
    receipt: ManagedSessionProvisionReceipt,
    *,
    expected_source_session_id: str | None,
) -> tuple[str, str | None]:
    action_digest = claimed.creation_action_digest
    if (
        action_digest is None
        or receipt.session_id != claimed.hermes_session_id
        or receipt.action_digest != action_digest
        or type(receipt.created) is not bool
        or type(receipt.recovered) is not bool
        or (receipt.created and receipt.recovered)
    ):
        raise ManagedSessionProvisionError(
            "session_receipt_identity_mismatch",
            retryable=False,
        )
    if claimed.parent_platform_session_id is None:
        if any(
            value is not None
            for value in (
                receipt.source_session_id,
                receipt.resolved_source_session_id,
                receipt.fork_point,
                receipt.preserve_source,
            )
        ):
            raise ManagedSessionProvisionError(
                "session_receipt_shape_invalid",
                retryable=False,
            )
    else:
        resolved_source_session_id = receipt.resolved_source_session_id
        if (
            receipt.source_session_id != expected_source_session_id
            or type(resolved_source_session_id) is not str
            or _HERMES_ID_RE.fullmatch(resolved_source_session_id) is None
            or resolved_source_session_id == claimed.hermes_session_id
            or receipt.fork_point != claimed.fork_point
            or receipt.preserve_source is not True
        ):
            raise ManagedSessionProvisionError(
                "session_fork_receipt_mismatch",
                retryable=False,
            )
    evidence = {
        "action_digest": receipt.action_digest,
        "created": receipt.created,
        "fork_point": receipt.fork_point,
        "preserve_source": receipt.preserve_source,
        "recovered": receipt.recovered,
        "resolved_source_session_id": receipt.resolved_source_session_id,
        "session_id": receipt.session_id,
        "source_session_id": receipt.source_session_id,
    }
    digest = hashlib.sha256(
        json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return digest, receipt.resolved_source_session_id


def _receipt_from_document(
    document: Mapping[str, object],
    *,
    operation: str,
    session_id: str,
    action_digest: str,
    source_session_id: str | None = None,
    fork_point: str | None = None,
) -> ManagedSessionProvisionReceipt:
    ensure_fields = {
        "ok",
        "session_id",
        "action_digest",
        "created",
        "recovered",
        "session",
    }
    fork_fields = ensure_fields | {
        "source_session_id",
        "resolved_source_session_id",
        "fork_point",
        "preserve_source",
    }
    expected_fields = ensure_fields if operation == "session-ensure" else fork_fields
    if set(document) != expected_fields or not isinstance(document.get("session"), Mapping):
        raise ManagedSessionProvisionError(
            "session_cli_invalid_receipt",
            retryable=True,
        )
    created = document.get("created")
    recovered = document.get("recovered")
    if (
        document.get("session_id") != session_id
        or document.get("action_digest") != action_digest
        or type(created) is not bool
        or type(recovered) is not bool
        or (created and recovered)
    ):
        raise ManagedSessionProvisionError(
            "session_cli_identity_mismatch",
            retryable=False,
        )
    if operation == "session-ensure":
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=created,
            recovered=recovered,
        )
    resolved_source_session_id = document.get("resolved_source_session_id")
    session = document["session"]
    if (
        document.get("source_session_id") != source_session_id
        or type(resolved_source_session_id) is not str
        or _HERMES_ID_RE.fullmatch(resolved_source_session_id) is None
        or resolved_source_session_id == session_id
        or document.get("fork_point") != fork_point
        or document.get("preserve_source") is not True
        or session.get("id") != session_id
        or session.get("parent_session_id") != resolved_source_session_id
    ):
        raise ManagedSessionProvisionError(
            "session_cli_fork_identity_mismatch",
            retryable=False,
        )
    return ManagedSessionProvisionReceipt(
        session_id=session_id,
        action_digest=action_digest,
        created=created,
        recovered=recovered,
        source_session_id=source_session_id,
        resolved_source_session_id=resolved_source_session_id,
        fork_point=fork_point,
        preserve_source=True,
    )


def _parse_stdout(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise ManagedSessionProvisionError(
            "session_cli_invalid_stdout",
            retryable=True,
        )
    try:
        text = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ManagedSessionProvisionError(
            "session_cli_invalid_stdout",
            retryable=True,
        ) from exc
    if not text or "\n" in text:
        raise ManagedSessionProvisionError(
            "session_cli_invalid_stdout",
            retryable=True,
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ManagedSessionProvisionError(
            "session_cli_invalid_stdout",
            retryable=True,
        ) from exc
    if not isinstance(value, dict):
        raise ManagedSessionProvisionError(
            "session_cli_invalid_stdout",
            retryable=True,
        )
    return value


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON field")
        document[key] = value
    return document


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


__all__ = [
    "ManagedSessionProvisionError",
    "ManagedSessionProvisionPort",
    "ManagedSessionProvisionReceipt",
    "ManagedSessionProvisionResult",
    "ManagedSessionProvisioner",
    "SubprocessManagedSessionProvisionPort",
]
