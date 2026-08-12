from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def _write_accepted_receipt(root) -> str:
    unsigned = {
        "contract": "hqa.d34_final_acceptance/v1",
        "workspace_id": "default",
        "accepted": True,
        "blockers": [],
        "live_execution_enabled": False,
        "soak": {"time_gate_ready": True},
    }
    digest = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    path = root / "d34/acceptance/latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**unsigned, "receipt_digest": digest}), encoding="utf-8")
    return digest


def test_time_gate_alone_does_not_switch_without_final_acceptance(
    tmp_path,
    monkeypatch,
) -> None:
    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "active", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": True},
                "soak": {
                    "completed_cycles": 10,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": True,
                    "blockers": [],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    monkeypatch.setattr(
        "quant_system.d34.cli.load_settings",
        lambda: SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path)),
    )

    result = runner.invoke(app, ["d34", "research-routing"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["default_research_entry"] == "d33"
    assert payload["d33_new_intake_enabled"] is True
    assert payload["reason_codes"] == ["d34_final_acceptance_pending"]


def test_d34_routing_disables_only_d33_new_intake_after_time_gate(
    monkeypatch,
) -> None:
    acceptance_digest = "a" * 64

    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            assert workspace_id == "default"
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "active", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": True},
                "soak": {
                    "completed_cycles": 10,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": True,
                    "blockers": [],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    monkeypatch.setattr(
        "quant_system.d34.cli.D34ResearchRoutingAuthority",
        lambda _path: SimpleNamespace(
            observe=lambda: {
                "contract": "hqa.d34_research_routing_state/v1",
                "requested_default": "d34",
                "final_acceptance_digest": acceptance_digest,
                "reason": "final acceptance passed",
                "updated_at": "2026-08-20T00:00:00+00:00",
            }
        ),
    )

    result = runner.invoke(app, ["d34", "research-routing"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "contract": "hqa.d34_research_routing/v1",
        "d33_maintenance_enabled": True,
        "d33_new_intake_enabled": False,
        "default_research_entry": "d34",
        "final_acceptance_digest": acceptance_digest,
        "reason_codes": ["d34_final_acceptance_recorded"],
        "requested_default": "d34",
        "soak": {
            "canary_observation_days": 5,
            "completed_cycles": 10,
            "required_canary_observation_days": 5,
            "required_completed_cycles": 10,
            "time_gate_ready": True,
        },
        "workspace_id": "default",
    }


def test_d34_routing_restores_d33_intake_when_rollback_pauses_mandate(
    monkeypatch,
) -> None:
    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "paused", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": False},
                "soak": {
                    "completed_cycles": 10,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": True,
                    "blockers": [],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)

    result = runner.invoke(app, ["d34", "research-routing"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["default_research_entry"] == "d33"
    assert payload["d33_new_intake_enabled"] is True
    assert payload["d33_maintenance_enabled"] is True
    assert payload["reason_codes"] == ["d34_final_acceptance_pending"]


def test_final_acceptance_cutover_persists_d34_as_default(tmp_path, monkeypatch) -> None:
    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "active", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": True},
                "soak": {
                    "completed_cycles": 10,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": True,
                    "blockers": [],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    monkeypatch.setattr(
        "quant_system.d34.cli.load_settings",
        lambda: SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path)),
    )
    digest = _write_accepted_receipt(tmp_path)

    cutover = runner.invoke(
        app,
        [
            "d34",
            "research-cutover",
            "--final-acceptance-digest",
            digest,
            "--reason",
            "10 cycles, 5 days, zero duplicates and no live eligibility",
        ],
    )
    observed = runner.invoke(app, ["d34", "research-routing"])

    assert cutover.exit_code == 0, cutover.output
    assert observed.exit_code == 0, observed.output
    assert json.loads(observed.output)["default_research_entry"] == "d34"
    state = json.loads((tmp_path / "d34/research-routing.json").read_text())
    assert state["final_acceptance_digest"] == digest
    assert state["requested_default"] == "d34"


def test_cutover_refuses_before_time_gate_without_writing_state(
    tmp_path,
    monkeypatch,
) -> None:
    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "active", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": True},
                "soak": {
                    "completed_cycles": 9,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": False,
                    "blockers": ["d34_completed_cycles_below_10"],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    monkeypatch.setattr(
        "quant_system.d34.cli.load_settings",
        lambda: SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path)),
    )

    result = runner.invoke(
        app,
        [
            "d34",
            "research-cutover",
            "--final-acceptance-digest",
            "c" * 64,
            "--reason",
            "too early",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["message"] == "d34_research_cutover_not_qualified"
    assert not (tmp_path / "d34/research-routing.json").exists()


def test_cutover_rejects_digest_without_matching_final_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    class SafetyBoundary:
        def __init__(self, _settings) -> None:
            pass

        def observe(self, *, workspace_id: str) -> dict[str, object]:
            return {
                "contract": "hqa.effective_paper_safety/v2",
                "workspace_id": workspace_id,
                "active_mandate": {"status": "active", "remaining_seconds": 3600},
                "emergency_stop": {"active": False},
                "d33": {"mode_enabled": True, "auto_land_enabled": True},
                "d34": {"mandate_active": True},
                "soak": {
                    "completed_cycles": 10,
                    "required_completed_cycles": 10,
                    "canary_observation_days": 5,
                    "required_canary_observation_days": 5,
                    "time_gate_ready": True,
                    "blockers": [],
                },
            }

    monkeypatch.setattr("quant_system.d34.cli.D34SafetyAuthority", SafetyBoundary)
    monkeypatch.setattr(
        "quant_system.d34.cli.load_settings",
        lambda: SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path)),
    )

    result = runner.invoke(
        app,
        [
            "d34",
            "research-cutover",
            "--final-acceptance-digest",
            "e" * 64,
            "--reason",
            "unrecorded acceptance",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["message"] == "d34_final_acceptance_receipt_invalid"
    assert not (tmp_path / "d34/research-routing.json").exists()
