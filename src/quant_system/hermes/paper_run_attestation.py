"""Read-only canonical attestation for HQA paper-research Hermes Runs.

This module deliberately separates two identities:

* ``invocation`` is the Hermes Run that is executing the HQA tool right now.
  It only proves an exact delivered/succeeded Platform Command binding.
* ``subject`` is a *prior*, terminal planning or final-research Run.  In
  addition to the Platform binding it must be terminal in the official Hermes
  GET-only API and carry an actual provider/model response receipt.

No provider call or mutation is available on this surface.  The returned
attestation is content-addressed and contains only bounded, non-secret facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    HermesApiReadError,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

PAPER_RUN_ATTESTATION_SCHEMA_VERSION = 1
_CONTRACT = "agent-v0.2-paper-run-attestation/v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RUN_REF_RE = re.compile(r"^run:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTANCE_RE = re.compile(r"^[0-9a-f]{32}$")
_EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{32}$")
_MAX_EVENT_BYTES = 4 * 1024 * 1024
_READY_SESSION_FUNCTION_BODY_SHA256 = (
    "ec95128ab07f6eecda0b831087bc02d76dd27fd2b05e1aca1d45bd3b90ae3a11"
)
_COMPLETION_BINDING_FUNCTION_BODY_SHA256 = (
    "61038b3f3f57ed4566d13b79d1b2eadfec61a7ea0a080a12f16040cb6c5108d3"
)

PaperRunAttestationMode = Literal["invocation", "subject"]


class PaperRunAttestationError(RuntimeError):
    """Stable, secret-free attestation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PaperRunAttestationValidationError(PaperRunAttestationError):
    def __init__(self, message: str) -> None:
        super().__init__("paper_run_attestation_validation", message)


class PaperRunAttestationConflict(PaperRunAttestationError):
    def __init__(self, message: str) -> None:
        super().__init__("paper_run_attestation_conflict", message)


class PaperRunAttestationUnavailable(PaperRunAttestationError):
    def __init__(self, message: str) -> None:
        super().__init__("paper_run_attestation_unavailable", message)


@dataclass(frozen=True)
class AttestPaperRun:
    mode: PaperRunAttestationMode
    workspace_id: str
    platform_session_id: str
    hermes_session_id: str
    command_id: str
    hermes_run_id: str


@dataclass(frozen=True)
class _PlatformRunBinding:
    """Exact Platform command tip plus its stable managed-conversation root."""

    command_state: str
    hermes_session_id: str
    resolved_hermes_session_id: str


class HermesRunEvidenceReader(Protocol):
    def capabilities(self) -> Mapping[str, object]: ...

    def run_status(self, run_id: str) -> Mapping[str, object]: ...

    def run_events(self, run_id: str) -> tuple[Mapping[str, object], ...]: ...


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise PaperRunAttestationUnavailable("paper Run evidence is not canonical JSON") from exc


def _identifier(value: object, field: str, *, maximum: int = 200) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or _ID_RE.fullmatch(value) is None
    ):
        raise PaperRunAttestationValidationError(f"{field} is invalid")
    return value


def _command_id(value: object) -> str:
    if type(value) is not str:
        raise PaperRunAttestationValidationError("command_id is invalid")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise PaperRunAttestationValidationError("command_id is invalid") from exc
    if str(parsed) != value:
        raise PaperRunAttestationValidationError("command_id must use canonical UUID form")
    return value


def _bounded_receipt_value(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > 256
        or not value.isprintable()
        or any(char in value for char in ("\r", "\n", "\x00"))
    ):
        raise PaperRunAttestationConflict(f"Hermes actual {field} receipt is missing or invalid")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _has_canonical_event_sequence(
    events: tuple[Mapping[str, object], ...],
    *,
    run_id: str,
) -> bool:
    previous_sequence = 0
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, Mapping):
            return False
        sequence = event.get("seq")
        event_id = event.get("event_id")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence <= previous_sequence
            or type(event_id) is not str
            or _EVENT_ID_RE.fullmatch(event_id) is None
            or event_id in event_ids
            or event.get("run_id") != run_id
        ):
            return False
        previous_sequence = sequence
        event_ids.add(event_id)
    return True


