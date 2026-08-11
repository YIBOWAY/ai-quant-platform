"""Production AgentWorkspace must never expose process-local V7/V8 authorities.

The in-process authorities remain useful hermetic contract-test adapters, but
their facts disappear on restart and therefore cannot be projected or mutated
by the production BFF.  Production defaults fail closed until a durable
canonical adapter is explicitly mounted.
"""

from __future__ import annotations

from typing import Any

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.approval_release_port import (
    FakeHermesApprovalReleaseAdapter,
    project_pending_challenge,
    reset_default_approval_release_adapter,
)
from quant_system.hermes.canary_grant_authority import (
    default_canary_grant_authority,
    reset_default_canary_grant_authority,
)
from quant_system.hermes.command_approval_authority import (
    CommandApprovalAuthority,
    default_command_approval_authority,
    reset_default_command_approval_authority,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.public_cutover_authority import (
    default_public_cutover_authority,
    reset_default_public_cutover_authority,
)
from quant_system.hermes.run_stop_port import FakeHermesRunStopAdapter
from quant_system.hermes.submission_saga import submit_action

WORKSPACE_ID = "ws-production-authority-boundary"
DIGEST = "a" * 64
BUILD_DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def _reset_process_local_authorities() -> None:
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()
    reset_default_canary_grant_authority()
    reset_default_public_cutover_authority()
    yield
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()
    reset_default_canary_grant_authority()
    reset_default_public_cutover_authority()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _seed_process_local_facts() -> None:
    default_command_approval_authority().seed_pending(
        workspace_id=WORKSPACE_ID,
        approval_id="challenge.must-stay-hermetic",
        run_id="hermes.must-stay-hermetic",
        command_digest=DIGEST,
        expires_at="2099-01-01T00:00:00.000000Z",
    )
    default_canary_grant_authority().issue(
        workspace_id=WORKSPACE_ID,
        build_digest=BUILD_DIGEST,
        route="/hermes",
        ttl_seconds=600,
        grant_note="must stay process-local",
        client_action_id="seed-hermetic-canary",
        action_digest="c" * 64,
    )
    default_public_cutover_authority().open(
        workspace_id=WORKSPACE_ID,
        build_digest=BUILD_DIGEST,
        route="/hermes",
        acceptance_id="acceptance.must-stay-hermetic",
        open_note="must stay process-local",
        client_action_id="seed-hermetic-cutover",
        action_digest="d" * 64,
        acceptance_exists=True,
    )


def test_default_workspace_does_not_project_process_local_authorities() -> None:
    _seed_process_local_facts()

    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snapshot = workspace.snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )

    assert snapshot.approvals == ()
    assert snapshot.gates == ()
    assert snapshot.tasks == ()
    assert snapshot.attempts == ()
    assert snapshot.runs == ()
    assert snapshot.results == ()
    assert snapshot.canary_grants == ()
    assert snapshot.public_cutovers == ()
    for name in (
        "command_approval",
        "gate_1",
        "gate_2",
        "gate_3",
        "task",
        "attempt",
        "run",
        "result",
        "canary_grant",
        "public_cutover",
    ):
        assert snapshot.authority_health[name] == "unavailable"


@pytest.mark.parametrize(
    "action",
    [
        {
            "schema_version": 1,
            "kind": "hermes.command_approval.decide",
            "client_action_id": "act-production-approval",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "approval_ref": "approval:challenge.1",
            "run_ref": "run:hermes.1",
            "command_digest": DIGEST,
            "expected_status": "pending",
            "expected_expires_at": "2099-01-01T00:00:00.000000Z",
            "decision": "deny",
        },
        {
            "schema_version": 1,
            "kind": "run.stop.request",
            "client_action_id": "act-production-stop",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "run_ref": "run:hermes.1",
            "task_ref": None,
            "attempt_ref": None,
            "platform_job_ref": None,
        },
        {
            "schema_version": 1,
            "kind": "gate1.formula_source.confirm",
            "client_action_id": "act-production-gate",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "task_ref": "task:factor.1",
            "reviewed_source_sha256": DIGEST,
            "confirmation_note": "production must refuse process-local Gate 1",
        },
        {
            "schema_version": 1,
            "kind": "vertical.options_a.bind",
            "client_action_id": "act-production-vertical",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "ticker": "AAPL",
            "goal_note": "production must refuse process-local Task facts",
            "expiry": "2026-12-18",
            "strike": 200.0,
            "bid": 5.0,
            "ask": 5.2,
            "delta": 0.25,
            "iv": 0.3,
            "apr": 0.1,
            "include_provider_evidence": True,
            "provider_mode": "hermetic_fixture",
            "auth_envelope": None,
        },
        {
            "schema_version": 1,
            "kind": "canary.grant.issue",
            "client_action_id": "act-production-canary",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "build_digest": BUILD_DIGEST,
            "route": "/hermes",
            "ttl_seconds": 600,
            "grant_note": "production must refuse process-local canary",
        },
        {
            "schema_version": 1,
            "kind": "public.cutover.open",
            "client_action_id": "act-production-cutover",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "build_digest": BUILD_DIGEST,
            "route": "/hermes",
            "acceptance_id": "acceptance.production",
            "open_note": "production must use durable release authority",
        },
    ],
)
def test_default_workspace_rejects_process_local_mutations(
    action: dict[str, Any],
) -> None:
    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)

    receipt = workspace.act(str(ROOT_USER_ID), action)

    assert receipt.status == "unavailable"
    if action["kind"] == "gate1.formula_source.confirm":
        # Paper Gates now have a production PostgreSQL authority + strict HQA
        # port. With database disabled this is an honest durable-authority
        # outage, not a fallback to the process-local test authority.
        assert receipt.reason_code == "paper_gate_authority_unavailable"
    elif action["kind"] == "public.cutover.open":
        # Production cutover mutation has one control plane: the PostgreSQL
        # ReleaseAuthority operator CLI, never this legacy browser action.
        assert receipt.reason_code == "release_operator_cli_required"
    else:
        assert receipt.reason_code == "canonical_authority_adapter_unavailable"
    assert receipt.command_id is None
    assert receipt.task_id is None
    assert receipt.attempt_id is None
    assert receipt.run_id is None
    assert receipt.result_id is None


