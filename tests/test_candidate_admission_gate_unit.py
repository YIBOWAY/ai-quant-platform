from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_system.config.settings import (
    AgentV02ReleaseSettings,
    CandidateAdmissionSettings,
    PaperAccountSettings,
    Settings,
)
from quant_system.hermes import candidate_admission_gate as gate_module
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID


def test_candidate_gate_rejects_non_web_workspace_before_authority_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate_module,
        "CandidateAdmissionAuthority",
        lambda _settings: pytest.fail(
            "workspace mismatch must fail before candidate authority I/O"
        ),
    )
    settings = Settings(
        agent_v02_release=AgentV02ReleaseSettings(
            workspace_id="workspace-root",
        ),
        candidate_admission=CandidateAdmissionSettings(enabled=True),
    )

    decision = gate_module.current_candidate_decision(
        settings,
        require_connector=True,
    )

    assert decision.ready is False
    assert decision.dispatch_ready is False
    assert decision.connector_ready is False
    assert decision.blockers == ("release_workspace_profile_mismatch",)
    assert decision.record is None


@pytest.mark.parametrize("db_mode", ["file", "mirror"])
def test_candidate_gate_requires_canonical_paper_authority_before_io(
    monkeypatch: pytest.MonkeyPatch,
    db_mode: str,
) -> None:
    def unexpected_io(name: str):
        return lambda *_args, **_kwargs: pytest.fail(
            f"{name} must stay untouched outside canonical paper mode"
        )

    monkeypatch.setattr(
        gate_module,
        "CandidateAdmissionAuthority",
        unexpected_io("candidate authority"),
    )
    monkeypatch.setattr(
        gate_module,
        "ConnectorLivenessAuthority",
        unexpected_io("connector authority"),
    )
    monkeypatch.setattr(
        gate_module,
        "runtime_identity_observation",
        unexpected_io("runtime identity"),
    )
    monkeypatch.setattr(
        gate_module,
        "get_database",
        unexpected_io("database"),
    )
    settings = Settings(
        agent_v02_release=AgentV02ReleaseSettings(
            workspace_id=PLATFORM_WORKSPACE_ID,
        ),
        candidate_admission=CandidateAdmissionSettings(enabled=True),
        paper_account=PaperAccountSettings(db_mode=db_mode),
    )

    decision = gate_module.current_candidate_decision(
        settings,
        require_connector=True,
    )

    assert decision.ready is False
    assert decision.dispatch_ready is False
    assert decision.connector_ready is False
    assert decision.blockers == ("canonical_paper_authority_required",)
    assert decision.record is None


def test_candidate_gate_rejects_stale_paper_epoch_before_connector_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        agent_v02_release=SimpleNamespace(
            workspace_id=PLATFORM_WORKSPACE_ID,
            connector_heartbeat_max_age_seconds=30,
        ),
        candidate_admission=SimpleNamespace(enabled=True),
        local_mutation=SimpleNamespace(enabled=True, composer_open=True),
        safety=SimpleNamespace(
            kill_switch=True,
            live_trading_enabled=False,
            paper_trading=True,
            dry_run=True,
            no_live_trade_without_manual_approval=True,
        ),
        paper_account=SimpleNamespace(
            auto_process_pending_orders_enabled=False,
            db_mode="canonical",
        ),
        database=SimpleNamespace(auto_migrate=False),
        hermes_gateway=SimpleNamespace(enabled=True),
    )
    record = SimpleNamespace(
        admission_id="candidate-epoch-stale",
        admission_digest="a" * 64,
        status="open",
        paper_authority_epoch=40,
        platform_runtime_digest="b" * 64,
        hqa_runtime_digest="c" * 64,
        hermes_runtime_digest="d" * 64,
        database_schema_fingerprint="e" * 64,
        preflight_evidence_digest="f" * 64,
        opened_at=SimpleNamespace(),
    )
    monkeypatch.setattr(
        gate_module,
        "CandidateAdmissionAuthority",
        lambda _settings: SimpleNamespace(
            active=lambda _workspace: None,
            current=lambda _workspace: record,
        ),
    )
    monkeypatch.setattr(
        gate_module,
        "PaperSafetyAuthority",
        lambda _settings: SimpleNamespace(
            observe=lambda _workspace, candidate_paper_authority_epoch: SimpleNamespace(
                blockers=("candidate_paper_authority_epoch_stale",),
            )
        ),
    )
    monkeypatch.setattr(
        gate_module,
        "ConnectorLivenessAuthority",
        lambda _settings: pytest.fail(
            "stale paper authority must fail before connector probe"
        ),
    )
    monkeypatch.setattr(
        gate_module,
        "runtime_identity_observation",
        lambda _settings: SimpleNamespace(
            platform_runtime_digest=record.platform_runtime_digest,
            hqa_runtime_digest=record.hqa_runtime_digest,
            hermes_runtime_digest=record.hermes_runtime_digest,
        ),
    )
    monkeypatch.setattr(gate_module, "get_database", lambda _settings: object())
    monkeypatch.setattr(
        gate_module,
        "schema_fingerprint",
        lambda _database: record.database_schema_fingerprint,
    )
    monkeypatch.setattr(
        gate_module,
        "candidate_preflight_evidence_observation",
        lambda _path: SimpleNamespace(
            digest=record.preflight_evidence_digest,
            platform_runtime_digest=record.platform_runtime_digest,
            hqa_runtime_digest=record.hqa_runtime_digest,
            hermes_runtime_digest=record.hermes_runtime_digest,
        ),
    )
    monkeypatch.setattr(
        gate_module,
        "candidate_admission_runtime_security_is_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        gate_module,
        "candidate_evidence_runtime_security_is_ready",
        lambda _settings: True,
    )
    monkeypatch.setattr(
        gate_module,
        "current_release_decision",
        lambda _settings: SimpleNamespace(blockers=()),
    )
    settings.candidate_admission.preflight_evidence_file = "unused"

    decision = gate_module.current_candidate_decision(
        settings,
        require_connector=True,
    )

    assert decision.ready is False
    assert decision.dispatch_ready is False
    assert decision.connector_ready is False
    assert "candidate_paper_authority_epoch_stale" in decision.blockers