class OfficialHermesRunEvidenceReader:
    """Fixed GET-only reader for capability, status and terminal event facts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings.hermes_gateway
        self._client = HermesApiReadClient(self._settings)

    def capabilities(self) -> Mapping[str, object]:
        return self._client.capabilities()

    def run_status(self, run_id: str) -> Mapping[str, object]:
        # ``_get_json`` is private specifically to avoid a generic public
        # request surface.  This fixed adapter supplies one reviewed GET path.
        return self._client._get_json(  # noqa: SLF001
            f"/v1/runs/{quote(run_id, safe='')}",
            not_found_code="run_not_found",
            not_found_message="Hermes Run was not found",
        )

    def run_events(self, run_id: str) -> tuple[Mapping[str, object], ...]:
        token = self._client._api_key()  # noqa: SLF001
        timeout = httpx.Timeout(self._settings.timeout_seconds)
        try:
            with (
                httpx.Client(
                    base_url=self._client.base_url,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    headers={
                        "accept": "text/event-stream",
                        "authorization": f"Bearer {token}",
                    },
                ) as client,
                client.stream(
                    "GET",
                    f"/v1/runs/{quote(run_id, safe='')}/events",
                    params={"since": 0},
                ) as response,
            ):
                if response.status_code != 200:
                    raise PaperRunAttestationUnavailable("Hermes Run events are unavailable")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > min(
                        self._settings.max_response_bytes,
                        _MAX_EVENT_BYTES,
                    ):
                        raise PaperRunAttestationUnavailable(
                            "Hermes Run events exceeded the read bound"
                        )
                    chunks.append(chunk)
        except PaperRunAttestationError:
            raise
        except httpx.TimeoutException as exc:
            raise PaperRunAttestationUnavailable("Hermes Run events timed out") from exc
        except httpx.HTTPError as exc:
            raise PaperRunAttestationUnavailable("Hermes Run events are unavailable") from exc
        return _parse_sse_events(b"".join(chunks))


def _parse_sse_events(raw: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise PaperRunAttestationUnavailable("Hermes Run events are not valid UTF-8") from exc
    events: list[Mapping[str, object]] = []
    previous_sequence = 0
    event_ids: set[str] = set()
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        fields: dict[str, str] = {}
        for line in frame.splitlines():
            if not line or line.startswith(":"):
                continue
            key, separator, value = line.partition(":")
            if not separator or key not in {"id", "event", "data"}:
                raise PaperRunAttestationUnavailable("Hermes Run event frame is invalid")
            value = value[1:] if value.startswith(" ") else value
            if key in fields:
                raise PaperRunAttestationUnavailable("Hermes Run event frame has duplicate fields")
            fields[key] = value
        if set(fields) != {"id", "event", "data"}:
            raise PaperRunAttestationUnavailable("Hermes Run event frame is incomplete")
        try:
            payload = json.loads(
                fields["data"],
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise PaperRunAttestationUnavailable("Hermes Run event data is invalid") from exc
        if not isinstance(payload, dict):
            raise PaperRunAttestationUnavailable("Hermes Run event data is not an object")
        if payload.get("event") != fields["event"]:
            raise PaperRunAttestationUnavailable(
                "Hermes Run event envelope does not match its data"
            )
        sequence = payload.get("seq")
        event_id = payload.get("event_id")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence <= 0
            or fields["id"] != str(sequence)
            or sequence <= previous_sequence
            or type(event_id) is not str
            or _EVENT_ID_RE.fullmatch(event_id) is None
            or event_id in event_ids
        ):
            raise PaperRunAttestationUnavailable("Hermes Run event identity is invalid")
        previous_sequence = sequence
        event_ids.add(event_id)
        events.append(dict(payload))
    return tuple(events)


def paper_run_attestation_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    relations = conn.execute(
        """
        SELECT
            relation.relname,
            pg_get_userbyid(relation.relowner),
            relation.relrowsecurity,
            relation.relforcerowsecurity
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relkind = 'r'
          AND relation.relname = ANY(%s)
        """,
        (
            SCHEMA,
            [
                "agent_v02_paper_run_attestation_meta",
                "agent_v02_paper_gate_challenges",
                "agent_v02_paper_gate_completions",
            ],
        ),
    ).fetchall()
    if {(str(row[0]), str(row[1]), bool(row[2]), bool(row[3])) for row in relations} != {
        (
            "agent_v02_paper_run_attestation_meta",
            "quant_migrator",
            False,
            False,
        ),
        (
            "agent_v02_paper_gate_challenges",
            "quant_migrator",
            True,
            True,
        ),
        (
            "agent_v02_paper_gate_completions",
            "quant_migrator",
            True,
            True,
        ),
    }:
        return False
    meta = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_paper_run_attestation_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if meta != (PAPER_RUN_ATTESTATION_SCHEMA_VERSION,):
        return False

    expected_columns = {
        (
            "agent_v02_paper_gate_challenges",
            "provider_evidence_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "subject_command_id",
            "uuid",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "subject_hermes_run_id",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "subject_run_attestation_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "subject_run_attestation_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_provider",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_receipt_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_config_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_config_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_summary_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_summary_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_report_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_challenges",
            "final_backtest_report_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "plan_version",
            "bigint",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "plan_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "plan_confirmation_note_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "subject_command_id",
            "uuid",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "subject_hermes_run_id",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "subject_run_attestation_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "subject_run_attestation_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_provider",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_receipt_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_config_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_config_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_summary_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_summary_digest",
            "character",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_report_ref",
            "text",
            "YES",
        ),
        (
            "agent_v02_paper_gate_completions",
            "final_backtest_report_digest",
            "character",
            "YES",
        ),
    }
    columns = conn.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
          AND (
                (
                    table_name = 'agent_v02_paper_gate_challenges'
                    AND column_name = ANY(%s)
                )
                OR
                (
                    table_name = 'agent_v02_paper_gate_completions'
                    AND column_name = ANY(%s)
                )
          )
        """,
        (
            SCHEMA,
            [row[1] for row in expected_columns if row[0] == "agent_v02_paper_gate_challenges"],
            [row[1] for row in expected_columns if row[0] == "agent_v02_paper_gate_completions"],
        ),
    ).fetchall()
    if {
        (str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in columns
    } != expected_columns:
        return False

    constraints = conn.execute(
        """
        SELECT constraint_record.conname, constraint_record.convalidated
        FROM pg_constraint AS constraint_record
        JOIN pg_class AS relation
          ON relation.oid = constraint_record.conrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND constraint_record.conname = ANY(%s)
        """,
        (
            SCHEMA,
            [
                "ck_agent_v02_paper_gate_run_attestation",
                "ck_agent_v02_paper_completion_attestation",
                "fk_agent_v02_paper_gate_subject_command",
                "fk_agent_v02_paper_completion_subject_command",
            ],
        ),
    ).fetchall()
    if {(str(row[0]), bool(row[1])) for row in constraints} != {
        ("ck_agent_v02_paper_gate_run_attestation", True),
        ("ck_agent_v02_paper_completion_attestation", True),
        ("fk_agent_v02_paper_gate_subject_command", True),
        ("fk_agent_v02_paper_completion_subject_command", True),
    }:
        return False

    triggers = conn.execute(
        """
        SELECT
            trigger.tgname,
            relation.relname,
            trigger.tgenabled,
            procedure.proname,
            pg_get_userbyid(procedure.proowner),
            procedure.prosecdef,
            pg_get_triggerdef(trigger.oid, TRUE)
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        WHERE namespace.nspname = %s
          AND trigger.tgname = ANY(%s)
          AND NOT trigger.tgisinternal
        """,
        (
            SCHEMA,
            [
                "trg_agent_v02_paper_gate_ready_session",
                "trg_agent_v02_paper_completion_binding",
            ],
        ),
    ).fetchall()
    observed_triggers = {
        str(row[0]): (
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            bool(row[5]),
            " ".join(str(row[6]).split()).lower(),
        )
        for row in triggers
    }
    if set(observed_triggers) != {
        "trg_agent_v02_paper_gate_ready_session",
        "trg_agent_v02_paper_completion_binding",
    }:
        return False
    ready_trigger = observed_triggers["trg_agent_v02_paper_gate_ready_session"]
    completion_trigger = observed_triggers["trg_agent_v02_paper_completion_binding"]
    if (
        ready_trigger[:5]
        != (
            "agent_v02_paper_gate_challenges",
            "A",
            "require_agent_v02_paper_gate_ready_session",
            "quant_migrator",
            False,
        )
        or "before insert or update" not in ready_trigger[5]
        or completion_trigger[:5]
        != (
            "agent_v02_paper_gate_completions",
            "A",
            "require_agent_v02_paper_completion_binding",
            "quant_migrator",
            False,
        )
        or "before insert" not in completion_trigger[5]
    ):
        return False

    functions = conn.execute(
        """
        SELECT
            procedure.proname,
            procedure.prosrc,
            procedure.provolatile,
            procedure.prosecdef,
            pg_get_userbyid(procedure.proowner)
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = %s
          AND procedure.proname = ANY(%s)
          AND procedure.pronargs = 0
        """,
        (
            SCHEMA,
            [
                "require_agent_v02_paper_gate_ready_session",
                "require_agent_v02_paper_completion_binding",
            ],
        ),
    ).fetchall()
    observed_functions = {
        str(row[0]): (
            hashlib.sha256(" ".join(str(row[1]).split()).lower().encode("utf-8")).hexdigest(),
            str(row[2]),
            bool(row[3]),
            str(row[4]),
        )
        for row in functions
    }
    if observed_functions != {
        "require_agent_v02_paper_gate_ready_session": (
            _READY_SESSION_FUNCTION_BODY_SHA256,
            "s",
            False,
            "quant_migrator",
        ),
        "require_agent_v02_paper_completion_binding": (
            _COMPLETION_BINDING_FUNCTION_BODY_SHA256,
            "s",
            False,
            "quant_migrator",
        ),
    }:
        return False

    roles = conn.execute(
        """
        SELECT count(*)
        FROM pg_roles
        WHERE rolname = ANY(%s)
        """,
        (["quant_runtime", "quant_readonly", "quant_migrator"],),
    ).fetchone()
    if roles != (3,):
        return False
    privileges = conn.execute(
        """
        WITH roles(role_name) AS (
            VALUES
                ('quant_runtime'),
                ('quant_readonly'),
                ('quant_migrator')
        ),
        tables(table_name) AS (
            VALUES
                ('agent_v02_paper_run_attestation_meta'),
                ('agent_v02_paper_gate_challenges'),
                ('agent_v02_paper_gate_completions')
        )
        SELECT
            role_name,
            table_name,
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'SELECT'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'INSERT'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'UPDATE'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'DELETE'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'TRUNCATE'
            )
        FROM roles CROSS JOIN tables
        """,
        (SCHEMA, SCHEMA, SCHEMA, SCHEMA, SCHEMA),
    ).fetchall()
    observed_privileges = {
        (str(row[0]), str(row[1])): tuple(bool(value) for value in row[2:]) for row in privileges
    }
    if observed_privileges != {
        (
            "quant_runtime",
            "agent_v02_paper_run_attestation_meta",
        ): (True, False, False, False, False),
        (
            "quant_runtime",
            "agent_v02_paper_gate_challenges",
        ): (True, True, True, False, False),
        (
            "quant_runtime",
            "agent_v02_paper_gate_completions",
        ): (True, True, False, False, False),
        (
            "quant_readonly",
            "agent_v02_paper_run_attestation_meta",
        ): (True, False, False, False, False),
        (
            "quant_readonly",
            "agent_v02_paper_gate_challenges",
        ): (True, False, False, False, False),
        (
            "quant_readonly",
            "agent_v02_paper_gate_completions",
        ): (True, False, False, False, False),
        (
            "quant_migrator",
            "agent_v02_paper_run_attestation_meta",
        ): (True, True, True, True, True),
        (
            "quant_migrator",
            "agent_v02_paper_gate_challenges",
        ): (True, True, True, True, True),
        (
            "quant_migrator",
            "agent_v02_paper_gate_completions",
        ): (True, True, True, True, True),
    }:
        return False
    schema_privileges = conn.execute(
        """
        SELECT
            has_schema_privilege('quant_runtime', %s, 'USAGE'),
            has_schema_privilege('quant_runtime', %s, 'CREATE'),
            has_schema_privilege('quant_readonly', %s, 'USAGE'),
            has_schema_privilege('quant_readonly', %s, 'CREATE'),
            has_schema_privilege('quant_migrator', %s, 'USAGE')
        """,
        (SCHEMA, SCHEMA, SCHEMA, SCHEMA, SCHEMA),
    ).fetchone()
    return schema_privileges == (True, False, True, False, True)


def paper_run_attestation_runtime_security_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    """Require the active reader to be the constrained runtime principal.

    The catalog can be perfectly provisioned while a service is accidentally
    connected as ``quant_migrator`` or a superuser.  Such a connection bypasses
    the FORCE RLS boundary used by the exact command/session lookup below, so
    schema readiness alone is not sufficient attestation evidence.
    """

    if not paper_run_attestation_schema_is_ready_on_connection(conn):
        return False
    principal = conn.execute(
        """
        SELECT
            EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = session_user
                  AND rolcanlogin
                  AND NOT rolsuper
                  AND NOT rolbypassrls
                  AND NOT rolcreatedb
                  AND NOT rolcreaterole
                  AND NOT rolreplication
            ),
            current_user = session_user,
            pg_has_role(session_user, 'quant_runtime', 'MEMBER'),
            NOT pg_has_role(session_user, 'quant_migrator', 'MEMBER'),
            has_schema_privilege(session_user, %s, 'USAGE'),
            NOT has_schema_privilege(session_user, %s, 'CREATE')
        """,
        (SCHEMA, SCHEMA),
    ).fetchone()
    if principal is None or not all(bool(value) for value in principal):
        return False

    expected = {
        "agent_v02_paper_gate_challenges": (
            True,
            True,
            True,
            False,
            False,
        ),
        "agent_v02_paper_gate_completions": (
            True,
            True,
            False,
            False,
            False,
        ),
        "agent_v02_paper_run_attestation_meta": (
            True,
            False,
            False,
            False,
            False,
        ),
    }
    privileges = conn.execute(
        """
        SELECT
            relation_name,
            has_table_privilege(
                session_user,
                %s || '.' || relation_name,
                'SELECT'
            ),
            has_table_privilege(
                session_user,
                %s || '.' || relation_name,
                'INSERT'
            ),
            has_table_privilege(
                session_user,
                %s || '.' || relation_name,
                'UPDATE'
            ),
            has_table_privilege(
                session_user,
                %s || '.' || relation_name,
                'DELETE'
            ),
            has_table_privilege(
                session_user,
                %s || '.' || relation_name,
                'TRUNCATE'
            )
        FROM unnest(%s::text[]) AS relation_name
        """,
        (
            SCHEMA,
            SCHEMA,
            SCHEMA,
            SCHEMA,
            SCHEMA,
            list(expected),
        ),
    ).fetchall()
    return {str(row[0]): tuple(bool(value) for value in row[1:]) for row in privileges} == expected


def paper_run_attestation_runtime_security_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return paper_run_attestation_runtime_security_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


class PaperRunAttestationAuthority:
    """Read canonical Platform/Hermes facts and emit one content address."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        run_reader: HermesRunEvidenceReader | None = None,
    ) -> None:
        self._settings = settings
        self._database_override = database
        self._run_reader_override = run_reader

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise PaperRunAttestationUnavailable("paper Run attestation database is disabled")
        return database

    def _platform_binding(self, request: AttestPaperRun) -> _PlatformRunBinding:
        allowed_states = ("succeeded",) if request.mode == "subject" else ("delivered", "succeeded")
        try:
            with self._database().connect() as conn:
                if not paper_run_attestation_runtime_security_is_ready_on_connection(conn):
                    raise PaperRunAttestationUnavailable(
                        "paper Run attestation runtime security is not ready"
                    )
                row = conn.execute(
                    f"""
                    SELECT
                        command.state,
                        session.hermes_session_id,
                        command.resolved_hermes_session_id
                    FROM {SCHEMA}.hermes_workspace_sessions AS session
                    JOIN {SCHEMA}.hermes_commands AS command
                      ON command.command_id = %s
                     AND command.owner_user_id = session.owner_user_id
                     AND command.platform_session_id =
                            session.platform_session_id
                     AND command.hermes_session_id =
                            session.hermes_session_id
                     AND command.hermes_run_id = %s
                     AND command.candidate_admission_id
                            IS NOT DISTINCT FROM
                                session.candidate_admission_id
                    WHERE session.owner_user_id = %s
                      AND session.workspace_id = %s
                      AND session.platform_session_id = %s
                      AND session.hermes_session_id = %s
                      AND session.kind = 'web_managed_session'
                      AND session.writer = 'web_control_plane'
                      AND session.provision_state = 'ready'
                      AND command.state = ANY(%s)
                    """,
                    (
                        request.command_id,
                        request.hermes_run_id,
                        ROOT_USER_ID,
                        request.workspace_id,
                        request.platform_session_id,
                        request.hermes_session_id,
                        list(allowed_states),
                    ),
                ).fetchone()
        except PaperRunAttestationError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperRunAttestationUnavailable(
                "paper Run Platform binding is unavailable"
            ) from exc
        if (
            row is None
            or str(row[0]) not in allowed_states
            or type(row[1]) is not str
            or _ID_RE.fullmatch(row[1]) is None
            or type(row[2]) is not str
            or _ID_RE.fullmatch(row[2]) is None
        ):
            raise PaperRunAttestationConflict(
                "paper Run does not have the required exact Platform binding"
            )
        return _PlatformRunBinding(
            command_state=str(row[0]),
            hermes_session_id=row[1],
            resolved_hermes_session_id=row[2],
        )

    @staticmethod
    def _subject_evidence(
        request: AttestPaperRun,
        reader: HermesRunEvidenceReader,
        *,
        hermes_session_id: str,
        resolved_hermes_session_id: str,
    ) -> dict[str, object]:
        try:
            capabilities = reader.capabilities()
            status = reader.run_status(request.hermes_run_id)
            events = reader.run_events(request.hermes_run_id)
        except PaperRunAttestationError:
            raise
        except HermesApiReadError as exc:
            raise PaperRunAttestationUnavailable(
                "official Hermes Run evidence is unavailable"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - read-only seam fails closed
            raise PaperRunAttestationUnavailable(
                "official Hermes Run evidence is unavailable"
            ) from exc

        if not _has_canonical_event_sequence(
            events,
            run_id=request.hermes_run_id,
        ):
            raise PaperRunAttestationConflict("Hermes subject Run event sequence is not canonical")

        features = capabilities.get("features")
        durable = capabilities.get("durable")
        runtime = capabilities.get("runtime")
        if (
            not isinstance(features, Mapping)
            or features.get("run_status") is not True
            or features.get("run_events_sse") is not True
            or not isinstance(durable, Mapping)
            or not isinstance(durable.get("run_evidence"), Mapping)
            or durable["run_evidence"].get("supported") is not True
            or durable["run_evidence"].get("grounded") is not True
            or not isinstance(durable.get("event_replay"), Mapping)
            or durable["event_replay"].get("supported") is not True
            or durable["event_replay"].get("grounded") is not True
            or not isinstance(runtime, Mapping)
        ):
            raise PaperRunAttestationConflict(
                "Hermes durable Run evidence capability is not grounded"
            )
        runtime_instance = runtime.get("instance_id")
        runtime_started = runtime.get("started_at")
        if (
            type(runtime_instance) is not str
            or _INSTANCE_RE.fullmatch(runtime_instance) is None
            or type(runtime_started) is not str
            or not runtime_started
            or len(runtime_started) > 64
        ):
            raise PaperRunAttestationConflict("Hermes runtime identity is unavailable")
        actual = status.get("actual_policy")
        if (
            status.get("object") != "hermes.run"
            or status.get("run_id") != request.hermes_run_id
            or status.get("session_id") != resolved_hermes_session_id
            or status.get("resolved_session_id") != resolved_hermes_session_id
            or status.get("conversation_session_id") != hermes_session_id
            or status.get("status") != "succeeded"
            or not isinstance(actual, Mapping)
            or set(actual) != {"model", "provider"}
        ):
            raise PaperRunAttestationConflict(
                "Hermes subject Run is not exact, terminal and provider-grounded"
            )
        model = _bounded_receipt_value(actual.get("model"), "model")
        provider = _bounded_receipt_value(actual.get("provider"), "provider")
        completed = [
            event
            for event in events
            if event.get("event") == "run.completed"
            and event.get("run_id") == request.hermes_run_id
        ]
        if len(completed) != 1:
            raise PaperRunAttestationConflict(
                "Hermes subject Run has no unique terminal completion event"
            )
        terminal = completed[0]
        output = terminal.get("output")
        if type(output) is not str or not output:
            raise PaperRunAttestationConflict(
                "Hermes subject Run has no canonical assistant output"
            )
        live_output = status.get("output")
        if live_output is not None and live_output != output:
            raise PaperRunAttestationConflict(
                "Hermes live and durable subject Run outputs disagree"
            )
        try:
            output_bytes = output.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise PaperRunAttestationConflict("Hermes subject Run output is invalid") from exc
        output_digest = hashlib.sha256(output_bytes).hexdigest()
        sequence = terminal.get("seq")
        event_id = terminal.get("event_id")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence <= 0
            or type(event_id) is not str
            or _EVENT_ID_RE.fullmatch(event_id) is None
        ):
            raise PaperRunAttestationConflict(
                "Hermes subject Run terminal event identity is missing"
            )
        terminal_event_ref = (
            "hermes-event:"
            + hashlib.sha256(
                _canonical_bytes(
                    {
                        "event": "run.completed",
                        "event_id": event_id,
                        "output_digest": output_digest,
                        "run_id": request.hermes_run_id,
                        "seq": sequence,
                    }
                )
            ).hexdigest()
        )
        return {
            "actual_model": model,
            "actual_provider": provider,
            "output_digest": output_digest,
            "hermes_runtime_instance_id": runtime_instance,
            "hermes_runtime_started_at": runtime_started,
            "terminal_event_ref": terminal_event_ref,
        }

    def attest(self, request: AttestPaperRun) -> dict[str, object]:
        if type(request) is not AttestPaperRun:
            raise TypeError("request must be AttestPaperRun")
        if request.mode not in {"invocation", "subject"}:
            raise PaperRunAttestationValidationError("mode is invalid")
        workspace_id = _identifier(request.workspace_id, "workspace_id")
        platform_session_id = _identifier(
            request.platform_session_id,
            "platform_session_id",
        )
        hermes_session_id = _identifier(
            request.hermes_session_id,
            "hermes_session_id",
            maximum=256,
        )
        command_id = _command_id(request.command_id)
        hermes_run_id = _identifier(
            request.hermes_run_id,
            "hermes_run_id",
            maximum=256,
        )
        normalized = AttestPaperRun(
            mode=request.mode,
            workspace_id=workspace_id,
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            command_id=command_id,
            hermes_run_id=hermes_run_id,
        )
        platform_binding = self._platform_binding(normalized)
        subject: dict[str, object] = {
            "actual_model": None,
            "actual_provider": None,
            "output_digest": None,
            "hermes_runtime_instance_id": None,
            "hermes_runtime_started_at": None,
            "terminal_event_ref": None,
        }
        if normalized.mode == "subject":
            reader = self._run_reader_override or OfficialHermesRunEvidenceReader(self._settings)
            subject = self._subject_evidence(
                normalized,
                reader,
                hermes_session_id=platform_binding.hermes_session_id,
                resolved_hermes_session_id=(
                    platform_binding.resolved_hermes_session_id
                ),
            )
        hqa_run_ref = f"run:{hermes_run_id}" if normalized.mode == "subject" else None
        if hqa_run_ref is not None and _RUN_REF_RE.fullmatch(hqa_run_ref) is None:
            raise PaperRunAttestationConflict("Hermes Run ID cannot form a canonical HQA run ref")
        evidence = {
            "schema_version": PAPER_RUN_ATTESTATION_SCHEMA_VERSION,
            "mode": normalized.mode,
            "workspace_id": workspace_id,
            "platform_session_id": platform_session_id,
            "hermes_session_id": hermes_session_id,
            "resolved_hermes_session_id": (
                platform_binding.resolved_hermes_session_id
            ),
            "command_id": command_id,
            "hermes_run_id": hermes_run_id,
            "command_state": platform_binding.command_state,
            "hqa_run_ref": hqa_run_ref,
            **subject,
        }
        # The capability runtime is the *current observer*, not the immutable
        # producer of the subject Run.  Return it as diagnostic metadata but do
        # not let a later Hermes restart change this content address.
        digest = hashlib.sha256(
            _canonical_bytes(
                {
                    key: value
                    for key, value in evidence.items()
                    if key
                    not in {
                        "hermes_runtime_instance_id",
                        "hermes_runtime_started_at",
                    }
                }
            )
        ).hexdigest()
        assert _DIGEST_RE.fullmatch(digest)
        return {
            **evidence,
            "evidence_digest": digest,
            "attestation_ref": f"paper-run-attestation:{digest}",
            "provider_evidence_ref": (
                f"provider-evidence:paper-run-{digest}" if normalized.mode == "subject" else None
            ),
        }


__all__ = [
    "AttestPaperRun",
    "HermesRunEvidenceReader",
    "OfficialHermesRunEvidenceReader",
    "PAPER_RUN_ATTESTATION_SCHEMA_VERSION",
    "PaperRunAttestationAuthority",
    "PaperRunAttestationConflict",
    "PaperRunAttestationError",
    "PaperRunAttestationUnavailable",
    "PaperRunAttestationValidationError",
    "paper_run_attestation_runtime_security_is_ready_on_connection",
    "paper_run_attestation_runtime_security_ready",
    "paper_run_attestation_schema_is_ready_on_connection",
]
