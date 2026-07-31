from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from quant_system.hermes.candidate_admission_authority import (
    AcceptedCandidateReleaseBinding,
)
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_authority import (
    PublicCutoverRecord,
    ReleaseStampRecord,
    canonical_public_cutover_digest,
    canonical_release_stamp_digest,
)

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)
PLATFORM = "1" * 64
HQA = "2" * 64
HERMES = "3" * 64
SCHEMA = "4" * 64
EVIDENCE = "5" * 64
ADMISSION = "8" * 64
ACCEPTANCE = "9" * 64
EVIDENCE_SET = "a" * 64
FINAL_ORDER = "b" * 64
PAPER_EPOCH = 17


def _release_digest() -> str:
    return canonical_release_stamp_digest(
        stamp_id="stamp-1",
        workspace_id="workspace-root",
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        evidence_digest=EVIDENCE,
        opened_at=NOW,
        candidate_admission_id="candidate-1",
        candidate_admission_digest=ADMISSION,
        candidate_acceptance_digest=ACCEPTANCE,
        evidence_set_id="evidence-set-1",
        evidence_set_digest=EVIDENCE_SET,
        final_order_snapshot_digest=FINAL_ORDER,
        paper_authority_epoch=PAPER_EPOCH,
    )


def _cutover_digest() -> str:
    return canonical_public_cutover_digest(
        cutover_id="cutover-1",
        stamp_id="stamp-1",
        workspace_id="workspace-root",
        route="/hermes",
        release_digest=_release_digest(),
        opened_at=NOW,
        candidate_admission_id="candidate-1",
        candidate_admission_digest=ADMISSION,
        candidate_acceptance_digest=ACCEPTANCE,
        evidence_set_id="evidence-set-1",
        evidence_set_digest=EVIDENCE_SET,
        final_order_snapshot_digest=FINAL_ORDER,
        paper_authority_epoch=PAPER_EPOCH,
    )


def _candidate_binding() -> AcceptedCandidateReleaseBinding:
    return AcceptedCandidateReleaseBinding(
        admission_id="candidate-1",
        workspace_id="workspace-root",
        route="/hermes",
        admission_digest=ADMISSION,
        acceptance_digest=ACCEPTANCE,
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        final_evidence_digest=EVIDENCE,
        evidence_set_id="evidence-set-1",
        evidence_set_digest=EVIDENCE_SET,
        final_order_snapshot_digest=FINAL_ORDER,
        paper_authority_epoch=PAPER_EPOCH,
    )


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
        release_digest=_release_digest(),
        status="active",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
        candidate_admission_id="candidate-1",
        candidate_admission_digest=ADMISSION,
        candidate_acceptance_digest=ACCEPTANCE,
        evidence_set_id="evidence-set-1",
        evidence_set_digest=EVIDENCE_SET,
        final_order_snapshot_digest=FINAL_ORDER,
        paper_authority_epoch=PAPER_EPOCH,
    )


def _cutover() -> PublicCutoverRecord:
    return PublicCutoverRecord(
        cutover_id="cutover-1",
        stamp_id="stamp-1",
        workspace_id="workspace-root",
        route="/hermes",
        release_digest=_release_digest(),
        cutover_digest=_cutover_digest(),
        status="open",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
        candidate_admission_id="candidate-1",
        candidate_admission_digest=ADMISSION,
        candidate_acceptance_digest=ACCEPTANCE,
        evidence_set_id="evidence-set-1",
        evidence_set_digest=EVIDENCE_SET,
        final_order_snapshot_digest=FINAL_ORDER,
        paper_authority_epoch=PAPER_EPOCH,
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
                "run_events_snapshot": True,
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
        candidate_binding: AcceptedCandidateReleaseBinding | None = None,
        candidate_binding_available: bool = True,
    ) -> None:
        self.stamp = stamp if stamp is not None else _stamp()
        self.cutover = cutover if cutover is not None else _cutover()
        self.candidate_binding = (
            candidate_binding
            if candidate_binding is not None
            else (_candidate_binding() if candidate_binding_available else None)
        )
        self.candidate_binding_reads = 0

    def active_release_stamp(self, workspace_id: str) -> ReleaseStampRecord | None:
        assert workspace_id == "workspace-root"
        return self.stamp

    def open_public_cutover(self, workspace_id: str) -> PublicCutoverRecord | None:
        assert workspace_id == "workspace-root"
        return self.cutover

    def current_event_cursor(self, workspace_id: str) -> int:
        assert workspace_id == "workspace-root"
        return 42

    def accepted_candidate_release_binding(
        self,
        workspace_id: str,
        admission_id: str,
    ) -> AcceptedCandidateReleaseBinding | None:
        assert workspace_id == "workspace-root"
        assert admission_id == "candidate-1"
        self.candidate_binding_reads += 1
        return self.candidate_binding


