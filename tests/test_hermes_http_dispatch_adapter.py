"""Unit tests for HttpHermesDispatchAdapter (no live Hermes, mock transport)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from quant_system.hermes.dispatch_adapter import (
    HermesDispatchRequest,
    HttpHermesDispatchAdapter,
    build_http_dispatch_adapter,
    fixed_input_resolver,
    metadata_input_resolver,
)


def _key_file(tmp_path: Path) -> Path:
    path = tmp_path / "hermes-api.key"
    path.write_text("test-key-value\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _settings(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8642",
        "api_key_file": _key_file(tmp_path),
        "timeout_seconds": 2.0,
        "dispatch_timeout_seconds": 30.0,
        "allow_ephemeral_runs": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _request(**overrides: object) -> HermesDispatchRequest:
    base = dict(
        command_id="00000000-0000-4000-8000-000000000001",
        kind="research_chat",
        client_request_id="client-req-smoke-0001",
        platform_session_id="wm_deadbeef",
        hermes_session_id="web_deadbeef",
        canonical_request_digest="a" * 64,
        payload_ref="hqa-payload:sha256:" + ("b" * 64),
        provider_policy_digest="c" * 64,
    )
    base.update(overrides)
    return HermesDispatchRequest(**base)  # type: ignore[arg-type]


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_accepts_ephemeral_run_when_durable_absent(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "object": "hermes.api_server.capabilities",
                    "features": {"run_submission": True, "session_resources": True},
                },
            )
        assert request.url.path == "/v1/runs"
        assert request.headers.get("authorization") == "Bearer test-key-value"
        assert request.headers.get("idempotency-key") == (
            "00000000-0000-4000-8000-000000000001"
        )
        body = json.loads(request.content.decode("utf-8"))
        assert body["input"] == "Reply with exactly: pong"
        assert body["session_id"] == "web_deadbeef"
        assert "metadata" in body
        return httpx.Response(
            200,
            json={
                "run_id": "run_abc123",
                "session_id": "web_deadbeef",
                "status": "completed",
                "created": True,
            },
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("Reply with exactly: pong"),
        allow_ephemeral_runs=True,
        transport=_mock_transport(handler),
    )
    result = adapter.submit_or_recover(_request())
    assert result.kind == "accepted"
    assert result.hermes_run_id == "run_abc123"
    assert result.hermes_session_id == "web_deadbeef"
    assert result.provider_call_count == 1
    assert result.evidence_digest


def test_recover_by_idempotency_key_without_second_provider_call(tmp_path: Path) -> None:
    calls = {"runs": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={"features": {"run_submission": True}},
            )
        calls["runs"] += 1
        return httpx.Response(
            200,
            json={
                "run_id": "run_once",
                "session_id": "web_deadbeef",
                "created": True,
            },
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("ping"),
        transport=_mock_transport(handler),
    )
    req = _request()
    first = adapter.submit_or_recover(req)
    second = adapter.submit_or_recover(req)
    assert first.kind == "accepted"
    assert second.kind == "recovered"
    assert second.hermes_run_id == "run_once"
    assert second.provider_call_count == 0
    assert calls["runs"] == 1


def test_adapter_rejects_response_that_substitutes_managed_session(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={"features": {"run_submission": True}},
            )
        return httpx.Response(
            202,
            json={
                "run_id": "run_wrong_session",
                "session_id": "different_session",
                "created": True,
            },
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("ping"),
        transport=_mock_transport(handler),
    )

    result = adapter.submit_or_recover(_request())

    assert result.kind == "transport_error"
    assert result.error_code == "session_identity_mismatch"


def test_same_client_id_in_two_sessions_has_distinct_upstream_keys(
    tmp_path: Path,
) -> None:
    observed: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={"features": {"run_submission": True}},
            )
        body = json.loads(request.content.decode("utf-8"))
        key = request.headers["idempotency-key"]
        session_id = body["session_id"]
        observed.append((key, session_id))
        return httpx.Response(
            202,
            json={
                "run_id": f"run_{len(observed)}",
                "session_id": session_id,
                "created": True,
            },
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("ping"),
        transport=_mock_transport(handler),
    )
    first = _request(
        command_id="00000000-0000-4000-8000-000000000001",
        platform_session_id="wm_one",
        hermes_session_id="web_one",
    )
    second = _request(
        command_id="00000000-0000-4000-8000-000000000002",
        platform_session_id="wm_two",
        hermes_session_id="web_two",
    )

    assert adapter.submit_or_recover(first).is_success
    assert adapter.submit_or_recover(second).is_success
    assert observed == [
        ("00000000-0000-4000-8000-000000000001", "web_one"),
        ("00000000-0000-4000-8000-000000000002", "web_two"),
    ]


def test_durable_absent_fails_closed_without_ephemeral_allow(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"features": {"run_submission": True}},
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path, allow_ephemeral_runs=False),
        allow_ephemeral_runs=False,
        transport=_mock_transport(handler),
    )
    result = adapter.submit_or_recover(_request())
    assert result.kind == "unavailable"
    assert result.error_code == "durable_unavailable"


def test_run_submission_false_is_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"features": {"run_submission": False}},
        )

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        transport=_mock_transport(handler),
    )
    result = adapter.submit_or_recover(_request())
    assert result.kind == "unavailable"
    assert result.error_code == "run_submission_unavailable"


def test_timeout_maps_to_timeout_kind(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {"run_submission": True}})
        raise httpx.ReadTimeout("slow")

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("x"),
        transport=_mock_transport(handler),
    )
    result = adapter.submit_or_recover(_request())
    assert result.kind == "timeout"
    assert result.error_code == "upstream_timeout"


def test_upstream_400_is_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {"run_submission": True}})
        return httpx.Response(400, json={"error": "Missing input"})

    adapter = HttpHermesDispatchAdapter(
        settings=_settings(tmp_path),
        input_resolver=fixed_input_resolver("x"),
        transport=_mock_transport(handler),
    )
    result = adapter.submit_or_recover(_request())
    assert result.kind == "rejected"
    assert result.error_code == "invalid_request"


def test_metadata_input_resolver_is_bounded_and_deterministic() -> None:
    req = _request()
    text = metadata_input_resolver(req)
    assert "Reply with exactly: ack" in text
    assert req.command_id in text
    assert len(text.encode("utf-8")) < 16_384


def test_build_http_dispatch_adapter_requires_enabled(tmp_path: Path) -> None:
    from quant_system.hermes.dispatch_adapter import HermesDispatchAdapterError

    with pytest.raises(HermesDispatchAdapterError) as exc:
        build_http_dispatch_adapter(
            SimpleNamespace(hermes_gateway=_settings(tmp_path, enabled=False))
        )
    assert exc.value.code == "integration_disabled"


def test_build_http_dispatch_adapter_fixed_input(tmp_path: Path) -> None:
    adapter = build_http_dispatch_adapter(
        SimpleNamespace(hermes_gateway=_settings(tmp_path)),
        fixed_input="Reply with exactly: pong",
    )
    assert adapter.allow_ephemeral_runs is True
    assert adapter.input_resolver(_request()) == "Reply with exactly: pong"
