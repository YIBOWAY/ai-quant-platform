"""Plan-V6-Token-Stream-M1: ephemeral transcript *hints* on follow/SSE.

Hints never carry assistant bodies. Text authority remains
``GET /api/hermes/sessions/{id}/messages``. Durable command-event cursor is
unchanged. No Task invention, no public write, no provider token passthrough.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from threading import Lock
from typing import Any, Literal

TranscriptPhase = Literal["waiting", "partial", "final", "unavailable"]

_FORBIDDEN_BODY_KEYS = frozenset(
    {
        "content",
        "text",
        "tokens",
        "delta",
        "messages",
        "message",
        "body",
        "assistant",
        "payload",
    }
)

_TERMINAL_FINAL = frozenset(
    {
        "succeeded",
        "cancelled",
        "failed",
        "rejected",
        "timed_out",
    }
)

_IN_FLIGHT = frozenset(
    {
        "queued",
        "leased",
        "running",
        "dispatching",
        "accepted",
        "submitting",
        "delivered",
        "outcome_unknown",
    }
)

_HERMES_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


def phase_from_command_state(state: str | None) -> TranscriptPhase | None:
    """Map command lifecycle state → transcript phase hint (no body)."""
    if type(state) is not str or not state:
        return None
    s = state.strip().lower()
    if s in _TERMINAL_FINAL:
        return "final"
    if s in _IN_FLIGHT:
        return "waiting"
    return None


def revision_for(
    *,
    hermes_session_id: str,
    command_id: str | None,
    state: str | None,
    command_version: int | None = None,
) -> str:
    """Opaque monotonic-enough revision for FE dedupe (no body material)."""
    ver = int(command_version) if type(command_version) is int else 0
    cid = command_id or ""
    st = state or ""
    return f"{hermes_session_id}|{cid}|{st}|{ver}"


def project_transcript_hint(
    *,
    workspace_id: str,
    hermes_session_id: str,
    command_id: str | None,
    phase: TranscriptPhase | str,
    revision: str,
    mutation_enabled: bool = False,
) -> dict[str, object]:
    """Browser-safe transcript hint. Forbidden keys are stripped if present."""
    if type(workspace_id) is not str or not workspace_id.strip():
        raise ValueError("workspace_id required")
    sid = str(hermes_session_id or "").strip()
    if not sid:
        raise ValueError("hermes_session_id required")
    # `web_*` is the canonical Hermes SessionDB identity for managed Web
    # sessions. Platform-only `wm_*` registry ids must never hit messages BFF.
    if sid.startswith("wm_") or _HERMES_SESSION_ID_RE.fullmatch(sid) is None:
        raise ValueError("hermes_session_id not usable for messages")
    phase_s = str(phase or "").strip().lower()
    if phase_s not in {"waiting", "partial", "final", "unavailable"}:
        raise ValueError("invalid transcript phase")
    rev = str(revision or "").strip()
    if not rev:
        raise ValueError("revision required")
    payload: dict[str, object] = {
        "workspace_id": workspace_id,
        "hermes_session_id": sid,
        "command_id": None if command_id in (None, "") else str(command_id),
        "phase": phase_s,
        "revision": rev,
        "mutation_enabled": bool(mutation_enabled),
        # Honesty markers for FE/docs (not bodies).
        "transport": "spine-refetch",
        "limitations": [
            "assistant_body_not_on_follow_spine",
            "not_provider_token_passthrough",
            "messages_bff_is_text_authority",
            "public_write_off",
        ],
    }
    for key in list(payload.keys()):
        if key in _FORBIDDEN_BODY_KEYS:
            payload.pop(key, None)
    return payload


def hints_from_command_events(
    *,
    workspace_id: str,
    events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    mutation_enabled: bool = False,
) -> list[dict[str, object]]:
    """Derive body-free transcript hints from follow command events."""
    out: list[dict[str, object]] = []
    seen_rev: set[str] = set()
    for item in events:
        if not isinstance(item, Mapping):
            continue
        sid = item.get("hermes_session_id")
        if type(sid) is not str or not sid.strip():
            continue
        if sid.startswith("wm_"):
            continue
        state = item.get("state")
        phase = phase_from_command_state(
            str(state) if state is not None else None
        )
        if phase is None:
            continue
        command_id = item.get("command_id")
        version = item.get("command_version")
        if type(version) is not int:
            version = item.get("version")
        rev = revision_for(
            hermes_session_id=sid,
            command_id=str(command_id) if command_id else None,
            state=str(state) if state is not None else None,
            command_version=version if type(version) is int else None,
        )
        if rev in seen_rev:
            continue
        seen_rev.add(rev)
        try:
            out.append(
                project_transcript_hint(
                    workspace_id=workspace_id,
                    hermes_session_id=sid,
                    command_id=str(command_id) if command_id else None,
                    phase=phase,
                    revision=rev,
                    mutation_enabled=mutation_enabled,
                )
            )
        except ValueError:
            continue
    return out


def assert_hint_has_no_body(hint: Mapping[str, Any]) -> None:
    """Raise if a hint smuggles assistant body fields."""
    for key in _FORBIDDEN_BODY_KEYS:
        if key in hint and hint[key] not in (None, "", [], {}):
            raise ValueError(f"transcript hint forbids body field: {key}")


class TranscriptObserveJournal:
    """Fingerprint journal so SSE only emits changed transcript hints.

    Independent of durable command event_id cursor and of approval/gate/result
    journals. Process-global hermetic M1.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # (workspace_id, hermes_session_id) -> last revision
        self._last_rev: dict[tuple[str, str], str] = {}
        self._last_fp: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._last_rev.clear()
            self._last_fp.clear()

    def take_hints_if_changed(
        self,
        workspace_id: str,
        hints: list[dict[str, object]],
    ) -> list[dict[str, object]] | None:
        """Return hints that are new/changed vs last emission; None if idle."""
        if type(workspace_id) is not str or not workspace_id:
            return None
        clean: list[dict[str, object]] = []
        for h in hints:
            if not isinstance(h, dict):
                continue
            try:
                assert_hint_has_no_body(h)
            except ValueError:
                continue
            sid = h.get("hermes_session_id")
            rev = h.get("revision")
            if type(sid) is not str or type(rev) is not str:
                continue
            clean.append(h)
        if not clean:
            # Still update empty fingerprint so we do not re-emit forever.
            fp = ""
            with self._lock:
                prior = self._last_fp.get(workspace_id)
                if prior == fp:
                    return None
                self._last_fp[workspace_id] = fp
            return None

        changed: list[dict[str, object]] = []
        with self._lock:
            for h in clean:
                sid = str(h["hermes_session_id"])
                rev = str(h["revision"])
                key = (workspace_id, sid)
                if self._last_rev.get(key) == rev:
                    continue
                self._last_rev[key] = rev
                changed.append(h)
            fp = "|".join(
                f"{h.get('hermes_session_id')}:{h.get('revision')}:{h.get('phase')}"
                for h in clean
            )
            self._last_fp[workspace_id] = fp
        return changed or None


_DEFAULT_JOURNAL = TranscriptObserveJournal()


def default_transcript_observe_journal() -> TranscriptObserveJournal:
    return _DEFAULT_JOURNAL


def reset_default_transcript_observe_journal() -> None:
    _DEFAULT_JOURNAL.reset()


__all__ = [
    "TranscriptObserveJournal",
    "TranscriptPhase",
    "assert_hint_has_no_body",
    "default_transcript_observe_journal",
    "hints_from_command_events",
    "phase_from_command_state",
    "project_transcript_hint",
    "reset_default_transcript_observe_journal",
    "revision_for",
]
