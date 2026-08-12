from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import CSRF_HEADER_NAME, issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:3001"


class _Safety:
    def __init__(self) -> None:
        self.emergency = False

    def observe(self, *, workspace_id: str):
        assert workspace_id == "default"
        return {
            "contract": "hqa.effective_paper_safety/v2",
            "workspace_id": "default",
            "active_mandate": {
                "mandate_id": "mandate-test",
                "status": "active",
                "expires_at": "2026-09-10T00:00:00+00:00",
                "remaining_seconds": 2592000,
                "paper_execution_allowed": True,
            },
            "paper_execution_enabled": not self.emergency,
            "blockers": ["emergency_stop_active"] if self.emergency else [],
            "research_execution_enabled": not self.emergency,
            "research_blockers": ["emergency_stop_active"] if self.emergency else [],
            "emergency_stop": {
                "active": self.emergency,
                "reason": "owner stop" if self.emergency else None,
                "created_at": "2026-08-11T00:00:00+00:00" if self.emergency else None,
            },
            "d33": {"mode_enabled": True, "auto_land_enabled": True},
            "d34": {
                "mandate_active": True,
                "queued_jobs": 1,
                "running_jobs": 0,
                "active_canaries": 1,
            },
            "budget": {
                "limit_usd": "100.00",
                "spent_usd": "12.500000",
                "remaining_usd": "87.500000",
                "warning_fraction": "0.800000",
                "warning": False,
            },
            "quota": {"new_canaries_today": 1, "max_new_canaries_per_day": 1},
            "canaries": {"active_count": 1, "allocated_cash": "1000.00"},
            "soak": {
                "completed_cycles": 4,
                "required_completed_cycles": 10,
                "canary_observation_days": 2,
                "required_canary_observation_days": 5,
                "time_gate_ready": False,
                "blockers": [
                    "d34_completed_cycles_below_10",
                    "d34_canary_observation_days_below_5",
                ],
            },
            "risk": {
                "max_sleeve_cash": "10000.00",
                "max_sleeve_nav_fraction": 0.01,
                "max_total_nav_fraction": 0.10,
                "max_symbol_nav_fraction": 0.05,
                "max_daily_loss": 0.02,
                "max_drawdown": 0.10,
            },
            "live_execution_enabled": False,
        }

    def set_emergency_stop(self, *, workspace_id: str, enabled: bool, reason: str):
        assert workspace_id == "default"
        assert reason == "owner stop"
        self.emergency = enabled
        return self.observe(workspace_id=workspace_id)


def _headers() -> dict[str, str]:
    return {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "Host": "testserver"}


def test_owner_reads_v2_safety_and_persists_emergency_stop(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            hermes_gateway=HermesGatewaySettings(enabled=False),
            local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
            api_cors_origins=[ORIGIN],
        ),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.state.services["d34_safety_authority"] = _Safety()
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    csrf = bootstrap.json()["csrf_token"]

    before = client.get("/api/safety/effective/v2?workspace_id=default", headers=_headers())
    stopped = client.post(
        "/api/safety/emergency-stop",
        json={"workspace_id": "default", "enabled": True, "reason": "owner stop"},
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert before.status_code == 200, before.text
    assert before.json()["paper_execution_enabled"] is True
    assert before.json()["research_execution_enabled"] is True
    assert before.json()["live_execution_enabled"] is False
    assert before.json()["research_routing"] == {
        "requested_default": "d33",
        "default_research_entry": "d33",
        "final_acceptance_digest": None,
        "d33_new_intake_enabled": True,
        "d33_maintenance_enabled": True,
        "reason_codes": ["d34_time_gate_pending"],
    }
    assert before.json()["soak"] == {
        "completed_cycles": 4,
        "required_completed_cycles": 10,
        "canary_observation_days": 2,
        "required_canary_observation_days": 5,
        "time_gate_ready": False,
        "blockers": [
            "d34_completed_cycles_below_10",
            "d34_canary_observation_days_below_5",
        ],
    }
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["emergency_stop"]["active"] is True
    assert stopped.json()["blockers"] == ["emergency_stop_active"]
    assert stopped.json()["research_blockers"] == ["emergency_stop_active"]
    assert stopped.json()["research_routing"]["d33_new_intake_enabled"] is False
    assert stopped.json()["research_routing"]["reason_codes"] == [
        "d34_time_gate_pending",
        "emergency_stop_active",
    ]
