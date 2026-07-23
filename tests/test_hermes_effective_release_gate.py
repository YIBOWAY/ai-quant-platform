from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_authority import (
    PublicCutoverRecord,
    ReleaseStampRecord,
)

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)
PLATFORM = "1" * 64
HQA = "2" * 64
HERMES = "3" * 64
SCHEMA = "4" * 64
EVIDENCE = "5" * 64
RELEASE = "6" * 64
CUTOVER = "7" * 64


def _stamp() -> ReleaseStampRecord:
    return ReleaseStampRecord(
        stamp_id="stamp-1",
        workspace_id="workspace-root",
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        evidence_digest=EVIDENCE,
        release_digest=RELEASE,
        status="active",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )


def _cutover() -> PublicCutoverRecord:
    return PublicCutoverRecord(
        cutover_id="cutover-1",
        stamp_id="stamp-1",
        workspace_id="workspace-root",
        route="/hermes",
        release_digest=RELEASE,
        cutover_digest=CUTOVER,
        status="open",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )


def _capabilities(*, observed_at: datetime = NOW) -> HermesDurableCapabilityObservation:
    return HermesDurableCapabilityObservation(
        runtime_digest=HERMES,
        observed_at=observed_at,
        payload={
            "contract_version": 1,
            "features": {
                "session_resources": True,
                "run_submission": True,
                "run_events_sse": True,
                "run_status": True,
                "run_approval_response": True,
                "run_stop": True,
                "managed_run_sessions": True,
            },
            "managed_session_contract": {
                "history_authority": "hermes_session_db",
                "fork_mode": "preserve_source_exact_message_cursor",
            },
            "durable": {
                name: {
                    "supported": True,
                    "grounded": True,
                    "evidence": f"store.transactional_probe:{name}",
                }
                for name in (
                    "idempotency",
                    "event_replay",
                    "approval_cas",
                    "idempotent_stop",
                    "restart_reconcile",
                    "run_evidence",
                )
            },
        },
    )


class _Authority:
    def __init__(
        self,
        *,
        stamp: ReleaseStampRecord | None = None,
        cutover: PublicCutoverRecord | None = None,
    ) -> None:
        self.stamp = stamp if stamp is not None else _stamp()
        self.cutover = cutover if cutover is not None else _cutover()

    def active_release_stamp(self, workspace_id: str) -> ReleaseStampRecord | None:
        assert workspace_id == "workspace-root"
        return self.stamp

    def open_public_cutover(self, workspace_id: str) -> PublicCutoverRecord | None:
        assert workspace_id == "workspace-root"
        return self.cutover

    def current_event_cursor(self, workspace_id: str) -> int:
        assert workspace_id == "workspace-root"
        return 42


def _gate(
    *,
    authority: _Authority | None = None,
    flags: LocalReleaseFlags | None = None,
    identities: RuntimeIdentityObservation | None = None,
    capability: HermesDurableCapabilityObservation | None = None,
    schema: str = SCHEMA,
    evidence: str = EVIDENCE,
    role_ready: bool = True,
    authority_schema_ready: bool = True,
) -> EffectiveReleaseGate:
    return EffectiveReleaseGate(
        authority=authority or _Authority(),
        local_flags_probe=lambda: flags
        or LocalReleaseFlags(mutation_enabled=True, composer_open=True),
        runtime_identity_probe=lambda: identities
        or RuntimeIdentityObservation(
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
        ),
        database_schema_fingerprint_probe=lambda: schema,
        release_evidence_digest_probe=lambda: evidence,
        runtime_role_readiness_probe=lambda: role_ready,
        authority_schema_readiness_probe=lambda: authority_schema_ready,
        hermes_capability_probe=lambda: capability or _capabilities(),
        now=lambda: NOW,
        capability_max_age=timedelta(seconds=30),
    )


