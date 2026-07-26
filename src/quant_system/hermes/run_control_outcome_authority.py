"""Durable outcomes for production Hermes approval and Run-stop controls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

RunControlOutcomeStatus = Literal["succeeded", "conflict", "outcome_unknown"]
_KINDS = frozenset({"hermes_command_approval_decide", "run_stop_request"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CONTRACT = "agent-v0.2-run-control-outcome/v1"


class RunControlOutcomeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RunControlOutcome:
    command_id: str
    action_digest: str
    action_kind: str
    target_run_id: str
    status: RunControlOutcomeStatus
    reason_code: str | None
    external_status: str | None
    external_idempotent_replay: bool
    command_state: str
    command_version: int
    command_event_id: int
    idempotent_replay: bool = False


def _validate_identity(
    *,
    command_id: str,
    action_digest: str,
    action_kind: str,
    target_run_id: str,
) -> UUID:
    try:
        parsed_command_id = UUID(command_id)
    except (TypeError, ValueError) as exc:
        raise RunControlOutcomeError(
            "run_control_outcome_validation",
            "control command_id is invalid",
        ) from exc
    if (
        _DIGEST_RE.fullmatch(action_digest) is None
        or action_kind not in _KINDS
        or _ID_RE.fullmatch(target_run_id) is None
    ):
        raise RunControlOutcomeError(
            "run_control_outcome_validation",
            "control outcome identity is invalid",
        )
    return parsed_command_id


def _receipt(
    *,
    action_digest: str,
    action_kind: str,
    target_run_id: str,
    status: RunControlOutcomeStatus,
    reason_code: str | None,
    external_status: str | None,
    external_idempotent_replay: bool,
) -> dict[str, object]:
    if (
        status not in {"succeeded", "conflict", "outcome_unknown"}
        or (
            status == "succeeded"
            and reason_code is not None
        )
        or (
            status != "succeeded"
            and (
                reason_code is None
                or _REASON_RE.fullmatch(reason_code) is None
            )
        )
        or (
            external_status is not None
            and _REASON_RE.fullmatch(external_status) is None
        )
    ):
        raise RunControlOutcomeError(
            "run_control_outcome_validation",
            "control outcome receipt is invalid",
        )
    return {
        "action_digest": action_digest,
        "action_kind": action_kind,
        "contract": _CONTRACT,
        "external_idempotent_replay": bool(external_idempotent_replay),
        "external_status": external_status,
        "outcome_status": status,
        "reason_code": reason_code,
        "target_run_id": target_run_id,
    }


class RunControlOutcomeAuthority:
    """Read/finalize the pre-effect command identity without worker dispatch."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def ready(self) -> bool:
        return run_control_outcome_runtime_security_ready(self._settings)

    def read(
        self,
        *,
        command_id: str,
        action_digest: str,
        action_kind: str,
        target_run_id: str,
    ) -> RunControlOutcome | None:
        parsed_command_id = _validate_identity(
            command_id=command_id,
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
        )
        database = get_database(self._settings)
        if database is None:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome authority is unavailable",
            )
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT
                        command.state,
                        command.version,
                        event.event_id,
                        event.event_data
                    FROM {SCHEMA}.hermes_commands AS command
                    LEFT JOIN LATERAL (
                        SELECT event_id, event_data
                        FROM {SCHEMA}.hermes_command_events
                        WHERE command_id = command.command_id
                          AND actor = 'bff'
                          AND event_type LIKE 'run_control.%%'
                        ORDER BY command_version DESC
                        LIMIT 1
                    ) AS event ON TRUE
                    WHERE command.owner_user_id = %s
                      AND command.command_id = %s
                      AND command.platform_session_id LIKE 'awctl_%%'
                      AND command.kind = %s
                      AND command.canonical_request_digest = %s
                    """,
                    (
                        ROOT_USER_ID,
                        parsed_command_id,
                        action_kind,
                        action_digest,
                    ),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome authority is unavailable",
            ) from exc
        if row is None:
            raise RunControlOutcomeError(
                "run_control_outcome_conflict",
                "control command identity mismatches",
            )
        state, version, event_id, raw_receipt = row
        if state == "queued" and event_id is None:
            return None
        if state not in {"succeeded", "failed", "outcome_unknown"}:
            raise RunControlOutcomeError(
                "run_control_outcome_conflict",
                "control command state is invalid",
            )
        if not isinstance(raw_receipt, dict):
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome receipt is unavailable",
            )
        status = raw_receipt.get("outcome_status")
        reason_code = raw_receipt.get("reason_code")
        external_status = raw_receipt.get("external_status")
        external_replay = raw_receipt.get("external_idempotent_replay")
        expected = _receipt(
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
            status=status,  # type: ignore[arg-type]
            reason_code=reason_code,  # type: ignore[arg-type]
            external_status=external_status,  # type: ignore[arg-type]
            external_idempotent_replay=external_replay is True,
        )
        if raw_receipt != expected or (
            (status == "succeeded" and state != "succeeded")
            or (status == "conflict" and state != "failed")
            or (status == "outcome_unknown" and state != "outcome_unknown")
        ):
            raise RunControlOutcomeError(
                "run_control_outcome_conflict",
                "control outcome receipt mismatches its command projection",
            )
        return RunControlOutcome(
            command_id=command_id,
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
            status=status,  # type: ignore[arg-type]
            reason_code=reason_code,  # type: ignore[arg-type]
            external_status=external_status,  # type: ignore[arg-type]
            external_idempotent_replay=external_replay is True,
            command_state=str(state),
            command_version=int(version),
            command_event_id=int(event_id),
        )

    def finalize(
        self,
        *,
        command_id: str,
        action_digest: str,
        action_kind: str,
        target_run_id: str,
        status: RunControlOutcomeStatus,
        reason_code: str | None,
        external_status: str | None,
        external_idempotent_replay: bool = False,
    ) -> RunControlOutcome:
        parsed_command_id = _validate_identity(
            command_id=command_id,
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
        )
        receipt = _receipt(
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
            status=status,
            reason_code=reason_code,
            external_status=external_status,
            external_idempotent_replay=external_idempotent_replay,
        )
        database = get_database(self._settings)
        if database is None:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome authority is unavailable",
            )
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT *
                    FROM {SCHEMA}.finalize_agent_v02_run_control(
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        ROOT_USER_ID,
                        parsed_command_id,
                        action_digest,
                        action_kind,
                        target_run_id,
                        status,
                        reason_code,
                        external_status,
                        bool(external_idempotent_replay),
                        Jsonb(receipt),
                    ),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome could not be persisted",
            ) from exc
        if row is None:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome could not be persisted",
            )
        observed = self.read(
            command_id=command_id,
            action_digest=action_digest,
            action_kind=action_kind,
            target_run_id=target_run_id,
        )
        if observed is None:
            raise RunControlOutcomeError(
                "run_control_outcome_unavailable",
                "control outcome readback is unavailable",
            )
        return RunControlOutcome(
            **{
                **observed.__dict__,
                "idempotent_replay": bool(row[3]),
            }
        )


def run_control_outcome_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    row = conn.execute(
        f"""
        SELECT
            EXISTS (
                SELECT 1
                FROM {SCHEMA}.agent_v02_run_control_meta
                WHERE singleton IS TRUE AND schema_version = 1
            ),
            (
                SELECT relation.relrowsecurity
                       AND relation.relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = %s
                  AND relation.relname =
                        'agent_v02_run_control_meta'
            ),
            EXISTS (
                SELECT 1
                FROM pg_proc AS function_row
                JOIN pg_namespace AS namespace
                  ON namespace.oid = function_row.pronamespace
                WHERE namespace.nspname = %s
                  AND function_row.proname =
                        'finalize_agent_v02_run_control'
                  AND function_row.prosecdef IS TRUE
                  AND pg_get_userbyid(function_row.proowner) =
                        'quant_migrator'
            ),
            has_function_privilege(
                'quant_runtime',
                %s,
                'EXECUTE'
            ),
            NOT has_function_privilege(
                'quant_readonly',
                %s,
                'EXECUTE'
            ),
            NOT EXISTS (
                SELECT 1
                FROM pg_proc AS function_row
                JOIN pg_namespace AS namespace
                  ON namespace.oid = function_row.pronamespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(
                        function_row.proacl,
                        acldefault('f', function_row.proowner)
                    )
                ) AS acl
                WHERE namespace.nspname = %s
                  AND function_row.proname =
                        'finalize_agent_v02_run_control'
                  AND acl.grantee = 0
                  AND acl.privilege_type = 'EXECUTE'
            )
        """,
        (
            SCHEMA,
            SCHEMA,
            (
                f"{SCHEMA}.finalize_agent_v02_run_control("
                "uuid,uuid,character,text,text,text,text,text,boolean,jsonb)"
            ),
            (
                f"{SCHEMA}.finalize_agent_v02_run_control("
                "uuid,uuid,character,text,text,text,text,text,boolean,jsonb)"
            ),
            SCHEMA,
        ),
    ).fetchone()
    return row is not None and all(value is True for value in row)


def run_control_outcome_runtime_security_ready(settings: Settings) -> bool:
    database = get_database(settings)
    if database is None:
        return False
    try:
        with database.connect() as conn:
            return run_control_outcome_schema_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


__all__ = [
    "RunControlOutcome",
    "RunControlOutcomeAuthority",
    "RunControlOutcomeError",
    "run_control_outcome_runtime_security_ready",
    "run_control_outcome_schema_is_ready_on_connection",
]
