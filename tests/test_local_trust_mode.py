"""Local trust mode: identity-ritual bypass that can never bypass safety."""

from __future__ import annotations

import pytest

from quant_system.config.settings import Settings
from quant_system.hermes import candidate_admission_gate
from quant_system.hermes.candidate_admission_gate import (
    current_candidate_decision,
)
from quant_system.hermes.local_trust import (
    TRUST_RED_LINES,
    trust_mode_active,
    trust_mode_requested_but_refused,
    trust_red_line_blockers,
    trust_runtime_digest,
)


def _trust_settings(**overrides) -> Settings:
    base = {
        "local_trust": {"mode": True},
        "local_mutation": {"enabled": True, "composer_open": True},
        "paper_account": {
            "db_mode": "canonical",
            "auto_process_pending_orders_enabled": False,
        },
        "database": {"auto_migrate": False},
        "hermes_gateway": {"enabled": True},
    }
    base.update(overrides)
    return Settings(**base)


def test_local_trust_defaults_off() -> None:
    assert Settings().local_trust.mode is False
    assert trust_mode_active(Settings()) is False
    assert trust_mode_requested_but_refused(Settings()) == ()


def test_trust_mode_active_when_flag_set_and_red_lines_hold() -> None:
    settings = _trust_settings()
    assert trust_red_line_blockers(settings) == ()
    assert trust_mode_active(settings) is True


@pytest.mark.parametrize(
    ("overrides", "expected_blocker"),
    [
        (
            {
                "safety": {
                    "live_trading_enabled": True,
                    "manual_live_trading_confirmation": (
                        "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING"
                    ),
                }
            },
            "live_trading_enabled",
        ),
    ],
)
def test_trust_mode_refuses_activation_on_each_red_line(
    overrides: dict,
    expected_blocker: str,
) -> None:
    settings = _trust_settings(**overrides)
    assert expected_blocker in trust_red_line_blockers(settings)
    assert trust_mode_active(settings) is False
    assert expected_blocker in trust_mode_requested_but_refused(settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"safety": {"kill_switch": False}},
        {"safety": {"paper_trading": False}},
        {"safety": {"dry_run": False}},
        {"safety": {"no_live_trade_without_manual_approval": False}},
        {
            "paper_account": {
                "db_mode": "canonical",
                "auto_process_pending_orders_enabled": True,
            }
        },
    ],
)
def test_research_mode_toggles_do_not_refuse_trust(overrides: dict) -> None:
    settings = _trust_settings(**overrides)
    assert trust_red_line_blockers(settings) == ()
    assert trust_mode_active(settings) is True


def test_red_line_catalog_matches_checks() -> None:
    names = {name for name, _ in TRUST_RED_LINES}
    assert names == {"live_trading_enabled"}


def test_trust_mode_candidate_decision_skips_all_identity_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _trust_settings()

    def _fail(*_args, **_kwargs):  # pragma: no cover - failure is the assert
        pytest.fail("identity-ritual I/O must not run under trust mode")

    monkeypatch.setattr(
        candidate_admission_gate,
        "CandidateAdmissionAuthority",
        _fail,
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "runtime_identity_observation",
        _fail,
    )
    monkeypatch.setattr(candidate_admission_gate, "get_database", _fail)
    monkeypatch.setattr(
        candidate_admission_gate,
        "candidate_preflight_evidence_observation",
        _fail,
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "current_release_decision",
        _fail,
    )

    decision = current_candidate_decision(settings, require_connector=False)
    assert decision.dispatch_ready is True
    assert decision.ready is True
    assert decision.admission_id is None
    assert decision.admission_digest is None
    assert decision.blockers == ()


def test_trust_mode_still_closes_on_safety_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _trust_settings(
        safety={
            "live_trading_enabled": True,
            "manual_live_trading_confirmation": (
                "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING"
            ),
        }
    )

    # With a red line violated, trust mode must NOT apply: the gate falls
    # back to the full ritual (which needs a DB) and reports the safety
    # blocker. Stub the ritual I/O so the unit test needs no PostgreSQL.
    class _NoAuthority:
        def __init__(self, *_a, **_k) -> None:
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        candidate_admission_gate,
        "CandidateAdmissionAuthority",
        _NoAuthority,
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "runtime_identity_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no runtime")),
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "get_database",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no db")),
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "candidate_preflight_evidence_observation",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no evidence")),
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "current_release_decision",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no release")),
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "candidate_admission_runtime_security_is_ready",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        candidate_admission_gate,
        "candidate_evidence_runtime_security_is_ready",
        lambda *_a, **_k: True,
    )

    decision = current_candidate_decision(settings, require_connector=False)
    assert decision.ready is False
    assert decision.dispatch_ready is False
    assert "live_trading_enabled" in decision.blockers


