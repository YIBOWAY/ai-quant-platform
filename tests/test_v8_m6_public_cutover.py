"""V8-M6: hermetic public flag cutover (G7 open + G8 rollback).

Safety rails held on every path:
* release_authorized stays False (full V8 release is a separate stamp)
* m6_gate2_decide_authorized stays False
* v2_durable_live stays False
* kill_switch_unchanged stays True
* mutation_enabled gate still required
* route locked to /hermes
* open requires G6 dual-vertical acceptance_id evidence
* single open cutover CAS; close is one-click rollback retaining facts
* default (no open cutover) keeps public_write/chat_write False
"""

from __future__ import annotations

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    ClosePublicCutover,
    OpenPublicCutover,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.canary_grant_authority import (
    default_canary_grant_authority,
    reset_default_canary_grant_authority,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.public_cutover_authority import (
    PublicCutoverAuthorityError,
    canonical_public_cutover_digest,
    default_public_cutover_authority,
    reset_default_public_cutover_authority,
)
from quant_system.hermes.public_cutover_observe import (
    project_workspace_public_cutovers,
    public_cutover_authority_health,
    workspace_public_flag_open,
)
from quant_system.hermes.result_observe import reset_default_result_observe_journal
from quant_system.hermes.result_surface_authority import (
    default_result_surface_authority,
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import SubmissionSagaError, submit_action
from quant_system.hermes.vertical_binding_authority import (
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import reset_default_vertical_observe_journal

WS = "ws-v8-m6-cutover"
BUILD = "d" * 64
PAPER_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_public_cutover_authority()
    reset_default_canary_grant_authority()
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    yield
    reset_default_public_cutover_authority()
    reset_default_canary_grant_authority()
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _assert_rails(payload: dict, *, public_open: bool | None = None) -> None:
    assert payload.get("release_authorized") is False
    assert payload.get("m6_gate2_decide_authorized") is False
    assert payload.get("v2_durable_live") is False
    assert payload.get("kill_switch_unchanged") is True
    if public_open is True:
        assert payload.get("public_write_authorized") is True
        assert payload.get("chat_write_ready") is True
        assert payload.get("public_flag_open") is True
    elif public_open is False:
        assert payload.get("public_write_authorized") is False
        assert payload.get("chat_write_ready") is False


def _seed_g6_acceptance(*, acceptance_id: str = "acc-v8m6-g6") -> str:
    """Seed a dual-vertical acceptance fact required by G7 open."""
    # Minimal: write acceptance directly into canary authority store via public API.
    # Prefer going through accept_dual_vertical when a grant is active.
    from quant_system.hermes.canary_grant_authority import DualVerticalAcceptance
    from datetime import datetime, timezone

    auth = default_canary_grant_authority()
    # Use internal store via issue+accept path for honesty.
    grant = auth.issue(
        workspace_id=WS,
        build_digest=BUILD,
        route="/hermes",
        ttl_seconds=600,
        grant_note="seed for M6",
        client_action_id="seed-issue",
        action_digest="e" * 64,
    )
    # Manually register a matching options/factor binding is heavy; inject acceptance.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    acc = DualVerticalAcceptance(
        workspace_id=WS,
        acceptance_id=acceptance_id,
        grant_id=grant.grant_id,
        grant_digest=grant.grant_digest,
        build_digest=BUILD,
        options_a_task_id="task-opt",
        options_a_result_id="res-opt",
        factor_b_task_id="task-fac",
        factor_b_result_id="res-fac",
        acceptance_note="seeded G6 evidence for M6",
        accepted_at=now,
        action_id="seed-accept",
        action_digest="f" * 64,
    )
    with auth._lock:  # noqa: SLF001 — hermetic test seed
        auth._acceptances.setdefault(WS, {})[acceptance_id] = acc  # noqa: SLF001
        # consume grant like real accept
        grant.status = "consumed"
    return acceptance_id


def _open_doc(
    *,
    client_action_id: str = "act-v8m6-open",
    build_digest: str = BUILD,
    route: str = "/hermes",
    acceptance_id: str = "acc-v8m6-g6",
    open_note: str = "V8-M6 G7 single public flag open after dual-vertical accept",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "public.cutover.open",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "build_digest": build_digest,
        "route": route,
        "acceptance_id": acceptance_id,
        "open_note": open_note,
    }


def _close_doc(
    *,
    cutover_ref: str,
    expected_cutover_digest: str,
    client_action_id: str = "act-v8m6-close",
    reason: str = "G8 one-click rollback after canary window",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "public.cutover.close",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "cutover_ref": cutover_ref,
        "expected_cutover_digest": expected_cutover_digest,
        "reason": reason,
    }


def test_parse_and_digest_open_close() -> None:
    aid = _seed_g6_acceptance()
    open_doc = _open_doc(acceptance_id=aid)
    parsed = parse_user_action_v1(open_doc)
    assert isinstance(parsed, OpenPublicCutover)
    assert parsed.route == "/hermes"
    d1 = canonical_action_digest(parsed)
    assert d1 == canonical_action_digest(parse_user_action_v1(action_to_document(parsed)))

    # close needs a fake ref shape
    close_doc = _close_doc(
        cutover_ref="cutover:pct-test",
        expected_cutover_digest="a" * 64,
    )
    parsed_c = parse_user_action_v1(close_doc)
    assert isinstance(parsed_c, ClosePublicCutover)
    assert canonical_action_digest(parsed_c)


def test_route_must_be_hermes() -> None:
    with pytest.raises(AgentWorkspaceActionError):
        parse_user_action_v1(_open_doc(route="/chat"))


def test_open_requires_g6_acceptance() -> None:
    # No seed → validation error (G6 prerequisite)
    with pytest.raises(SubmissionSagaError) as ei:
        submit_action(
            _settings(),
            _open_doc(acceptance_id="missing-acc"),
            mutation_enabled=True,
            actor_owner_user_id=ROOT_USER_ID,
        )
    assert "dual_vertical_acceptance_required" in str(ei.value)
    assert workspace_public_flag_open(WS) is False


def test_mutation_off_unavailable_honesty() -> None:
    aid = _seed_g6_acceptance()
    rcpt = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=False,
        actor_owner_user_id=ROOT_USER_ID,
    )
    payload = rcpt.to_public_dict()
    assert payload["status"] == "unavailable"
    assert payload["reason_code"] == "authenticated_mutation_bff_unavailable"
    _assert_rails(payload, public_open=False)


def test_open_spine_and_flag() -> None:
    aid = _seed_g6_acceptance()
    rcpt = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    payload = rcpt.to_public_dict()
    assert payload["status"] == "accepted"
    assert payload.get("cutover_id")
    assert payload.get("cutover_digest")
    assert str(payload.get("cutover_ref", "")).startswith("cutover:")
    _assert_rails(payload, public_open=True)
    assert workspace_public_flag_open(WS) is True

    rows = project_workspace_public_cutovers(WS)
    assert len(rows) >= 1
    assert rows[0]["status"] == "open"
    assert rows[0]["public_flag_open"] is True
    assert rows[0]["release_authorized"] is False
    assert rows[0]["m6_gate2_decide_authorized"] is False
    assert rows[0]["v2_durable_live"] is False
    assert rows[0]["kill_switch_unchanged"] is True

    health = public_cutover_authority_health()
    assert health["public_cutover"] == "ready"

    # Snapshot carries public_cutovers + health
    ws = PlatformAgentWorkspace(settings=_settings())
    snap = ws.snapshot(ROOT_USER_ID, WS)
    pub = snap.to_public_dict()
    assert pub["authority_health"].get("public_cutover") == "ready"
    assert any(c.get("status") == "open" for c in pub.get("public_cutovers", []))


def test_second_open_conflicts_honesty() -> None:
    aid = _seed_g6_acceptance()
    first = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid, client_action_id="act-open-1"),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    assert first.to_public_dict()["status"] == "accepted"
    second = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid, client_action_id="act-open-2"),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    payload = second.to_public_dict()
    assert payload["status"] == "conflict"
    assert "public_cutover_already_open" in str(payload.get("reason_code"))
    _assert_rails(payload, public_open=False)
    # flag remains open from first
    assert workspace_public_flag_open(WS) is True


