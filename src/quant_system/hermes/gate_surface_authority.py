"""Hermetic Domain Gate 1/2/3 surface authority (V7e-Gate-Surfaces-M1).

In-process, owner-local store for pending Gate challenges and single-use typed
decisions. This is **not** Hermes command-approval and must never share
``approvals[]`` / ``event:approvals`` / ``canDecide``.

Design freeze
-------------
* Gate 1 ``gate1.formula_source.confirm`` — exact task_ref + reviewed_source_sha256
  + nonempty confirmation_note. ConfirmResearchPlan is **not** Gate 1.
* Gate 2 ``gate2.candidate.review`` — exact candidate_ref + expected_digest +
  expected_status=pending + note (no-refetch CAS).
* Gate 3 ``gate3.promotion_review.prepare`` — exact candidate + digest +
  final_backtest_receipt_ref + base_commit (40-hex). Prepare only; web does
  **not** Git-commit. Human commit remains the completion fact.
* No always-allow. No stuffing Gates into command-approval. No dual private poll.
* Empty remains honest until explicitly seeded (hermetic fixtures / later verticals).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

GateKind = Literal["gate1", "gate2", "gate3"]
GateStatus = Literal[
    "pending",
    "confirmed",
    "reviewed",
    "prepared",
    "rejected",
    "expired",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")

_KIND_PUBLIC = {
    "gate1": "gate1.formula_source",
    "gate2": "gate2.candidate",
    "gate3": "gate3.promotion_review",
}


class GateSurfaceAuthorityError(RuntimeError):
    """Typed authority failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canon_now() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_rfc3339(value: str) -> datetime:
    if type(value) is not str or not value:
        raise GateSurfaceAuthorityError(
            "validation", "expires_at must be timezone-aware RFC3339"
        )
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise GateSurfaceAuthorityError(
            "validation", "expires_at must be timezone-aware RFC3339"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GateSurfaceAuthorityError(
            "validation", "expires_at must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _canon_ts(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise GateSurfaceAuthorityError(
                "validation", "expires_at must be timezone-aware"
            )
        dt = dt.astimezone(UTC)
    else:
        dt = _parse_rfc3339(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _strip_ref(value: str, prefix: str, field: str) -> str:
    if type(value) is not str or not value.startswith(prefix) or value == prefix:
        raise GateSurfaceAuthorityError(
            "validation", f"{field} must be a bounded {prefix} reference"
        )
    body = value[len(prefix) :]
    if _ID.fullmatch(body) is None:
        raise GateSurfaceAuthorityError(
            "validation", f"{field} must be a bounded {prefix} reference"
        )
    return body


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise GateSurfaceAuthorityError(
            "validation", f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_note(value: str, field: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 2_000
        or not value.isprintable()
    ):
        raise GateSurfaceAuthorityError(
            "validation", f"{field} must be bounded nonempty printable text"
        )
    return value


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise GateSurfaceAuthorityError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


@dataclass
class GateChallenge:
    workspace_id: str
    gate_id: str
    gate_kind: GateKind
    status: GateStatus = "pending"
    # Gate 1
    task_id: str | None = None
    reviewed_source_sha256: str | None = None
    # Gate 2 / Gate 3
    candidate_id: str | None = None
    expected_digest: str | None = None
    # Gate 3 only
    final_backtest_receipt_id: str | None = None
    base_commit: str | None = None
    # Optional soft expiry (hermetic)
    expires_at: str | None = None
    # Decision facts
    note: str | None = None
    decided_at: str | None = None
    decision_action_id: str | None = None
    decision_action_digest: str | None = None

    @property
    def task_ref(self) -> str | None:
        return None if self.task_id is None else f"task:{self.task_id}"

    @property
    def candidate_ref(self) -> str | None:
        return None if self.candidate_id is None else f"candidate:{self.candidate_id}"

    @property
    def final_backtest_receipt_ref(self) -> str | None:
        if self.final_backtest_receipt_id is None:
            return None
        return f"receipt:{self.final_backtest_receipt_id}"

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "gate_id": self.gate_id,
            "gate_kind": self.gate_kind,
            "kind": _KIND_PUBLIC[self.gate_kind],
            "status": self.status,
            "expected_status": "pending" if self.status == "pending" else self.status,
        }
        if self.task_id is not None:
            payload["task_id"] = self.task_id
            payload["task_ref"] = self.task_ref
        if self.reviewed_source_sha256 is not None:
            payload["reviewed_source_sha256"] = self.reviewed_source_sha256
        if self.candidate_id is not None:
            payload["candidate_id"] = self.candidate_id
            payload["candidate_ref"] = self.candidate_ref
        if self.expected_digest is not None:
            payload["expected_digest"] = self.expected_digest
        if self.final_backtest_receipt_id is not None:
            payload["final_backtest_receipt_id"] = self.final_backtest_receipt_id
            payload["final_backtest_receipt_ref"] = self.final_backtest_receipt_ref
        if self.base_commit is not None:
            payload["base_commit"] = self.base_commit
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at
        if self.note is not None:
            payload["note"] = self.note
        if self.decided_at is not None:
            payload["decided_at"] = self.decided_at
        return payload


class GateSurfaceAuthority:
    """Thread-safe in-process Gate 1/2/3 challenge store (hermetic + local-dark)."""

    def __init__(self) -> None:
        self._lock = Lock()
        # key = (workspace_id, gate_id)
        self._rows: dict[tuple[str, str], GateChallenge] = {}

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()

    def seed_gate1_pending(
        self,
        *,
        workspace_id: str,
        gate_id: str,
        task_id: str,
        reviewed_source_sha256: str,
        expires_at: str | datetime | None = None,
    ) -> GateChallenge:
        ws = _validate_id(workspace_id, "workspace_id")
        gid = _validate_id(gate_id, "gate_id")
        tid = _validate_id(task_id, "task_id")
        digest = _validate_digest(reviewed_source_sha256, "reviewed_source_sha256")
        exp = _canon_ts(expires_at)
        row = GateChallenge(
            workspace_id=ws,
            gate_id=gid,
            gate_kind="gate1",
            status="pending",
            task_id=tid,
            reviewed_source_sha256=digest,
            expires_at=exp,
        )
        return self._put_pending(row)

    def seed_gate2_pending(
        self,
        *,
        workspace_id: str,
        gate_id: str,
        candidate_id: str,
        expected_digest: str,
        expires_at: str | datetime | None = None,
    ) -> GateChallenge:
        ws = _validate_id(workspace_id, "workspace_id")
        gid = _validate_id(gate_id, "gate_id")
        cid = _validate_id(candidate_id, "candidate_id")
        digest = _validate_digest(expected_digest, "expected_digest")
        exp = _canon_ts(expires_at)
        row = GateChallenge(
            workspace_id=ws,
            gate_id=gid,
            gate_kind="gate2",
            status="pending",
            candidate_id=cid,
            expected_digest=digest,
            expires_at=exp,
        )
        return self._put_pending(row)

    def seed_gate3_pending(
        self,
        *,
        workspace_id: str,
        gate_id: str,
        candidate_id: str,
        expected_digest: str,
        final_backtest_receipt_id: str,
        base_commit: str,
        expires_at: str | datetime | None = None,
    ) -> GateChallenge:
        ws = _validate_id(workspace_id, "workspace_id")
        gid = _validate_id(gate_id, "gate_id")
        cid = _validate_id(candidate_id, "candidate_id")
        digest = _validate_digest(expected_digest, "expected_digest")
        rid = _validate_id(final_backtest_receipt_id, "final_backtest_receipt_id")
        if type(base_commit) is not str or _HEX40.fullmatch(base_commit) is None:
            raise GateSurfaceAuthorityError(
                "validation", "base_commit must be a lowercase 40-hex commit"
            )
        exp = _canon_ts(expires_at)
        row = GateChallenge(
            workspace_id=ws,
            gate_id=gid,
            gate_kind="gate3",
            status="pending",
            candidate_id=cid,
            expected_digest=digest,
            final_backtest_receipt_id=rid,
            base_commit=base_commit,
            expires_at=exp,
        )
        return self._put_pending(row)

    def _put_pending(self, row: GateChallenge) -> GateChallenge:
        key = (row.workspace_id, row.gate_id)
        with self._lock:
            existing = self._rows.get(key)
            if existing is not None and existing.status == "pending":
                # Idempotent re-seed of the same pending shape is OK; conflict otherwise.
                if (
                    existing.gate_kind == row.gate_kind
                    and existing.task_id == row.task_id
                    and existing.reviewed_source_sha256 == row.reviewed_source_sha256
                    and existing.candidate_id == row.candidate_id
                    and existing.expected_digest == row.expected_digest
                    and existing.final_backtest_receipt_id
                    == row.final_backtest_receipt_id
                    and existing.base_commit == row.base_commit
                ):
                    return existing
                raise GateSurfaceAuthorityError(
                    "conflict", "gate_challenge_already_exists"
                )
            if existing is not None and existing.status != "pending":
                raise GateSurfaceAuthorityError(
                    "conflict", "gate_challenge_already_terminal"
                )
            self._rows[key] = row
            return row

    def get(self, workspace_id: str, gate_id: str) -> GateChallenge | None:
        with self._lock:
            row = self._rows.get((workspace_id, gate_id))
            return None if row is None else row

    def delete_pending_if_matches(
        self,
        *,
        workspace_id: str,
        gate_id: str,
        task_id: str,
        reviewed_source_sha256: str,
    ) -> bool:
        """Narrow abort cleanup for V7g-B-M3 seed: remove pending only if owned shape matches."""
        key = (workspace_id, gate_id)
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return False
            if row.status != "pending":
                return False
            if row.gate_kind != "gate1":
                return False
            if row.task_id != task_id:
                return False
            if row.reviewed_source_sha256 != reviewed_source_sha256:
                return False
            del self._rows[key]
            return True

    def delete_gate2_pending_if_matches(
        self,
        *,
        workspace_id: str,
        gate_id: str,
        candidate_id: str,
        expected_digest: str,
    ) -> bool:
        """Remove an owned pending Gate2 during narrow V7g-B-M5 abort cleanup."""
        key = (workspace_id, gate_id)
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return False
            if row.status != "pending":
                return False
            if row.gate_kind != "gate2":
                return False
            if row.candidate_id != candidate_id:
                return False
            if row.expected_digest != expected_digest:
                return False
            del self._rows[key]
            return True

    def list_observed(
        self,
        workspace_id: str,
        *,
        decided_limit: int = 20,
        now: datetime | None = None,
    ) -> list[GateChallenge]:
        """Pending first (CAS-complete), then recent decided/prepared facts."""
        clock = now or _utc_now()
        limit = decided_limit if type(decided_limit) is int and decided_limit > 0 else 20
        pending: list[GateChallenge] = []
        decided: list[GateChallenge] = []
        with self._lock:
            for (ws, _), row in self._rows.items():
                if ws != workspace_id:
                    continue
                if row.status == "pending":
                    if row.expires_at is not None:
                        try:
                            exp = _parse_rfc3339(row.expires_at)
                        except GateSurfaceAuthorityError:
                            exp = None
                        if exp is not None and exp <= clock:
                            row.status = "expired"
                            row.decided_at = _canon_now()
                            decided.append(row)
                            continue
                    pending.append(row)
                else:
                    decided.append(row)
        # Stable order: pending by gate_id, decided by decided_at desc then gate_id.
        pending.sort(key=lambda r: r.gate_id)
        decided.sort(
            key=lambda r: (r.decided_at or "", r.gate_id),
            reverse=True,
        )
        return pending + decided[:limit]

    def confirm_formula_source(
        self,
        *,
        workspace_id: str,
        task_ref: str,
        reviewed_source_sha256: str,
        confirmation_note: str,
        client_action_id: str,
        action_digest: str,
        gate_id: str | None = None,
        now: datetime | None = None,
    ) -> GateChallenge:
        """Gate 1 CAS: exact task + source SHA-256 + note against a pending row."""
        ws = _validate_id(workspace_id, "workspace_id")
        task_id = _strip_ref(task_ref, "task:", "task_ref")
        digest = _validate_digest(reviewed_source_sha256, "reviewed_source_sha256")
        note = _validate_note(confirmation_note, "confirmation_note")
        _validate_id(client_action_id, "client_action_id")
        _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()
        with self._lock:
            row = self._find_pending_locked(
                workspace_id=ws,
                gate_kind="gate1",
                gate_id=gate_id,
                task_id=task_id,
                reviewed_source_sha256=digest,
                clock=clock,
                client_action_id=client_action_id,
                action_digest=action_digest,
            )
            if row.status != "pending":
                # Exact replay of a prior successful decide.
                if (
                    row.decision_action_id == client_action_id
                    and row.decision_action_digest == action_digest
                    and row.status == "confirmed"
                ):
                    return row
                raise GateSurfaceAuthorityError("conflict", "gate_not_pending")
            row.status = "confirmed"
            row.note = note
            row.decided_at = _canon_now()
            row.decision_action_id = client_action_id
            row.decision_action_digest = action_digest
            return row

    def review_candidate(
        self,
        *,
        workspace_id: str,
        candidate_ref: str,
        expected_digest: str,
        expected_status: str,
        note: str,
        client_action_id: str,
        action_digest: str,
        gate_id: str | None = None,
        now: datetime | None = None,
    ) -> GateChallenge:
        """Gate 2 CAS: exact candidate + digest + pending + note (no-refetch)."""
        ws = _validate_id(workspace_id, "workspace_id")
        candidate_id = _strip_ref(candidate_ref, "candidate:", "candidate_ref")
        digest = _validate_digest(expected_digest, "expected_digest")
        if type(expected_status) is not str or expected_status != "pending":
            raise GateSurfaceAuthorityError(
                "validation", "expected_status must be pending"
            )
        note_v = _validate_note(note, "note")
        _validate_id(client_action_id, "client_action_id")
        _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()
        with self._lock:
            row = self._find_pending_locked(
                workspace_id=ws,
                gate_kind="gate2",
                gate_id=gate_id,
                candidate_id=candidate_id,
                expected_digest=digest,
                clock=clock,
                client_action_id=client_action_id,
                action_digest=action_digest,
            )
            if row.status != "pending":
                if (
                    row.decision_action_id == client_action_id
                    and row.decision_action_digest == action_digest
                    and row.status == "reviewed"
                ):
                    return row
                raise GateSurfaceAuthorityError("conflict", "gate_not_pending")
            row.status = "reviewed"
            row.note = note_v
            row.decided_at = _canon_now()
            row.decision_action_id = client_action_id
            row.decision_action_digest = action_digest
            return row

    def prepare_promotion_review(
        self,
        *,
        workspace_id: str,
        candidate_ref: str,
        expected_digest: str,
        final_backtest_receipt_ref: str,
        base_commit: str,
        client_action_id: str,
        action_digest: str,
        gate_id: str | None = None,
        now: datetime | None = None,
    ) -> GateChallenge:
        """Gate 3 CAS prepare only — never performs a Git commit."""
        ws = _validate_id(workspace_id, "workspace_id")
        candidate_id = _strip_ref(candidate_ref, "candidate:", "candidate_ref")
        digest = _validate_digest(expected_digest, "expected_digest")
        receipt_id = _strip_ref(
            final_backtest_receipt_ref, "receipt:", "final_backtest_receipt_ref"
        )
        if type(base_commit) is not str or _HEX40.fullmatch(base_commit) is None:
            raise GateSurfaceAuthorityError(
                "validation", "base_commit must be a lowercase 40-hex commit"
            )
        _validate_id(client_action_id, "client_action_id")
        _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()
        with self._lock:
            row = self._find_pending_locked(
                workspace_id=ws,
                gate_kind="gate3",
                gate_id=gate_id,
                candidate_id=candidate_id,
                expected_digest=digest,
                final_backtest_receipt_id=receipt_id,
                base_commit=base_commit,
                clock=clock,
                client_action_id=client_action_id,
                action_digest=action_digest,
            )
            if row.status != "pending":
                if (
                    row.decision_action_id == client_action_id
                    and row.decision_action_digest == action_digest
                    and row.status == "prepared"
                ):
                    return row
                raise GateSurfaceAuthorityError("conflict", "gate_not_pending")
            row.status = "prepared"
            row.decided_at = _canon_now()
            row.decision_action_id = client_action_id
            row.decision_action_digest = action_digest
            # Explicit non-goal marker: prepare never mutates git.
            row.note = "promotion_review_prepared; human_git_commit_required"
            return row

    def _find_pending_locked(
        self,
        *,
        workspace_id: str,
        gate_kind: GateKind,
        gate_id: str | None,
        clock: datetime,
        client_action_id: str,
        action_digest: str,
        task_id: str | None = None,
        reviewed_source_sha256: str | None = None,
        candidate_id: str | None = None,
        expected_digest: str | None = None,
        final_backtest_receipt_id: str | None = None,
        base_commit: str | None = None,
    ) -> GateChallenge:
        candidates: list[GateChallenge] = []
        for (ws, gid), row in self._rows.items():
            if ws != workspace_id:
                continue
            if gate_id is not None and gid != gate_id:
                continue
            if row.gate_kind != gate_kind:
                continue
            # Exact-replay of already-decided row with same action wins first.
            if (
                row.status != "pending"
                and row.decision_action_id == client_action_id
                and row.decision_action_digest == action_digest
            ):
                return row
            if row.status != "pending":
                continue
            if row.expires_at is not None:
                try:
                    exp = _parse_rfc3339(row.expires_at)
                except GateSurfaceAuthorityError:
                    exp = None
                if exp is not None and exp <= clock:
                    row.status = "expired"
                    row.decided_at = _canon_now()
                    continue
            if task_id is not None and row.task_id != task_id:
                continue
            if (
                reviewed_source_sha256 is not None
                and row.reviewed_source_sha256 != reviewed_source_sha256
            ):
                continue
            if candidate_id is not None and row.candidate_id != candidate_id:
                continue
            if expected_digest is not None and row.expected_digest != expected_digest:
                continue
            if (
                final_backtest_receipt_id is not None
                and row.final_backtest_receipt_id != final_backtest_receipt_id
            ):
                continue
            if base_commit is not None and row.base_commit != base_commit:
                continue
            candidates.append(row)
        if not candidates:
            # Maybe an exact replay against a terminal row that didn't match above
            # because gate_id was unbound — scan terminals.
            for (ws, _), row in self._rows.items():
                if ws != workspace_id or row.gate_kind != gate_kind:
                    continue
                if (
                    row.decision_action_id == client_action_id
                    and row.decision_action_digest == action_digest
                ):
                    return row
            raise GateSurfaceAuthorityError("conflict", "gate_challenge_not_found")
        if len(candidates) > 1 and gate_id is None:
            # Ambiguous without gate_id — fail closed (no silent pick).
            raise GateSurfaceAuthorityError(
                "conflict", "gate_challenge_ambiguous_without_gate_id"
            )
        return candidates[0]


_DEFAULT_AUTHORITY = GateSurfaceAuthority()


def default_gate_surface_authority() -> GateSurfaceAuthority:
    return _DEFAULT_AUTHORITY


def reset_default_gate_surface_authority() -> None:
    _DEFAULT_AUTHORITY.reset()


__all__ = [
    "GateChallenge",
    "GateSurfaceAuthority",
    "GateSurfaceAuthorityError",
    "default_gate_surface_authority",
    "reset_default_gate_surface_authority",
]
