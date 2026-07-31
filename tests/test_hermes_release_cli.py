from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.hermes import release_cli
from quant_system.hermes.candidate_admission_authority import (
    AcceptedCandidateReleaseBinding,
)
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseDecision,
    EffectiveReleaseGate,
    HermesDurableCapabilityObservation,
    LocalReleaseFlags,
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_authority import (
    ClosePublicCutoverRequest,
    CloseReleaseStampRequest,
    CreatePublicCutoverRequest,
    CreateReleaseStampRequest,
    PublicCutoverRecord,
    ReleaseAuthorityReceipt,
    ReleaseStampRecord,
    canonical_release_action_digest,
    canonical_release_stamp_digest,
)

runner = CliRunner()
NOW = datetime(2026, 7, 24, 12, 30, tzinfo=UTC)
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


def _decision(
    *,
    blockers: tuple[str, ...] = (
        "active_release_stamp_missing",
        "open_public_cutover_missing",
    ),
    stamp_id: str | None = None,
    release_digest: str | None = None,
    cutover_id: str | None = None,
    cutover_digest: str | None = None,
) -> EffectiveReleaseDecision:
    ready = not blockers
    return EffectiveReleaseDecision(
        workspace_id="workspace-root",
        ready=ready,
        release_authorized=ready,
        public_write_authorized=ready,
        chat_write_ready=ready,
        blockers=blockers,
        checked_at=NOW,
        release_stamp_id=stamp_id,
        release_digest=release_digest,
        public_cutover_id=cutover_id,
        cutover_digest=cutover_digest,
        event_cursor=7,
        local_mutation_requested=True,
        local_composer_requested=True,
    )


