"""V8-M5: hermetic canary grant + dual-vertical owner-accept (G5/G6).

Safety rails held on every path:
* public_write_authorized / chat_write_ready / release_authorized stay False
* no kill_switch flip, no M6 Gate2 decide, no V2 durable live ON
* mutation_enabled gate still required
* route locked to /hermes
* short TTL + exact build_digest + single active grant CAS
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import (
    PlatformAgentWorkspace as _PlatformAgentWorkspace,
)
from quant_system.hermes.agent_workspace_actions import (
    AcceptCanaryDualVertical,
    AgentWorkspaceActionError,
    IssueCanaryGrant,
    RevokeCanaryGrant,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.canary_grant_authority import (
    CanaryGrantAuthorityError,
    default_canary_grant_authority,
    reset_default_canary_grant_authority,
)
from quant_system.hermes.canary_observe import (
    project_workspace_canary_acceptances,
    project_workspace_canary_grants,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.composer_readiness import authority_readiness
from quant_system.hermes.result_observe import reset_default_result_observe_journal
from quant_system.hermes.result_surface_authority import (
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import submit_action as _submit_action
from quant_system.hermes.vertical_binding_authority import (
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import reset_default_vertical_observe_journal

submit_action = partial(_submit_action, allow_hermetic_authorities=True)
PlatformAgentWorkspace = partial(
    _PlatformAgentWorkspace,
    hermetic_authorities=True,
)

WS = "ws-v8-m5-canary"
BUILD = "b" * 64
BUILD_OTHER = "c" * 64
PAPER_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_canary_grant_authority()
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    yield
    reset_default_canary_grant_authority()
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _issue_doc(
    *,
    client_action_id: str = "act-v8m5-issue",
    build_digest: str = BUILD,
    route: str = "/hermes",
    ttl_seconds: int = 600,
    grant_note: str = "V8-M5 hermetic canary for dual-vertical accept",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "canary.grant.issue",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "build_digest": build_digest,
        "route": route,
        "ttl_seconds": ttl_seconds,
        "grant_note": grant_note,
    }


def _revoke_doc(
    *,
    canary_ref: str,
    expected_grant_digest: str,
    client_action_id: str = "act-v8m5-revoke",
    reason: str = "operator revoke after accept window",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "canary.grant.revoke",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "canary_ref": canary_ref,
        "expected_grant_digest": expected_grant_digest,
        "reason": reason,
    }


def _options_doc(*, client_action_id: str = "act-v8m5-opt") -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.options_a.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "ticker": "AAPL",
        "goal_note": "V8-M5 options A under canary",
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


def _factor_doc(*, client_action_id: str = "act-v8m5-fac") -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "goal_note": "V8-M5 factor B under canary",
        "paper_ref": "fixture:paper/momentum_reversal_v1.pdf",
        "paper_digest": PAPER_DIGEST,
        "factor_name": "momentum_20d_reversal",
        "formula_sketch": "ret_20d = close/close.shift(20)-1; signal = -ret_20d",
        "universe_note": "CSI300 hermetic fixture",
        "include_provider_evidence": True,
    }


def _accept_doc(
    *,
    canary_ref: str,
    expected_grant_digest: str,
    options_a_task_id: str,
    options_a_result_id: str,
    factor_b_task_id: str,
    factor_b_result_id: str,
    client_action_id: str = "act-v8m5-accept",
    expected_build_digest: str = BUILD,
    acceptance_note: str = "owner accepts dual vertical under canary",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "canary.dual_vertical.accept",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "canary_ref": canary_ref,
        "expected_build_digest": expected_build_digest,
        "expected_grant_digest": expected_grant_digest,
        "options_a_task_ref": f"task:{options_a_task_id}",
        "options_a_result_ref": f"result:{options_a_result_id}",
        "factor_b_task_ref": f"task:{factor_b_task_id}",
        "factor_b_result_ref": f"result:{factor_b_result_id}",
        "acceptance_note": acceptance_note,
    }


def _assert_public_write_still_off(payload: dict) -> None:
    assert payload.get("public_write_authorized") is False
    assert payload.get("chat_write_ready") is False
    assert payload.get("release_authorized") is False


# ---------------------------------------------------------------------------
# Parse / digest
# ---------------------------------------------------------------------------


def test_parse_and_digest_issue_stable() -> None:
    doc = _issue_doc()
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is IssueCanaryGrant
    assert parsed.route == "/hermes"
    assert parsed.ttl_seconds == 600
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2 and len(d1) == 64


def test_issue_rejects_non_hermes_route() -> None:
    doc = _issue_doc(route="/canary")
    with pytest.raises(AgentWorkspaceActionError, match="/hermes"):
        parse_user_action_v1(doc)


def test_issue_rejects_ttl_out_of_range() -> None:
    with pytest.raises(AgentWorkspaceActionError, match="ttl_seconds"):
        parse_user_action_v1(_issue_doc(ttl_seconds=10))
    with pytest.raises(AgentWorkspaceActionError, match="ttl_seconds"):
        parse_user_action_v1(_issue_doc(ttl_seconds=99999))


# ---------------------------------------------------------------------------
# Issue / revoke / TTL
# ---------------------------------------------------------------------------


def test_issue_accepted_and_projects_on_spine() -> None:
    receipt = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.grant_id
    assert receipt.grant_digest and len(receipt.grant_digest) == 64
    assert receipt.canary_ref == f"canary:{receipt.grant_id}"
    assert receipt.terminal_status == "active"
    pub = receipt.to_public_dict()
    _assert_public_write_still_off(pub)

    grants = project_workspace_canary_grants(WS)
    assert len(grants) == 1
    assert grants[0]["grant_id"] == receipt.grant_id
    assert grants[0]["status"] == "active"
    assert grants[0]["build_digest"] == BUILD
    assert grants[0]["route"] == "/hermes"
    _assert_public_write_still_off(grants[0])

    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WS).to_public_dict()
    assert snap["authority_health"]["canary_grant"] == "hermetic"
    assert len(snap["canary_grants"]) == 1
    assert snap["canary_grants"][0]["grant_id"] == receipt.grant_id
    # Public composer/chat write remains settings-gated OFF in hermetic.
    surface = authority_readiness(_settings())
    assert surface.get("chat_write_ready") is False
    assert surface.get("composer_write_ready") is False or surface.get("chat_write_ready") is False


def test_issue_mutation_off_unavailable() -> None:
    receipt = submit_action(_settings(), _issue_doc(), mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert project_workspace_canary_grants(WS) == []
    _assert_public_write_still_off(receipt.to_public_dict())


def test_issue_second_active_conflicts() -> None:
    r1 = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    assert r1.status == "accepted"
    r2 = submit_action(
        _settings(),
        _issue_doc(client_action_id="act-v8m5-issue-2"),
        mutation_enabled=True,
    )
    assert r2.status == "conflict"
    assert r2.reason_code == "canary_grant_already_active"
    # Honesty triad present even on conflict (no grant_id on r2).
    _assert_public_write_still_off(r2.to_public_dict())


def test_issue_idempotent_replay() -> None:
    doc = _issue_doc()
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == r2.status == "accepted"
    assert r1.grant_id == r2.grant_id
    assert r1.grant_digest == r2.grant_digest
    assert len(project_workspace_canary_grants(WS)) == 1


def test_revoke_active_grant() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    assert issued.status == "accepted"
    revoked = submit_action(
        _settings(),
        _revoke_doc(
            canary_ref=issued.canary_ref or "",
            expected_grant_digest=issued.grant_digest or "",
        ),
        mutation_enabled=True,
    )
    assert revoked.status == "accepted"
    assert revoked.terminal_status == "revoked"
    _assert_public_write_still_off(revoked.to_public_dict())
    # No active grant remains.
    auth = default_canary_grant_authority()
    assert auth.active_grant(WS) is None
    observed = project_workspace_canary_grants(WS)
    assert observed[0]["status"] == "revoked"


def test_revoke_digest_mismatch_conflicts() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    bad = submit_action(
        _settings(),
        _revoke_doc(
            canary_ref=issued.canary_ref or "",
            expected_grant_digest="d" * 64,
        ),
        mutation_enabled=True,
    )
    assert bad.status == "conflict"
    assert bad.reason_code == "canary_grant_digest_mismatch"
    assert default_canary_grant_authority().active_grant(WS) is not None


def test_ttl_expiry_marks_expired_and_blocks_accept() -> None:
    auth = default_canary_grant_authority()
    past = datetime.now(UTC) - timedelta(seconds=5)
    grant = auth.issue(
        workspace_id=WS,
        build_digest=BUILD,
        route="/hermes",
        ttl_seconds=60,
        grant_note="ttl drill",
        client_action_id="act-ttl-issue",
        action_digest="e" * 64,
        now=past - timedelta(seconds=120),
    )
    # Observe past expiry.
    row = auth.get(WS, grant.grant_id)
    assert row is not None
    assert row.status == "expired"
    assert auth.active_grant(WS) is None

    # Bind verticals so accept would otherwise be shape-valid.
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    fac = submit_action(_settings(), _factor_doc(), mutation_enabled=True)
    assert opt.status == fac.status == "accepted"
    receipt = submit_action(
        _settings(),
        _accept_doc(
            canary_ref=grant.canary_ref,
            expected_grant_digest=grant.grant_digest,
            options_a_task_id=opt.task_id or "",
            options_a_result_id=opt.result_id or "",
            factor_b_task_id=fac.task_id or "",
            factor_b_result_id=fac.result_id or "",
        ),
        mutation_enabled=True,
    )
    assert receipt.status == "conflict"
    assert receipt.reason_code == "canary_grant_expired"


# ---------------------------------------------------------------------------
# Dual-vertical accept (G6 hermetic)
# ---------------------------------------------------------------------------


def test_dual_vertical_accept_consumes_grant() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    assert issued.status == "accepted"
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    fac = submit_action(_settings(), _factor_doc(), mutation_enabled=True)
    assert opt.status == fac.status == "accepted"
    assert opt.task_id and opt.result_id and fac.task_id and fac.result_id

    accepted = submit_action(
        _settings(),
        _accept_doc(
            canary_ref=issued.canary_ref or "",
            expected_grant_digest=issued.grant_digest or "",
            options_a_task_id=opt.task_id,
            options_a_result_id=opt.result_id,
            factor_b_task_id=fac.task_id,
            factor_b_result_id=fac.result_id,
        ),
        mutation_enabled=True,
    )
    assert accepted.status == "accepted"
    assert accepted.acceptance_id
    assert accepted.terminal_status == "consumed"
    pub = accepted.to_public_dict()
    _assert_public_write_still_off(pub)

    auth = default_canary_grant_authority()
    assert auth.active_grant(WS) is None
    grants = project_workspace_canary_grants(WS)
    assert grants[0]["status"] == "consumed"
    assert grants[0]["acceptance"]["acceptance_id"] == accepted.acceptance_id
    _assert_public_write_still_off(grants[0])

    accs = project_workspace_canary_acceptances(WS)
    assert len(accs) == 1
    assert accs[0]["options_a_task_id"] == opt.task_id
    assert accs[0]["factor_b_task_id"] == fac.task_id
    _assert_public_write_still_off(accs[0])

    # Snapshot still honest; canary consumed; public write OFF.
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WS).to_public_dict()
    assert snap["authority_health"]["canary_grant"] == "hermetic"
    assert any(g["status"] == "consumed" for g in snap["canary_grants"])
    surface = authority_readiness(_settings())
    assert surface.get("chat_write_ready") is False


def test_dual_vertical_accept_build_mismatch() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    fac = submit_action(_settings(), _factor_doc(), mutation_enabled=True)
    bad = submit_action(
        _settings(),
        _accept_doc(
            canary_ref=issued.canary_ref or "",
            expected_grant_digest=issued.grant_digest or "",
            expected_build_digest=BUILD_OTHER,
            options_a_task_id=opt.task_id or "",
            options_a_result_id=opt.result_id or "",
            factor_b_task_id=fac.task_id or "",
            factor_b_result_id=fac.result_id or "",
        ),
        mutation_enabled=True,
    )
    assert bad.status == "conflict"
    assert bad.reason_code == "canary_build_digest_mismatch"
    assert default_canary_grant_authority().active_grant(WS) is not None


def test_dual_vertical_accept_idempotent() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    fac = submit_action(_settings(), _factor_doc(), mutation_enabled=True)
    doc = _accept_doc(
        canary_ref=issued.canary_ref or "",
        expected_grant_digest=issued.grant_digest or "",
        options_a_task_id=opt.task_id or "",
        options_a_result_id=opt.result_id or "",
        factor_b_task_id=fac.task_id or "",
        factor_b_result_id=fac.result_id or "",
    )
    a1 = submit_action(_settings(), doc, mutation_enabled=True)
    a2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert a1.status == a2.status == "accepted"
    assert a1.acceptance_id == a2.acceptance_id
    assert len(project_workspace_canary_acceptances(WS)) == 1


def test_dual_vertical_accept_missing_vertical_conflicts() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    # Only options bound — factor missing.
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    bad = submit_action(
        _settings(),
        _accept_doc(
            canary_ref=issued.canary_ref or "",
            expected_grant_digest=issued.grant_digest or "",
            options_a_task_id=opt.task_id or "",
            options_a_result_id=opt.result_id or "",
            factor_b_task_id="missing-factor-task",
            factor_b_result_id="missing-factor-result",
        ),
        mutation_enabled=True,
    )
    assert bad.status == "conflict"
    assert bad.reason_code == "factor_b_task_not_found"


def test_follow_carries_canary_grants() -> None:
    issued = submit_action(_settings(), _issue_doc(), mutation_enabled=True)
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(ROOT_USER_ID, WS).to_public_dict()
    assert "canary_grants" in page
    assert page["canary_grants"][0]["grant_id"] == issued.grant_id
    assert page["authority_health"]["canary_grant"] == "hermetic"
    _assert_public_write_still_off(page["canary_grants"][0])


def test_parse_revoke_and_accept_roundtrip() -> None:
    rev = _revoke_doc(canary_ref="canary:cgr-abc", expected_grant_digest=BUILD)
    parsed_r = parse_user_action_v1(rev)
    assert type(parsed_r) is RevokeCanaryGrant
    assert action_to_document(parsed_r) == rev

    acc = _accept_doc(
        canary_ref="canary:cgr-abc",
        expected_grant_digest=BUILD,
        options_a_task_id="t-a",
        options_a_result_id="r-a",
        factor_b_task_id="t-b",
        factor_b_result_id="r-b",
    )
    parsed_a = parse_user_action_v1(acc)
    assert type(parsed_a) is AcceptCanaryDualVertical
    assert action_to_document(parsed_a) == acc


def test_authority_issue_validation_errors() -> None:
    auth = default_canary_grant_authority()
    with pytest.raises(CanaryGrantAuthorityError) as ei:
        auth.issue(
            workspace_id=WS,
            build_digest="nope",
            route="/hermes",
            ttl_seconds=600,
            grant_note="x",
            client_action_id="a",
            action_digest=BUILD,
        )
    assert ei.value.code == "validation"
