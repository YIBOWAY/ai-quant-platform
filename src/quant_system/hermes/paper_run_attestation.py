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
_MAX_EVENT_BYTES = 4 * 1024 * 1024

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
        raise PaperRunAttestationUnavailable(
            "paper Run evidence is not canonical JSON"
        ) from exc


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
        raise PaperRunAttestationValidationError(
            "command_id must use canonical UUID form"
        )
    return value


def _bounded_receipt_value(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > 256
        or not value.isprintable()
        or any(char in value for char in ("\r", "\n", "\x00"))
    ):
        raise PaperRunAttestationConflict(
            f"Hermes actual {field} receipt is missing or invalid"
        )
    return value


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
                    raise PaperRunAttestationUnavailable(
                        "Hermes Run events are unavailable"
                    )
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
            raise PaperRunAttestationUnavailable(
                "Hermes Run events timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise PaperRunAttestationUnavailable(
                "Hermes Run events are unavailable"
            ) from exc
        return _parse_sse_events(b"".join(chunks))


def _parse_sse_events(raw: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise PaperRunAttestationUnavailable(
            "Hermes Run events are not valid UTF-8"
        ) from exc
    events: list[Mapping[str, object]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        fields: dict[str, str] = {}
        data_lines: list[str] = []
        for line in frame.splitlines():
            if not line or line.startswith(":"):
                continue
            key, separator, value = line.partition(":")
            if not separator or key not in {"id", "event", "data"}:
                raise PaperRunAttestationUnavailable(
                    "Hermes Run event frame is invalid"
                )
            value = value[1:] if value.startswith(" ") else value
            if key == "data":
                data_lines.append(value)
            elif key in fields:
                raise PaperRunAttestationUnavailable(
                    "Hermes Run event frame has duplicate fields"
                )
            else:
                fields[key] = value
        if not data_lines or "event" not in fields:
            raise PaperRunAttestationUnavailable(
                "Hermes Run event frame is incomplete"
            )
        try:
            payload = json.loads("\n".join(data_lines))
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise PaperRunAttestationUnavailable(
                "Hermes Run event data is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise PaperRunAttestationUnavailable(
                "Hermes Run event data is not an object"
            )
        if payload.get("event") != fields["event"]:
            raise PaperRunAttestationUnavailable(
                "Hermes Run event envelope does not match its data"
            )
        events.append(dict(payload))
    return tuple(events)


def paper_run_attestation_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    meta = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_paper_run_attestation_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if meta != (PAPER_RUN_ATTESTATION_SCHEMA_VERSION,):
        return False
    trigger = conn.execute(
        """
        SELECT
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
          AND relation.relname = 'agent_v02_paper_gate_challenges'
          AND trigger.tgname =
                'trg_agent_v02_paper_gate_ready_session'
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA,),
    ).fetchone()
    if (
        trigger is None
        or trigger[:4]
        != (
            "A",
            "require_agent_v02_paper_gate_ready_session",
            "quant_migrator",
            False,
        )
        or "before insert or update"
        not in " ".join(str(trigger[4]).split()).lower()
    ):
        return False
    function_source = conn.execute(
        """
        SELECT lower(regexp_replace(prosrc, '\\s+', ' ', 'g'))
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = %s
          AND procedure.proname =
                'require_agent_v02_paper_gate_ready_session'
          AND procedure.pronargs = 0
        """,
        (SCHEMA,),
    ).fetchone()
    if function_source is None:
        return False
    source = str(function_source[0])
    return (
        "command.state in ('delivered', 'succeeded')" in source
        and "command.hermes_session_id = managed_session.hermes_session_id"
        in source
        and "command.hermes_run_id = new.hermes_run_id" in source
        and "command.state = 'leased'" not in source
    )


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
            raise PaperRunAttestationUnavailable(
                "paper Run attestation database is disabled"
            )
        return database

    def _platform_binding(self, request: AttestPaperRun) -> str:
        allowed_states = (
            ("succeeded",)
            if request.mode == "subject"
            else ("delivered", "succeeded")
        )
        try:
            with self._database().connect() as conn:
                if not paper_run_attestation_schema_is_ready_on_connection(conn):
                    raise PaperRunAttestationUnavailable(
                        "paper Run attestation schema is not ready"
                    )
                row = conn.execute(
                    f"""
                    SELECT command.state
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
        if row is None or str(row[0]) not in allowed_states:
            raise PaperRunAttestationConflict(
                "paper Run does not have the required exact Platform binding"
            )
        return str(row[0])

    @staticmethod
    def _subject_evidence(
        request: AttestPaperRun,
        reader: HermesRunEvidenceReader,
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
            raise PaperRunAttestationConflict(
                "Hermes runtime identity is unavailable"
            )
        actual = status.get("actual_policy")
        if (
            status.get("object") != "hermes.run"
            or status.get("run_id") != request.hermes_run_id
            or status.get("session_id") != request.hermes_session_id
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
            raise PaperRunAttestationConflict(
                "Hermes subject Run output is invalid"
            ) from exc
        output_digest = hashlib.sha256(output_bytes).hexdigest()
        sequence = terminal.get("seq")
        event_id = terminal.get("event_id")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence <= 0
            or type(event_id) is not str
            or not event_id
            or len(event_id) > 256
        ):
            raise PaperRunAttestationConflict(
                "Hermes subject Run terminal event identity is missing"
            )
        terminal_event_ref = "hermes-event:" + hashlib.sha256(
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
        command_state = self._platform_binding(normalized)
        subject: dict[str, object] = {
            "actual_model": None,
            "actual_provider": None,
            "output_digest": None,
            "hermes_runtime_instance_id": None,
            "hermes_runtime_started_at": None,
            "terminal_event_ref": None,
        }
        if normalized.mode == "subject":
            reader = self._run_reader_override or OfficialHermesRunEvidenceReader(
                self._settings
            )
            subject = self._subject_evidence(normalized, reader)
        hqa_run_ref = (
            f"run:{hermes_run_id}" if normalized.mode == "subject" else None
        )
        if hqa_run_ref is not None and _RUN_REF_RE.fullmatch(hqa_run_ref) is None:
            raise PaperRunAttestationConflict(
                "Hermes Run ID cannot form a canonical HQA run ref"
            )
        evidence = {
            "schema_version": PAPER_RUN_ATTESTATION_SCHEMA_VERSION,
            "mode": normalized.mode,
            "workspace_id": workspace_id,
            "platform_session_id": platform_session_id,
            "hermes_session_id": hermes_session_id,
            "command_id": command_id,
            "hermes_run_id": hermes_run_id,
            "command_state": command_state,
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
                f"provider-evidence:hermes-run:{digest}"
                if normalized.mode == "subject"
                else None
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
    "paper_run_attestation_schema_is_ready_on_connection",
]