def test_gate_opens_only_when_every_independent_fact_matches() -> None:
    decision = _gate().evaluate("workspace-root")

    assert decision.ready is True
    assert decision.release_authorized is True
    assert decision.chat_write_ready is True
    assert decision.blockers == ()
    assert decision.release_stamp_id == "stamp-1"
    assert decision.public_cutover_id == "cutover-1"
    assert decision.event_cursor == 42


def test_local_flags_are_deny_only_not_an_authority() -> None:
    no_stamp = _Authority()
    no_stamp.stamp = None
    no_stamp.cutover = None
    decision = _gate(authority=no_stamp).evaluate("workspace-root")
    assert decision.ready is False
    assert "active_release_stamp_missing" in decision.blockers
    assert "open_public_cutover_missing" in decision.blockers

    mutation_off = _gate(
        flags=LocalReleaseFlags(mutation_enabled=False, composer_open=True)
    ).evaluate("workspace-root")
    assert mutation_off.ready is False
    assert "local_mutation_disabled" in mutation_off.blockers

    composer_off = _gate(
        flags=LocalReleaseFlags(mutation_enabled=True, composer_open=False)
    ).evaluate("workspace-root")
    assert composer_off.ready is False
    assert "local_composer_closed" in composer_off.blockers


def test_gate_rejects_runtime_schema_cutover_and_role_drift() -> None:
    mismatched_identity = RuntimeIdentityObservation(
        platform_runtime_digest="a" * 64,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
    )
    identity_decision = _gate(identities=mismatched_identity).evaluate(
        "workspace-root"
    )
    assert "platform_runtime_identity_mismatch" in identity_decision.blockers

    schema_decision = _gate(schema="b" * 64).evaluate("workspace-root")
    assert "database_schema_fingerprint_mismatch" in schema_decision.blockers

    evidence_decision = _gate(evidence="c" * 64).evaluate("workspace-root")
    assert "release_evidence_digest_mismatch" in evidence_decision.blockers

    role_decision = _gate(role_ready=False).evaluate("workspace-root")
    assert "restricted_runtime_role_unready" in role_decision.blockers

    wrong_cutover = replace(_cutover(), stamp_id="stamp-other")
    cutover_decision = _gate(
        authority=_Authority(cutover=wrong_cutover)
    ).evaluate("workspace-root")
    assert "public_cutover_release_binding_mismatch" in cutover_decision.blockers


def test_gate_rejects_stale_or_ungrounded_hermes_capability() -> None:
    stale = _capabilities(observed_at=NOW - timedelta(seconds=31))
    stale_decision = _gate(capability=stale).evaluate("workspace-root")
    assert "hermes_durable_capability_stale" in stale_decision.blockers

    payload = _capabilities().payload
    broken = {
        **payload,
        "durable": {
            **payload["durable"],
            "run_evidence": {
                "supported": True,
                "grounded": False,
                "evidence": "store.transactional_probe:run_evidence",
            },
        },
    }
    ungrounded = HermesDurableCapabilityObservation(
        runtime_digest=HERMES,
        observed_at=NOW,
        payload=broken,
    )
    capability_decision = _gate(capability=ungrounded).evaluate("workspace-root")
    assert "hermes_durable_run_evidence_unready" in capability_decision.blockers


def test_gate_requires_hermes_owned_history_and_exact_fork_contract() -> None:
    payload = _capabilities().payload
    platform_owned_history = HermesDurableCapabilityObservation(
        runtime_digest=HERMES,
        observed_at=NOW,
        payload={
            **payload,
            "managed_session_contract": {
                "history_authority": "platform_transcript",
                "fork_mode": "best_effort_latest",
            },
        },
    )

    decision = _gate(capability=platform_owned_history).evaluate("workspace-root")

    assert decision.ready is False
    assert (
        "hermes_managed_session_history_authority_unready" in decision.blockers
    )
    assert "hermes_managed_session_fork_mode_unready" in decision.blockers