def _runtime(**overrides):
    values = {
        "settings": SimpleNamespace(
            agent_v02_release=SimpleNamespace(workspace_id="workspace-root")
        ),
        "authority": SimpleNamespace(),
        "runtime_identity_probe": lambda: RuntimeIdentityObservation(
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
        ),
        "schema_fingerprint_probe": lambda: SCHEMA,
        "evidence_digest_probe": lambda: EVIDENCE,
        "status_probe": _decision,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_hermes_release_cli_is_registered_without_digest_inputs() -> None:
    result = runner.invoke(app, ["hermes", "release", "--help"])

    assert result.exit_code == 0
    assert "inspect" in result.stdout
    assert "identities" in result.stdout
    assert "status" in result.stdout
    assert "open-stamp" in result.stdout
    assert "open-cutover" in result.stdout
    assert "close-cutover" in result.stdout
    assert "close-stamp" in result.stdout
    assert "--release-digest" not in result.stdout
    assert "--build-digest" not in result.stdout
    assert "--schema-fingerprint" not in result.stdout
    assert "--runtime-digest" not in result.stdout


@pytest.mark.parametrize(
    "operation",
    ["open-stamp", "open-cutover", "close-cutover", "close-stamp"],
)
def test_release_write_commands_expose_no_caller_supplied_digest(
    operation: str,
) -> None:
    result = runner.invoke(app, ["hermes", "release", operation, "--help"])

    assert result.exit_code == 0
    assert "--release-digest" not in result.stdout
    assert "--cutover-digest" not in result.stdout
    assert "--build-digest" not in result.stdout
    assert "--schema-fingerprint" not in result.stdout
    assert "--runtime-digest" not in result.stdout


def test_release_identities_observes_exact_local_facts_without_input_digests(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(),
    )

    result = runner.invoke(app, ["hermes", "release", "identities"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "contract": "agent-v0.2-release-cli/v1",
        "database_schema_fingerprint": SCHEMA,
        "evidence_digest": EVIDENCE,
        "runtime": {
            "hermes": HERMES,
            "hqa": HQA,
            "platform": PLATFORM,
        },
        "workspace_id": "workspace-root",
    }


def test_release_status_emits_the_effective_fail_closed_decision(monkeypatch) -> None:
    decision = _decision(blockers=("restricted_runtime_role_unready",))
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(status_probe=lambda: decision),
    )

    result = runner.invoke(app, ["hermes", "release", "status"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": decision.to_public_dict(),
    }


def test_release_inspect_projects_only_bounded_authority_records(monkeypatch) -> None:
    release_digest = "6" * 64
    cutover_digest = "7" * 64
    stamp = ReleaseStampRecord(
        stamp_id="release_01",
        workspace_id="workspace-root",
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        evidence_digest=EVIDENCE,
        release_digest=release_digest,
        status="active",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    cutover = PublicCutoverRecord(
        cutover_id="cutover_01",
        stamp_id=stamp.stamp_id,
        workspace_id=stamp.workspace_id,
        route=stamp.route,
        release_digest=release_digest,
        cutover_digest=cutover_digest,
        status="open",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    authority = SimpleNamespace(
        active_release_stamp=lambda _workspace_id: stamp,
        open_public_cutover=lambda _workspace_id: cutover,
        current_event_cursor=lambda _workspace_id: 9,
    )
    decision = _decision(
        blockers=(),
        stamp_id=stamp.stamp_id,
        release_digest=release_digest,
        cutover_id=cutover.cutover_id,
        cutover_digest=cutover_digest,
    )
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(authority=authority, status_probe=lambda: decision),
    )

    result = runner.invoke(app, ["hermes", "release", "inspect"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["contract"] == "agent-v0.2-release-cli/v1"
    assert payload["decision"] == decision.to_public_dict()
    assert payload["event_cursor"] == 9
    assert payload["active_release_stamp"] == {
        "closed_at": None,
        "database_schema_fingerprint": SCHEMA,
        "evidence_digest": EVIDENCE,
        "hermes_runtime_digest": HERMES,
        "hqa_runtime_digest": HQA,
        "opened_at": "2026-07-24T12:30:00Z",
        "platform_runtime_digest": PLATFORM,
        "release_digest": release_digest,
        "route": "/hermes",
        "stamp_id": "release_01",
        "status": "active",
        "workspace_id": "workspace-root",
    }
    assert payload["open_public_cutover"] == {
        "closed_at": None,
        "cutover_digest": cutover_digest,
        "cutover_id": "cutover_01",
        "opened_at": "2026-07-24T12:30:00Z",
        "release_digest": release_digest,
        "route": "/hermes",
        "stamp_id": "release_01",
        "status": "open",
        "workspace_id": "workspace-root",
    }


@pytest.mark.parametrize("operation", ["inspect", "identities", "status"])
def test_release_read_commands_fail_closed_without_leaking_probe_details(
    monkeypatch,
    operation: str,
) -> None:
    def unavailable():
        raise RuntimeError("secret DSN and local path must never reach stdout")

    monkeypatch.setattr(release_cli, "build_release_cli_runtime", unavailable)

    result = runner.invoke(app, ["hermes", "release", operation])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "contract": "agent-v0.2-release-cli/v1",
        "error_code": "release_cli_unavailable",
        "operation": operation,
    }
    assert "secret" not in result.stdout
    assert "local path" not in result.stdout


def test_open_stamp_derives_all_authority_digests_from_live_observations(
    monkeypatch,
) -> None:
    captured: list[CreateReleaseStampRequest] = []
    receipt = ReleaseAuthorityReceipt(
        operation="release.open",
        workspace_id="workspace-root",
        client_action_id="operator-open-001",
        action_digest="8" * 64,
        resource_id="release_01",
        resource_digest="9" * 64,
        status="active",
        event_cursor=10,
        occurred_at=NOW,
    )

    class Authority:
        def create_release_stamp(self, request):
            captured.append(request)
            return receipt

    decisions = iter(
        [
            _decision(),
            _decision(
                blockers=("open_public_cutover_missing",),
                stamp_id=receipt.resource_id,
                release_digest=receipt.resource_digest,
            ),
        ]
    )
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=lambda: next(decisions),
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "open-stamp",
            "--note",
            "full local Agent v0.2 evidence reviewed",
            "--client-action-id",
            "operator-open-001",
        ],
    )

    assert result.exit_code == 0
    assert len(captured) == 1
    request = captured[0]
    assert request.workspace_id == "workspace-root"
    assert request.route == "/hermes"
    assert request.platform_runtime_digest == PLATFORM
    assert request.hqa_runtime_digest == HQA
    assert request.hermes_runtime_digest == HERMES
    assert request.evidence_digest == EVIDENCE
    assert request.note == "full local Agent v0.2 evidence reviewed"
    assert request.client_action_id == "operator-open-001"
    expected_payload = {
        "workspace_id": "workspace-root",
        "route": "/hermes",
        "platform_runtime_digest": PLATFORM,
        "hqa_runtime_digest": HQA,
        "hermes_runtime_digest": HERMES,
        "evidence_digest": EVIDENCE,
        "note": "full local Agent v0.2 evidence reviewed",
    }
    assert request.action_digest == canonical_release_action_digest(
        "release.open",
        expected_payload,
    )
    payload = json.loads(result.stdout)
    assert payload["receipt"]["resource_id"] == "release_01"
    assert payload["receipt"]["resource_digest"] == "9" * 64
    assert payload["receipt"]["status"] == "active"
    assert payload["decision"]["blockers"] == ["open_public_cutover_missing"]


def test_effective_status_allows_cli_open_stamp_for_accepted_candidate(
    monkeypatch,
) -> None:
    candidate = AcceptedCandidateReleaseBinding(
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

    class Authority:
        stamp: ReleaseStampRecord | None = None

        def active_release_stamp(self, _workspace_id):
            return self.stamp

        def open_public_cutover(self, _workspace_id):
            return None

        def accepted_candidate_release_binding(self, workspace_id, admission_id):
            assert workspace_id == candidate.workspace_id
            assert admission_id == candidate.admission_id
            return candidate

        def current_event_cursor(self, _workspace_id):
            return 12

        def create_release_stamp(self, request):
            opened_at = NOW
            release_digest = canonical_release_stamp_digest(
                stamp_id="release-prod-style",
                workspace_id=request.workspace_id,
                route=request.route,
                platform_runtime_digest=request.platform_runtime_digest,
                hqa_runtime_digest=request.hqa_runtime_digest,
                hermes_runtime_digest=request.hermes_runtime_digest,
                database_schema_fingerprint=SCHEMA,
                evidence_digest=request.evidence_digest,
                opened_at=opened_at,
                candidate_admission_id=candidate.admission_id,
                candidate_admission_digest=candidate.admission_digest,
                candidate_acceptance_digest=candidate.acceptance_digest,
                evidence_set_id=candidate.evidence_set_id,
                evidence_set_digest=candidate.evidence_set_digest,
                final_order_snapshot_digest=candidate.final_order_snapshot_digest,
                paper_authority_epoch=candidate.paper_authority_epoch,
            )
            self.stamp = ReleaseStampRecord(
                stamp_id="release-prod-style",
                workspace_id=request.workspace_id,
                route=request.route,
                platform_runtime_digest=request.platform_runtime_digest,
                hqa_runtime_digest=request.hqa_runtime_digest,
                hermes_runtime_digest=request.hermes_runtime_digest,
                database_schema_fingerprint=SCHEMA,
                evidence_digest=request.evidence_digest,
                release_digest=release_digest,
                status="active",
                opened_at=opened_at,
                closed_at=None,
                close_reason=None,
                candidate_admission_id=candidate.admission_id,
                candidate_admission_digest=candidate.admission_digest,
                candidate_acceptance_digest=candidate.acceptance_digest,
                evidence_set_id=candidate.evidence_set_id,
                evidence_set_digest=candidate.evidence_set_digest,
                final_order_snapshot_digest=candidate.final_order_snapshot_digest,
                paper_authority_epoch=candidate.paper_authority_epoch,
            )
            return ReleaseAuthorityReceipt(
                operation="release.open",
                workspace_id=request.workspace_id,
                client_action_id=request.client_action_id,
                action_digest=request.action_digest,
                resource_id=self.stamp.stamp_id,
                resource_digest=self.stamp.release_digest,
                status="active",
                event_cursor=12,
                occurred_at=NOW,
            )

    authority = Authority()
    gate = EffectiveReleaseGate(
        authority=authority,
        local_flags_probe=lambda: LocalReleaseFlags(
            mutation_enabled=True,
            composer_open=True,
            hermes_gateway_enabled=True,
            kill_switch_enabled=True,
            live_trading_enabled=False,
            candidate_admission_enabled=True,
        ),
        runtime_identity_probe=lambda: RuntimeIdentityObservation(
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
        ),
        database_schema_fingerprint_probe=lambda: SCHEMA,
        release_evidence_probe=lambda: ReleaseEvidenceObservation(
            digest=EVIDENCE,
            platform_runtime_digest=PLATFORM,
            hqa_runtime_digest=HQA,
            hermes_runtime_digest=HERMES,
            contract="agent-v0.2-release-evidence/v4",
            candidate_admission_id=candidate.admission_id,
            candidate_admission_digest=candidate.admission_digest,
            evidence_set_id=candidate.evidence_set_id,
            evidence_set_digest=candidate.evidence_set_digest,
            final_order_snapshot_digest=candidate.final_order_snapshot_digest,
        ),
        runtime_role_readiness_probe=lambda: True,
        authority_schema_readiness_probe=lambda: True,
        hermes_capability_probe=lambda: HermesDurableCapabilityObservation(
            runtime_digest=HERMES,
            observed_at=NOW,
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
        ),
        now=lambda: NOW,
    )
    before = gate.evaluate("workspace-root")
    assert before.blockers == (
        "active_release_stamp_missing",
        "open_public_cutover_missing",
    )
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=authority,
            status_probe=lambda: gate.evaluate("workspace-root"),
        ),
    )
    status_result = runner.invoke(app, ["hermes", "release", "status"])
    assert status_result.exit_code == 0, status_result.stdout
    assert json.loads(status_result.stdout)["decision"]["blockers"] == [
        "active_release_stamp_missing",
        "open_public_cutover_missing",
    ]

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "open-stamp",
            "--note",
            "accepted evidence reviewed",
            "--client-action-id",
            "operator-open-production-style",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["receipt"]["resource_id"] == "release-prod-style"
    assert payload["decision"]["blockers"] == ["open_public_cutover_missing"]


def test_open_stamp_refuses_any_non_transition_preflight_blocker(
    monkeypatch,
) -> None:
    class Authority:
        def create_release_stamp(self, _request):
            raise AssertionError("blocked preflight must not write")

    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            runtime_identity_probe=lambda: (_ for _ in ()).throw(
                AssertionError("blocked preflight must not inspect identities again")
            ),
            status_probe=lambda: _decision(
                blockers=(
                    "active_release_stamp_missing",
                    "open_public_cutover_missing",
                    "hermes_durable_capability_unavailable",
                )
            ),
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "open-stamp",
            "--note",
            "must not open",
            "--client-action-id",
            "operator-open-blocked",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "blockers": [
            "active_release_stamp_missing",
            "open_public_cutover_missing",
            "hermes_durable_capability_unavailable",
        ],
        "contract": "agent-v0.2-release-cli/v1",
        "error_code": "release_preflight_failed",
    }


