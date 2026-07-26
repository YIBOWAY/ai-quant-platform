"""Authority-backed real-flow evidence for Agent v0.2 candidate admission.

Release-evidence JSON files are useful attachments, but JSON cannot prove that
the referenced commands, Hermes Sessions, provider receipts, or research gates
ever existed.  This module re-reads each canonical authority and freezes one
append-only, content-addressed fact set in PostgreSQL.

No prompt or transcript body is persisted.  Hermes message bodies are read only
long enough to compute a canonical transcript digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import psycopg

from quant_system.agent.paths import resolve_agent_output_dir
from quant_system.agent.promotion_workspace import (
    PromotionWorkspaceError,
    default_promotion_root,
    promotion_status,
    resolve_managed_worktree_root,
    resolve_platform_repo,
)
from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    DecideHermesCommandApproval,
    RequestStop,
    WorkspaceRef,
    canonical_action_digest,
)
from quant_system.hermes.candidate_admission_authority import (
    CandidateAdmissionConflict,
    CandidateAdmissionUnavailable,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.gateway_client import (
    HermesApiReadError,
    HermesRunControlError,
    OfficialHermesRunControlClient,
)
from quant_system.hermes.submission_saga import control_plane_session_id
from quant_system.hermes.zero_order_observation import (
    capture_canonical_zero_order_snapshot,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

_FACTS_CONTRACT = "agent-v0.2-candidate-evidence-facts/v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_INSTANCE_RE = re.compile(r"^[0-9a-f]{32}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CANDIDATE_EVIDENCE_SCHEMA_SIGNATURES = frozenset(
    {
        # Candidate evidence + resolved lineage, before release hardening 020.
        "576b5df1989c01d38094d96eca3dc3e402dc9f360117619d4415338b5a9d770f",
        # Full replay through release hardening 020 and resolved lineage 022.
        "83d1101279db10e1d08ddb0d8404a2d933918c907cd51638a743f734860e77f5",
    }
)
_CANDIDATE_EVIDENCE_TABLES = (
    "agent_v02_candidate_admissions",
    "agent_v02_candidate_evidence_meta",
    "agent_v02_candidate_restart_observations",
    "agent_v02_candidate_evidence_sets",
)
_CANDIDATE_EVIDENCE_FUNCTIONS = (
    "guard_agent_v02_candidate_transition",
    "guard_agent_v02_candidate_restart_observation",
    "guard_agent_v02_candidate_evidence_set",
    "guard_agent_v02_candidate_resolved_fork_lineage",
    "reject_agent_v02_candidate_evidence_mutation",
)
_REQUIRED_FLOW_NAMES = frozenset(
    {
        "web_chat_multi_turn",
        "hermes_restart_recovery",
        "exact_message_fork",
        "options_vertical_live_futu_ro",
        "paper_factor_gate_1_2_3_via_hermes",
    }
)


class CandidateEvidenceV3Error(RuntimeError):
    """A canonical fact was unavailable or inconsistent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CandidateEvidenceGateway(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def session_detail(self, session_id: str) -> dict[str, Any]: ...

    def session_messages(self, session_id: str) -> dict[str, Any]: ...

    def run_status(self, run_id: str) -> dict[str, object]: ...

    def run_events(self, run_id: str) -> tuple[dict[str, object], ...]: ...


@dataclass(frozen=True)
class CandidateEvidenceReferences:
    admission_id: str
    admission_digest: str
    web_platform_session_id: str
    web_command_ids: tuple[str, ...]
    fork_source_platform_session_id: str
    fork_child_platform_session_id: str
    options_request_id: str
    paper_gate3_id: str
    reviewed_commit: str
    approval_command_id: str
    stop_command_id: str


@dataclass(frozen=True)
class CandidateRestartObservation:
    observation_id: str
    admission_id: str
    phase: Literal["before", "after"]
    platform_session_id: str
    hermes_session_id: str
    runtime_instance_id: str
    runtime_started_at: datetime
    transcript_digest: str
    message_count: int
    observed_at: datetime

    def to_public_dict(self) -> dict[str, object]:
        return {
            "admission_id": self.admission_id,
            "hermes_session_id": self.hermes_session_id,
            "message_count": self.message_count,
            "observation_id": self.observation_id,
            "observed_at": _timestamp(self.observed_at),
            "phase": self.phase,
            "platform_session_id": self.platform_session_id,
            "runtime_instance_id": self.runtime_instance_id,
            "runtime_started_at": _timestamp(self.runtime_started_at),
            "transcript_digest": self.transcript_digest,
        }


@dataclass(frozen=True)
class VerifiedCandidateEvidenceSet:
    evidence_set_id: str
    admission_id: str
    admission_digest: str
    facts_digest: str
    final_order_snapshot_digest: str
    verified_at: datetime
    facts: Mapping[str, object]
    idempotent_replay: bool = False

    def to_public_dict(self) -> dict[str, object]:
        return {
            "admission_digest": self.admission_digest,
            "admission_id": self.admission_id,
            "evidence_set_id": self.evidence_set_id,
            "facts_digest": self.facts_digest,
            "final_order_snapshot_digest": self.final_order_snapshot_digest,
            "idempotent_replay": self.idempotent_replay,
            "verified_at": _timestamp(self.verified_at),
        }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_timestamp",
            "candidate evidence timestamp must be timezone-aware",
        )
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or len(value) > 128:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_timestamp",
            f"{field} is not a bounded timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_timestamp",
            f"{field} is not a valid timestamp",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_timestamp",
            f"{field} is not timezone-aware",
        )
    return parsed.astimezone(UTC)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_reference",
            f"{field} is not a bounded identifier",
        )
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_digest",
            f"{field} is not a lowercase SHA-256 digest",
        )
    return value


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def canonical_transcript_observation(
    document: Mapping[str, object],
    *,
    expected_session_id: str,
) -> tuple[str, int, dict[str, int]]:
    """Return a stable digest/counts for one complete Hermes transcript."""

    if document.get("session_id") != expected_session_id:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_session_mismatch",
            "Hermes transcript substituted the requested Session",
        )
    omitted = document.get("omitted_message_count")
    messages = document.get("data")
    if (
        isinstance(omitted, bool)
        or not isinstance(omitted, int)
        or omitted != 0
        or not isinstance(messages, list)
    ):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_incomplete_transcript",
            "Hermes transcript must be complete and untruncated",
        )
    canonical_messages: list[dict[str, object]] = []
    counts = {"assistant": 0, "user": 0}
    seen_ids: set[str] = set()
    for raw in messages:
        if not isinstance(raw, Mapping):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_transcript",
                "Hermes transcript contains a non-object message",
            )
        message_id = raw.get("id")
        role = raw.get("role")
        content = raw.get("content")
        if (
            not isinstance(message_id, str)
            or not message_id
            or len(message_id) > 256
            or message_id in seen_ids
            or role not in counts
            or not isinstance(content, str)
            or not content.strip()
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_transcript",
                "Hermes transcript message identity is invalid",
            )
        seen_ids.add(message_id)
        counts[str(role)] += 1
        canonical_messages.append(
            {
                "content": content,
                "fork_point": raw.get("fork_point"),
                "id": message_id,
                "role": role,
                "timestamp": raw.get("timestamp"),
            }
        )
    payload: dict[str, object] = {
        "messages": canonical_messages,
        "session_id": expected_session_id,
    }
    return _canonical_digest(payload), len(canonical_messages), counts


def _canonical_event_timestamp(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_invalid_run_event",
            f"{field} is not a valid Hermes event timestamp",
        )
    if isinstance(value, int | float):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        except (OSError, OverflowError, ValueError) as exc:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_run_event",
                f"{field} is not a valid Hermes event timestamp",
            ) from exc
    else:
        parsed = _parse_timestamp(value, field)
    return _timestamp(parsed)


def _validated_run_event_log(
    events: Sequence[Mapping[str, object]],
    *,
    run_id: str,
) -> tuple[Mapping[str, object], ...]:
    _identifier(run_id, "run_id")
    if not events or len(events) > 4096:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_incomplete_run_events",
            "Hermes Run event replay must be non-empty and bounded",
        )
    validated: list[Mapping[str, object]] = []
    event_ids: set[str] = set()
    for expected_seq, event in enumerate(events, start=1):
        if (
            not isinstance(event, Mapping)
            or event.get("run_id") != run_id
            or event.get("seq") != expected_seq
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_incomplete_run_events",
                "Hermes Run event replay is not exact and gap-free",
            )
        event_id = _identifier(event.get("event_id"), "run event_id")
        event_kind = _identifier(event.get("event"), "run event kind")
        if event_id in event_ids or not event_kind:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_run_event",
                "Hermes Run event identity is invalid",
            )
        event_ids.add(event_id)
        _canonical_event_timestamp(event.get("timestamp"), "run event timestamp")
        validated.append(event)
    return tuple(validated)


