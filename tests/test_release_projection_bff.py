"""BFF regressions for the PostgreSQL public-cutover projection/control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.routes import workspace as workspace_routes
from quant_system.api.safety.local_session import CSRF_HEADER_NAME, issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    DatabaseSettings,
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.release_authority import PublicCutoverRecord

ORIGIN = "http://127.0.0.1:3001"
WORKSPACE_ID = "ws-release-projection-bff"


class _ReleaseReader:
    def list_public_cutovers(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
    ) -> tuple[PublicCutoverRecord, ...]:
        assert workspace_id == WORKSPACE_ID
        assert limit == 20
        return (
            PublicCutoverRecord(
                cutover_id="cutover-bff",
                stamp_id="stamp-bff",
                workspace_id=workspace_id,
                route="/hermes",
                release_digest="1" * 64,
                cutover_digest="2" * 64,
                status="open",
                opened_at=datetime(2026, 7, 25, 9, 0, tzinfo=UTC),
                closed_at=None,
                close_reason=None,
                candidate_admission_id="admission-bff",
                candidate_admission_digest="3" * 64,
                candidate_acceptance_digest="4" * 64,
                evidence_set_id="evidence-bff",
                evidence_set_digest="5" * 64,
                final_order_snapshot_digest="6" * 64,
                paper_authority_epoch=7,
            ),
        )


def _settings(*, mutation_enabled: bool = False) -> Settings:
    return Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(
            enabled=mutation_enabled,
            composer_open=mutation_enabled,
        ),
        api_cors_origins=[
            ORIGIN,
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ],
    )


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _bootstrap(client: TestClient, tmp_path: Path) -> dict[str, str]:
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_snapshot_bff_carries_durable_public_cutover_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings()
    app = create_app(
        settings=settings,
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    monkeypatch.setattr(
        workspace_routes,
        "_workspace",
        lambda _settings: PlatformAgentWorkspace(
            settings,
            release_cutover_reader=_ReleaseReader(),
        ),
    )
    client = TestClient(app)
    _bootstrap(client, tmp_path)

    response = client.get(
        f"/api/workspace/{WORKSPACE_ID}/snapshot",
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authority_health"]["public_cutover"] == "ready"
    assert len(body["public_cutovers"]) == 1
    cutover = body["public_cutovers"][0]
    assert cutover["authority_source"] == "postgres_release_authority"
    assert cutover["kind"] == "agent_v0_2.release.public_cutover"
    assert cutover["cutover_id"] == "cutover-bff"
    assert cutover["stamp_id"] == "stamp-bff"
    assert cutover["release_digest"] == "1" * 64
    assert cutover["cutover_digest"] == "2" * 64
    assert cutover["status"] == "open"
    assert cutover["public_flag_open"] is True
    assert cutover["candidate_admission_id"] == "admission-bff"
    assert cutover["candidate_admission_digest"] == "3" * 64
    assert cutover["candidate_acceptance_digest"] == "4" * 64
    assert cutover["evidence_set_id"] == "evidence-bff"
    assert cutover["evidence_set_digest"] == "5" * 64
    assert cutover["final_order_snapshot_digest"] == "6" * 64
    assert cutover["paper_authority_epoch"] == 7
    assert "build_digest" not in cutover
    assert "acceptance_id" not in cutover
    assert "chat_write_ready" not in cutover
    assert "public_write_authorized" not in cutover


def test_legacy_cutover_open_bff_returns_operator_cli_required(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            settings=_settings(mutation_enabled=True),
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )
    boot = _bootstrap(client, tmp_path)

    response = client.post(
        f"/api/workspace/{WORKSPACE_ID}/act",
        json={
            "action": {
                "schema_version": 1,
                "kind": "public.cutover.open",
                "client_action_id": "legacy-bff-open",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "build_digest": "8" * 64,
                "route": "/hermes",
                "acceptance_id": "legacy-acceptance",
                "open_note": "operator CLI only",
            }
        },
        headers={**_headers(), CSRF_HEADER_NAME: boot["csrf_token"]},
    )

    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "unavailable"
    assert receipt["reason_code"] == "release_operator_cli_required"
    assert receipt["public_write_authorized"] is False
    assert receipt["chat_write_ready"] is False