def test_open_stamp_preserves_receipt_but_fails_if_post_write_gate_drifts(
    monkeypatch,
) -> None:
    receipt = ReleaseAuthorityReceipt(
        operation="release.open",
        workspace_id="workspace-root",
        client_action_id="operator-open-drift",
        action_digest="8" * 64,
        resource_id="release_drift",
        resource_digest="9" * 64,
        status="active",
        event_cursor=10,
        occurred_at=NOW,
    )

    class Authority:
        def create_release_stamp(self, _request):
            return receipt

    decisions = iter(
        [
            _decision(),
            _decision(
                blockers=(
                    "open_public_cutover_missing",
                    "hermes_durable_capability_unavailable",
                ),
                stamp_id=receipt.resource_id,
                release_digest=receipt.resource_digest,
            ),
        ]
    )
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=lambda: next(decisions),
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "open-stamp",
            "--note",
            "race-safe release attempt",
            "--client-action-id",
            "operator-open-drift",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "release_post_write_gate_closed"
    assert payload["receipt"]["resource_id"] == "release_drift"
    assert payload["decision"]["blockers"] == [
        "open_public_cutover_missing",
        "hermes_durable_capability_unavailable",
    ]


def test_open_cutover_binds_the_current_active_stamp_without_digest_options(
    monkeypatch,
) -> None:
    release_digest = "6" * 64
    cutover_digest = "7" * 64
    stamp = ReleaseStampRecord(
        stamp_id="release_01",
        workspace_id="workspace-root",
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        evidence_digest=EVIDENCE,
        release_digest=release_digest,
        status="active",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    captured: list[CreatePublicCutoverRequest] = []
    receipt = ReleaseAuthorityReceipt(
        operation="public_cutover.open",
        workspace_id="workspace-root",
        client_action_id="operator-cutover-001",
        action_digest="8" * 64,
        resource_id="cutover_01",
        resource_digest=cutover_digest,
        status="open",
        event_cursor=11,
        occurred_at=NOW,
    )

    class Authority:
        def active_release_stamp(self, _workspace_id):
            return stamp

        def create_public_cutover(self, request):
            captured.append(request)
            return receipt

    decisions = iter(
        [
            _decision(
                blockers=("open_public_cutover_missing",),
                stamp_id=stamp.stamp_id,
                release_digest=stamp.release_digest,
            ),
            _decision(
                blockers=(),
                stamp_id=stamp.stamp_id,
                release_digest=stamp.release_digest,
                cutover_id=receipt.resource_id,
                cutover_digest=receipt.resource_digest,
            ),
        ]
    )
    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=lambda: next(decisions),
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "open-cutover",
            "--note",
            "owner authorizes local /hermes",
            "--client-action-id",
            "operator-cutover-001",
        ],
    )

    assert result.exit_code == 0
    assert len(captured) == 1
    request = captured[0]
    assert request.workspace_id == "workspace-root"
    assert request.stamp_id == "release_01"
    assert request.expected_release_digest == release_digest
    assert request.route == "/hermes"
    assert request.note == "owner authorizes local /hermes"
    assert request.client_action_id == "operator-cutover-001"
    assert request.action_digest == canonical_release_action_digest(
        "public_cutover.open",
        {
            "workspace_id": "workspace-root",
            "stamp_id": "release_01",
            "expected_release_digest": release_digest,
            "route": "/hermes",
            "note": "owner authorizes local /hermes",
        },
    )
    assert json.loads(result.stdout)["decision"]["ready"] is True


