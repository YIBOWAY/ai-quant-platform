"""Hermetic V8-M5 release-candidate canary grant authority.

Owner-only, short-TTL, exact build-digest-bound grant for dual-vertical
acceptance under the same ``/hermes`` route. This is **not** public write,
**not** ``chat_write_ready=true``, **not** ``agentV02WebChat`` ON, **not**
M6 Gate2 decide, **not** V2 durable live ON, and **not** kill_switch flip.

Design freeze
-------------
* Issue CAS binds build_digest + route=/hermes + ttl + note → grant_id + grant_digest.
* At most one **active** grant per workspace (second issue conflicts unless prior
  revoked/expired/consumed).
* Revoke is idempotent on exact grant_digest; expired auto-marks on observe.
* Dual-vertical accept binds options_a + factor_b task/result refs under the
  active grant, records durable-in-process acceptance evidence, then **consumes**
  (revokes) the grant. Failure paths never open public flags.
* Snapshot projection lists active (non-expired) grant + recent terminal facts.
  Empty remains honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Literal
import hashlib
import json
import re
import uuid

GrantStatus = Literal["active", "revoked", "expired", "consumed"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ROUTE_ALLOWED = frozenset({"/hermes"})
_TTL_MIN = 60
_TTL_MAX = 3600


class CanaryGrantAuthorityError(RuntimeError):
    """Typed authority failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canon_ts(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CanaryGrantAuthorityError(
            "validation", "timestamp must be timezone-aware"
        )
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_rfc3339(value: str) -> datetime:
    if type(value) is not str or not value:
        raise CanaryGrantAuthorityError(
            "validation", "timestamp must be timezone-aware RFC3339"
        )
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise CanaryGrantAuthorityError(
            "validation", "timestamp must be timezone-aware RFC3339"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanaryGrantAuthorityError(
            "validation", "timestamp must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise CanaryGrantAuthorityError(
            "validation", f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise CanaryGrantAuthorityError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


def _validate_note(value: str, field: str) -> str:
    if type(value) is not str:
        raise CanaryGrantAuthorityError("validation", f"{field} must be a string")
    note = value.strip()
    if not note or len(note) > 500:
        raise CanaryGrantAuthorityError(
            "validation", f"{field} must be a nonempty note ≤500 chars"
        )
    return note


def _validate_route(route: str) -> str:
    if type(route) is not str or route not in _ROUTE_ALLOWED:
        raise CanaryGrantAuthorityError(
            "validation", "route must be exactly /hermes (no alternate canary page)"
        )
    return route


def _validate_ttl(ttl_seconds: int) -> int:
    if type(ttl_seconds) is not int or isinstance(ttl_seconds, bool):
        raise CanaryGrantAuthorityError(
            "validation", "ttl_seconds must be an int"
        )
    if ttl_seconds < _TTL_MIN or ttl_seconds > _TTL_MAX:
        raise CanaryGrantAuthorityError(
            "validation",
            f"ttl_seconds must be between {_TTL_MIN} and {_TTL_MAX}",
        )
    return ttl_seconds


def canonical_canary_grant_digest(
    *,
    workspace_id: str,
    grant_id: str,
    build_digest: str,
    route: str,
    expires_at: str,
    issued_at: str,
) -> str:
    """SHA-256 over canonical grant identity fields (no note; note is free text)."""
    payload = {
        "build_digest": build_digest,
        "expires_at": expires_at,
        "grant_id": grant_id,
        "issued_at": issued_at,
        "route": route,
        "workspace_id": workspace_id,
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class CanaryGrant:
    workspace_id: str
    grant_id: str
    build_digest: str
    route: str
    grant_digest: str
    issued_at: str
    expires_at: str
    status: GrantStatus = "active"
    grant_note: str = ""
    revoked_at: str | None = None
    revoke_reason: str | None = None
    issue_action_id: str | None = None
    issue_action_digest: str | None = None
    revoke_action_id: str | None = None
    revoke_action_digest: str | None = None
    # Dual-vertical acceptance evidence (set on consume).
    acceptance: dict[str, object] | None = None

    @property
    def canary_ref(self) -> str:
        return f"canary:{self.grant_id}"

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "grant_id": self.grant_id,
            "canary_ref": self.canary_ref,
            "build_digest": self.build_digest,
            "route": self.route,
            "grant_digest": self.grant_digest,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "kind": "v8.canary.grant",
            # Honesty: canary never implies public write.
            "public_write_authorized": False,
            "chat_write_ready": False,
            "release_authorized": False,
        }
        if self.grant_note:
            payload["grant_note"] = self.grant_note
        if self.revoked_at is not None:
            payload["revoked_at"] = self.revoked_at
        if self.revoke_reason is not None:
            payload["revoke_reason"] = self.revoke_reason
        if self.acceptance is not None:
            payload["acceptance"] = dict(self.acceptance)
        return payload


@dataclass
class DualVerticalAcceptance:
    workspace_id: str
    acceptance_id: str
    grant_id: str
    grant_digest: str
    build_digest: str
    options_a_task_id: str
    options_a_result_id: str
    factor_b_task_id: str
    factor_b_result_id: str
    acceptance_note: str
    accepted_at: str
    action_id: str
    action_digest: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "acceptance_id": self.acceptance_id,
            "grant_id": self.grant_id,
            "grant_digest": self.grant_digest,
            "build_digest": self.build_digest,
            "options_a_task_id": self.options_a_task_id,
            "options_a_result_id": self.options_a_result_id,
            "factor_b_task_id": self.factor_b_task_id,
            "factor_b_result_id": self.factor_b_result_id,
            "acceptance_note": self.acceptance_note,
            "accepted_at": self.accepted_at,
            "kind": "v8.canary.dual_vertical_acceptance",
            "public_write_authorized": False,
            "chat_write_ready": False,
            "release_authorized": False,
        }


class CanaryGrantAuthority:
    """In-process owner-local canary grant store (hermetic)."""

    def __init__(self) -> None:
        self._lock = Lock()
        # (workspace_id, grant_id) -> CanaryGrant
        self._grants: dict[tuple[str, str], CanaryGrant] = {}
        # workspace_id -> acceptance_id -> DualVerticalAcceptance
        self._acceptances: dict[str, dict[str, DualVerticalAcceptance]] = {}

    def reset(self) -> None:
        with self._lock:
            self._grants.clear()
            self._acceptances.clear()

    def _expire_locked(self, row: CanaryGrant, clock: datetime) -> CanaryGrant:
        if row.status == "active" and _parse_rfc3339(row.expires_at) <= clock:
            row.status = "expired"
            if row.revoked_at is None:
                row.revoked_at = _canon_ts(clock)
                row.revoke_reason = "ttl_expired"
        return row

    def get(self, workspace_id: str, grant_id: str) -> CanaryGrant | None:
        key = (workspace_id, grant_id)
        with self._lock:
            row = self._grants.get(key)
            if row is None:
                return None
            return self._expire_locked(row, _utc_now())

    def active_grant(self, workspace_id: str, *, now: datetime | None = None) -> CanaryGrant | None:
        clock = now or _utc_now()
        with self._lock:
            for (ws, _), row in self._grants.items():
                if ws != workspace_id:
                    continue
                self._expire_locked(row, clock)
                if row.status == "active":
                    return row
        return None

    def list_observed(
        self, workspace_id: str, *, now: datetime | None = None, limit: int = 20
    ) -> list[CanaryGrant]:
        """Active non-expired first, then recent terminal facts."""
        clock = now or _utc_now()
        with self._lock:
            rows = [
                self._expire_locked(r, clock)
                for (ws, _), r in self._grants.items()
                if ws == workspace_id
            ]
        active = [r for r in rows if r.status == "active"]
        terminal = sorted(
            [r for r in rows if r.status != "active"],
            key=lambda r: r.revoked_at or r.expires_at or r.issued_at,
            reverse=True,
        )
        out = active + terminal
        return out[: max(1, min(limit, 100))]

    def list_acceptances(
        self, workspace_id: str, *, limit: int = 20
    ) -> list[DualVerticalAcceptance]:
        with self._lock:
            rows = list(self._acceptances.get(workspace_id, {}).values())
        rows.sort(key=lambda r: r.accepted_at, reverse=True)
        return rows[: max(1, min(limit, 100))]

    def issue(
        self,
        *,
        workspace_id: str,
        build_digest: str,
        route: str,
        ttl_seconds: int,
        grant_note: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
        grant_id: str | None = None,
    ) -> CanaryGrant:
        ws = _validate_id(workspace_id, "workspace_id")
        bd = _validate_digest(build_digest, "build_digest")
        rt = _validate_route(route)
        ttl = _validate_ttl(ttl_seconds)
        note = _validate_note(grant_note, "grant_note")
        if type(client_action_id) is not str or not client_action_id:
            raise CanaryGrantAuthorityError("validation", "client_action_id required")
        ad = _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()

        with self._lock:
            # Idempotent replay of exact same issue action.
            for (w, _), row in self._grants.items():
                if w != ws:
                    continue
                if (
                    row.issue_action_id == client_action_id
                    and row.issue_action_digest == ad
                ):
                    return self._expire_locked(row, clock)

            # Expire any stale active, then refuse a second concurrent active.
            for (w, _), row in list(self._grants.items()):
                if w != ws:
                    continue
                self._expire_locked(row, clock)
                if row.status == "active":
                    raise CanaryGrantAuthorityError(
                        "conflict", "canary_grant_already_active"
                    )

            gid = grant_id or f"cgr-{uuid.uuid4().hex[:16]}"
            gid = _validate_id(gid, "grant_id")
            issued_at = _canon_ts(clock)
            expires_at = _canon_ts(clock + timedelta(seconds=ttl))
            gdigest = canonical_canary_grant_digest(
                workspace_id=ws,
                grant_id=gid,
                build_digest=bd,
                route=rt,
                expires_at=expires_at,
                issued_at=issued_at,
            )
            row = CanaryGrant(
                workspace_id=ws,
                grant_id=gid,
                build_digest=bd,
                route=rt,
                grant_digest=gdigest,
                issued_at=issued_at,
                expires_at=expires_at,
                status="active",
                grant_note=note,
                issue_action_id=client_action_id,
                issue_action_digest=ad,
            )
            self._grants[(ws, gid)] = row
            return row

    def revoke(
        self,
        *,
        workspace_id: str,
        canary_ref: str,
        expected_grant_digest: str,
        reason: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
        terminal_status: GrantStatus = "revoked",
    ) -> CanaryGrant:
        ws = _validate_id(workspace_id, "workspace_id")
        if type(canary_ref) is not str or not canary_ref.startswith("canary:"):
            raise CanaryGrantAuthorityError(
                "validation", "canary_ref must be canary:<grant_id>"
            )
        gid = _validate_id(canary_ref[len("canary:") :], "grant_id")
        ed = _validate_digest(expected_grant_digest, "expected_grant_digest")
        why = _validate_note(reason, "reason")
        if type(client_action_id) is not str or not client_action_id:
            raise CanaryGrantAuthorityError("validation", "client_action_id required")
        ad = _validate_digest(action_digest, "action_digest")
        if terminal_status not in ("revoked", "consumed"):
            raise CanaryGrantAuthorityError(
                "validation", "terminal_status must be revoked|consumed"
            )
        clock = now or _utc_now()
        key = (ws, gid)
        with self._lock:
            row = self._grants.get(key)
            if row is None:
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_not_found"
                )
            self._expire_locked(row, clock)

            # Idempotent exact revoke/consume replay.
            if (
                row.status in ("revoked", "consumed")
                and row.revoke_action_id == client_action_id
                and row.revoke_action_digest == ad
                and row.grant_digest == ed
            ):
                return row

            if row.grant_digest != ed:
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_digest_mismatch"
                )
            if row.status == "expired":
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_expired"
                )
            if row.status in ("revoked", "consumed"):
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_already_terminal"
                )
            if row.status != "active":
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_not_active"
                )

            row.status = terminal_status
            row.revoked_at = _canon_ts(clock)
            row.revoke_reason = why
            row.revoke_action_id = client_action_id
            row.revoke_action_digest = ad
            return row

    def accept_dual_vertical(
        self,
        *,
        workspace_id: str,
        canary_ref: str,
        expected_build_digest: str,
        expected_grant_digest: str,
        options_a_task_id: str,
        options_a_result_id: str,
        factor_b_task_id: str,
        factor_b_result_id: str,
        acceptance_note: str,
        client_action_id: str,
        action_digest: str,
        now: datetime | None = None,
    ) -> tuple[CanaryGrant, DualVerticalAcceptance]:
        """Record dual-vertical owner acceptance and consume the active grant."""
        ws = _validate_id(workspace_id, "workspace_id")
        if type(canary_ref) is not str or not canary_ref.startswith("canary:"):
            raise CanaryGrantAuthorityError(
                "validation", "canary_ref must be canary:<grant_id>"
            )
        gid = _validate_id(canary_ref[len("canary:") :], "grant_id")
        ebd = _validate_digest(expected_build_digest, "expected_build_digest")
        egd = _validate_digest(expected_grant_digest, "expected_grant_digest")
        oa_t = _validate_id(options_a_task_id, "options_a_task_id")
        oa_r = _validate_id(options_a_result_id, "options_a_result_id")
        fb_t = _validate_id(factor_b_task_id, "factor_b_task_id")
        fb_r = _validate_id(factor_b_result_id, "factor_b_result_id")
        note = _validate_note(acceptance_note, "acceptance_note")
        if type(client_action_id) is not str or not client_action_id:
            raise CanaryGrantAuthorityError("validation", "client_action_id required")
        ad = _validate_digest(action_digest, "action_digest")
        clock = now or _utc_now()

        # External vertical/result existence checks (outside lock for import safety).
        from quant_system.hermes.vertical_binding_authority import (
            default_vertical_binding_authority,
        )
        from quant_system.hermes.result_surface_authority import (
            default_result_surface_authority,
        )

        binder = default_vertical_binding_authority()
        rauth = default_result_surface_authority()

        oa_task = binder.get_task(ws, oa_t)
        fb_task = binder.get_task(ws, fb_t)
        if oa_task is None:
            raise CanaryGrantAuthorityError(
                "conflict", "options_a_task_not_found"
            )
        if fb_task is None:
            raise CanaryGrantAuthorityError(
                "conflict", "factor_b_task_not_found"
            )
        # VerticalTaskRecord.vertical is "options_a" | "factor_b".
        if str(getattr(oa_task, "vertical", "")) != "options_a":
            raise CanaryGrantAuthorityError(
                "conflict", "options_a_task_vertical_mismatch"
            )
        if str(getattr(fb_task, "vertical", "")) != "factor_b":
            raise CanaryGrantAuthorityError(
                "conflict", "factor_b_task_vertical_mismatch"
            )

        oa_res = rauth.get(ws, oa_r)
        fb_res = rauth.get(ws, fb_r)
        if oa_res is None:
            raise CanaryGrantAuthorityError(
                "conflict", "options_a_result_not_found"
            )
        if fb_res is None:
            raise CanaryGrantAuthorityError(
                "conflict", "factor_b_result_not_found"
            )
        if getattr(oa_res, "task_id", None) != oa_t:
            raise CanaryGrantAuthorityError(
                "conflict", "options_a_result_task_mismatch"
            )
        if getattr(fb_res, "task_id", None) != fb_t:
            raise CanaryGrantAuthorityError(
                "conflict", "factor_b_result_task_mismatch"
            )
        # TypedResultRecord.kind: options_vertical_a / factor.
        oa_kind = str(getattr(oa_res, "kind", "") or "")
        fb_kind = str(getattr(fb_res, "kind", "") or "")
        if oa_kind != "options_vertical_a":
            raise CanaryGrantAuthorityError(
                "conflict", "options_a_result_kind_mismatch"
            )
        if fb_kind != "factor":
            raise CanaryGrantAuthorityError(
                "conflict", "factor_b_result_kind_mismatch"
            )

        key = (ws, gid)
        with self._lock:
            row = self._grants.get(key)
            if row is None:
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_not_found"
                )
            self._expire_locked(row, clock)

            # Idempotent accept replay.
            existing_acc = None
            for acc in self._acceptances.get(ws, {}).values():
                if (
                    acc.action_id == client_action_id
                    and acc.action_digest == ad
                ):
                    existing_acc = acc
                    break
            if existing_acc is not None:
                return row, existing_acc

            if row.status == "expired":
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_expired"
                )
            if row.status != "active":
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_not_active"
                )
            if row.grant_digest != egd:
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_grant_digest_mismatch"
                )
            if row.build_digest != ebd:
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_build_digest_mismatch"
                )
            if row.route != "/hermes":
                raise CanaryGrantAuthorityError(
                    "conflict", "canary_route_mismatch"
                )

            aid = f"cacc-{uuid.uuid4().hex[:16]}"
            accepted_at = _canon_ts(clock)
            acceptance = DualVerticalAcceptance(
                workspace_id=ws,
                acceptance_id=aid,
                grant_id=gid,
                grant_digest=row.grant_digest,
                build_digest=row.build_digest,
                options_a_task_id=oa_t,
                options_a_result_id=oa_r,
                factor_b_task_id=fb_t,
                factor_b_result_id=fb_r,
                acceptance_note=note,
                accepted_at=accepted_at,
                action_id=client_action_id,
                action_digest=ad,
            )
            self._acceptances.setdefault(ws, {})[aid] = acceptance

            row.status = "consumed"
            row.revoked_at = accepted_at
            row.revoke_reason = "dual_vertical_accepted"
            row.revoke_action_id = client_action_id
            row.revoke_action_digest = ad
            row.acceptance = acceptance.to_public_dict()
            return row, acceptance


_DEFAULT = CanaryGrantAuthority()


def default_canary_grant_authority() -> CanaryGrantAuthority:
    return _DEFAULT


def reset_default_canary_grant_authority() -> None:
    _DEFAULT.reset()


__all__ = [
    "CanaryGrant",
    "CanaryGrantAuthority",
    "CanaryGrantAuthorityError",
    "DualVerticalAcceptance",
    "canonical_canary_grant_digest",
    "default_canary_grant_authority",
    "reset_default_canary_grant_authority",
]