def test_open_idempotent() -> None:
    aid = _seed_g6_acceptance()
    doc = _open_doc(acceptance_id=aid, client_action_id="act-open-idem")
    a = submit_action(
        _settings(), doc, mutation_enabled=True, actor_owner_user_id=ROOT_USER_ID
    )
    b = submit_action(
        _settings(), doc, mutation_enabled=True, actor_owner_user_id=ROOT_USER_ID
    )
    assert a.to_public_dict()["status"] == "accepted"
    assert b.to_public_dict()["status"] == "accepted"
    assert a.to_public_dict()["cutover_id"] == b.to_public_dict()["cutover_id"]
    assert a.to_public_dict()["cutover_digest"] == b.to_public_dict()["cutover_digest"]


def test_close_rollback_retains_facts() -> None:
    aid = _seed_g6_acceptance()
    opened = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    assert opened["status"] == "accepted"
    cref = opened["cutover_ref"]
    cdig = opened["cutover_digest"]

    closed = submit_action(
        _settings(),
        _close_doc(cutover_ref=cref, expected_cutover_digest=cdig),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    assert closed["status"] == "accepted"
    _assert_rails(closed, public_open=False)
    assert workspace_public_flag_open(WS) is False

    # Facts retained on spine (closed row still listed)
    rows = project_workspace_public_cutovers(WS)
    assert any(r.get("status") == "closed" and r.get("cutover_id") == opened["cutover_id"] for r in rows)
    # acceptance still present (append-only G6 fact)
    accs = default_canary_grant_authority().list_acceptances(WS)
    assert any(a.acceptance_id == aid for a in accs)


def test_close_digest_mismatch() -> None:
    aid = _seed_g6_acceptance()
    opened = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    bad = submit_action(
        _settings(),
        _close_doc(
            cutover_ref=opened["cutover_ref"],
            expected_cutover_digest="0" * 64,
        ),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    assert bad["status"] == "conflict"
    assert "cutover_digest_mismatch" in str(bad.get("reason_code"))
    _assert_rails(bad, public_open=False)
    assert workspace_public_flag_open(WS) is True  # still open


def test_close_idempotent() -> None:
    aid = _seed_g6_acceptance()
    opened = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    doc = _close_doc(
        cutover_ref=opened["cutover_ref"],
        expected_cutover_digest=opened["cutover_digest"],
        client_action_id="act-close-idem",
    )
    a = submit_action(
        _settings(), doc, mutation_enabled=True, actor_owner_user_id=ROOT_USER_ID
    ).to_public_dict()
    b = submit_action(
        _settings(), doc, mutation_enabled=True, actor_owner_user_id=ROOT_USER_ID
    ).to_public_dict()
    assert a["status"] == "accepted"
    assert b["status"] == "accepted"
    assert a["cutover_id"] == b["cutover_id"]
    assert workspace_public_flag_open(WS) is False


def test_reopen_after_close() -> None:
    aid = _seed_g6_acceptance()
    o1 = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid, client_action_id="act-o1"),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    submit_action(
        _settings(),
        _close_doc(
            cutover_ref=o1["cutover_ref"],
            expected_cutover_digest=o1["cutover_digest"],
            client_action_id="act-c1",
        ),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    o2 = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid, client_action_id="act-o2"),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    ).to_public_dict()
    assert o2["status"] == "accepted"
    assert o2["cutover_id"] != o1["cutover_id"]
    _assert_rails(o2, public_open=True)