def test_close_cutover_uses_current_exact_cas_even_when_gate_is_closed(
    monkeypatch,
) -> None:
    release_digest = "6" * 64
    cutover_digest = "7" * 64
    cutover = PublicCutoverRecord(
        cutover_id="cutover_01",
        stamp_id="release_01",
        workspace_id="workspace-root",
        route="/hermes",
        release_digest=release_digest,
        cutover_digest=cutover_digest,
        status="open",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    captured: list[ClosePublicCutoverRequest] = []
    order: list[str] = []
    receipt = ReleaseAuthorityReceipt(
        operation="public_cutover.close",
        workspace_id="workspace-root",
        client_action_id="operator-close-cutover-001",
        action_digest="8" * 64,
        resource_id=cutover.cutover_id,
        resource_digest=cutover.cutover_digest,
        status="closed",
        event_cursor=12,
        occurred_at=NOW,
    )

    class Authority:
        def open_public_cutover(self, _workspace_id):
            order.append("observe-cutover")
            return cutover

        def close_public_cutover(self, request):
            order.append("close-cutover")
            captured.append(request)
            return receipt

    def blocked_status():
        order.append("status")
        return _decision(
            blockers=(
                "local_mutation_disabled",
                "hermes_durable_capability_unavailable",
                "open_public_cutover_missing",
            ),
            stamp_id="release_01",
            release_digest=release_digest,
        )

    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=blocked_status,
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "close-cutover",
            "--reason",
            "operator rollback",
            "--client-action-id",
            "operator-close-cutover-001",
        ],
    )

    assert result.exit_code == 0
    assert order == ["observe-cutover", "close-cutover", "status"]
    request = captured[0]
    assert request == ClosePublicCutoverRequest(
        workspace_id="workspace-root",
        cutover_id="cutover_01",
        expected_cutover_digest=cutover_digest,
        reason="operator rollback",
        client_action_id="operator-close-cutover-001",
        action_digest=canonical_release_action_digest(
            "public_cutover.close",
            {
                "workspace_id": "workspace-root",
                "cutover_id": "cutover_01",
                "expected_cutover_digest": cutover_digest,
                "reason": "operator rollback",
            },
        ),
    )
    payload = json.loads(result.stdout)
    assert payload["receipt"]["status"] == "closed"
    assert payload["decision"]["ready"] is False
    assert "local_mutation_disabled" in payload["decision"]["blockers"]


