"""Hermetic Hermes command-approval challenge authority (V7a-M1).

In-process, owner-local store for pending command-approval challenges and
single-use allow_once|deny decisions. This is **not** Gate 1/2/3 and not the
``/hermes/approvals`` candidate page.

Design freeze
-------------
* Decision surface is exact CAS: approval_ref + run_ref + command_digest +
  expected_status=pending + expected_expires_at + decision ∈ {allow_once, deny}.
* No always-allow / permanent allow.
* Fail closed on stale, expired, wrong digest, wrong run, already-consumed,
  or cross-id replay.
* Snapshot projection lists still-pending, non-expired challenges plus recent
  decided facts (V7d projector). Empty remains honest.
* Durable PG store / live Hermes HTTP commit remain later slices; hermetic
  fixtures and local-dark smoke seed this store explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

Decision = Literal["allow_once", "deny"]
ChallengeStatus = Literal["pending", "allowed_once", "denied", "expired"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class CommandApprovalAuthorityError(RuntimeError):
    """Typed authority failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_rfc3339(value: str) -> datetime:
    if type(value) is not str or not value:
        raise CommandApprovalAuthorityError(
            "validation", "expires_at must be timezone-aware RFC3339"
        )
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise CommandApprovalAuthorityError(
            "validation", "expires_at must be timezone-aware RFC3339"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommandApprovalAuthorityError(
            "validation", "expires_at must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _canon_ts(value: str | datetime) -> str:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise CommandApprovalAuthorityError(
                "validation", "expires_at must be timezone-aware"
            )
        dt = dt.astimezone(UTC)
    else:
        dt = _parse_rfc3339(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _strip_ref(value: str, prefix: str, field: str) -> str:
    if type(value) is not str or not value.startswith(prefix) or value == prefix:
        raise CommandApprovalAuthorityError(
            "validation", f"{field} must be a bounded {prefix} reference"
        )
    body = value[len(prefix) :]
    if _ID.fullmatch(body) is None:
        raise CommandApprovalAuthorityError(
            "validation", f"{field} must be a bounded {prefix} reference"
        )
    return body


def _validate_digest(value: str, field: str = "command_digest") -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise CommandApprovalAuthorityError(
            "validation", f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_decision(value: str) -> Decision:
    if value not in ("allow_once", "deny"):
        raise CommandApprovalAuthorityError(
            "validation", "decision must be allow_once or deny"
        )
    return value  # type: ignore[return-value]


@dataclass
class ApprovalChallenge:
    workspace_id: str
    approval_id: str
    run_id: str
    command_digest: str
    expires_at: str
    status: ChallengeStatus = "pending"
    command_id: str | None = None
    kind: str = "hermes.command_approval"
    decided_at: str | None = None
    decision: Decision | None = None
    decision_action_id: str | None = None
    decision_action_digest: str | None = None

    @property
    def approval_ref(self) -> str:
        return f"approval:{self.approval_id}"

    @property
    def run_ref(self) -> str:
        return f"run:{self.run_id}"

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "command_id": self.command_id,
            "digest": self.command_digest,
            "expires_at": self.expires_at,
            "expected_status": "pending" if self.status == "pending" else self.status,
            "status": self.status,
            "kind": self.kind,
        }
        # V7d: surface decided facts when known (never invent Gate fields).
        if self.decision is not None:
            payload["decision"] = self.decision
        if self.decided_at is not None:
            payload["decided_at"] = self.decided_at
        return payload


class CommandApprovalAuthority:
    """Thread-safe in-process challenge store (hermetic + local-dark)."""

    def __init__(self) -> None:
        self._lock = Lock()
        # key = (workspace_id, approval_id)
        self._rows: dict[tuple[str, str], ApprovalChallenge] = {}

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()

    def seed_pending(
        self,
        *,
        workspace_id: str,
        approval_id: str,
        run_id: str,
        command_digest: str,
        expires_at: str | datetime,
        command_id: str | None = None,
        kind: str = "hermes.command_approval",
    ) -> ApprovalChallenge:
        if type(workspace_id) is not str or _ID.fullmatch(workspace_id) is None:
            raise CommandApprovalAuthorityError(
                "validation", "workspace_id must be a bounded identifier"
            )
        if type(approval_id) is not str or _ID.fullmatch(approval_id) is None:
            raise CommandApprovalAuthorityError(
                "validation", "approval_id must be a bounded identifier"
            )
        if type(run_id) is not str or _ID.fullmatch(run_id) is None:
            raise CommandApprovalAuthorityError(
                "validation", "run_id must be a bounded identifier"
            )
        digest = _validate_digest(command_digest)
        exp = _canon_ts(expires_at)
        row = ApprovalChallenge(
            workspace_id=workspace_id,
            approval_id=approval_id,
            run_id=run_id,
            command_digest=digest,
            expires_at=exp,
            status="pending",
            command_id=command_id,
            kind=kind if type(kind) is str and kind else "hermes.command_approval",
        )
        key = (workspace_id, approval_id)
        with self._lock:
            existing = self._rows.get(key)
            if existing is not None and existing.status == "pending":
                if (
                    existing.run_id == row.run_id
                    and existing.command_digest == row.command_digest
                    and existing.expires_at == row.expires_at
                ):
                    return existing
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_id already pending with different binding"
                )
            self._rows[key] = row
        # Outside lock: journal is best-effort observe rail (V7d).
        try:
            from quant_system.hermes.approval_observe import note_approval_raised

            note_approval_raised(workspace_id=workspace_id, approval=row)
        except Exception:
            pass
        return row

    def list_pending(
        self, workspace_id: str, *, now: datetime | None = None
    ) -> list[dict[str, object]]:
        clock = now or _utc_now()
        out: list[dict[str, object]] = []
        with self._lock:
            for (ws, _), row in sorted(self._rows.items(), key=lambda kv: kv[0][1]):
                if ws != workspace_id:
                    continue
                if row.status != "pending":
                    continue
                if _parse_rfc3339(row.expires_at) <= clock:
                    row.status = "expired"
                    continue
                out.append(row.to_public_dict())
        return out

    def list_observed(
        self,
        workspace_id: str,
        *,
        decided_limit: int = 20,
        now: datetime | None = None,
    ) -> list[dict[str, object]]:
        """Pending first, then recent decided/expired facts (V7d projector).

        Empty is honest. Never invents Gate rows. Decided rows keep their
        terminal status + decision so the spine can drop decide controls.
        """
        clock = now or _utc_now()
        limit = (
            decided_limit
            if type(decided_limit) is int and decided_limit > 0
            else 20
        )
        pending: list[dict[str, object]] = []
        decided: list[ApprovalChallenge] = []
        with self._lock:
            for (ws, _), row in sorted(self._rows.items(), key=lambda kv: kv[0][1]):
                if ws != workspace_id:
                    continue
                if row.status == "pending":
                    if _parse_rfc3339(row.expires_at) <= clock:
                        row.status = "expired"
                        decided.append(row)
                        continue
                    pending.append(row.to_public_dict())
                    continue
                if row.status in ("allowed_once", "denied", "expired"):
                    decided.append(row)
            # Most-recent decided first (by decided_at, then approval_id).
            def _decided_key(r: ApprovalChallenge) -> tuple[str, str]:
                return (r.decided_at or "", r.approval_id)

            decided_sorted = sorted(decided, key=_decided_key, reverse=True)[:limit]
            decided_out = [r.to_public_dict() for r in decided_sorted]
        return pending + decided_out

    def get(
        self, workspace_id: str, approval_id: str
    ) -> ApprovalChallenge | None:
        with self._lock:
            return self._rows.get((workspace_id, approval_id))

    def decide(
        self,
        *,
        workspace_id: str,
        approval_ref: str,
        run_ref: str,
        command_digest: str,
        expected_status: str,
        expected_expires_at: str,
        decision: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
    ) -> ApprovalChallenge:
        """Commit one single-use decision under exact CAS binding."""
        if expected_status != "pending":
            raise CommandApprovalAuthorityError(
                "validation", "expected_status must be pending"
            )
        decision_v = _validate_decision(decision)
        digest = _validate_digest(command_digest)
        approval_id = _strip_ref(approval_ref, "approval:", "approval_ref")
        run_id = _strip_ref(run_ref, "run:", "run_ref")
        exp = _canon_ts(expected_expires_at)
        clock = now or _utc_now()
        if type(client_action_id) is not str or not client_action_id:
            raise CommandApprovalAuthorityError(
                "validation", "client_action_id required"
            )
        if type(action_digest) is not str or _HEX64.fullmatch(action_digest) is None:
            raise CommandApprovalAuthorityError(
                "validation", "action_digest must be lowercase SHA-256"
            )

        key = (workspace_id, approval_id)
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_challenge_not_found"
                )

            # Idempotent replay of the exact same decision action.
            if (
                row.status in ("allowed_once", "denied")
                and row.decision_action_digest == action_digest
                and row.decision_action_id == client_action_id
                and row.decision == decision_v
            ):
                return row

            if row.status == "expired" or _parse_rfc3339(row.expires_at) <= clock:
                row.status = "expired"
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_challenge_expired"
                )
            if row.status != "pending":
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_challenge_already_decided"
                )
            if row.run_id != run_id:
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_run_mismatch"
                )
            if row.command_digest != digest:
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_digest_mismatch"
                )
            if row.expires_at != exp:
                raise CommandApprovalAuthorityError(
                    "conflict", "approval_expires_at_mismatch"
                )

            row.status = "allowed_once" if decision_v == "allow_once" else "denied"
            row.decision = decision_v
            row.decided_at = clock.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            row.decision_action_id = client_action_id
            row.decision_action_digest = action_digest
            decided_row = row
        try:
            from quant_system.hermes.approval_observe import note_approval_decided

            note_approval_decided(
                workspace_id=workspace_id, approval=decided_row
            )
        except Exception:
            pass
        return decided_row


_DEFAULT = CommandApprovalAuthority()


def default_command_approval_authority() -> CommandApprovalAuthority:
    return _DEFAULT


def reset_default_command_approval_authority() -> None:
    _DEFAULT.reset()


__all__ = [
    "ApprovalChallenge",
    "CommandApprovalAuthority",
    "CommandApprovalAuthorityError",
    "default_command_approval_authority",
    "reset_default_command_approval_authority",
]
