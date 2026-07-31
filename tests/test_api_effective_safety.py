from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import PaperAccountSettings, Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID


def _expected_fail_closed(blocker: str) -> dict[str, object]:
    return {
        "owner_user_id": str(ROOT_USER_ID),
        "workspace_id": PLATFORM_WORKSPACE_ID,
        "global_kill_switch": True,
        "canonical_account_count": None,
        "canonical_account_frozen": None,
        "current_paper_authority_epoch": None,
        "effective": False,
        "blockers": [blocker],
        "safety": {
            "bind_address": "127.0.0.1",
            "dry_run": True,
            "kill_switch": True,
            "live_trading_enabled": False,
            "paper_trading": True,
        },
    }


@pytest.mark.parametrize("db_mode", ["file", "mirror"])
def test_effective_safety_route_requires_canonical_paper_authority_without_io(
    monkeypatch,
    tmp_path,
    db_mode: str,
) -> None:
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("effective safety must not probe a provider or connector")
        ),
    )
    settings = Settings(
        paper_account=PaperAccountSettings(db_mode=db_mode),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/safety/effective")

    assert response.status_code == 200
    assert response.json() == _expected_fail_closed(
        "canonical_paper_authority_required"
    )


def test_effective_safety_route_is_provider_free_and_fails_closed_when_db_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("effective safety must not probe a provider or connector")
        ),
    )
    settings = Settings(
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/safety/effective")

    assert response.status_code == 200
    assert response.json() == _expected_fail_closed(
        "canonical_paper_authority_unavailable"
    )