def _exact_approval_event(
    events: Sequence[Mapping[str, object]],
    *,
    kind: str,
    challenge_id: str,
    approval_id: str,
    action_digest: str,
) -> Mapping[str, object]:
    matches = [
        event
        for event in events
        if event.get("event") == kind
        and event.get("challenge_id") == challenge_id
    ]
    if (
        len(matches) != 1
        or matches[0].get("approval_id") != approval_id
        or matches[0].get("action_digest") != action_digest
    ):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_approval_chain_mismatch",
            "Hermes approval CAS event chain is incomplete or substituted",
        )
    return matches[0]


def canonical_approval_control_evidence(
    events: Sequence[Mapping[str, object]],
    *,
    run_id: str,
    workspace_id: str,
    control_command_id: str,
    client_action_id: str,
    canonical_request_digest: str,
) -> dict[str, object]:
    """Bind one Platform approval intent to one complete official Hermes CAS.

    The Platform digest is recomputed from the exact request/decision facts in
    the durable Hermes event log.  This prevents a nearby challenge, Run, or
    decision from being substituted into candidate evidence.
    """

    validated = _validated_run_event_log(events, run_id=run_id)
    workspace = WorkspaceRef(_identifier(workspace_id, "workspace_id"))
    control_command_id = _identifier(control_command_id, "approval control_command_id")
    client_action_id = _identifier(client_action_id, "approval client_action_id")
    expected_digest = _digest(
        canonical_request_digest,
        "approval canonical_request_digest",
    )
    matches: list[dict[str, object]] = []
    requests = [event for event in validated if event.get("event") == "approval.request"]
    for request in requests:
        try:
            challenge_id = _identifier(request.get("challenge_id"), "challenge_id")
            approval_id = _identifier(request.get("approval_id"), "approval_id")
            action_digest = _digest(
                request.get("action_digest"),
                "approval action_digest",
            )
            expires_at = _canonical_event_timestamp(
                request.get("expires_at"),
                "approval expires_at",
            )
            choices = request.get("choices")
            if (
                not isinstance(choices, list | tuple)
                or "once" not in choices
                or "deny" not in choices
            ):
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_approval_chain_mismatch",
                    "Hermes approval request does not expose once and deny",
                )
            decision_event = _exact_approval_event(
                validated,
                kind="approval.decision_recorded",
                challenge_id=challenge_id,
                approval_id=approval_id,
                action_digest=action_digest,
            )
            release_event = _exact_approval_event(
                validated,
                kind="approval.release_committed",
                challenge_id=challenge_id,
                approval_id=approval_id,
                action_digest=action_digest,
            )
            signalled_event = _exact_approval_event(
                validated,
                kind="approval.signalled",
                challenge_id=challenge_id,
                approval_id=approval_id,
                action_digest=action_digest,
            )
            choice = decision_event.get("choice")
            if (
                choice not in {"once", "deny"}
                or release_event.get("choice") != choice
                or signalled_event.get("choice") != choice
                or release_event.get("decision_status") != "committed"
                or signalled_event.get("decision_status") != "committed"
                or signalled_event.get("waiter_signal_status") != "confirmed"
                or not (
                    int(request["seq"])
                    < int(decision_event["seq"])
                    < int(release_event["seq"])
                    < int(signalled_event["seq"])
                )
            ):
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_approval_chain_mismatch",
                    "Hermes approval decision/release/signal chain is invalid",
                )
            action = DecideHermesCommandApproval(
                client_action_id=client_action_id,
                workspace=workspace,
                approval_ref=f"approval:{challenge_id}",
                run_ref=f"run:{run_id}",
                command_digest=action_digest,
                expected_status="pending",
                expected_expires_at=expires_at,
                decision="allow_once" if choice == "once" else "deny",
            )
        except CandidateEvidenceV3Error:
            raise
        except (TypeError, ValueError) as exc:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_approval_chain_mismatch",
                "Hermes approval CAS event chain is invalid",
            ) from exc
        if canonical_action_digest(action) != expected_digest:
            continue
        matches.append(
            {
                "action_digest": expected_digest,
                "approval_id": approval_id,
                "challenge_id": challenge_id,
                "choice": choice,
                "command_digest": action_digest,
                "control_command_id": control_command_id,
                "decision": "allow_once" if choice == "once" else "deny",
                "event_ids": [
                    str(request["event_id"]),
                    str(decision_event["event_id"]),
                    str(release_event["event_id"]),
                    str(signalled_event["event_id"]),
                ],
                "expected_expires_at": expires_at,
                "route": "/hermes",
                "run_id": run_id,
                "waiter_signal_status": "confirmed",
            }
        )
    if len(matches) != 1:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_approval_control_mismatch",
            "Platform approval intent does not bind one exact Hermes CAS chain",
        )
    return matches[0]


def canonical_stop_control_evidence(
    events: Sequence[Mapping[str, object]],
    *,
    run_status: Mapping[str, object],
    run_id: str,
    workspace_id: str,
    control_command_id: str,
    client_action_id: str,
    canonical_request_digest: str,
) -> dict[str, object]:
    """Bind one Platform stop intent to durable intent + cancelled Run facts."""

    validated = _validated_run_event_log(events, run_id=run_id)
    if (
        not isinstance(run_status, Mapping)
        or run_status.get("object") != "hermes.run"
        or run_status.get("run_id") != run_id
        or run_status.get("status") != "stopped"
    ):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_stop_not_terminal",
            "Hermes Run stop is not durably terminal",
        )
    requested = [event for event in validated if event.get("event") == "run.stop_requested"]
    cancelled = [event for event in validated if event.get("event") == "run.cancelled"]
    if (
        len(requested) != 1
        or len(cancelled) != 1
        or int(requested[0]["seq"]) >= int(cancelled[0]["seq"])
    ):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_stop_chain_mismatch",
            "Hermes stop intent/cancellation chain is incomplete or substituted",
        )
    action = RequestStop(
        client_action_id=_identifier(client_action_id, "stop client_action_id"),
        workspace=WorkspaceRef(_identifier(workspace_id, "workspace_id")),
        run_ref=f"run:{_identifier(run_id, 'run_id')}",
        task_ref=None,
        attempt_ref=None,
        platform_job_ref=None,
    )
    expected_digest = _digest(
        canonical_request_digest,
        "stop canonical_request_digest",
    )
    if canonical_action_digest(action) != expected_digest:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_stop_control_mismatch",
            "Platform stop intent does not bind the cancelled Hermes Run",
        )
    return {
        "action_digest": expected_digest,
        "control_command_id": _identifier(
            control_command_id,
            "stop control_command_id",
        ),
        "idempotent_recovery_proven": True,
        "route": "/hermes",
        "run_id": run_id,
        "status": "stopped",
        "stop_requested_at": _canonical_event_timestamp(
            requested[0].get("timestamp"),
            "stop requested timestamp",
        ),
        "stop_requested_event_id": str(requested[0]["event_id"]),
        "terminal_event_id": str(cancelled[0]["event_id"]),
        "terminal_event": "run.cancelled",
    }


def _runtime_capability_identity(
    capabilities: Mapping[str, object],
) -> tuple[str, datetime]:
    runtime = capabilities.get("runtime")
    if not isinstance(runtime, Mapping):
        raise CandidateEvidenceV3Error(
            "candidate_evidence_runtime_identity_unavailable",
            "Hermes capability runtime identity is unavailable",
        )
    instance_id = runtime.get("instance_id")
    if not isinstance(instance_id, str) or _INSTANCE_RE.fullmatch(instance_id) is None:
        raise CandidateEvidenceV3Error(
            "candidate_evidence_runtime_identity_unavailable",
            "Hermes capability instance identity is unavailable",
        )
    return instance_id, _parse_timestamp(
        runtime.get("started_at"),
        "Hermes capability runtime.started_at",
    )