def test_follow_carries_public_cutovers() -> None:
    aid = _seed_g6_acceptance()
    submit_action(
        _settings(),
        _open_doc(acceptance_id=aid),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    ws = PlatformAgentWorkspace(settings=_settings())
    page = ws.follow(ROOT_USER_ID, WS)
    pub = page.to_public_dict()
    assert pub.get("public_cutovers") is not None
    assert any(c.get("status") == "open" for c in pub["public_cutovers"])
    assert pub.get("authority_health", {}).get("public_cutover") == "ready"


def test_canonical_digest_stable() -> None:
    d = canonical_public_cutover_digest(
        workspace_id=WS,
        cutover_id="pct-1",
        build_digest=BUILD,
        route="/hermes",
        acceptance_id="acc-1",
        opened_at="2026-07-23T00:00:00.000000Z",
    )
    d2 = canonical_public_cutover_digest(
        workspace_id=WS,
        cutover_id="pct-1",
        build_digest=BUILD,
        route="/hermes",
        acceptance_id="acc-1",
        opened_at="2026-07-23T00:00:00.000000Z",
    )
    assert d == d2
    assert len(d) == 64


def test_authority_validation_route_and_note() -> None:
    auth = default_public_cutover_authority()
    with pytest.raises(PublicCutoverAuthorityError):
        auth.open(
            workspace_id=WS,
            build_digest=BUILD,
            route="/other",
            acceptance_id="acc",
            open_note="note",
            client_action_id="x",
            action_digest="a" * 64,
            acceptance_exists=True,
        )
    with pytest.raises(PublicCutoverAuthorityError):
        auth.open(
            workspace_id=WS,
            build_digest=BUILD,
            route="/hermes",
            acceptance_id="acc",
            open_note="   ",
            client_action_id="x",
            action_digest="a" * 64,
            acceptance_exists=True,
        )


def test_default_no_cutover_public_off() -> None:
    assert workspace_public_flag_open(WS) is False
    assert project_workspace_public_cutovers(WS) == [] or all(
        r.get("status") != "open" for r in project_workspace_public_cutovers(WS)
    )
    # empty honest health still ready
    assert public_cutover_authority_health()["public_cutover"] == "ready"


def test_open_replay_after_close_does_not_claim_write() -> None:
    """Honesty hole fix: same open action after close must not claim public write."""
    aid = _seed_g6_acceptance()
    open_doc = _open_doc(acceptance_id=aid, client_action_id="act-replay-open")
    rcpt = submit_action(
        _settings(),
        open_doc,
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    assert rcpt.status == "accepted"
    assert rcpt.public_flag_open is True
    d = rcpt.to_public_dict()
    _assert_rails(d, public_open=True)
    cref = rcpt.cutover_ref
    cdig = rcpt.cutover_digest
    assert workspace_public_flag_open(WS) is True

    close_rcpt = submit_action(
        _settings(),
        _close_doc(cutover_ref=cref, expected_cutover_digest=cdig),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    assert close_rcpt.status == "accepted"
    assert close_rcpt.public_flag_open is False
    assert workspace_public_flag_open(WS) is False

    # Replay exact same open doc — must NOT resurrect write authorization.
    replay = submit_action(
        _settings(),
        open_doc,
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    assert replay.status == "conflict"
    assert replay.reason_code == "public_cutover_already_closed"
    rd = replay.to_public_dict()
    _assert_rails(rd, public_open=False)
    assert rd.get("public_flag_open") is False
    assert rd.get("public_write_authorized") is False
    assert rd.get("chat_write_ready") is False
    assert workspace_public_flag_open(WS) is False
    # Closed fact retained; no new open row.
    rows = project_workspace_public_cutovers(WS)
    assert any(r.get("status") == "closed" for r in rows)
    assert not any(r.get("status") == "open" for r in rows)


def test_open_requires_acceptance_build_digest_match() -> None:
    """G6 acceptance_id alone is not enough — build_digest must CAS-bind."""
    aid = _seed_g6_acceptance()  # seeds with BUILD
    other = PAPER_DIGEST  # different 64-hex
    assert other != BUILD
    rcpt = submit_action(
        _settings(),
        _open_doc(acceptance_id=aid, build_digest=other, client_action_id="act-mismatch-bd"),
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )
    assert rcpt.status == "conflict"
    assert rcpt.reason_code == "acceptance_build_digest_mismatch"
    d = rcpt.to_public_dict()
    _assert_rails(d, public_open=False)
    assert workspace_public_flag_open(WS) is False
    assert project_workspace_public_cutovers(WS) == []

