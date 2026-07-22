"""V4 composer / research readiness surface — always fail-closed for writes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.composer_readiness import (
    UPSTREAM_CHAT_WRITE_BLOCKERS,
    authority_readiness,
    chat_write_blockers,
    composer_readiness_snapshot,
    platform_delivery_blockers,
)


ORIGIN = "http://127.0.0.1:3001"

_PERMANENT = {
    "authenticated_mutation_bff_unavailable",
    "prompt_retention_boundary_unavailable",
    "research_workflow_submission_unavailable",
    "composer_resume_stop_unavailable",
    "independent_security_review_unavailable",
    "user_chat_cutover_approval_required",
}


def _settings() -> Settings:
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            settings=_settings(),
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )


def _browser_headers(*, origin: str = ORIGIN, site: str = "same-origin") -> dict[str, str]:
    return {"Origin": origin, "Sec-Fetch-Site": site, "Host": "testserver"}


def test_authority_readiness_without_database() -> None:
    ready = authority_readiness(_settings())
    assert ready["command_ledger_schema_ready"] is False
    assert ready["session_registry_schema_ready"] is False
    assert ready["workflow_binding_schema_ready"] is False
    assert ready["ready"] is False
    assert ready["research_binding_ready"] is False
    assert ready["dark_dispatch_ready"] is False
    assert ready["mutation_enabled"] is False
    assert ready["composer_write_ready"] is False
    assert ready["chat_write_ready"] is False


def test_platform_blockers_include_permanent_and_schema_gaps() -> None:
    blockers = platform_delivery_blockers(_settings())
    for code in _PERMANENT:
        assert code in blockers, code
    # No DB → schema gaps surface as dynamic blockers.
    assert "command_ledger_schema_unavailable" in blockers
    assert "session_registry_schema_unavailable" in blockers
    assert "hqa_task_attempt_binding_unavailable" in blockers
    # Dispatch adapter is schema-gated (V5); absent binding ⇒ unavailable.
    assert "command_dispatch_adapter_unavailable" in blockers
    # CSRF is implemented; must not reappear.
    assert "csrf_protection_unavailable" not in blockers


def test_chat_write_blockers_envelope() -> None:
    payload = chat_write_blockers(_settings(), "integration_disabled")
    assert payload["upstream_blockers"] == list(UPSTREAM_CHAT_WRITE_BLOCKERS)
    assert "integration_disabled" in payload["blockers"]
    assert set(payload["platform_delivery_blockers"]).issubset(payload["blockers"])
    assert set(payload["upstream_blockers"]).issubset(payload["blockers"])


def test_composer_readiness_snapshot_never_opens() -> None:
    snap = composer_readiness_snapshot(_settings())
    assert snap["composer_open"] is False
    assert snap["mutation_enabled"] is False
    assert snap["chat_write_ready"] is False
    assert snap["composer_write_ready"] is False
    assert snap["platform_delivery_blocker_count"] >= len(_PERMANENT)
    assert isinstance(snap["platform_delivery_blockers"], list)


def test_gateway_exposes_research_and_security_blockers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/hermes/gateway")
    assert response.status_code == 200
    body = response.json()
    assert body["chat_write_ready"] is False
    platform = body["platform_delivery_blockers"]
    assert "authenticated_mutation_bff_unavailable" in platform
    assert "research_workflow_submission_unavailable" in platform
    assert "independent_security_review_unavailable" in platform
    assert "user_chat_cutover_approval_required" in platform
    assert "hqa_task_attempt_binding_unavailable" in platform
    assert "csrf_protection_unavailable" not in platform


def test_health_exposes_research_binding_and_composer_flags(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    ledger = response.json()["hermes_command_ledger"]
    assert ledger["research_binding_ready"] is False
    assert ledger["composer_write_ready"] is False
    assert ledger["chat_write_ready"] is False
    assert ledger["mutation_enabled"] is False
    assert ledger["agent_workspace_authorities_ready"] is False


def test_workspace_authorities_composite_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = issue_bootstrap_token(tmp_path)
    boot = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert boot.status_code == 200, boot.text

    response = client.get(
        "/api/workspace/authorities",
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mutation_enabled"] is False
    assert body["composer_write_ready"] is False
    assert body["chat_write_ready"] is False
    assert body["composer_open"] is False
    assert body["research_binding_ready"] is False
    assert "platform_delivery_blockers" in body
    assert "authenticated_mutation_bff_unavailable" in body["platform_delivery_blockers"]
    assert "research_workflow_submission_unavailable" in body["platform_delivery_blockers"]
    assert "independent_security_review_unavailable" in body["platform_delivery_blockers"]


def test_local_mutation_settings_clear_authenticated_bff_blocker() -> None:
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=False),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )
    ready = authority_readiness(settings)
    assert ready["mutation_enabled"] is True
    # Schemas absent → composer still closed even with mutation on.
    assert ready["composer_write_ready"] is False
    assert ready["chat_write_ready"] is False
    blockers = platform_delivery_blockers(settings)
    assert "authenticated_mutation_bff_unavailable" not in blockers
    assert "independent_security_review_unavailable" not in blockers
    assert "user_chat_cutover_approval_required" not in blockers
    # Research submission still blocked without binding schema.
    assert "research_workflow_submission_unavailable" in blockers
    assert "composer_resume_stop_unavailable" in blockers
