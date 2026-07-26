"""V4 composer / research readiness surface — always fail-closed for writes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    AgentV02ReleaseSettings,
    CandidateAdmissionSettings,
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes import composer_readiness as readiness_module
from quant_system.hermes.composer_readiness import (
    UPSTREAM_CHAT_WRITE_BLOCKERS,
    authority_readiness,
    chat_write_blockers,
    composer_readiness_snapshot,
    platform_delivery_blockers,
)

ORIGIN = "http://127.0.0.1:3001"


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


def test_platform_blockers_report_the_live_release_gate() -> None:
    blockers = platform_delivery_blockers(_settings())
    assert "local_mutation_disabled" in blockers
    assert "local_composer_closed" in blockers
    assert "release_authority_schema_unready" in blockers
    assert "restricted_runtime_role_unready" in blockers
    assert "active_release_stamp_missing" in blockers
    assert "open_public_cutover_missing" in blockers
    assert "connector_liveness_unavailable" in blockers
    # Research authority is independent of ordinary Hermes chat.
    assert "research_workflow_submission_unavailable" not in blockers
    assert "hqa_task_attempt_binding_unavailable" not in blockers


def test_chat_write_blockers_envelope() -> None:
    payload = chat_write_blockers(_settings(), "integration_disabled")
    assert "integration_disabled" in payload["blockers"]
    assert set(payload["platform_delivery_blockers"]).issubset(payload["blockers"])
    assert set(payload["upstream_blockers"]).issubset(payload["blockers"])
    assert "hermes_durable_capability_unavailable" in payload["upstream_blockers"]
    assert list(UPSTREAM_CHAT_WRITE_BLOCKERS) == []


def test_composer_readiness_snapshot_never_opens() -> None:
    snap = composer_readiness_snapshot(_settings())
    assert snap["composer_open"] is False
    assert snap["mutation_enabled"] is False
    assert snap["chat_write_ready"] is False
    assert snap["composer_write_ready"] is False
    assert snap["platform_delivery_blocker_count"] > 0
    assert isinstance(snap["platform_delivery_blockers"], list)


def test_gateway_exposes_effective_release_and_connector_blockers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/hermes/gateway")
    assert response.status_code == 200
    body = response.json()
    assert body["chat_write_ready"] is False
    platform = body["platform_delivery_blockers"]
    assert "local_mutation_disabled" in platform
    assert "local_composer_closed" in platform
    assert "active_release_stamp_missing" in platform
    assert "open_public_cutover_missing" in platform
    assert "connector_liveness_unavailable" in platform
    assert "research_workflow_submission_unavailable" not in platform
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
    assert "local_mutation_disabled" in body["platform_delivery_blockers"]
    assert "active_release_stamp_missing" in body["platform_delivery_blockers"]
    assert "connector_liveness_unavailable" in body["platform_delivery_blockers"]
    assert "research_workflow_submission_unavailable" not in body["platform_delivery_blockers"]


def test_local_mutation_settings_clear_only_the_deny_only_mutation_flag() -> None:
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
    assert "local_mutation_disabled" not in blockers
    assert "local_composer_closed" in blockers
    assert "restricted_runtime_role_unready" in blockers
    assert "active_release_stamp_missing" in blockers
    assert "open_public_cutover_missing" in blockers
    assert "research_workflow_submission_unavailable" not in blockers


def test_local_dark_readiness_never_promotes_public_chat_or_hides_upstream(
    monkeypatch,
) -> None:
    """Local operator enablement and public V8 release are separate gates."""

    monkeypatch.setattr(readiness_module, "command_ledger_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "session_registry_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "workflow_binding_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "hermes_runtime_security_ready", lambda _settings: True)
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings)
    assert ready["runtime_security_ready"] is True
    assert ready["dark_dispatch_schema_ready"] is True
    assert ready["dark_dispatch_ready"] is False
    assert ready["local_chat_write_ready"] is False
    assert ready["composer_write_ready"] is False
    assert ready["public_chat_write_ready"] is False
    assert ready["chat_write_ready"] is False

    blockers = chat_write_blockers(settings)
    assert list(UPSTREAM_CHAT_WRITE_BLOCKERS) == []
    assert "hermes_durable_capability_unavailable" in blockers["upstream_blockers"]
    assert "connector_liveness_unavailable" in blockers["blockers"]


def test_local_flags_cannot_clear_runtime_security_or_public_cutover_blockers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(readiness_module, "command_ledger_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "session_registry_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "workflow_binding_schema_version", lambda _settings: 1)
    monkeypatch.setattr(readiness_module, "hermes_runtime_security_ready", lambda _settings: False)
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings)
    assert ready["schema_ready"] is True
    assert ready["write_authority_ready"] is False


def _patch_effective_runtime(
    monkeypatch,
    *,
    release_ready: bool,
    release_blockers: tuple[str, ...] = (),
    connector_ready: bool,
    connector_reason: str = "ready",
) -> None:
    monkeypatch.setattr(readiness_module, "command_ledger_schema_version", lambda _settings: 3)
    monkeypatch.setattr(readiness_module, "session_registry_schema_version", lambda _settings: 3)
    # Ordinary chat must not depend on the research-only Task/Attempt binding.
    monkeypatch.setattr(readiness_module, "workflow_binding_schema_version", lambda _settings: None)
    monkeypatch.setattr(readiness_module, "hermes_runtime_security_ready", lambda _settings: True)
    monkeypatch.setattr(
        readiness_module,
        "current_release_decision",
        lambda _settings: SimpleNamespace(
            ready=release_ready,
            blockers=release_blockers,
            release_authorized=release_ready,
            public_write_authorized=release_ready,
            chat_write_ready=release_ready,
            release_stamp_id="stamp-1" if release_ready else None,
            public_cutover_id="cutover-1" if release_ready else None,
            candidate_admission_id=(
                "candidate-release-1" if release_ready else None
            ),
            candidate_admission_digest=("c" * 64 if release_ready else None),
            event_cursor=17,
        ),
    )
    monkeypatch.setattr(
        readiness_module,
        "runtime_identity_observation",
        lambda _settings: SimpleNamespace(platform_runtime_digest="a" * 64),
    )

    class FakeLiveness:
        def __init__(self, _settings) -> None:
            pass

        def probe(self, **_kwargs):
            return SimpleNamespace(
                ready=connector_ready,
                reason=connector_reason,
                mode="supervised_dispatch" if connector_ready else None,
                worker_id="worker-1" if connector_ready else None,
                heartbeat_age_seconds=0.5 if connector_ready else None,
            )

    monkeypatch.setattr(readiness_module, "ConnectorLivenessAuthority", FakeLiveness)


def test_effective_release_and_live_connector_open_ordinary_chat_without_research_binding(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=True,
    )
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings, fresh=True)

    assert ready["workflow_binding_schema_ready"] is False
    assert ready["research_binding_ready"] is False
    assert ready["write_authority_ready"] is True
    assert ready["connector_liveness_ready"] is True
    assert ready["release_authorized"] is True
    assert ready["candidate_admission_id"] == "candidate-release-1"
    assert ready["candidate_admission_digest"] == "c" * 64
    assert ready["chat_write_ready"] is True
    assert ready["composer_write_ready"] is True
    assert ready["public_chat_write_ready"] is True
    assert "research_workflow_submission_unavailable" not in platform_delivery_blockers(
        settings,
        fresh=True,
    )


def test_candidate_and_release_split_brain_closes_composer(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=True,
    )
    monkeypatch.setattr(
        readiness_module,
        "current_candidate_decision",
        lambda _settings, *, require_connector: SimpleNamespace(
            ready=True,
            connector_ready=True,
            connector_worker_id="candidate-worker",
            connector_heartbeat_age_seconds=0.25,
            admission_id="candidate-replacement-open",
            admission_digest="d" * 64,
            blockers=(),
        ),
    )
    settings = Settings(
        candidate_admission=CandidateAdmissionSettings(
            enabled=True,
            ttl_seconds=120,
        ),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings, fresh=True)

    assert ready["release_authorized"] is True
    assert ready["candidate_admission_id"] is None
    assert ready["candidate_admission_digest"] is None
    assert ready["chat_write_ready"] is False
    assert ready["composer_write_ready"] is False
    assert "candidate_release_split_brain" in platform_delivery_blockers(
        settings,
        fresh=True,
    )


def test_release_closes_when_candidate_authority_cannot_exclude_split_brain(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=True,
    )

    def unavailable_candidate(_settings, *, require_connector):
        raise RuntimeError("candidate authority unavailable")

    monkeypatch.setattr(
        readiness_module,
        "current_candidate_decision",
        unavailable_candidate,
    )
    settings = Settings(
        candidate_admission=CandidateAdmissionSettings(
            enabled=True,
            ttl_seconds=120,
        ),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings, fresh=True)
    blockers = platform_delivery_blockers(settings, fresh=True)

    assert ready["release_authorized"] is True
    assert ready["candidate_admission_id"] is None
    assert ready["chat_write_ready"] is False
    assert "candidate_authority_unavailable" in blockers


def test_release_workspace_must_match_the_fixed_web_chat_profile(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=True,
    )
    monkeypatch.setattr(
        readiness_module,
        "current_release_decision",
        lambda _settings: pytest.fail("workspace mismatch must fail before release authority I/O"),
    )
    settings = Settings(
        agent_v02_release=AgentV02ReleaseSettings(
            workspace_id="workspace-root",
        ),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings, fresh=True)
    blockers = platform_delivery_blockers(settings, fresh=True)

    assert ready["chat_write_ready"] is False
    assert ready["composer_write_ready"] is False
    assert "release_workspace_profile_mismatch" in blockers


def test_effective_release_never_opens_when_supervised_connector_is_not_live(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=False,
        connector_reason="connector_heartbeat_stale",
    )
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    ready = authority_readiness(settings, fresh=True)
    blockers = platform_delivery_blockers(settings, fresh=True)

    assert ready["release_authorized"] is True
    assert ready["connector_liveness_ready"] is False
    assert ready["chat_write_ready"] is False
    assert blockers == ["connector_heartbeat_stale"]


def test_effective_release_blockers_are_reported_without_obsolete_static_gaps(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=False,
        release_blockers=("release_evidence_digest_mismatch",),
        connector_ready=True,
    )
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    envelope = chat_write_blockers(settings, fresh=True)

    assert envelope["upstream_blockers"] == []
    assert envelope["platform_delivery_blockers"] == ["release_evidence_digest_mismatch"]
    assert envelope["blockers"] == ["release_evidence_digest_mismatch"]
    assert "run_submission_not_idempotent" not in envelope["blockers"]


def test_fresh_composer_snapshot_uses_one_consistent_admission_observation(
    monkeypatch,
) -> None:
    _patch_effective_runtime(
        monkeypatch,
        release_ready=True,
        connector_ready=True,
    )
    calls = 0

    def changing_release(_settings):
        nonlocal calls
        calls += 1
        ready = calls == 1
        return SimpleNamespace(
            ready=ready,
            blockers=() if ready else ("active_release_stamp_missing",),
                release_stamp_id="stamp-1" if ready else None,
                public_cutover_id="cutover-1" if ready else None,
                candidate_admission_id=(
                    "candidate-release-1" if ready else None
                ),
                candidate_admission_digest=("c" * 64 if ready else None),
                event_cursor=calls,
            )

    monkeypatch.setattr(
        readiness_module,
        "current_release_decision",
        changing_release,
    )
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN],
    )

    snapshot = composer_readiness_snapshot(settings, fresh=True)

    assert calls == 1
    assert snapshot["chat_write_ready"] is True
    assert snapshot["platform_delivery_blockers"] == []