def _candidate_evidence_schema_catalog(
    conn: psycopg.Connection,
) -> dict[str, object]:
    """Return the complete catalog surface that authorizes v3 evidence."""

    table_names = list(_CANDIDATE_EVIDENCE_TABLES)
    columns = conn.execute(
        """
        SELECT relation.relname,
               attribute.attnum,
               attribute.attname,
               format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               COALESCE(
                   pg_get_expr(default_value.adbin, default_value.adrelid),
                   ''
               )
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
        LEFT JOIN pg_attrdef AS default_value
          ON default_value.adrelid = relation.oid
         AND default_value.adnum = attribute.attnum
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY relation.relname, attribute.attnum
        """,
        (SCHEMA, table_names),
    ).fetchall()
    constraints = conn.execute(
        """
        SELECT relation.relname,
               constraint_row.conname,
               constraint_row.contype,
               constraint_row.convalidated,
               pg_get_constraintdef(constraint_row.oid, TRUE)
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation
          ON relation.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        ORDER BY relation.relname, constraint_row.conname
        """,
        (SCHEMA, table_names),
    ).fetchall()
    indexes = conn.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s
          AND tablename = ANY(%s)
        ORDER BY tablename, indexname
        """,
        (SCHEMA, table_names[1:]),
    ).fetchall()
    triggers = conn.execute(
        """
        SELECT relation.relname,
               trigger_row.tgname,
               trigger_row.tgenabled,
               function_row.proname,
               function_namespace.nspname,
               pg_get_triggerdef(trigger_row.oid, TRUE)
        FROM pg_trigger AS trigger_row
        JOIN pg_class AS relation
          ON relation.oid = trigger_row.tgrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS function_row
          ON function_row.oid = trigger_row.tgfoid
        JOIN pg_namespace AS function_namespace
          ON function_namespace.oid = function_row.pronamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND NOT trigger_row.tgisinternal
        ORDER BY relation.relname, trigger_row.tgname
        """,
        (SCHEMA, table_names),
    ).fetchall()
    relations = conn.execute(
        """
        SELECT relation.relname,
               relation.relrowsecurity,
               relation.relforcerowsecurity,
               pg_get_userbyid(relation.relowner)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        ORDER BY relation.relname
        """,
        (SCHEMA, table_names),
    ).fetchall()
    policies = conn.execute(
        """
        SELECT relation.relname,
               policy.polname,
               policy.polcmd,
               COALESCE(pg_get_expr(policy.polqual, policy.polrelid), ''),
               COALESCE(
                   pg_get_expr(policy.polwithcheck, policy.polrelid),
                   ''
               ),
               ARRAY(
                   SELECT role.rolname::text
                   FROM unnest(policy.polroles) AS item(role_oid)
                   JOIN pg_roles AS role ON role.oid = item.role_oid
                   ORDER BY role.rolname::text
               )
        FROM pg_policy AS policy
        JOIN pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        ORDER BY relation.relname, policy.polname
        """,
        (SCHEMA, table_names),
    ).fetchall()
    functions = conn.execute(
        """
        SELECT function_row.proname,
               pg_get_userbyid(function_row.proowner),
               function_row.prosecdef,
               function_namespace.nspname,
               pg_get_functiondef(function_row.oid)
        FROM pg_proc AS function_row
        JOIN pg_namespace AS function_namespace
          ON function_namespace.oid = function_row.pronamespace
        WHERE function_namespace.nspname = %s
          AND function_row.proname = ANY(%s)
        ORDER BY function_row.proname
        """,
        (SCHEMA, list(_CANDIDATE_EVIDENCE_FUNCTIONS)),
    ).fetchall()

    def normalized(
        rows: list[tuple[object, ...]],
    ) -> list[list[object]]:
        result: list[list[object]] = []
        for row in rows:
            values: list[object] = []
            for value in row:
                if isinstance(value, list):
                    values.append([str(item) for item in value])
                elif isinstance(value, bool | int):
                    values.append(value)
                else:
                    values.append(" ".join(str(value).split()))
            result.append(values)
        return result

    return {
        "columns": normalized(columns),
        "constraints": normalized(constraints),
        "functions": normalized(functions),
        "indexes": normalized(indexes),
        "policies": normalized(policies),
        "relations": normalized(relations),
        "triggers": normalized(triggers),
    }


def _candidate_evidence_schema_signature(
    conn: psycopg.Connection,
) -> str:
    return _canonical_digest(_candidate_evidence_schema_catalog(conn))


def candidate_evidence_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    relation = conn.execute(
        """
        SELECT count(*) = %s
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        """,
        (
            len(_CANDIDATE_EVIDENCE_TABLES),
            SCHEMA,
            list(_CANDIDATE_EVIDENCE_TABLES),
        ),
    ).fetchone()
    if relation != (True,):
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_candidate_evidence_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (1,):
        return False
    return _candidate_evidence_schema_signature(conn) in _CANDIDATE_EVIDENCE_SCHEMA_SIGNATURES


def candidate_evidence_runtime_security_is_ready(
    settings: Settings,
) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            if not candidate_evidence_schema_is_ready_on_connection(conn):
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
                    pg_has_role(
                        session_user,
                        'quant_runtime',
                        'MEMBER'
                    ),
                    NOT pg_has_role(
                        session_user,
                        'quant_migrator',
                        'MEMBER'
                    ),
                    has_schema_privilege(
                        session_user,
                        %s,
                        'USAGE'
                    ),
                    NOT has_schema_privilege(
                        session_user,
                        %s,
                        'CREATE'
                    )
                """,
                (SCHEMA, SCHEMA),
            ).fetchone()
            if principal is None or not all(bool(value) for value in principal):
                return False
            meta_relation = f"{SCHEMA}.agent_v02_candidate_evidence_meta"
            meta_privileges = conn.execute(
                """
                SELECT
                    has_table_privilege(session_user, %s, 'SELECT'),
                    has_table_privilege(session_user, %s, 'INSERT'),
                    has_table_privilege(session_user, %s, 'UPDATE'),
                    has_table_privilege(session_user, %s, 'DELETE'),
                    has_table_privilege(session_user, %s, 'TRUNCATE'),
                    has_table_privilege(session_user, %s, 'REFERENCES'),
                    has_table_privilege(session_user, %s, 'TRIGGER')
                """,
                (
                    meta_relation,
                    meta_relation,
                    meta_relation,
                    meta_relation,
                    meta_relation,
                    meta_relation,
                    meta_relation,
                ),
            ).fetchone()
            if meta_privileges != (
                True,
                False,
                False,
                False,
                False,
                False,
                False,
            ):
                return False
            rows = conn.execute(
                """
                SELECT
                    relation.relname,
                    owner.rolname,
                    relation.relrowsecurity,
                    relation.relforcerowsecurity,
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'SELECT'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'INSERT'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'UPDATE'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'DELETE'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'TRUNCATE'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'REFERENCES'
                    ),
                    has_table_privilege(
                        session_user,
                        format(
                            '%%I.%%I',
                            namespace.nspname,
                            relation.relname
                        ),
                        'TRIGGER'
                    )
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_roles AS owner
                  ON owner.oid = relation.relowner
                WHERE namespace.nspname = %s
                  AND relation.relname = ANY(%s)
                ORDER BY relation.relname
                """,
                (
                    SCHEMA,
                    [
                        "agent_v02_candidate_restart_observations",
                        "agent_v02_candidate_evidence_sets",
                    ],
                ),
            ).fetchall()
            if len(rows) != 2:
                return False
            return all(
                str(row[1]) == "quant_migrator"
                and row[2] is True
                and row[3] is True
                and row[4] is True
                and row[5] is True
                and row[6] is False
                and row[7] is False
                and row[8] is False
                and row[9] is False
                and row[10] is False
                for row in rows
            )
    except (DatabaseUnavailable, psycopg.Error):
        return False


