from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import pytest

from quant_system.config.settings import Settings
from quant_system.hermes.paper_run_attestation import (
    AttestPaperRun,
    PaperRunAttestationAuthority,
    PaperRunAttestationConflict,
    PaperRunAttestationUnavailable,
    _parse_sse_events,
    _PlatformRunBinding,
)

COMMAND_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "run_paper_subject"
SESSION_ID = "web_paper_subject"
CONVERSATION_SESSION_ID = "web_paper_conversation_root"


def _event(
    sequence: int,
    event_type: str,
    *,
    event_id: str | None = None,
    run_id: str = RUN_ID,
    **values: object,
) -> dict[str, object]:
    return {
        "event": event_type,
        "event_id": event_id or f"evt_{sequence:032x}",
        "run_id": run_id,
        "seq": sequence,
        **values,
    }


def _frame(event: Mapping[str, object], *, frame_id: str | None = None) -> bytes:
    sequence = event["seq"] if frame_id is None else frame_id
    return (
        f"id: {sequence}\n"
        f"event: {event['event']}\n"
        f"data: {json.dumps(dict(event), separators=(',', ':'))}\n\n"
    ).encode()


class _Reader:
    def __init__(
        self,
        *,
        instance_id: str = "a" * 32,
        started_at: str = "2026-07-24T00:00:00Z",
        events: tuple[Mapping[str, object], ...] | None = None,
        output: str = "paper research completed",
        provider: str = "openrouter",
        model: str = "anthropic/claude-sonnet-4",
    ) -> None:
        self._instance_id = instance_id
        self._started_at = started_at
        self._output = output
        self._provider = provider
        self._model = model
        self._events = events or (
            _event(1, "run.started"),
            _event(2, "run.completed", output=output),
        )

    def capabilities(self) -> Mapping[str, object]:
        return {
            "features": {
                "run_events_sse": True,
                "run_events_snapshot": True,
                "run_status": True,
            },
            "durable": {
                "event_replay": {"grounded": True, "supported": True},
                "run_evidence": {"grounded": True, "supported": True},
            },
            "runtime": {
                "instance_id": self._instance_id,
                "started_at": self._started_at,
            },
        }

    def run_status(self, run_id: str) -> Mapping[str, object]:
        return {
            "actual_policy": {
                "model": self._model,
                "provider": self._provider,
            },
            "object": "hermes.run",
            "output": self._output,
            "run_id": run_id,
            "session_id": SESSION_ID,
            "conversation_session_id": CONVERSATION_SESSION_ID,
            "resolved_session_id": SESSION_ID,
            "status": "succeeded",
        }

    def run_events(self, run_id: str) -> tuple[Mapping[str, object], ...]:
        return self._events


class _BoundAuthority(PaperRunAttestationAuthority):
    def _platform_binding(self, request: AttestPaperRun) -> _PlatformRunBinding:
        return _PlatformRunBinding(
            command_state=("succeeded" if request.mode == "subject" else "delivered"),
            hermes_session_id=CONVERSATION_SESSION_ID,
            resolved_hermes_session_id=SESSION_ID,
        )


def _request(mode: str = "subject") -> AttestPaperRun:
    return AttestPaperRun(
        mode=mode,  # type: ignore[arg-type]
        workspace_id="workspace-root",
        platform_session_id="platform-session-paper",
        hermes_session_id=CONVERSATION_SESSION_ID,
        command_id=COMMAND_ID,
        hermes_run_id=RUN_ID,
    )


def test_sse_parser_accepts_exact_monotonic_canonical_frames() -> None:
    first = _event(1, "run.started")
    second = _event(3, "run.completed", output="done")

    assert _parse_sse_events(_frame(first) + _frame(second)) == (first, second)


@pytest.mark.parametrize(
    "raw",
    [
        (
            b"id: 1\nid: 1\nevent: run.started\n"
            b'data: {"event":"run.started","event_id":"evt_00000000000000000000000000000001",'
            b'"run_id":"run_paper_subject","seq":1}\n\n'
        ),
        (
            b"id: 1\nevent: run.started\nevent: run.started\n"
            b'data: {"event":"run.started","event_id":"evt_00000000000000000000000000000001",'
            b'"run_id":"run_paper_subject","seq":1}\n\n'
        ),
        (
            b"id: 1\nevent: run.started\n"
            b'data: {"event":"run.started","event_id":"evt_00000000000000000000000000000001",'
            b'"run_id":"run_paper_subject","seq":1}\n'
            b'data: {"event":"run.started","event_id":"evt_00000000000000000000000000000001",'
            b'"run_id":"run_paper_subject","seq":1}\n\n'
        ),
    ],
    ids=("duplicate-id", "duplicate-event", "duplicate-data"),
)
def test_sse_parser_rejects_every_duplicate_envelope_field(raw: bytes) -> None:
    with pytest.raises(PaperRunAttestationUnavailable, match="duplicate"):
        _parse_sse_events(raw)


