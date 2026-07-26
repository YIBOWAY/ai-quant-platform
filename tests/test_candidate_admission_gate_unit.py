from __future__ import annotations

import pytest

from quant_system.config.settings import (
    AgentV02ReleaseSettings,
    CandidateAdmissionSettings,
    Settings,
)
from quant_system.hermes import candidate_admission_gate as gate_module


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