def test_close_stamp_uses_current_exact_cas_without_effective_gate_admission(
    monkeypatch,
) -> None:
    release_digest = "6" * 64
    stamp = ReleaseStampRecord(
        stamp_id="release_01",
        workspace_id="workspace-root",
        route="/hermes",
        platform_runtime_digest=PLATFORM,
        hqa_runtime_digest=HQA,
        hermes_runtime_digest=HERMES,
        database_schema_fingerprint=SCHEMA,
        evidence_digest=EVIDENCE,
        release_digest=release_digest,
        status="active",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    captured: list[CloseReleaseStampRequest] = []
    order: list[str] = []
    receipt = ReleaseAuthorityReceipt(
        operation="release.close",
        workspace_id="workspace-root",
        client_action_id="operator-close-stamp-001",
        action_digest="8" * 64,
        resource_id=stamp.stamp_id,
        resource_digest=stamp.release_digest,
        status="closed",
        event_cursor=13,
        occurred_at=NOW,
    )

    class Authority:
        def active_release_stamp(self, _workspace_id):
            order.append("observe-stamp")
            return stamp

        def close_release_stamp(self, request):
            order.append("close-stamp")
            captured.append(request)
            return receipt

    def blocked_status():
        order.append("status")
        return _decision()

    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=blocked_status,
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "close-stamp",
            "--reason",
            "release evidence superseded",
            "--client-action-id",
            "operator-close-stamp-001",
        ],
    )

    assert result.exit_code == 0
    assert order == ["observe-stamp", "close-stamp", "status"]
    request = captured[0]
    assert request == CloseReleaseStampRequest(
        workspace_id="workspace-root",
        stamp_id="release_01",
        expected_release_digest=release_digest,
        reason="release evidence superseded",
        client_action_id="operator-close-stamp-001",
        action_digest=canonical_release_action_digest(
            "release.close",
            {
                "workspace_id": "workspace-root",
                "stamp_id": "release_01",
                "expected_release_digest": release_digest,
                "reason": "release evidence superseded",
            },
        ),
    )
    assert json.loads(result.stdout)["receipt"]["status"] == "closed"