def test_explicit_hermetic_workspace_can_project_and_mutate_test_authorities() -> None:
    _seed_process_local_facts()
    workspace = PlatformAgentWorkspace(
        _settings(),
        mutation_enabled=True,
        hermetic_authorities=True,
    )

    snapshot = workspace.snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )
    assert len(snapshot.approvals) == 1
    assert len(snapshot.canary_grants) == 1
    assert len(snapshot.public_cutovers) == 1
    assert snapshot.authority_health["command_approval"] == "hermetic"
    assert snapshot.authority_health["canary_grant"] == "hermetic"
    assert snapshot.authority_health["public_cutover"] == "hermetic"

    receipt = submit_action(
        _settings(),
        {
            "schema_version": 1,
            "kind": "canary.grant.issue",
            "client_action_id": "act-explicit-hermetic-canary",
            "workspace": {"workspace_id": "ws-explicit-hermetic"},
            "build_digest": BUILD_DIGEST,
            "route": "/hermes",
            "ttl_seconds": 600,
            "grant_note": "explicit hermetic contract test",
        },
        mutation_enabled=True,
        allow_hermetic_authorities=True,
    )
    assert receipt.status == "accepted"


def test_explicit_approval_ports_do_not_require_or_mutate_global_test_adapters() -> None:
    authority = CommandApprovalAuthority()
    release = FakeHermesApprovalReleaseAdapter()
    row = project_pending_challenge(
        workspace_id=WORKSPACE_ID,
        run_id="hermes.injected",
        command_digest=DIGEST,
        approval_id="challenge.injected",
        ttl_seconds=600,
        approval_authority=authority,
        release_adapter=release,
    )

    receipt = submit_action(
        _settings(),
        {
            "schema_version": 1,
            "kind": "hermes.command_approval.decide",
            "client_action_id": "act-injected-approval",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "approval_ref": "approval:challenge.injected",
            "run_ref": "run:hermes.injected",
            "command_digest": DIGEST,
            "expected_status": "pending",
            "expected_expires_at": row["expires_at"],
            "decision": "deny",
        },
        mutation_enabled=True,
        approval_authority=authority,
        approval_release_adapter=release,
    )

    assert receipt.status == "accepted"
    assert authority.list_pending(WORKSPACE_ID) == []
    assert default_command_approval_authority().list_observed(WORKSPACE_ID) == []
    assert release.respond_calls == 1


def test_explicit_stop_port_does_not_require_global_test_adapter() -> None:
    stop = FakeHermesRunStopAdapter()
    stop.ensure_run("hermes.injected-stop")

    receipt = submit_action(
        _settings(),
        {
            "schema_version": 1,
            "kind": "run.stop.request",
            "client_action_id": "act-injected-stop",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "run_ref": "run:hermes.injected-stop",
            "task_ref": None,
            "attempt_ref": None,
            "platform_job_ref": None,
        },
        mutation_enabled=True,
        stop_adapter=stop,
    )

    assert receipt.status == "accepted"
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["overall"] == "stopped"
    assert stop.stop_calls == 1


def test_managed_session_action_is_not_misclassified_as_hermetic() -> None:
    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)

    receipt = workspace.act(
        str(ROOT_USER_ID),
        {
            "schema_version": 1,
            "kind": "managed_session.create",
            "client_action_id": "act-real-managed-session",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "provider_policy_digest": DIGEST,
            "payload_ttl_days": 7,
        },
    )

    assert receipt.status == "unavailable"
    assert receipt.reason_code != "canonical_authority_adapter_unavailable"


def test_database_read_outage_is_not_reported_as_healthy_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace as workspace_module

    ready = {
        "ready": True,
        "mutation_enabled": True,
        "composer_write_ready": False,
        "chat_write_ready": False,
        "command_ledger_schema_ready": True,
        "session_registry_schema_ready": True,
        "workflow_binding_schema_ready": True,
        "research_binding_ready": True,
    }

    class _BrokenDatabase:
        def connect(self) -> Any:
            raise RuntimeError("simulated database outage")

    broken = _BrokenDatabase()
    monkeypatch.setattr(workspace_module, "authorities_ready", lambda _settings: ready)
    monkeypatch.setattr(workspace_module, "get_database", lambda _settings: broken)

    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snapshot = workspace.snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )

    assert snapshot.sessions == ()
    assert snapshot.managed_sessions == ()
    assert snapshot.commands == ()
    for name in (
        "database",
        "command_ledger",
        "session_registry",
        "workflow_binding",
        "research_binding",
    ):
        assert snapshot.authority_health[name] == "unavailable"

    page = workspace.follow(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
        after=0,
    )
    assert page.resync_required is True
    assert page.authority_health is not None
    for name in (
        "database",
        "command_ledger",
        "session_registry",
        "workflow_binding",
        "research_binding",
    ):
        assert page.authority_health[name] == "unavailable"
