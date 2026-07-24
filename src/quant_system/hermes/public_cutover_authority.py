"""Hermetic V8-M6 public flag cutover authority (G7 open + G8 rollback).

Single public flag cutover under the same ``/hermes`` route. Opening the flag
stamps ``public_write_authorized=true`` / ``chat_write_ready=true`` **on the
cutover public dict and ActionReceipt only while status=open**. Global gateway
``composer_readiness`` / health ``chat_write_ready`` remain a separate settings
composition and are **not** auto-flipped by this authority (compose at release
stamp if desired). Closing the flag is one-click rollback that:

* never deletes append-only facts
* never flips kill_switch / paper / dry_run
* never couples M6 Gate2 decide
* never smuggles V2 durable live ON
* never sets ``release_authorized=true`` (full V8 release is a separate stamp)

Design freeze
-------------
* Open CAS binds build_digest + route=/hermes + prerequisite dual-vertical
  acceptance_id (G6 evidence) + note → cutover_id + cutover_digest.
* At most one **open** cutover per workspace (second open conflicts unless prior
  closed/revoked).
* Close is idempotent on exact cutover_digest; closed cutover leaves facts.
* Snapshot projection lists open cutover + recent closed facts. Empty honest.
* Public dict honesty: ``release_authorized=False`` always; ``kill_switch``
  never touched; ``m6_gate2_decide_authorized=False``; ``v2_durable_live=False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
import hashlib
import json
import re
import uuid

CutoverStatus = Literal["open", "closed"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ROUTE_ALLOWED = frozenset({"/hermes"})


class PublicCutoverAuthorityError(RuntimeError):
    """Typed authority failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canon_ts(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PublicCutoverAuthorityError(
            "validation", "timestamp must be timezone-aware"
        )
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise PublicCutoverAuthorityError(
            "validation", f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise PublicCutoverAuthorityError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


def _validate_note(value: str, field: str) -> str:
    if type(value) is not str:
        raise PublicCutoverAuthorityError("validation", f"{field} must be a string")
    note = value.strip()
    if not note or len(note) > 500:
        raise PublicCutoverAuthorityError(
            "validation", f"{field} must be a nonempty note ≤500 chars"
        )
    return note


def _validate_route(route: str) -> str:
    if type(route) is not str or route not in _ROUTE_ALLOWED:
        raise PublicCutoverAuthorityError(
            "validation", "route must be exactly /hermes (no alternate public page)"
        )
    return route


def canonical_public_cutover_digest(
    *,
    workspace_id: str,
    cutover_id: str,
    build_digest: str,
    route: str,
    acceptance_id: str,
    opened_at: str,
) -> str:
    """SHA-256 over canonical cutover identity fields (no note; note is free text)."""
    payload = {
        "acceptance_id": acceptance_id,
        "build_digest": build_digest,
        "cutover_id": cutover_id,
        "opened_at": opened_at,
        "route": route,
        "workspace_id": workspace_id,
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class PublicCutover:
    workspace_id: str
    cutover_id: str
    build_digest: str
    route: str
    cutover_digest: str
    acceptance_id: str
    opened_at: str
    status: CutoverStatus = "open"
    open_note: str = ""
    closed_at: str | None = None
    close_reason: str | None = None
    open_action_id: str | None = None
    open_action_digest: str | None = None
    close_action_id: str | None = None
    close_action_digest: str | None = None

    @property
    def cutover_ref(self) -> str:
        return f"cutover:{self.cutover_id}"

    @property
    def public_flag_open(self) -> bool:
        return self.status == "open"

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "cutover_id": self.cutover_id,
            "cutover_ref": self.cutover_ref,
            "build_digest": self.build_digest,
            "route": self.route,
            "cutover_digest": self.cutover_digest,
            "acceptance_id": self.acceptance_id,
            "opened_at": self.opened_at,
            "status": self.status,
            "public_flag_open": self.public_flag_open,
            "kind": "v8.public.cutover",
            # Honesty triad for release / trading / durable rails.
            "release_authorized": False,
            "m6_gate2_decide_authorized": False,
            "v2_durable_live": False,
            "kill_switch_unchanged": True,
            # Public write surface is open only while status=open.
            "public_write_authorized": self.public_flag_open,
            "chat_write_ready": self.public_flag_open,
        }
        if self.open_note:
            payload["open_note"] = self.open_note
        if self.closed_at is not None:
            payload["closed_at"] = self.closed_at
        if self.close_reason is not None:
            payload["close_reason"] = self.close_reason
        return payload


class PublicCutoverAuthority:
    """In-process owner-local public cutover store (hermetic)."""

    def __init__(self) -> None:
        self._lock = Lock()
        # (workspace_id, cutover_id) -> PublicCutover
        self._cutovers: dict[tuple[str, str], PublicCutover] = {}

    def reset(self) -> None:
        with self._lock:
            self._cutovers.clear()

    def get(self, workspace_id: str, cutover_id: str) -> PublicCutover | None:
        return self._cutovers.get((workspace_id, cutover_id))

    def open_cutover(self, workspace_id: str) -> PublicCutover | None:
        """Return the currently open cutover for workspace, if any."""
        with self._lock:
            for (ws, _), row in self._cutovers.items():
                if ws == workspace_id and row.status == "open":
                    return row
        return None

    def is_public_flag_open(self, workspace_id: str) -> bool:
        row = self.open_cutover(workspace_id)
        return row is not None and row.status == "open"

    def list_observed(
        self, workspace_id: str, *, limit: int = 20
    ) -> list[PublicCutover]:
        """Open first, then recent closed facts."""
        with self._lock:
            rows = [r for (ws, _), r in self._cutovers.items() if ws == workspace_id]
        opened = [r for r in rows if r.status == "open"]
        closed = sorted(
            [r for r in rows if r.status != "open"],
            key=lambda r: r.closed_at or r.opened_at,
            reverse=True,
        )
        out = opened + closed
        return out[: max(1, min(limit, 100))]

    def open(
        self,
        *,
        workspace_id: str,
        build_digest: str,
        route: str,
        acceptance_id: str,
        open_note: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
        cutover_id: str | None = None,
        # Prerequisite checker: must prove G6 dual-vertical acceptance exists.
        require_acceptance: bool = True,
        acceptance_exists: bool | None = None,
    ) -> PublicCutover:
        ws = _validate_id(workspace_id, "workspace_id")
        bd = _validate_digest(build_digest, "build_digest")
        rt = _validate_route(route)
        aid = _validate_id(acceptance_id, "acceptance_id")
        note = _validate_note(open_note, "open_note")
        if type(client_action_id) is not str or not client_action_id:
            raise PublicCutoverAuthorityError("validation", "client_action_id required")
        ad = _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()

        if require_acceptance:
            # Caller supplies existence check (saga binds canary acceptances).
            if acceptance_exists is not True:
                raise PublicCutoverAuthorityError(
                    "validation",
                    "dual_vertical_acceptance_required",
                )

        with self._lock:
            # Idempotent replay of exact same open action — only while still open.
            # After close, replaying the same open action must NOT resurrect the
            # flag or claim public write; force a fresh client_action_id to reopen.
            for (w, _), row in self._cutovers.items():
                if w != ws:
                    continue
                if (
                    row.open_action_id == client_action_id
                    and row.open_action_digest == ad
                ):
                    if row.status == "open":
                        return row
                    raise PublicCutoverAuthorityError(
                        "conflict", "public_cutover_already_closed"
                    )
                if row.status == "open":
                    raise PublicCutoverAuthorityError(
                        "conflict", "public_cutover_already_open"
                    )

            cid = cutover_id or f"pct-{uuid.uuid4().hex[:16]}"
            cid = _validate_id(cid, "cutover_id")
            opened_at = _canon_ts(clock)
            cdigest = canonical_public_cutover_digest(
                workspace_id=ws,
                cutover_id=cid,
                build_digest=bd,
                route=rt,
                acceptance_id=aid,
                opened_at=opened_at,
            )
            row = PublicCutover(
                workspace_id=ws,
                cutover_id=cid,
                build_digest=bd,
                route=rt,
                cutover_digest=cdigest,
                acceptance_id=aid,
                opened_at=opened_at,
                status="open",
                open_note=note,
                open_action_id=client_action_id,
                open_action_digest=ad,
            )
            self._cutovers[(ws, cid)] = row
            return row

    def close(
        self,
        *,
        workspace_id: str,
        cutover_ref: str,
        expected_cutover_digest: str,
        reason: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
    ) -> PublicCutover:
        ws = _validate_id(workspace_id, "workspace_id")
        if type(cutover_ref) is not str or not cutover_ref.startswith("cutover:"):
            raise PublicCutoverAuthorityError(
                "validation", "cutover_ref must be cutover:<cutover_id>"
            )
        cid = _validate_id(cutover_ref[len("cutover:") :], "cutover_id")
        ed = _validate_digest(expected_cutover_digest, "expected_cutover_digest")
        why = _validate_note(reason, "reason")
        if type(client_action_id) is not str or not client_action_id:
            raise PublicCutoverAuthorityError("validation", "client_action_id required")
        ad = _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()

        with self._lock:
            row = self._cutovers.get((ws, cid))
            if row is None:
                raise PublicCutoverAuthorityError(
                    "not_found", "public_cutover_not_found"
                )
            if row.cutover_digest != ed:
                raise PublicCutoverAuthorityError(
                    "conflict", "cutover_digest_mismatch"
                )
            # Idempotent close of exact same action.
            if (
                row.status == "closed"
                and row.close_action_id == client_action_id
                and row.close_action_digest == ad
            ):
                return row
            if row.status == "closed":
                # Already closed by another action — still return the fact
                # (rollback is durable; append-only facts retained).
                return row
            row.status = "closed"
            row.closed_at = _canon_ts(clock)
            row.close_reason = why
            row.close_action_id = client_action_id
            row.close_action_digest = ad
            return row


_DEFAULT: PublicCutoverAuthority | None = None
_DEFAULT_LOCK = Lock()


def default_public_cutover_authority() -> PublicCutoverAuthority:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = PublicCutoverAuthority()
        return _DEFAULT


def reset_default_public_cutover_authority() -> None:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is not None:
            _DEFAULT.reset()
        _DEFAULT = PublicCutoverAuthority()


__all__ = [
    "PublicCutover",
    "PublicCutoverAuthority",
    "PublicCutoverAuthorityError",
    "canonical_public_cutover_digest",
    "default_public_cutover_authority",
    "reset_default_public_cutover_authority",
]
