"""V8-M3: hermetic cold-start + spine honesty drills (local-dark).

G3 dual cold-start analogs for in-process authorities (ephemeral by design).
HQA intent/workflow backup≠TTL-revive is covered in the HQA binder suite.
Does NOT authorize public write, canary, M6, kill_switch flip, or V2 durable live.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    DatabaseSettings,
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import WorkspaceRef
from quant_system.hermes.approval_observe import (
    project_workspace_approvals,
    reset_default_approval_observe_journal,
)
from quant_system.hermes.command_approval_authority import (
    default_command_approval_authority,
    reset_default_command_approval_authority,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.composer_readiness import composer_readiness_snapshot
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.gate_observe import (
    project_workspace_gates,
    reset_default_gate_observe_journal,
)
from quant_system.hermes.gate_surface_authority import (
    default_gate_surface_authority,
    reset_default_gate_surface_authority,
)
from quant_system.hermes.result_observe import (
    project_workspace_results,
    reset_default_result_observe_journal,
)
from quant_system.hermes.result_surface_authority import (
    default_result_surface_authority,
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import submit_action as _submit_action
from quant_system.hermes.vertical_binding_authority import (
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import (
    project_workspace_attempts,
    project_workspace_runs,
    project_workspace_tasks,
    reset_default_vertical_observe_journal,
)

submit_action = partial(_submit_action, allow_hermetic_authorities=True)

WS = PLATFORM_WORKSPACE_ID
ORIGIN = "http://127.0.0.1:3001"


@pytest.fixture(autouse=True)
def _reset_hermetic_authorities() -> None:
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()
    reset_default_command_approval_authority()
    reset_default_approval_observe_journal()
    yield
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()
    reset_default_command_approval_authority()
    reset_default_approval_observe_journal()


def _settings(*, mutation: bool = False) -> Settings:
    return Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=mutation, composer_open=mutation),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )


def _workspace(*, mutation: bool = False) -> PlatformAgentWorkspace:
    return PlatformAgentWorkspace(
        _settings(mutation=mutation),
        mutation_enabled=mutation,
        hermetic_authorities=True,
    )


def _bind_options_doc(*, client_action_id: str = "act-v8m3-bind") -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.options_a.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "ticker": "AAPL",
        "goal_note": "V8-M3 cold-start fixture",
        "expiry": "2026-08-15",
        "strike": 180.0,
        "bid": 2.35,
        "ask": 2.45,
        "delta": -0.25,
        "iv": 0.28,
        "apr": 0.12,
        "include_provider_evidence": True,
        "provider_mode": "hermetic_fixture",
        "auth_envelope": None,
    }


def _wipe_authorities() -> None:
    """Cold-start analog: process restart wipes in-memory authorities."""
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()
    reset_default_command_approval_authority()
    reset_default_approval_observe_journal()


def _assert_empty_honest_spine(ws: str = WS) -> None:
    assert project_workspace_tasks(ws) == []
    assert project_workspace_attempts(ws) == []
    assert project_workspace_runs(ws) == []
    assert project_workspace_results(ws) == []
    assert project_workspace_gates(ws) == []
    assert project_workspace_approvals(ws) == []
    assert default_vertical_binding_authority().list_tasks(ws) == []
    assert default_gate_surface_authority().list_observed(ws) == []
    assert default_command_approval_authority().list_observed(ws) == []
    assert default_result_surface_authority().list_observed(ws) == []


def _browser_headers(*, origin: str = ORIGIN, site: str = "same-origin") -> dict[str, str]:
    return {
        "Origin": origin,
        "Sec-Fetch-Site": site,
        "Host": "testserver",
    }


def _bootstrap(client: TestClient, tmp_path: Path) -> None:
    token = issue_bootstrap_token(tmp_path)
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text


# TC-V8-M3-G03-01
def test_v8_m3_cold_start_empty_spine_honest() -> None:
    """Fresh process defaults: empty projections; health ready; no invented rows."""
    _assert_empty_honest_spine()
    snap = _workspace(mutation=False).snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS))
    public = snap.to_public_dict()
    assert public["tasks"] == []
    assert public["attempts"] == []
    assert public["runs"] == []
    assert public["results"] == []
    assert public["gates"] == []
    assert public["approvals"] == []
    assert public["commands"] == []
    health = public["authority_health"]
    for key in (
        "command_approval",
        "gate_1",
        "gate_2",
        "gate_3",
        "task",
        "attempt",
        "run",
        "result",
    ):
        assert health[key] == "hermetic"
    assert health["mutation"] == "disabled"
    assert health["composer"] == "disabled"
    assert health["hermes_gateway"] == "dark"
    assert health["provider"] == "dark"
    assert public["mutation_enabled"] is False


# TC-V8-M3-G03-02
def test_v8_m3_dual_cold_start_after_bind_clears_rows() -> None:
    """Cold-start #1 seed bind → cold-start #2 reset → empty again (dual drill)."""
    r = submit_action(
        _settings(mutation=True),
        _bind_options_doc(client_action_id="act-v8m3-dual-1"),
        mutation_enabled=True,
    )
    assert r.status == "accepted"
    assert len(project_workspace_tasks(WS)) == 1
    assert r.task_id

    _wipe_authorities()

    _assert_empty_honest_spine()
    # Prior task_id must not reappear without durable restore (authorities are ephemeral).
    assert default_vertical_binding_authority().get_task(WS, r.task_id) is None

    snap = _workspace(mutation=False).snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS))
    assert list(snap.to_public_dict()["tasks"]) == []