def test_trust_mode_never_promotes_public_chat_write_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import composer_readiness

    settings = _trust_settings()

    class _Connector:
        ready = True
        reason = "ready"
        worker_id = "worker-1"
        generation_token = "gen-1"
        heartbeat_age_seconds = 1.0
        mode = "supervised_dispatch"
        started_at = None

    class _Liveness:
        def __init__(self, *_a, **_k) -> None: ...

        def probe(self, **_kwargs) -> _Connector:
            return _Connector()

    monkeypatch.setattr(
        candidate_admission_gate,
        "ConnectorLivenessAuthority",
        _Liveness,
    )
    monkeypatch.setattr(
        composer_readiness,
        "current_release_decision",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no release")),
    )
    monkeypatch.setattr(
        composer_readiness,
        "command_ledger_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "session_registry_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "workflow_binding_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "hermes_runtime_security_ready",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        composer_readiness,
        "run_control_outcome_runtime_security_ready",
        lambda *_a, **_k: True,
    )

    readiness = composer_readiness.authority_readiness(settings, fresh=True)
    assert readiness["chat_write_ready"] is True
    assert readiness["admission_mode"] == "local_trust"
    assert readiness["candidate_admission_id"] is None
    assert readiness["candidate_admission_digest"] is None
    assert readiness["local_trust_mode"] is True
    assert readiness["public_chat_write_ready"] is False
    assert readiness["release_authorized"] is False
    assert readiness["public_write_authorized"] is False


def test_trust_mode_still_requires_live_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _trust_settings()

    class _Stale:
        ready = False
        reason = "connector_heartbeat_stale"
        worker_id = None
        generation_token = None
        heartbeat_age_seconds = 999.0
        mode = None
        started_at = None

    class _Liveness:
        def __init__(self, *_a, **_k) -> None: ...

        def probe(self, **_kwargs) -> _Stale:
            return _Stale()

    monkeypatch.setattr(
        candidate_admission_gate,
        "ConnectorLivenessAuthority",
        _Liveness,
    )
    decision = current_candidate_decision(settings, require_connector=True)
    assert decision.ready is False
    assert decision.blockers == ("connector_heartbeat_stale",)


def test_trust_runtime_digest_is_stable_and_distinct() -> None:
    settings = _trust_settings()
    digest = trust_runtime_digest(settings)
    assert len(digest) == 64
    assert digest == trust_runtime_digest(settings)
    # It must never collide with a git-commit-derived runtime digest domain.
    from quant_system.hermes.release_runtime import (
        _runtime_digest_from_commit,
    )

    assert digest != _runtime_digest_from_commit(
        "platform", "0" * 40
    )


def test_trust_mode_refusal_is_surfaced_in_platform_delivery_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import composer_readiness

    settings = _trust_settings(
        safety={
            "live_trading_enabled": True,
            "manual_live_trading_confirmation": (
                "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING"
            ),
        }
    )
    monkeypatch.setattr(
        composer_readiness,
        "_observe_effective_admission",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unused")),
    )
    # composer_readiness_snapshot uses the cached admission path; give it a
    # closed admission directly.
    from quant_system.hermes.composer_readiness import _EffectiveAdmission

    closed = _EffectiveAdmission(
        release_ready=False,
        candidate_ready=False,
        connector_ready=False,
        ready=False,
        admission_mode="closed",
        blockers=("candidate_admission_missing",),
        final_release_blockers=(),
        release_stamp_id=None,
        public_cutover_id=None,
        candidate_admission_id=None,
        candidate_admission_digest=None,
        release_event_cursor=0,
        connector_reason="connector_liveness_unavailable",
        connector_worker_id=None,
        connector_mode=None,
        connector_heartbeat_age_seconds=None,
    )
    monkeypatch.setattr(
        composer_readiness,
        "_effective_admission",
        lambda *_a, **_k: closed,
    )
    monkeypatch.setattr(
        composer_readiness,
        "command_ledger_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "session_registry_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "workflow_binding_schema_version",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        composer_readiness,
        "hermes_runtime_security_ready",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        composer_readiness,
        "run_control_outcome_runtime_security_ready",
        lambda *_a, **_k: True,
    )

    snapshot = composer_readiness.composer_readiness_snapshot(settings)
    assert snapshot["composer_open"] is False
    assert (
        "local_trust_refused_live_trading_enabled"
        in snapshot["platform_delivery_blockers"]
    )
