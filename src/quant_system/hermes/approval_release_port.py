"""Hermetic Hermes command-approval release/signal port (V7b-M1).

Mirrors HQA ``HermesRunPort.respond_approval`` semantics without importing
``hqa``. After V7a CAS decides ``allow_once|deny`` on
:class:`CommandApprovalAuthority`, the submission saga maps the decision to
the adapter choice (``allow_once`` → ``once``, ``deny`` → ``deny``) and calls
:meth:`FakeHermesApprovalReleaseAdapter.respond_approval` so a waiter can be
signalled.

This is **not** always-allow, **not** Gate 1/2/3, **not** live HTTP Hermes,
and **not** a public write path. Production HTTP release remains a later slice.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Literal, Protocol

from quant_system.hermes.command_approval_authority import (
    CommandApprovalAuthority,
    CommandApprovalAuthorityError,
    default_command_approval_authority,
)

ReleaseChoice = Literal["once", "deny"]
DecisionStatus = Literal["committed"]
WaiterSignalStatus = Literal["confirmed", "unknown"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ALLOWED_CHOICES = frozenset({"once", "deny"})


class ApprovalReleaseError(RuntimeError):
    """Typed release failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApprovalReleaseResult:
    run_id: str
    choice: str
    decision_status: DecisionStatus = "committed"
    waiter_signal_status: WaiterSignalStatus = "confirmed"
    idempotent_replay: bool = False
    challenge_id: str = ""
    action_digest: str = ""
    resolved: int = 0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "choice": self.choice,
            "decision_status": self.decision_status,
            "waiter_signal_status": self.waiter_signal_status,
            "idempotent_replay": self.idempotent_replay,
            "challenge_id": self.challenge_id,
            "action_digest": self.action_digest,
            "resolved": self.resolved,
        }


class ApprovalReleasePort(Protocol):
    """Minimal release seam used by the approval-decision saga."""

    def respond_approval(
        self,
        run_id: str,
        *,
        choice: str,
        challenge_id: str,
        action_digest: str,
    ) -> ApprovalReleaseResult: ...


class ApprovalChallengeSeedPort(ApprovalReleasePort, Protocol):
    """Hermetic extension used only to seed a challenge in contract tests."""

    def raise_approval(
        self,
        run_id: str,
        *,
        action_digest: str,
        challenge_id: str | None = None,
        ttl_seconds: float = 300.0,
    ) -> dict[str, object]: ...


@dataclass
class _ReleaseGrant:
    challenge_id: str
    run_id: str
    action_digest: str
    expires_at: float
    consumed: bool = False
    choice: str | None = None
    resolved: int = 0


@dataclass
class _ReleaseEvent:
    seq: int
    event_type: str
    run_id: str
    payload: dict[str, object] = field(default_factory=dict)


def map_decision_to_release_choice(decision: str) -> ReleaseChoice:
    """Map V7a workspace decision to HQA/fake respond_approval choice."""
    if decision == "allow_once":
        return "once"
    if decision == "deny":
        return "deny"
    raise ApprovalReleaseError(
        "validation",
        "decision must map to release choice once|deny (no always-allow)",
    )