def _gate(
    *,
    authority: _Authority | None = None,
    flags: LocalReleaseFlags | None = None,
    identities: RuntimeIdentityObservation | None = None,
    capability: HermesDurableCapabilityObservation | None = None,
    schema: str = SCHEMA,
    evidence: str = EVIDENCE,
    evidence_platform_runtime: str = PLATFORM,
    role_ready: bool = True,
    authority_schema_ready: bool = True,
    gateway_enabled: bool = True,
    kill_switch: bool = True,
    live_trading_enabled: bool = False,
    candidate_admission_enabled: bool = True,
    evidence_contract: str = "agent-v0.2-release-evidence/v4",
) -> EffectiveReleaseGate:
    return EffectiveReleaseGate(
        authority=authority or _Authority(),
        local_flags_probe=lambda: (
            flags
            or LocalReleaseFlags(
                mutation_enabled=True,
                composer_open=True,
                hermes_gateway_enabled=gateway_enabled,
                kill_switch_enabled=kill_switch,
                live_trading_enabled=live_trading_enabled,
                candidate_admission_enabled=candidate_admission_enabled,
            )
        ),
        runtime_identity_probe=lambda: (
            identities
            or RuntimeIdentityObservation(
                platform_runtime_digest=PLATFORM,
                hqa_runtime_digest=HQA,
                hermes_runtime_digest=HERMES,
            )
        ),
        database_schema_fingerprint_probe=lambda: schema,
        release_evidence_probe=lambda: ReleaseEvidenceObservation(
            digest=evidence,
            platform_runtime_digest=evidence_platform_runtime,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
            contract=evidence_contract,
            candidate_admission_id="candidate-1",
            candidate_admission_digest=ADMISSION,
            evidence_set_id="evidence-set-1",
            evidence_set_digest=EVIDENCE_SET,
            final_order_snapshot_digest=FINAL_ORDER,
        ),
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


def test_release_requires_candidate_mode_and_verified_v4_evidence() -> None:
    disabled = _gate(candidate_admission_enabled=False).evaluate("workspace-root")
    legacy = _gate(evidence_contract="agent-v0.2-release-evidence/v2").evaluate("workspace-root")

    assert disabled.ready is False
    assert "candidate_admission_disabled" in disabled.blockers
    assert legacy.ready is False
    assert "candidate_evidence_v4_unavailable" in legacy.blockers


def test_gate_requeries_the_accepted_candidate_on_every_evaluation() -> None:
    authority = _Authority(candidate_binding_available=False)

    first = _gate(authority=authority).evaluate("workspace-root")
    second = _gate(authority=authority).evaluate("workspace-root")

    assert first.ready is False
    assert second.ready is False
    assert "accepted_candidate_binding_unavailable" in first.blockers
    assert authority.candidate_binding_reads == 2


def test_accepted_candidate_without_stamp_is_not_a_stamp_binding_mismatch() -> None:
    authority = _Authority()
    authority.stamp = None
    authority.cutover = None

    decision = _gate(authority=authority).evaluate("workspace-root")

    assert decision.ready is False
    assert "active_release_stamp_missing" in decision.blockers
    assert "open_public_cutover_missing" in decision.blockers
    assert "release_stamp_candidate_binding_mismatch" not in decision.blockers
    assert authority.candidate_binding_reads == 1


def test_gate_rejects_candidate_stamp_and_cutover_epoch_binding_drift() -> None:
    stale_candidate = replace(
        _candidate_binding(),
        final_order_snapshot_digest="c" * 64,
    )
    candidate_decision = _gate(authority=_Authority(candidate_binding=stale_candidate)).evaluate(
        "workspace-root"
    )
    assert "accepted_candidate_evidence_binding_mismatch" in candidate_decision.blockers
    assert "release_stamp_candidate_binding_mismatch" in candidate_decision.blockers

    stale_stamp = replace(
        _stamp(),
        paper_authority_epoch=PAPER_EPOCH + 1,
    )
    stamp_decision = _gate(authority=_Authority(stamp=stale_stamp)).evaluate("workspace-root")
    assert "release_stamp_candidate_binding_mismatch" in stamp_decision.blockers

    stale_cutover = replace(
        _cutover(),
        paper_authority_epoch=PAPER_EPOCH + 1,
    )
    cutover_decision = _gate(authority=_Authority(cutover=stale_cutover)).evaluate("workspace-root")
    assert "public_cutover_release_binding_mismatch" in cutover_decision.blockers


def test_local_flags_are_deny_only_not_an_authority() -> None:
    no_stamp = _Authority()
    no_stamp.stamp = None
    no_stamp.cutover = None
    decision = _gate(authority=no_stamp).evaluate("workspace-root")
    assert decision.ready is False
    assert "active_release_stamp_missing" in decision.blockers
    assert "open_public_cutover_missing" in decision.blockers

    mutation_off = _gate(
        flags=LocalReleaseFlags(
            mutation_enabled=False,
            composer_open=True,
            hermes_gateway_enabled=True,
            kill_switch_enabled=True,
            live_trading_enabled=False,
            candidate_admission_enabled=True,
        )
    ).evaluate("workspace-root")
    assert mutation_off.ready is False
    assert "local_mutation_disabled" in mutation_off.blockers

    composer_off = _gate(
        flags=LocalReleaseFlags(
            mutation_enabled=True,
            composer_open=False,
            hermes_gateway_enabled=True,
            kill_switch_enabled=True,
            live_trading_enabled=False,
            candidate_admission_enabled=True,
        )
    ).evaluate("workspace-root")
    assert composer_off.ready is False
    assert "local_composer_closed" in composer_off.blockers


def test_disabled_hermes_gateway_closes_release_even_when_every_other_fact_matches() -> None:
    decision = _gate(gateway_enabled=False).evaluate("workspace-root")

    assert decision.ready is False
    assert decision.chat_write_ready is False
    assert "hermes_gateway_disabled" in decision.blockers


def test_current_trading_safety_flags_must_remain_fail_closed() -> None:
    kill_switch_off = _gate(kill_switch=False).evaluate("workspace-root")
    live_enabled = _gate(live_trading_enabled=True).evaluate("workspace-root")

    assert "trading_kill_switch_disabled" in kill_switch_off.blockers
    assert "live_trading_enabled" in live_enabled.blockers
    assert kill_switch_off.ready is False
    assert live_enabled.ready is False


def test_gate_rejects_runtime_schema_cutover_and_role_drift() -> None:
    mismatched_identity = RuntimeIdentityObservation(
        platform_runtime_digest="a" * 64,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
    )
    identity_decision = _gate(identities=mismatched_identity).evaluate("workspace-root")
    assert "platform_runtime_identity_mismatch" in identity_decision.blockers

    schema_decision = _gate(schema="b" * 64).evaluate("workspace-root")
    assert "database_schema_fingerprint_mismatch" in schema_decision.blockers

    evidence_decision = _gate(evidence="c" * 64).evaluate("workspace-root")
    assert "release_evidence_digest_mismatch" in evidence_decision.blockers

    pre_stamp = _Authority()
    pre_stamp.stamp = None
    pre_stamp.cutover = None
    unbound_evidence = _gate(
        authority=pre_stamp,
        evidence_platform_runtime="d" * 64,
    ).evaluate("workspace-root")
    assert "release_evidence_platform_runtime_mismatch" in unbound_evidence.blockers

    role_decision = _gate(role_ready=False).evaluate("workspace-root")
    assert "restricted_runtime_role_unready" in role_decision.blockers

    wrong_cutover = replace(_cutover(), stamp_id="stamp-other")
    cutover_decision = _gate(authority=_Authority(cutover=wrong_cutover)).evaluate("workspace-root")
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
    assert "hermes_managed_session_history_authority_unready" in decision.blockers
    assert "hermes_managed_session_fork_mode_unready" in decision.blockers