def test_post_write_probe_failure_preserves_the_frozen_rollback_receipt(
    monkeypatch,
) -> None:
    cutover = PublicCutoverRecord(
        cutover_id="cutover_01",
        stamp_id="release_01",
        workspace_id="workspace-root",
        route="/hermes",
        release_digest="6" * 64,
        cutover_digest="7" * 64,
        status="open",
        opened_at=NOW,
        closed_at=None,
        close_reason=None,
    )
    receipt = ReleaseAuthorityReceipt(
        operation="public_cutover.close",
        workspace_id="workspace-root",
        client_action_id="rollback-recovery-001",
        action_digest="8" * 64,
        resource_id=cutover.cutover_id,
        resource_digest=cutover.cutover_digest,
        status="closed",
        event_cursor=14,
        occurred_at=NOW,
    )

    class Authority:
        def open_public_cutover(self, _workspace_id):
            return cutover

        def close_public_cutover(self, _request):
            return receipt

    monkeypatch.setattr(
        release_cli,
        "build_release_cli_runtime",
        lambda: _runtime(
            authority=Authority(),
            status_probe=lambda: (_ for _ in ()).throw(RuntimeError("secret probe failure")),
        ),
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "release",
            "close-cutover",
            "--reason",
            "rollback despite probe outage",
            "--client-action-id",
            "rollback-recovery-001",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "contract": "agent-v0.2-release-cli/v1",
        "error_code": "release_post_write_status_unavailable",
        "receipt": {
            "action_digest": "8" * 64,
            "client_action_id": "rollback-recovery-001",
            "event_cursor": 14,
            "idempotent_replay": False,
            "occurred_at": "2026-07-24T12:30:00Z",
            "operation": "public_cutover.close",
            "resource_digest": "7" * 64,
            "resource_id": "cutover_01",
            "status": "closed",
            "workspace_id": "workspace-root",
        },
    }
    assert "secret" not in result.stdout