@pytest.mark.parametrize(
    ("events", "frame_ids"),
    [
        ((_event(1, "run.started"),), ("2",)),
        ((_event(0, "run.started"),), ("0",)),
        ((_event(2, "run.started"), _event(1, "run.completed")), ("2", "1")),
        ((_event(1, "run.started"), _event(1, "run.completed")), ("1", "1")),
        (
            (
                _event(1, "run.started", event_id="evt_" + "a" * 32),
                _event(2, "run.completed", event_id="evt_" + "a" * 32),
            ),
            ("1", "2"),
        ),
        ((_event(1, "run.started", event_id="event-" + "a" * 32),), ("1",)),
    ],
    ids=(
        "id-payload-mismatch",
        "non-positive",
        "descending",
        "duplicate-sequence",
        "duplicate-event-id",
        "non-canonical-event-id",
    ),
)
def test_sse_parser_rejects_noncanonical_event_identity(
    events: tuple[Mapping[str, object], ...],
    frame_ids: tuple[str, ...],
) -> None:
    raw = b"".join(
        _frame(event, frame_id=frame_id) for event, frame_id in zip(events, frame_ids, strict=True)
    )

    with pytest.raises(PaperRunAttestationUnavailable, match="identity"):
        _parse_sse_events(raw)


def test_sse_parser_rejects_nonfinite_json() -> None:
    raw = (
        b"id: 1\nevent: run.started\n"
        b'data: {"event":"run.started","event_id":"evt_00000000000000000000000000000001",'
        b'"run_id":"run_paper_subject","seq":1,"value":NaN}\n\n'
    )

    with pytest.raises(PaperRunAttestationUnavailable, match="data is invalid"):
        _parse_sse_events(raw)


def test_subject_attestation_rejects_fake_reader_event_identity() -> None:
    events = (
        _event(1, "run.started"),
        _event(
            2,
            "run.completed",
            event_id="forged-event",
            output="paper research completed",
        ),
    )
    authority = _BoundAuthority(
        Settings(),
        run_reader=_Reader(events=events),
    )

    with pytest.raises(PaperRunAttestationConflict, match="not canonical"):
        authority.attest(_request())


def test_subject_attestation_digest_excludes_observer_runtime_diagnostics() -> None:
    first = _BoundAuthority(
        Settings(),
        run_reader=_Reader(
            instance_id="a" * 32,
            started_at="2026-07-24T00:00:00Z",
        ),
    ).attest(_request())
    second = _BoundAuthority(
        Settings(),
        run_reader=_Reader(
            instance_id="b" * 32,
            started_at="2026-07-24T01:00:00Z",
        ),
    ).attest(_request())

    assert first["hermes_runtime_instance_id"] != second["hermes_runtime_instance_id"]
    assert first["hermes_runtime_started_at"] != second["hermes_runtime_started_at"]
    assert first["hermes_session_id"] == CONVERSATION_SESSION_ID
    assert first["resolved_hermes_session_id"] == SESSION_ID
    assert first["evidence_digest"] == second["evidence_digest"]
    assert first["attestation_ref"] == second["attestation_ref"]
    assert first["provider_evidence_ref"] == (
        f"provider-evidence:paper-run-{first['evidence_digest']}"
    )
    assert second["provider_evidence_ref"] == first["provider_evidence_ref"]

    digest_payload = {
        key: value
        for key, value in first.items()
        if key
        not in {
            "attestation_ref",
            "evidence_digest",
            "hermes_runtime_instance_id",
            "hermes_runtime_started_at",
            "provider_evidence_ref",
        }
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert first["evidence_digest"] == expected_digest


def test_subject_attestation_rejects_run_status_from_unrelated_lineage() -> None:
    class WrongLineageReader(_Reader):
        def run_status(self, run_id: str) -> Mapping[str, object]:
            return {
                **super().run_status(run_id),
                "conversation_session_id": "web_unrelated_conversation",
            }

    authority = _BoundAuthority(
        Settings(),
        run_reader=WrongLineageReader(),
    )

    with pytest.raises(PaperRunAttestationConflict, match="not exact"):
        authority.attest(_request())


def test_subject_attestation_digest_binds_provider_and_output() -> None:
    baseline = _BoundAuthority(
        Settings(),
        run_reader=_Reader(),
    ).attest(_request())
    changed = _BoundAuthority(
        Settings(),
        run_reader=_Reader(
            output="different terminal output",
            provider="another-provider",
        ),
    ).attest(_request())

    assert baseline["evidence_digest"] != changed["evidence_digest"]