class CandidateEvidenceV3Authority:
    """Capture restart observations and freeze one verified fact set."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database,
        gateway: CandidateEvidenceGateway | None = None,
        hqa_probe: Callable[[str, Sequence[str]], Mapping[str, object]] | None = None,
        promotion_probe: Callable[[str], Mapping[str, object]] | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._gateway = gateway or OfficialHermesRunControlClient(
            settings.hermes_gateway
        )
        self._hqa_probe = hqa_probe or self._invoke_hqa_workflow
        self._promotion_probe = promotion_probe or self._promotion_status

    @staticmethod
    def _clock(conn: psycopg.Connection) -> datetime:
        row = conn.execute("SELECT clock_timestamp()").fetchone()
        if row is None or not isinstance(row[0], datetime):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_database_clock_unavailable",
                "PostgreSQL clock is unavailable",
            )
        return row[0].astimezone(UTC)

    @staticmethod
    def _lock(conn: psycopg.Connection, workspace_id: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"agent-v02-candidate:{workspace_id}",),
        )

    def _candidate(
        self,
        conn: psycopg.Connection,
        admission_id: str,
        admission_digest: str,
        *,
        lock: bool = False,
    ) -> Mapping[str, object]:
        row = conn.execute(
            f"""
            SELECT
                admission_id,
                workspace_id,
                admission_digest,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest,
                status,
                opened_at,
                expires_at
            FROM {SCHEMA}.agent_v02_candidate_admissions
            WHERE owner_user_id = %s
              AND admission_id = %s
              AND admission_digest = %s
            {"FOR UPDATE" if lock else ""}
            """,
            (ROOT_USER_ID, admission_id, admission_digest),
        ).fetchone()
        if row is None:
            raise CandidateAdmissionConflict("exact candidate admission does not exist")
        keys = (
            "admission_id",
            "workspace_id",
            "admission_digest",
            "platform_runtime_digest",
            "hqa_runtime_digest",
            "hermes_runtime_digest",
            "database_schema_fingerprint",
            "baseline_order_snapshot_digest",
            "status",
            "opened_at",
            "expires_at",
        )
        document = dict(zip(keys, row, strict=True))
        clock = self._clock(conn)
        if document["status"] != "open" or document["expires_at"] <= clock:
            raise CandidateAdmissionConflict("candidate admission is not open and unexpired")
        return document

    def capture_restart(
        self,
        *,
        admission_id: str,
        admission_digest: str,
        phase: Literal["before", "after"],
        platform_session_id: str,
    ) -> CandidateRestartObservation:
        admission_id = _identifier(admission_id, "admission_id")
        admission_digest = _digest(admission_digest, "admission_digest")
        platform_session_id = _identifier(platform_session_id, "platform_session_id")
        if phase not in {"before", "after"}:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_phase",
                "restart phase must be before or after",
            )
        try:
            with self._database.connect() as conn:
                candidate = self._candidate(conn, admission_id, admission_digest)
                session = conn.execute(
                    f"""
                    SELECT hermes_session_id
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND platform_session_id = %s
                      AND candidate_admission_id = %s
                      AND kind = 'web_managed_session'
                      AND provision_state = 'ready'
                    """,
                    (
                        ROOT_USER_ID,
                        candidate["workspace_id"],
                        platform_session_id,
                        admission_id,
                    ),
                ).fetchone()
            if session is None:
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_session_unavailable",
                    "restart capture requires an exact ready candidate Session",
                )
            hermes_session_id = str(session[0])
            instance_id, started_at = _runtime_capability_identity(self._gateway.capabilities())
            transcript_digest, message_count, counts = canonical_transcript_observation(
                self._gateway.session_messages(hermes_session_id),
                expected_session_id=hermes_session_id,
            )
            confirmed_instance_id, confirmed_started_at = _runtime_capability_identity(
                self._gateway.capabilities()
            )
            if confirmed_instance_id != instance_id or confirmed_started_at != started_at:
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_runtime_changed_during_capture",
                    "Hermes restarted while restart evidence was being captured",
                )
            if counts["user"] < 2 or counts["assistant"] < 2:
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_multiturn_missing",
                    "restart capture requires at least two complete turns",
                )
            observation_payload: dict[str, object] = {
                "admission_id": admission_id,
                "hermes_session_id": hermes_session_id,
                "message_count": message_count,
                "phase": phase,
                "platform_session_id": platform_session_id,
                "runtime_instance_id": instance_id,
                "runtime_started_at": _timestamp(started_at),
                "transcript_digest": transcript_digest,
            }
            observation_id = f"restart_{_canonical_digest(observation_payload)[:32]}"
            with self._database.connect() as conn, conn.transaction():
                self._lock(conn, str(candidate["workspace_id"]))
                self._candidate(
                    conn,
                    admission_id,
                    admission_digest,
                    lock=True,
                )
                row = conn.execute(
                    f"""
                    INSERT INTO
                        {SCHEMA}.agent_v02_candidate_restart_observations (
                            observation_id,
                            owner_user_id,
                            workspace_id,
                            admission_id,
                            admission_digest,
                            phase,
                            platform_session_id,
                            hermes_session_id,
                            runtime_instance_id,
                            runtime_started_at,
                            transcript_digest,
                            message_count
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (admission_id, phase) DO NOTHING
                    RETURNING observed_at
                    """,
                    (
                        observation_id,
                        ROOT_USER_ID,
                        candidate["workspace_id"],
                        admission_id,
                        admission_digest,
                        phase,
                        platform_session_id,
                        hermes_session_id,
                        instance_id,
                        started_at,
                        transcript_digest,
                        message_count,
                    ),
                ).fetchone()
                if row is None:
                    existing = conn.execute(
                        f"""
                        SELECT
                            observation_id,
                            platform_session_id,
                            hermes_session_id,
                            runtime_instance_id,
                            runtime_started_at,
                            transcript_digest,
                            message_count,
                            observed_at
                        FROM
                            {SCHEMA}.agent_v02_candidate_restart_observations
                        WHERE admission_id = %s AND phase = %s
                        """,
                        (admission_id, phase),
                    ).fetchone()
                    expected = (
                        observation_id,
                        platform_session_id,
                        hermes_session_id,
                        instance_id,
                        started_at,
                        transcript_digest,
                        message_count,
                    )
                    if existing is None or tuple(existing[:7]) != expected:
                        raise CandidateAdmissionConflict(
                            "restart phase already has different evidence"
                        )
                    observed_at = existing[7]
                else:
                    observed_at = row[0]
            return CandidateRestartObservation(
                observation_id=observation_id,
                admission_id=admission_id,
                phase=phase,
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
                runtime_instance_id=instance_id,
                runtime_started_at=started_at,
                transcript_digest=transcript_digest,
                message_count=message_count,
                observed_at=observed_at,
            )
        except (
            CandidateAdmissionConflict,
            CandidateEvidenceV3Error,
        ):
            raise
        except (HermesApiReadError, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable(
                "candidate restart evidence authority is unavailable"
            ) from exc

    def _chat_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
        workspace_id: str,
    ) -> dict[str, object]:
        if len(refs.web_command_ids) < 2 or len(set(refs.web_command_ids)) != len(
            refs.web_command_ids
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_multiturn_missing",
                "multi-turn evidence requires distinct command identities",
            )
        for command_id in refs.web_command_ids:
            _identifier(command_id, "web_command_id")
        rows = conn.execute(
            f"""
            SELECT
                command.command_id::text,
                command.hermes_session_id,
                command.hermes_run_id,
                command.state,
                terminal.event_id
            FROM {SCHEMA}.hermes_commands AS command
            JOIN {SCHEMA}.hermes_workspace_sessions AS session
              ON session.platform_session_id =
                    command.platform_session_id
             AND session.owner_user_id = command.owner_user_id
            JOIN LATERAL (
                SELECT event.event_id
                FROM {SCHEMA}.hermes_command_events AS event
                WHERE event.command_id = command.command_id
                  AND event.to_state = 'succeeded'
                  AND event.hermes_session_id =
                        command.hermes_session_id
                  AND event.hermes_run_id = command.hermes_run_id
                ORDER BY event.command_version DESC
                LIMIT 1
            ) AS terminal ON TRUE
            WHERE command.owner_user_id = %s
              AND command.platform_session_id = %s
              AND command.candidate_admission_id = %s
              AND command.kind = 'conversation_turn'
              AND command.command_id::text = ANY(%s)
              AND command.state = 'succeeded'
              AND command.hermes_session_id IS NOT NULL
              AND command.hermes_run_id IS NOT NULL
              AND session.workspace_id = %s
              AND session.kind = 'web_managed_session'
              AND session.provision_state = 'ready'
              AND session.candidate_admission_id = %s
            ORDER BY command.created_at, command.command_id
            """,
            (
                ROOT_USER_ID,
                refs.web_platform_session_id,
                refs.admission_id,
                list(refs.web_command_ids),
                workspace_id,
                refs.admission_id,
            ),
        ).fetchall()
        if {str(row[0]) for row in rows} != set(refs.web_command_ids):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_multiturn_missing",
                "multi-turn commands are not exact succeeded candidate facts",
            )
        hermes_sessions = {str(row[1]) for row in rows}
        run_ids = [str(row[2]) for row in rows]
        if len(hermes_sessions) != 1 or len(set(run_ids)) != len(run_ids):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_multiturn_mismatch",
                "multi-turn commands do not share one Session and distinct Runs",
            )
        hermes_session_id = next(iter(hermes_sessions))
        transcript_digest, message_count, counts = canonical_transcript_observation(
            self._gateway.session_messages(hermes_session_id),
            expected_session_id=hermes_session_id,
        )
        if counts["user"] < 2 or counts["assistant"] < 2:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_multiturn_missing",
                "Hermes canonical history does not contain two complete turns",
            )
        return {
            "assistant_message_count": counts["assistant"],
            "command_ids": sorted(str(row[0]) for row in rows),
            "hermes_session_id": hermes_session_id,
            "message_count": message_count,
            "platform_session_id": refs.web_platform_session_id,
            "route": "/hermes",
            "run_ids": sorted(run_ids),
            "terminal_event_ids": sorted(int(row[4]) for row in rows),
            "transcript_digest": transcript_digest,
            "user_message_count": counts["user"],
        }

    def _restart_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
    ) -> dict[str, object]:
        rows = conn.execute(
            f"""
            SELECT
                observation_id,
                phase,
                platform_session_id,
                hermes_session_id,
                runtime_instance_id,
                runtime_started_at,
                transcript_digest,
                message_count,
                observed_at
            FROM {SCHEMA}.agent_v02_candidate_restart_observations
            WHERE owner_user_id = %s
              AND admission_id = %s
              AND admission_digest = %s
            ORDER BY phase
            """,
            (ROOT_USER_ID, refs.admission_id, refs.admission_digest),
        ).fetchall()
        by_phase = {str(row[1]): row for row in rows}
        if set(by_phase) != {"before", "after"}:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_restart_missing",
                "both restart observations are required",
            )
        before = by_phase["before"]
        after = by_phase["after"]
        if (
            str(before[2]) != refs.web_platform_session_id
            or before[2] != after[2]
            or before[3] != after[3]
            or before[4] == after[4]
            or before[5] >= after[5]
            or before[6] != after[6]
            or before[8] >= after[8]
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_restart_mismatch",
                "restart observations do not prove stable history across a fresh instance",
            )
        return {
            "after_observation_id": str(after[0]),
            "before_observation_id": str(before[0]),
            "hermes_session_id": str(before[3]),
            "message_count": int(before[7]),
            "platform_session_id": str(before[2]),
            "post_restart_instance_id": str(after[4]),
            "post_restart_observed_at": _timestamp(after[8]),
            "post_restart_started_at": _timestamp(after[5]),
            "pre_restart_instance_id": str(before[4]),
            "route": "/hermes",
            "transcript_digest": str(before[6]),
        }

    def _control_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
        workspace_id: str,
        candidate: Mapping[str, object],
        restart: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Verify approval + stop against Platform intent and Hermes Run facts."""

        control_ids = (refs.approval_command_id, refs.stop_command_id)
        rows = conn.execute(
            f"""
            SELECT
                command.command_id::text,
                command.client_request_id,
                command.kind,
                command.canonical_request_digest,
                command.created_at,
                command.state,
                outcome.event_data
            FROM {SCHEMA}.hermes_commands AS command
            JOIN LATERAL (
                SELECT event.event_data
                FROM {SCHEMA}.hermes_command_events AS event
                WHERE event.command_id = command.command_id
                  AND event.command_version = command.version
                  AND event.actor = 'bff'
                  AND event.event_type = 'run_control.succeeded'
                  AND event.to_state = 'succeeded'
                LIMIT 1
            ) AS outcome ON TRUE
            WHERE command.owner_user_id = %s
              AND command.platform_session_id = %s
              AND command.command_id::text = ANY(%s)
              AND command.kind IN (
                    'hermes_command_approval_decide',
                    'run_stop_request'
              )
              AND command.state = 'succeeded'
              AND command.created_at >= %s
              AND command.created_at <= %s
            """,
            (
                ROOT_USER_ID,
                control_plane_session_id(workspace_id),
                list(control_ids),
                candidate["opened_at"],
                candidate["expires_at"],
            ),
        ).fetchall()
        controls = {str(row[0]): row for row in rows}
        if (
            set(controls) != set(control_ids)
            or controls[refs.approval_command_id][2]
            != "hermes_command_approval_decide"
            or controls[refs.stop_command_id][2] != "run_stop_request"
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_control_command_missing",
                "exact candidate-window approval/stop commands are unavailable",
            )
        for control_id, row in controls.items():
            receipt = row[6]
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("contract")
                != "agent-v0.2-run-control-outcome/v1"
                or receipt.get("action_digest") != str(row[3]).strip()
                or receipt.get("action_kind") != row[2]
                or receipt.get("outcome_status") != "succeeded"
                or receipt.get("reason_code") is not None
                or not isinstance(receipt.get("target_run_id"), str)
            ):
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_control_outcome_mismatch",
                    f"control outcome {control_id} is not exact and terminal",
                )

        run_rows = conn.execute(
            f"""
            SELECT
                command.command_id::text,
                command.hermes_run_id,
                command.state,
                command.resolved_hermes_session_id
            FROM {SCHEMA}.hermes_commands AS command
            JOIN {SCHEMA}.hermes_workspace_sessions AS session
              ON session.owner_user_id = command.owner_user_id
             AND session.platform_session_id = command.platform_session_id
             AND session.hermes_session_id = command.hermes_session_id
            WHERE command.owner_user_id = %s
              AND command.candidate_admission_id = %s
              AND command.kind = 'conversation_turn'
              AND command.hermes_run_id IS NOT NULL
              AND command.state IN ('succeeded', 'failed', 'cancelled')
              AND session.workspace_id = %s
              AND session.kind = 'web_managed_session'
              AND session.provision_state = 'ready'
              AND session.candidate_admission_id = %s
            ORDER BY command.created_at, command.command_id
            """,
            (
                ROOT_USER_ID,
                refs.admission_id,
                workspace_id,
                refs.admission_id,
            ),
        ).fetchall()
        if (
            not run_rows
            or len(run_rows) > 64
            or len({str(row[1]) for row in run_rows}) != len(run_rows)
            or any(not isinstance(row[3], str) for row in run_rows)
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_control_run_missing",
                "candidate control evidence requires a bounded exact Run set",
            )

        instance_before, started_before = _runtime_capability_identity(
            self._gateway.capabilities()
        )
        if (
            instance_before != restart.get("post_restart_instance_id")
            or _timestamp(started_before) != restart.get("post_restart_started_at")
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_control_restart_mismatch",
                "control evidence is not read from the captured post-restart runtime",
            )

        event_logs: dict[str, tuple[dict[str, object], ...]] = {}
        statuses: dict[str, dict[str, object]] = {}
        for row in run_rows:
            run_id = str(row[1])
            event_logs[run_id] = self._gateway.run_events(run_id)
            statuses[run_id] = self._gateway.run_status(run_id)

        instance_after, started_after = _runtime_capability_identity(
            self._gateway.capabilities()
        )
        if (
            instance_after != instance_before
            or started_after != started_before
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_runtime_changed_during_capture",
                "Hermes restarted while control evidence was being verified",
            )

        approval_control = controls[refs.approval_command_id]
        approval_matches: list[dict[str, object]] = []
        stop_control = controls[refs.stop_command_id]
        stop_matches: list[dict[str, object]] = []
        for (
            target_command_id,
            raw_run_id,
            platform_state,
            resolved_session_id,
        ) in run_rows:
            run_id = str(raw_run_id)
            events = event_logs[run_id]
            event_names = {
                str(event.get("event"))
                for event in events
                if isinstance(event, Mapping)
            }
            if (
                run_id == controls[refs.approval_command_id][6]["target_run_id"]
                and "approval.request" in event_names
                and platform_state == "succeeded"
            ):
                try:
                    approval = canonical_approval_control_evidence(
                        events,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        control_command_id=refs.approval_command_id,
                        client_action_id=str(approval_control[1]),
                        canonical_request_digest=str(approval_control[3]).strip(),
                    )
                except CandidateEvidenceV3Error as exc:
                    if exc.code != "candidate_evidence_approval_control_mismatch":
                        raise
                else:
                    if (
                        statuses[run_id].get("status") != "succeeded"
                        or statuses[run_id].get("session_id")
                        != resolved_session_id
                    ):
                        raise CandidateEvidenceV3Error(
                            "candidate_evidence_approval_run_not_terminal",
                            "approved Hermes Run is not durably succeeded",
                        )
                    approval.update(
                        {
                            "platform_command_id": str(target_command_id),
                            "platform_command_state": "succeeded",
                            "run_status": "succeeded",
                        }
                    )
                    approval_matches.append(approval)
            if (
                "run.stop_requested" in event_names
                and platform_state == "cancelled"
                and run_id
                == controls[refs.stop_command_id][6]["target_run_id"]
            ):
                try:
                    stop = canonical_stop_control_evidence(
                        events,
                        run_status=statuses[run_id],
                        run_id=run_id,
                        workspace_id=workspace_id,
                        control_command_id=refs.stop_command_id,
                        client_action_id=str(stop_control[1]),
                        canonical_request_digest=str(stop_control[3]).strip(),
                    )
                except CandidateEvidenceV3Error as exc:
                    if exc.code != "candidate_evidence_stop_control_mismatch":
                        raise
                else:
                    if statuses[run_id].get("session_id") != resolved_session_id:
                        raise CandidateEvidenceV3Error(
                            "candidate_evidence_control_run_mismatch",
                            "stopped Run does not bind the resolved Session tip",
                        )
                    requested_at = _parse_timestamp(
                        stop["stop_requested_at"],
                        "stop_requested_at",
                    )
                    post_restart_observed_at = _parse_timestamp(
                        restart.get("post_restart_observed_at"),
                        "post_restart_observed_at",
                    )
                    if requested_at >= post_restart_observed_at:
                        raise CandidateEvidenceV3Error(
                            "candidate_evidence_stop_restart_mismatch",
                            "stop intent was not committed before the captured restart",
                        )
                    stop.update(
                        {
                            "platform_command_id": str(target_command_id),
                            "platform_command_state": "cancelled",
                            "post_restart_instance_id": instance_after,
                        }
                    )
                    stop_matches.append(stop)
        if len(approval_matches) != 1 or len(stop_matches) != 1:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_control_flow_mismatch",
                "candidate evidence requires one exact approval and one restart-recovered stop",
            )
        if approval_matches[0]["run_id"] == stop_matches[0]["run_id"]:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_control_flow_mismatch",
                "approval and stop evidence must use distinct Hermes Runs",
            )
        return approval_matches[0], stop_matches[0]

    def _fork_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
        workspace_id: str,
    ) -> dict[str, object]:
        row = conn.execute(
            f"""
            SELECT
                source.hermes_session_id,
                source.source_channel,
                child.hermes_session_id,
                child.source_channel,
                child.parent_platform_session_id,
                child.fork_point,
                child.provisioning_receipt_digest,
                COALESCE(
                    child.resolved_source_session_id,
                    source.hermes_session_id
                )
            FROM {SCHEMA}.hermes_workspace_sessions AS source
            JOIN {SCHEMA}.hermes_workspace_sessions AS child
              ON child.parent_platform_session_id =
                    source.platform_session_id
            WHERE source.owner_user_id = %s
              AND source.workspace_id = %s
              AND source.platform_session_id = %s
              AND source.kind = 'observed_external_session'
              AND source.source_channel = 'discord'
              AND child.owner_user_id = source.owner_user_id
              AND child.workspace_id = source.workspace_id
              AND child.platform_session_id = %s
              AND child.kind = 'web_managed_session'
              AND child.writer = 'web_control_plane'
              AND child.provision_state = 'ready'
              AND child.candidate_admission_id = %s
              AND child.fork_point ~ '^message:[1-9][0-9]*$'
            """,
            (
                ROOT_USER_ID,
                workspace_id,
                refs.fork_source_platform_session_id,
                refs.fork_child_platform_session_id,
                refs.admission_id,
            ),
        ).fetchone()
        if row is None:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_fork_missing",
                "exact Discord-to-managed fork lineage is unavailable",
            )
        source_hermes = str(row[0])
        child_hermes = str(row[2])
        fork_point = str(row[5])
        resolved_source_session_id = str(row[7])
        child_detail = self._gateway.session_detail(child_hermes)
        if (
            child_detail.get("id") != child_hermes
            or child_detail.get("parent_session_id") != resolved_source_session_id
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_fork_mismatch",
                "Hermes child lineage does not match the Platform registry",
            )
        source_messages = self._gateway.session_messages(source_hermes)
        source_digest, source_message_count, _ = canonical_transcript_observation(
            source_messages,
            expected_session_id=resolved_source_session_id,
        )
        messages = source_messages.get("data")
        if not isinstance(messages, list) or not any(
            isinstance(message, Mapping) and message.get("fork_point") == fork_point
            for message in messages
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_fork_point_missing",
                "fork point is not an authoritative source message cursor",
            )
        return {
            "child_hermes_session_id": child_hermes,
            "child_platform_session_id": refs.fork_child_platform_session_id,
            "fork_point": fork_point,
            "provisioning_receipt_digest": _digest(row[6], "fork provisioning receipt"),
            "route": "/hermes",
            "resolved_source_session_id": resolved_source_session_id,
            "source_channel": "discord",
            "source_hermes_session_id": source_hermes,
            "source_message_count": source_message_count,
            "source_platform_session_id": refs.fork_source_platform_session_id,
            "source_transcript_digest": source_digest,
        }

    def _options_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
        workspace_id: str,
    ) -> dict[str, object]:
        row = conn.execute(
            f"""
            SELECT
                request.request_id,
                claim.claim_id,
                claim.command_id::text,
                claim.platform_session_id,
                claim.hermes_session_id,
                claim.hermes_run_id,
                claim.admission_digest,
                zero.capture_digest,
                zero.orders_created,
                zero.delta_zero,
                provider.provider_receipt_id,
                provider.provider,
                provider.provider_request_id,
                provider.receipt_digest,
                result.result_id,
                result.status,
                result.sample_or_real,
                result.public_payload_digest,
                outcome.status,
                command.state,
                command.kind,
                command.client_request_id,
                command.canonical_request_digest
            FROM {SCHEMA}.agent_v02_vertical_a_requests AS request
            JOIN {SCHEMA}.agent_v02_vertical_a_claims AS claim
              ON claim.request_id = request.request_id
             AND claim.owner_user_id = request.owner_user_id
             AND claim.workspace_id = request.workspace_id
             AND claim.admission_id = request.admission_id
             AND claim.admission_digest = request.admission_digest
            JOIN
                {SCHEMA}.agent_v02_vertical_a_zero_order_observations
                AS zero
              ON zero.claim_id = claim.claim_id
            JOIN {SCHEMA}.agent_v02_vertical_a_provider_receipts AS provider
              ON provider.claim_id = claim.claim_id
             AND provider.capture_digest = zero.capture_digest
            JOIN {SCHEMA}.agent_v02_vertical_a_results AS result
              ON result.request_id = request.request_id
             AND result.claim_id = claim.claim_id
             AND result.provider_receipt_id =
                    provider.provider_receipt_id
            JOIN {SCHEMA}.agent_v02_vertical_a_outcomes AS outcome
              ON outcome.request_id = request.request_id
             AND outcome.claim_id = claim.claim_id
             AND outcome.result_id = result.result_id
            JOIN {SCHEMA}.hermes_commands AS command
              ON command.command_id = claim.command_id
             AND command.candidate_admission_id =
                    request.admission_id
             AND command.hermes_session_id =
                    claim.hermes_session_id
             AND command.hermes_run_id = claim.hermes_run_id
            WHERE request.owner_user_id = %s
              AND request.workspace_id = %s
              AND request.request_id = %s
              AND request.admission_id = %s
              AND request.admission_digest = %s
              AND zero.orders_created = 0
              AND zero.delta_zero IS TRUE
              AND zero.begin_snapshot_digest =
                    zero.end_snapshot_digest
              AND provider.provider = 'futu'
              AND result.status = 'completed'
              AND result.sample_or_real = 'real'
              AND outcome.status = 'completed'
              AND command.state = 'succeeded'
              AND command.kind = 'conversation_turn'
            """,
            (
                ROOT_USER_ID,
                workspace_id,
                refs.options_request_id,
                refs.admission_id,
                refs.admission_digest,
            ),
        ).fetchone()
        if row is None:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_options_missing",
                "exact live Futu read-only Vertical-A result is unavailable",
            )
        return {
            "admission_digest": str(row[6]).strip(),
            "capture_digest": str(row[7]).strip(),
            "claim_id": str(row[1]),
            "command_id": str(row[2]),
            "hermes_run_id": str(row[5]),
            "hermes_session_id": str(row[4]),
            "ingress": {
                "canonical_request_digest": str(row[22]).strip(),
                "client_request_id": str(row[21]),
                "command_id": str(row[2]),
                "command_kind": str(row[20]),
                "route": "/hermes",
            },
            "orders_created": int(row[8]),
            "platform_session_id": str(row[3]),
            "provider": str(row[11]),
            "provider_receipt_digest": str(row[13]).strip(),
            "provider_receipt_id": str(row[10]),
            "provider_request_id": str(row[12]),
            "request_id": str(row[0]),
            "result_id": str(row[14]),
            "result_payload_digest": str(row[17]).strip(),
            "sample_or_real": str(row[16]),
        }

    def _paper_facts(
        self,
        conn: psycopg.Connection,
        refs: CandidateEvidenceReferences,
        workspace_id: str,
    ) -> dict[str, object]:
        row = conn.execute(
            f"""
            SELECT
                gate1.gate_id,
                gate1.gate1_confirmation_id,
                gate1.reviewed_source_sha256,
                gate1.hqa_receipt_ref,
                gate1.hqa_receipt_digest,
                gate2.gate_id,
                gate2.candidate_id,
                gate2.expected_digest,
                gate2.hqa_receipt_ref,
                gate2.hqa_receipt_digest,
                gate3.gate_id,
                gate3.final_backtest_receipt_id,
                gate3.base_commit,
                gate3.hqa_receipt_ref,
                gate3.hqa_receipt_digest,
                gate3.promotion_id,
                gate3.task_ref,
                gate3.attempt_ref,
                gate3.platform_session_id,
                gate3.hermes_run_id,
                session.hermes_session_id,
                command3.command_id::text,
                gate1.hqa_gate_ref,
                gate2.hqa_gate_ref,
                gate3.hqa_gate_ref,
                gate1.attempt_ref,
                gate2.attempt_ref,
                gate1.command_id::text,
                gate2.command_id::text,
                gate3.command_id::text,
                gate1.hermes_run_id,
                gate2.hermes_run_id,
                gate3.hqa_run_ref,
                gate1.expected_task_version,
                gate2.expected_task_version,
                gate3.expected_task_version,
                completion.reviewed_commit,
                completion.hqa_completion_receipt_ref,
                completion.hqa_completion_receipt_digest,
                completion.task_version,
                completion.task_status,
                completion.task_terminal_outcome,
                completion.attempt_status,
                completion.attempt_terminal_outcome,
                completion.domain_gate_outcome,
                completion.provider_evidence_ref,
                completion.workflow_audit_status,
                completion.workflow_audit_ref,
                completion.workflow_audit_digest,
                completion.attempt_completion_event_id,
                completion.task_completion_event_id
            FROM {SCHEMA}.agent_v02_paper_gate_challenges AS gate3
            JOIN {SCHEMA}.agent_v02_paper_gate_challenges AS gate2
              ON gate2.gate_id = gate3.parent_gate_id
             AND gate2.owner_user_id = gate3.owner_user_id
             AND gate2.workspace_id = gate3.workspace_id
             AND gate2.gate_kind = 'gate2'
             AND gate2.status = 'reviewed'
            JOIN {SCHEMA}.agent_v02_paper_gate_challenges AS gate1
              ON gate1.gate_id = gate2.parent_gate_id
             AND gate1.owner_user_id = gate2.owner_user_id
             AND gate1.workspace_id = gate2.workspace_id
             AND gate1.gate_kind = 'gate1'
             AND gate1.status = 'confirmed'
            JOIN {SCHEMA}.hermes_workspace_sessions AS session
              ON session.platform_session_id =
                    gate3.platform_session_id
             AND session.owner_user_id = gate3.owner_user_id
             AND session.workspace_id = gate3.workspace_id
             AND session.kind = 'web_managed_session'
             AND session.provision_state = 'ready'
             AND session.candidate_admission_id = %s
            JOIN {SCHEMA}.hermes_commands AS command1
              ON command1.command_id = gate1.command_id
             AND command1.owner_user_id = gate3.owner_user_id
             AND command1.platform_session_id =
                    gate3.platform_session_id
             AND command1.hermes_session_id =
                    session.hermes_session_id
             AND command1.hermes_run_id = gate1.hermes_run_id
             AND command1.candidate_admission_id = %s
             AND command1.state = 'succeeded'
            JOIN {SCHEMA}.hermes_commands AS command2
              ON command2.command_id = gate2.command_id
             AND command2.owner_user_id = gate3.owner_user_id
             AND command2.platform_session_id =
                    gate3.platform_session_id
             AND command2.hermes_session_id =
                    session.hermes_session_id
             AND command2.hermes_run_id = gate2.hermes_run_id
             AND command2.candidate_admission_id = %s
             AND command2.state = 'succeeded'
            JOIN {SCHEMA}.hermes_commands AS command3
              ON command3.command_id = gate3.command_id
             AND command3.owner_user_id = gate3.owner_user_id
             AND command3.platform_session_id =
                    gate3.platform_session_id
             AND command3.hermes_session_id =
                    session.hermes_session_id
             AND command3.hermes_run_id = gate3.hermes_run_id
             AND command3.candidate_admission_id = %s
             AND command3.state = 'succeeded'
            JOIN {SCHEMA}.agent_v02_paper_gate_completions AS completion
              ON completion.gate_id = gate3.gate_id
             AND completion.owner_user_id = gate3.owner_user_id
             AND completion.workspace_id = gate3.workspace_id
             AND completion.task_ref = gate3.task_ref
             AND completion.attempt_ref = gate3.attempt_ref
             AND completion.domain_gate_ref = gate3.hqa_gate_ref
             AND completion.hqa_run_ref = gate3.hqa_run_ref
             AND completion.promotion_id = gate3.promotion_id
             AND completion.candidate_id = gate3.candidate_id
             AND completion.candidate_digest = gate3.expected_digest
             AND completion.final_backtest_receipt_id =
                    gate3.final_backtest_receipt_id
             AND completion.base_commit = gate3.base_commit
            WHERE gate3.owner_user_id = %s
              AND gate3.workspace_id = %s
              AND gate3.gate_id = %s
              AND gate3.gate_kind = 'gate3'
              AND gate3.status = 'prepared'
              AND gate3.task_ref = gate2.task_ref
              AND gate3.task_ref = gate1.task_ref
              AND gate2.attempt_ref = gate1.attempt_ref
              AND gate2.hqa_gate_ref = gate1.hqa_gate_ref
              AND gate3.attempt_ref <> gate2.attempt_ref
              AND gate3.hqa_run_ref IS NOT NULL
              AND gate3.platform_session_id =
                    gate2.platform_session_id
              AND gate3.platform_session_id =
                    gate1.platform_session_id
              AND gate1.hermes_session_id =
                    session.hermes_session_id
              AND gate2.hermes_session_id =
                    session.hermes_session_id
              AND gate3.hermes_session_id =
                    session.hermes_session_id
              AND gate3.hermes_run_id <> gate2.hermes_run_id
              AND gate2.expected_task_version >
                    gate1.expected_task_version
              AND gate3.expected_task_version >
                    gate2.expected_task_version
              AND gate3.candidate_id = gate2.candidate_id
              AND gate3.expected_digest = gate2.expected_digest
              AND gate3.reviewed_source_sha256 =
                    gate1.reviewed_source_sha256
              AND gate3.gate1_confirmation_id =
                    gate1.gate1_confirmation_id
            """,
            (
                refs.admission_id,
                refs.admission_id,
                refs.admission_id,
                refs.admission_id,
                ROOT_USER_ID,
                workspace_id,
                refs.paper_gate3_id,
            ),
        ).fetchone()
        if row is None:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_paper_gate_missing",
                "exact durable paper Gate 1/2/3 chain is unavailable",
            )
        promotion = self._promotion_probe(str(row[15]))
        if (
            promotion.get("promotion_id") != row[15]
            or promotion.get("status") not in {"reviewed", "cleaned"}
            or promotion.get("reviewed_commit") != refs.reviewed_commit
            or promotion.get("candidate_id") != row[6]
            or promotion.get("candidate_digest") != str(row[7]).strip()
            or promotion.get("final_backtest_receipt_id") != row[11]
            or promotion.get("base_commit") != row[12]
            or str(row[36]).strip() != refs.reviewed_commit
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_promotion_unreviewed",
                "Gate 3 promotion is not the exact human-reviewed commit",
            )
        task_ref = str(row[16])
        workflow = self._hqa_probe("show", ("--task-ref", task_ref))
        audit = self._hqa_probe("audit", ())
        attempts = workflow.get("attempts")
        plan_attempts = (
            [
                attempt
                for attempt in attempts
                if isinstance(attempt, Mapping) and attempt.get("attempt_ref") == row[25]
            ]
            if isinstance(attempts, list)
            else []
        )
        research_attempts = (
            [
                attempt
                for attempt in attempts
                if isinstance(attempt, Mapping)
                and attempt.get("attempt_ref") == row[17]
                and attempt.get("run_ref") == row[32]
                and attempt.get("submission_command_ref") == f"command:{row[29]}"
                and isinstance(attempt.get("gate3_refs"), list | tuple)
                and row[24] in attempt.get("gate3_refs", [])
            ]
            if isinstance(attempts, list)
            else []
        )
        if (
            audit.get("status") != "consistent"
            or workflow.get("task_ref") != task_ref
            or workflow.get("state") != "terminal"
            or workflow.get("terminal_outcome") != "completed"
            or workflow.get("version") != row[39]
            or workflow.get("managed_session_ref") != f"session:{row[18]}"
            or workflow.get("gate1_ref") != row[22]
            or workflow.get("gate1_source_digest") != str(row[2]).strip()
            or workflow.get("gate1_candidate_ref") != f"candidate:{row[6]}"
            or workflow.get("gate1_manifest_digest") != str(row[7]).strip()
            or row[24] not in workflow.get("gate3_refs", [])
            or f"result:{row[11]}" not in workflow.get("result_refs", [])
            or len(plan_attempts) != 1
            or len(research_attempts) != 1
            or research_attempts[0].get("terminal_outcome") != "completed"
            or research_attempts[0].get("domain_gate_outcome") != "passed"
            or row[45] not in research_attempts[0].get("provider_evidence_refs", [])
            or row[40] != "completed"
            or row[41] != "completed"
            or row[42] != "completed"
            or row[43] != "completed"
            or row[44] != "passed"
            or row[46] != "consistent"
        ):
            raise CandidateEvidenceV3Error(
                "candidate_evidence_hqa_audit_mismatch",
                "HQA workflow authority does not match the paper Gate chain",
            )
        return {
            "attempt_ref": str(row[17]),
            "gate1_attempt_ref": str(row[25]),
            "gate2_attempt_ref": str(row[26]),
            "gate3_attempt_ref": str(row[17]),
            "candidate_digest": str(row[7]).strip(),
            "candidate_id": str(row[6]),
            "command_id": str(row[21]),
            "gate1_command_id": str(row[27]),
            "gate2_command_id": str(row[28]),
            "gate3_command_id": str(row[29]),
            "final_backtest_receipt_id": str(row[11]),
            "gate1_confirmation_id": str(row[1]),
            "gate1_id": str(row[0]),
            "gate1_hqa_ref": str(row[22]),
            "gate1_source_digest": str(row[2]).strip(),
            "gate1_receipt_digest": str(row[4]).strip(),
            "gate1_receipt_ref": str(row[3]),
            "gate2_id": str(row[5]),
            "gate2_hqa_ref": str(row[23]),
            "gate2_receipt_digest": str(row[9]).strip(),
            "gate2_receipt_ref": str(row[8]),
            "gate3_id": str(row[10]),
            "gate3_hqa_ref": str(row[24]),
            "gate3_receipt_digest": str(row[14]).strip(),
            "gate3_receipt_ref": str(row[13]),
            "hermes_run_id": str(row[19]),
            "gate1_hermes_run_id": str(row[30]),
            "gate2_hermes_run_id": str(row[31]),
            "gate3_hermes_run_id": str(row[19]),
            "hermes_session_id": str(row[20]),
            "hqa_run_ref": str(row[32]),
            "orders_created": 0,
            "platform_session_id": str(row[18]),
            "promotion_id": str(row[15]),
            "provider": "futu",
            "reviewed_commit": refs.reviewed_commit,
            "completion_receipt_ref": str(row[37]),
            "completion_receipt_digest": str(row[38]).strip(),
            "task_version": int(row[39]),
            "task_status": str(row[40]),
            "task_terminal_outcome": str(row[41]),
            "attempt_status": str(row[42]),
            "attempt_terminal_outcome": str(row[43]),
            "domain_gate_outcome": str(row[44]),
            "provider_evidence_ref": str(row[45]),
            "workflow_audit_ref": str(row[47]),
            "workflow_audit_digest": str(row[48]).strip(),
            "attempt_completion_event_id": str(row[49]),
            "task_completion_event_id": str(row[50]),
            "route": "/hermes",
            "task_ref": task_ref,
            "workflow_audit_status": "consistent",
        }

    def verify_and_store(
        self,
        refs: CandidateEvidenceReferences,
    ) -> VerifiedCandidateEvidenceSet:
        admission_id = _identifier(refs.admission_id, "admission_id")
        admission_digest = _digest(refs.admission_digest, "admission_digest")
        if _COMMIT_RE.fullmatch(refs.reviewed_commit) is None:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_invalid_commit",
                "reviewed_commit must be an exact Git commit",
            )
        for field, value in (
            ("web_platform_session_id", refs.web_platform_session_id),
            (
                "fork_source_platform_session_id",
                refs.fork_source_platform_session_id,
            ),
            (
                "fork_child_platform_session_id",
                refs.fork_child_platform_session_id,
            ),
            ("options_request_id", refs.options_request_id),
            ("paper_gate3_id", refs.paper_gate3_id),
            ("approval_command_id", refs.approval_command_id),
            ("stop_command_id", refs.stop_command_id),
        ):
            _identifier(value, field)
        try:
            with self._database.connect() as conn:
                candidate = self._candidate(conn, admission_id, admission_digest)
                workspace_id = str(candidate["workspace_id"])
                chat = self._chat_facts(conn, refs, workspace_id)
                restart = self._restart_facts(conn, refs)
                approval, stop = self._control_facts(
                    conn,
                    refs,
                    workspace_id,
                    candidate,
                    restart,
                )
                chat["command_approval_exact_cas"] = approval
                chat["run_stop_recovery"] = stop
                flows: dict[str, object] = {
                    "web_chat_multi_turn": chat,
                    "hermes_restart_recovery": restart,
                    "exact_message_fork": self._fork_facts(conn, refs, workspace_id),
                    "options_vertical_live_futu_ro": self._options_facts(conn, refs, workspace_id),
                    "paper_factor_gate_1_2_3_via_hermes": (
                        self._paper_facts(conn, refs, workspace_id)
                    ),
                }
            if set(flows) != _REQUIRED_FLOW_NAMES:
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_required_flow_missing",
                    "candidate evidence is missing a required flow",
                )
            with self._database.connect() as conn:
                final_orders = capture_canonical_zero_order_snapshot(
                    conn,
                    owner_user_id=ROOT_USER_ID,
                )
            baseline_orders = str(candidate["baseline_order_snapshot_digest"]).strip()
            if final_orders.snapshot_digest != baseline_orders:
                raise CandidateEvidenceV3Error(
                    "candidate_evidence_orders_changed",
                    "canonical paper/order authorities changed during the candidate",
                )
            facts: dict[str, object] = {
                "admission_digest": admission_digest,
                "admission_id": admission_id,
                "contract": _FACTS_CONTRACT,
                "database_schema_fingerprint": str(
                    candidate["database_schema_fingerprint"]
                ).strip(),
                "final_order_snapshot_digest": (final_orders.snapshot_digest),
                "flows": flows,
                "runtime": {
                    "hermes": str(candidate["hermes_runtime_digest"]).strip(),
                    "hqa": str(candidate["hqa_runtime_digest"]).strip(),
                    "platform": str(candidate["platform_runtime_digest"]).strip(),
                },
                "workspace_id": workspace_id,
            }
            facts_json = _canonical_bytes(facts).decode("utf-8")
            with self._database.connect() as conn, conn.transaction():
                digest_row = conn.execute(
                    """
                    SELECT encode(
                        sha256(convert_to(%s::jsonb::text, 'UTF8')),
                        'hex'
                    )
                    """,
                    (facts_json,),
                ).fetchone()
                if digest_row is None:
                    raise CandidateAdmissionUnavailable("candidate evidence digest is unavailable")
                facts_digest = str(digest_row[0])
                evidence_set_id = f"evidence_{facts_digest[:32]}"
                self._lock(conn, workspace_id)
                current = self._candidate(
                    conn,
                    admission_id,
                    admission_digest,
                    lock=True,
                )
                if any(
                    current[field] != candidate[field]
                    for field in (
                        "platform_runtime_digest",
                        "hqa_runtime_digest",
                        "hermes_runtime_digest",
                        "database_schema_fingerprint",
                        "baseline_order_snapshot_digest",
                    )
                ):
                    raise CandidateAdmissionConflict(
                        "candidate identity drifted during evidence verification"
                    )
                inserted = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_candidate_evidence_sets (
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
                    ON CONFLICT (admission_id) DO NOTHING
                    RETURNING verified_at
                    """,
                    (
                        evidence_set_id,
                        ROOT_USER_ID,
                        workspace_id,
                        admission_id,
                        admission_digest,
                        candidate["platform_runtime_digest"],
                        candidate["hqa_runtime_digest"],
                        candidate["hermes_runtime_digest"],
                        candidate["database_schema_fingerprint"],
                        baseline_orders,
                        final_orders.snapshot_digest,
                        facts_json,
                        facts_digest,
                    ),
                ).fetchone()
                replay = inserted is None
                if replay:
                    existing = conn.execute(
                        f"""
                        SELECT
                            evidence_set_id,
                            facts_digest,
                            final_order_snapshot_digest,
                            facts,
                            verified_at
                        FROM {SCHEMA}.agent_v02_candidate_evidence_sets
                        WHERE admission_id = %s
                        """,
                        (admission_id,),
                    ).fetchone()
                    if (
                        existing is None
                        or str(existing[0]) != evidence_set_id
                        or str(existing[1]).strip() != facts_digest
                        or str(existing[2]).strip() != final_orders.snapshot_digest
                        or existing[3] != facts
                    ):
                        raise CandidateAdmissionConflict(
                            "candidate already has different verified evidence"
                        )
                    verified_at = existing[4]
                else:
                    verified_at = inserted[0]
            return VerifiedCandidateEvidenceSet(
                evidence_set_id=evidence_set_id,
                admission_id=admission_id,
                admission_digest=admission_digest,
                facts_digest=facts_digest,
                final_order_snapshot_digest=final_orders.snapshot_digest,
                verified_at=verified_at,
                facts=facts,
                idempotent_replay=replay,
            )
        except (
            CandidateAdmissionConflict,
            CandidateEvidenceV3Error,
        ):
            raise
        except (
            HermesApiReadError,
            HermesRunControlError,
            PromotionWorkspaceError,
            psycopg.Error,
        ) as exc:
            raise CandidateAdmissionUnavailable(
                "candidate evidence verification is unavailable"
            ) from exc

    def _invoke_hqa_workflow(
        self,
        operation: str,
        arguments: Sequence[str],
    ) -> Mapping[str, object]:
        if operation not in {"show", "audit"}:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_hqa_operation_invalid",
                "unsupported HQA workflow read operation",
            )
        root = self._settings.intent_payload.hqa_root.expanduser().resolve()
        python = self._settings.intent_payload.python_executable
        if python is None:
            candidate = root / ".venv" / "bin" / "python"
            python = candidate if candidate.is_file() else Path(sys.executable)
        env = {
            key: os.environ[key] for key in ("HOME", "LANG", "LC_ALL", "TZ") if key in os.environ
        }
        for key in (
            "HQA_WORKFLOW_AUTHORITY_DIR",
            "HQA_WORKFLOW_OWNER_USER_ID",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        env["PYTHONPATH"] = str(root)
        env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [
                str(Path(python).expanduser().resolve()),
                "-m",
                "hqa.workflow_authority_cli",
                operation,
                *arguments,
            ],
            cwd=root,
            env=env,
            capture_output=True,
            check=False,
            timeout=self._settings.intent_payload.timeout_seconds,
        )
        if completed.returncode != 0 or len(completed.stdout) > 1024 * 1024 or completed.stderr:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_hqa_audit_unavailable",
                "HQA workflow authority read failed",
            )
        try:
            document = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_hqa_audit_unavailable",
                "HQA workflow authority returned invalid JSON",
            ) from exc
        if not isinstance(document, Mapping) or "error" in document:
            raise CandidateEvidenceV3Error(
                "candidate_evidence_hqa_audit_unavailable",
                "HQA workflow authority returned no canonical fact",
            )
        return document

    @staticmethod
    def _promotion_status(promotion_id: str) -> Mapping[str, object]:
        agent_root = resolve_agent_output_dir()
        return promotion_status(
            promotion_id=promotion_id,
            agent_output_dir=agent_root,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            repo_dir=resolve_platform_repo(),
        )


__all__ = [
    "CandidateEvidenceReferences",
    "CandidateEvidenceV3Authority",
    "CandidateEvidenceV3Error",
    "CandidateRestartObservation",
    "VerifiedCandidateEvidenceSet",
    "candidate_evidence_runtime_security_is_ready",
    "candidate_evidence_schema_is_ready_on_connection",
    "canonical_approval_control_evidence",
    "canonical_stop_control_evidence",
    "canonical_transcript_observation",
]