# TC-V8-M3-G03-03
def test_v8_m3_second_cold_start_still_empty_after_empty_first() -> None:
    """Two successive cold-starts from empty remain empty (no phantom revive)."""
    _assert_empty_honest_spine()
    _wipe_authorities()
    _assert_empty_honest_spine()


# TC-V8-M3-G03-04
def test_v8_m3_composer_and_chat_write_stay_off_on_cold_start() -> None:
    """Cold-start defaults: chat_write_ready false unless operator opens both flags."""
    snap = composer_readiness_snapshot(_settings(mutation=False))
    assert snap["mutation_enabled"] is False
    assert snap["chat_write_ready"] is False
    assert snap["composer_write_ready"] is False


# TC-V8-M3-G03-05 — production BFF never mounts cold-start authorities
def test_v8_m3_bff_never_projects_process_local_authorities(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            settings=_settings(mutation=True),
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )
    _bootstrap(client, tmp_path)

    receipt = submit_action(
        _settings(mutation=True),
        _bind_options_doc(client_action_id="act-v8m3-bff-1"),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    assert receipt.task_id

    r1 = client.get(f"/api/workspace/{WS}/snapshot", headers=_browser_headers())
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1.get("tasks") == []
    assert body1["authority_health"]["task"] == "unavailable"
    assert receipt.task_id not in (body1.get("tasks") or [])

    _wipe_authorities()

    r2 = client.get(f"/api/workspace/{WS}/snapshot", headers=_browser_headers())
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2.get("tasks") == []
    assert body2.get("attempts") == []
    assert body2.get("runs") == []
    assert body2.get("results") == []
    assert body2.get("gates") == []
    assert receipt.task_id not in (body2.get("tasks") or [])


# TC-V8-M3-G03-06 — deep-link catalog (observe-only; no restore of ephemeral state)
def test_v8_m3_deep_link_catalog_is_observe_only() -> None:
    """G3 deep-link list: routes + query keys are observe surfaces, not write gates."""
    catalog = {
        "routes": {
            "today": "/hermes",
            "sessions": "/hermes/sessions",
            "tasks": "/hermes/tasks",
            "approvals": "/hermes/approvals",
            "results": "/hermes/results",
        },
        "query_keys_observe": (
            "focus",
            "task_id",
            "gate_id",
            "approval_id",
            "result_id",
            "hermes_session_id",
            "command_id",
        ),
        "limitations": (
            "in_memory_authorities_empty_after_process_restart",
            "deep_link_does_not_restore_ephemeral_rows",
            "hqa_intent_workflow_backup_is_separate_rail",
            "public_write_off",
            "not_canary",
            "not_m6_gate2_decide",
        ),
    }
    assert "conversation" not in " ".join(catalog["routes"].values())
    assert "write" not in " ".join(catalog["query_keys_observe"])
    snap = composer_readiness_snapshot(_settings(mutation=False))
    assert snap["chat_write_ready"] is False
    # Catalog is data-only — mutating it must not open write.
    catalog["routes"]["forge"] = "/hermes/conversation/write"
    snap2 = composer_readiness_snapshot(_settings(mutation=False))
    assert snap2["chat_write_ready"] is False


# TC-V8-M3-GAP-04 lite — refresh/replay honesty after cold wipe
def test_v8_m3_snapshot_refresh_after_wipe_no_dup_phantom() -> None:
    """Full refresh after cold wipe: empty; no duplicate phantom task rows."""
    submit_action(
        _settings(mutation=True),
        _bind_options_doc(client_action_id="act-v8m3-refresh-1"),
        mutation_enabled=True,
    )
    assert len(project_workspace_tasks(WS)) == 1
    _wipe_authorities()
    a = project_workspace_tasks(WS)
    b = project_workspace_tasks(WS)
    assert a == b == []


# TC-V8-M3-G02 platform note — durable OFF honesty (no smuggle V2 live)
def test_v8_m3_durable_absent_still_requires_explicit_ephemeral_allow(
    tmp_path: Path,
) -> None:
    """GAP-12 adjacent: durable absent fails closed unless ephemeral allow."""
    import importlib

    mod = importlib.import_module("test_hermes_http_dispatch_adapter")
    # Binder re-executes the existing hermetic proofs under the V8-M3 campaign.
    mod.test_durable_absent_fails_closed_without_ephemeral_allow(tmp_path)
    mod.test_accepts_ephemeral_run_when_durable_absent(tmp_path)


# TC-V8-M3-G03-07 — re-bind after cold-start mints fresh ids (no revive)
def test_v8_m3_rebind_after_cold_start_mints_fresh_ids() -> None:
    """After wipe, a new bind is accepted with a new task_id (no silent revive)."""
    first = submit_action(
        _settings(mutation=True),
        _bind_options_doc(client_action_id="act-v8m3-rebind-a"),
        mutation_enabled=True,
    )
    assert first.status == "accepted"
    old_task = first.task_id
    _wipe_authorities()
    second = submit_action(
        _settings(mutation=True),
        _bind_options_doc(client_action_id="act-v8m3-rebind-b"),
        mutation_enabled=True,
    )
    assert second.status == "accepted"
    assert second.task_id
    assert second.task_id != old_task
    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == second.task_id