def _validate_digest(value: str, field: str = "action_digest") -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ApprovalReleaseError(
            "validation", f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ApprovalReleaseError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


def _canon_expires_rfc3339(expires_at: float) -> str:
    return (
        datetime.fromtimestamp(expires_at, tz=UTC)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )


class FakeHermesApprovalReleaseAdapter:
    """In-process respond_approval double matching HQA fake semantics.

    Scripting hooks (not a product path):
    * :meth:`ensure_run` / :meth:`raise_approval` issue a pending grant
    * ``next_fault``: ``None`` | ``"stale"`` | ``"unavailable"`` | ``"run_not_found"``
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: set[str] = set()
        self._approvals: dict[str, _ReleaseGrant] = {}
        self._events: dict[str, list[_ReleaseEvent]] = {}
        self.next_fault: str | None = None
        self.respond_calls: int = 0

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()
            self._approvals.clear()
            self._events.clear()
            self.next_fault = None
            self.respond_calls = 0

    def ensure_run(self, run_id: str) -> str:
        rid = _validate_id(run_id, "run_id")
        with self._lock:
            self._runs.add(rid)
            self._events.setdefault(rid, [])
        return rid

    def raise_approval(
        self,
        run_id: str,
        *,
        action_digest: str,
        challenge_id: str | None = None,
        ttl_seconds: float = 300.0,
    ) -> dict[str, object]:
        """Issue one pending challenge (test/local-dark scripting hook)."""
        rid = self.ensure_run(run_id)
        digest = _validate_digest(action_digest)
        if ttl_seconds <= 0:
            raise ApprovalReleaseError("validation", "ttl_seconds must be positive")
        cid = challenge_id
        cid = (
            f"ch_{uuid.uuid4().hex}"
            if cid is None
            else _validate_id(cid, "challenge_id")
        )
        expires_at = time.time() + float(ttl_seconds)
        grant = _ReleaseGrant(
            challenge_id=cid,
            run_id=rid,
            action_digest=digest,
            expires_at=expires_at,
        )
        with self._lock:
            existing = self._approvals.get(cid)
            if existing is not None and not existing.consumed:
                if (
                    existing.run_id == rid
                    and existing.action_digest == digest
                ):
                    return {
                        "challenge_id": existing.challenge_id,
                        "run_id": existing.run_id,
                        "action_digest": existing.action_digest,
                        "expires_at": existing.expires_at,
                        "expires_at_rfc3339": _canon_expires_rfc3339(
                            existing.expires_at
                        ),
                    }
                raise ApprovalReleaseError(
                    "conflict",
                    "challenge_id already pending with different binding",
                )
            self._approvals[cid] = grant
        return {
            "challenge_id": grant.challenge_id,
            "run_id": grant.run_id,
            "action_digest": grant.action_digest,
            "expires_at": grant.expires_at,
            "expires_at_rfc3339": _canon_expires_rfc3339(grant.expires_at),
        }

    def events(self, run_id: str) -> list[dict[str, object]]:
        rid = _validate_id(run_id, "run_id")
        with self._lock:
            rows = list(self._events.get(rid, ()))
        return [
            {
                "seq": e.seq,
                "event_type": e.event_type,
                "run_id": e.run_id,
                "payload": dict(e.payload),
            }
            for e in rows
        ]

    def list_pending_grants(self) -> list[dict[str, object]]:
        now = time.time()
        out: list[dict[str, object]] = []
        with self._lock:
            for grant in sorted(
                self._approvals.values(), key=lambda g: g.challenge_id
            ):
                if grant.consumed or grant.expires_at <= now:
                    continue
                out.append(
                    {
                        "challenge_id": grant.challenge_id,
                        "run_id": grant.run_id,
                        "action_digest": grant.action_digest,
                        "expires_at": grant.expires_at,
                        "expires_at_rfc3339": _canon_expires_rfc3339(
                            grant.expires_at
                        ),
                    }
                )
        return out

    def _append_event_unlocked(
        self, run_id: str, event_type: str, payload: Mapping[str, object]
    ) -> None:
        bucket = self._events.setdefault(run_id, [])
        seq = (bucket[-1].seq + 1) if bucket else 1
        bucket.append(
            _ReleaseEvent(
                seq=seq,
                event_type=event_type,
                run_id=run_id,
                payload=dict(payload),
            )
        )

    def respond_approval(
        self,
        run_id: str,
        *,
        choice: str,
        challenge_id: str,
        action_digest: str,
    ) -> ApprovalReleaseResult:
        """Commit release + signal, or identify exact durable replay.

        Choice surface is ``once`` | ``deny`` only (HQA fake contract). Stale,
        expired, wrong-run, digest-mismatch, or already-consumed-with-other
        choice fail closed without consuming a fresh grant.
        """
        rid = _validate_id(run_id, "run_id")
        cid = _validate_id(challenge_id, "challenge_id")
        digest = _validate_digest(action_digest)
        if choice not in _ALLOWED_CHOICES:
            raise ApprovalReleaseError(
                "validation",
                "choice must be once or deny (no always-allow)",
            )

        with self._lock:
            self.respond_calls += 1
            fault = self.next_fault
            self.next_fault = None

            if fault == "unavailable":
                raise ApprovalReleaseError(
                    "release_unavailable",
                    "Approval release port unavailable",
                )
            if fault == "run_not_found" or rid not in self._runs:
                raise ApprovalReleaseError(
                    "run_not_found", f"Run not found: {rid}"
                )
            if not cid or not digest:
                raise ApprovalReleaseError(
                    "approval_challenge_required",
                    "Approval requires challenge_id and action_digest",
                )
            grant = self._approvals.get(cid)
            if grant is None or grant.run_id != rid:
                raise ApprovalReleaseError(
                    "approval_challenge_invalid",
                    "Approval challenge is invalid for this run",
                )
            if fault == "stale":
                raise ApprovalReleaseError(
                    "approval_challenge_invalid",
                    "Approval challenge is stale, expired, already used, or mismatched",
                )

            if grant.consumed:
                if grant.action_digest == digest and grant.choice == choice:
                    return ApprovalReleaseResult(
                        run_id=rid,
                        choice=choice,
                        decision_status="committed",
                        waiter_signal_status="confirmed",
                        idempotent_replay=True,
                        challenge_id=cid,
                        action_digest=digest,
                        resolved=grant.resolved,
                    )
                raise ApprovalReleaseError(
                    "approval_challenge_invalid",
                    "Approval challenge is stale, expired, already used, or mismatched",
                )
            if grant.action_digest != digest:
                raise ApprovalReleaseError(
                    "approval_challenge_invalid",
                    "Approval challenge is stale, expired, already used, or mismatched",
                )
            if grant.expires_at <= time.time():
                raise ApprovalReleaseError(
                    "approval_challenge_invalid",
                    "Approval challenge is stale, expired, already used, or mismatched",
                )

            grant.consumed = True
            grant.choice = choice
            grant.resolved = 0
            payload = {
                "choice": choice,
                "decision_status": "committed",
                "waiter_signal_status": "unknown",
                "challenge_id": cid,
                "action_digest": digest,
            }
            self._append_event_unlocked(rid, "approval.responded", payload)
            self._append_event_unlocked(
                rid, "approval.release_committed", payload
            )
            signalled = {
                **payload,
                "waiter_signal_status": "confirmed",
            }
            self._append_event_unlocked(rid, "approval.signalled", signalled)
            return ApprovalReleaseResult(
                run_id=rid,
                choice=choice,
                decision_status="committed",
                waiter_signal_status="confirmed",
                idempotent_replay=False,
                challenge_id=cid,
                action_digest=digest,
                resolved=0,
            )


def project_pending_challenge(
    *,
    workspace_id: str,
    run_id: str,
    command_digest: str,
    approval_id: str | None = None,
    command_id: str | None = None,
    ttl_seconds: float = 300.0,
    release_adapter: ApprovalChallengeSeedPort | None = None,
    approval_authority: CommandApprovalAuthority | None = None,
) -> dict[str, object]:
    """Raise on the release adapter AND seed CommandApprovalAuthority.

    Snapshot then projects the pending row; decide CAS + respond_approval share
    the same challenge_id / digest / expires_at binding.
    """
    adapter = release_adapter or default_approval_release_adapter()
    authority = approval_authority or default_command_approval_authority()
    if type(workspace_id) is not str or _ID.fullmatch(workspace_id) is None:
        raise ApprovalReleaseError(
            "validation", "workspace_id must be a bounded identifier"
        )
    digest = _validate_digest(command_digest, "command_digest")
    raised = adapter.raise_approval(
        run_id,
        action_digest=digest,
        challenge_id=approval_id,
        ttl_seconds=ttl_seconds,
    )
    exp = str(raised["expires_at_rfc3339"])
    try:
        row = authority.seed_pending(
            workspace_id=workspace_id,
            approval_id=str(raised["challenge_id"]),
            run_id=str(raised["run_id"]),
            command_digest=digest,
            expires_at=exp,
            command_id=command_id,
        )
    except CommandApprovalAuthorityError as exc:
        raise ApprovalReleaseError(exc.code, exc.message) from exc
    return row.to_public_dict()


_DEFAULT_RELEASE = FakeHermesApprovalReleaseAdapter()


def default_approval_release_adapter() -> FakeHermesApprovalReleaseAdapter:
    return _DEFAULT_RELEASE


def reset_default_approval_release_adapter() -> None:
    _DEFAULT_RELEASE.reset()


__all__ = [
    "ApprovalChallengeSeedPort",
    "ApprovalReleaseError",
    "ApprovalReleasePort",
    "ApprovalReleaseResult",
    "FakeHermesApprovalReleaseAdapter",
    "default_approval_release_adapter",
    "map_decision_to_release_choice",
    "project_pending_challenge",
    "reset_default_approval_release_adapter",
]
