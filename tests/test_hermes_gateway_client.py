from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from quant_system.config.settings import HermesGatewaySettings
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    HermesApiReadError,
)


def _token_file(tmp_path: Path, value: str = "test-only-token") -> Path:
    path = tmp_path / "hermes-api.key"
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _settings(tmp_path: Path, **overrides: object) -> HermesGatewaySettings:
    values: dict[str, object] = {
        "enabled": True,
        "base_url": "http://127.0.0.1:8642",
        "timeout_seconds": 1.0,
        "max_response_bytes": 64 * 1024,
        "max_messages": 2,
    }
    values.update(overrides)
    if "api_key_file" not in values:
        values["api_key_file"] = _token_file(tmp_path)
    return HermesGatewaySettings(**values)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8642",
        "http://192.168.1.4:8642",
        "https://127.0.0.1:8642",
        "http://127.0.0.1:8642/v1",
        "http://user:pass@127.0.0.1:8642",
        "http://127.0.0.1",
    ],
)
def test_client_rejects_non_loopback_or_ambiguous_base_url(
    tmp_path: Path,
    base_url: str,
) -> None:
    with pytest.raises(HermesApiReadError) as exc:
        HermesApiReadClient(_settings(tmp_path, base_url=base_url))
    assert exc.value.code == "invalid_endpoint"


def test_client_requires_owner_only_regular_token_file(tmp_path: Path) -> None:
    token_file = _token_file(tmp_path)
    os.chmod(token_file, 0o644)
    client = HermesApiReadClient(_settings(tmp_path, api_key_file=token_file))
    with pytest.raises(HermesApiReadError) as exc:
        client.capabilities()
    assert exc.value.code == "api_key_file_permissions"

    os.chmod(token_file, 0o600)
    symlink = tmp_path / "linked.key"
    symlink.symlink_to(token_file)
    client = HermesApiReadClient(_settings(tmp_path, api_key_file=symlink))
    with pytest.raises(HermesApiReadError) as exc:
        client.capabilities()
    assert exc.value.code == "api_key_file_invalid"


def test_client_reads_the_same_key_file_object_it_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = _token_file(tmp_path, "original-token")
    replacement = tmp_path / "replacement.key"
    replacement.write_text("replacement-token\n", encoding="utf-8")
    os.chmod(replacement, 0o600)
    real_open = os.open
    real_stat = Path.stat
    stat_calls = 0
    open_called = False

    def swap_path() -> None:
        token_file.unlink(missing_ok=True)
        token_file.symlink_to(replacement)

    def swapping_open(path: object, flags: int, *args: object) -> int:
        nonlocal open_called
        fd = real_open(path, flags, *args)
        if Path(path) == token_file:
            open_called = True
            swap_path()
        return fd

    def swapping_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal stat_calls
        result = real_stat(path, *args, **kwargs)
        if path == token_file and not open_called:
            stat_calls += 1
            if stat_calls == 2:
                swap_path()
        return result

    monkeypatch.setattr("quant_system.hermes.gateway_client.os.open", swapping_open)
    monkeypatch.setattr(Path, "stat", swapping_stat)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer original-token"
        return httpx.Response(
            200,
            json={
                "object": "hermes.api_server.capabilities",
                "model": "codex-local",
                "features": {"session_resources": True},
            },
        )

    client = HermesApiReadClient(
        _settings(tmp_path, api_key_file=token_file),
        transport=httpx.MockTransport(handler),
    )

    client.capabilities()

    assert open_called is True


@pytest.mark.parametrize(
    "session_id",
    [".", "..", "parent..child", "nested/session", r"nested\session", "C:drive"],
)
def test_client_rejects_path_unsafe_session_ids(
    tmp_path: Path,
    session_id: str,
) -> None:
    client = HermesApiReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"unexpected upstream request: {request.url}")
        ),
    )

    with pytest.raises(HermesApiReadError) as exc:
        client.session_detail(session_id)

    assert exc.value.code == "invalid_session_id"


def test_client_calls_only_allowlisted_gets_and_keeps_bearer_server_side(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                request.url.raw_path.decode(),
                request.headers.get("authorization"),
            )
        )
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "object": "hermes.api_server.capabilities",
                    "platform": "hermes-agent",
                    "model": "codex-local",
                    "contract_version": 1,
                    "features": {
                        "session_resources": True,
                        "run_submission": True,
                        "run_events_sse": True,
                        "run_status": True,
                        "run_approval_response": True,
                        "run_stop": True,
                        "managed_run_sessions": True,
                        "managed_run_history_authority": "hermes_session_db",
                        "managed_session_fork_mode": (
                            "preserve_source_exact_message_cursor"
                        ),
                    },
                    "durable": {
                        name: {
                            "supported": True,
                            "grounded": True,
                            "evidence": f"store.transactional_probe:{name}",
                            "secret": "must-not-escape",
                        }
                        for name in (
                            "idempotency",
                            "event_replay",
                            "approval_cas",
                            "idempotent_stop",
                            "restart_reconcile",
                            "run_evidence",
                        )
                    },
                },
            )
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "session-1",
                            "title": "Risk review",
                            "source": "api_server",
                            "model": "codex-local",
                            "message_count": 4,
                            "last_active": 1_720_000_000.0,
                            "preview": "Review AAPL",
                            "system_prompt": "must not escape",
                        }
                    ],
                    "limit": 5,
                    "offset": 0,
                    "has_more": False,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = HermesApiReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    capabilities = client.capabilities()
    sessions = client.list_sessions(limit=5, offset=0)

    assert capabilities["model"] == "codex-local"
    assert capabilities["features"]["session_resources"] is True
    assert capabilities["features"]["managed_run_sessions"] is True
    assert capabilities["contract_version"] == 1
    assert capabilities["managed_session_contract"] == {
        "history_authority": "hermes_session_db",
        "fork_mode": "preserve_source_exact_message_cursor",
    }
    assert capabilities["durable"]["run_evidence"] == {
        "supported": True,
        "grounded": True,
        "evidence": "store.transactional_probe:run_evidence",
    }
    assert sessions["data"] == [
        {
            "id": "session-1",
            "title": "Risk review",
            "source": "api_server",
            "model": "codex-local",
            "message_count": 4,
            "last_active": "2024-07-03T09:46:40Z",
            "preview": "Review AAPL",
            "parent_session_id": None,
            "ended_at": None,
        }
    ]
    assert seen == [
        ("GET", "/v1/capabilities", "Bearer test-only-token"),
        ("GET", "/api/sessions?limit=5&offset=0", "Bearer test-only-token"),
    ]


def test_client_never_inherits_environment_proxy_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.Client
    seen_kwargs: dict[str, object] = {}

    def client_factory(*args: object, **kwargs: object) -> httpx.Client:
        seen_kwargs.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "quant_system.hermes.gateway_client.httpx.Client",
        client_factory,
    )
    client = HermesApiReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "object": "hermes.api_server.capabilities",
                    "model": "codex-local",
                    "features": {"session_resources": True},
                },
            )
        ),
    )

    client.capabilities()

    assert seen_kwargs["trust_env"] is False


def test_message_history_is_bounded_and_drops_tool_and_reasoning_payloads(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.raw_path.decode() == "/api/sessions/session%3Aencoded/messages"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "session_id": "session:encoded",
                "data": [
                    {"id": 1, "role": "system", "content": "secret system prompt"},
                    {"id": 2, "role": "user", "content": "first"},
                    {
                        "id": 3,
                        "role": "tool",
                        "content": "TOKEN=secret",
                        "tool_calls": [{"arguments": "secret"}],
                    },
                    {
                        "id": 4,
                        "role": "assistant",
                        "content": "second",
                        "timestamp": 1_720_000_000.0,
                        "reasoning": "private chain",
                    },
                    {"id": 5, "role": "user", "content": "third"},
                ],
            },
        )

    client = HermesApiReadClient(
        _settings(tmp_path, max_messages=2),
        transport=httpx.MockTransport(handler),
    )
    result = client.session_messages("session:encoded")

    assert result == {
        "session_id": "session:encoded",
        "data": [
            {
                "id": "4",
                "role": "assistant",
                "content": "second",
                "timestamp": "2024-07-03T09:46:40Z",
                "fork_point": "message:4",
            },
            {
                "id": "5",
                "role": "user",
                "content": "third",
                "timestamp": None,
                "fork_point": "message:5",
            },
        ],
        "omitted_message_count": 3,
    }
    assert "secret" not in json.dumps(result)
    assert "reasoning" not in json.dumps(result)


def test_client_rejects_oversized_or_malformed_upstream_response(tmp_path: Path) -> None:
    for response, expected in (
        (httpx.Response(200, content=b"x" * 4097), "response_too_large"),
        (httpx.Response(200, content=b"not-json"), "invalid_upstream_response"),
    ):
        client = HermesApiReadClient(
            _settings(tmp_path, max_response_bytes=4096),
            transport=httpx.MockTransport(lambda _request, response=response: response),
        )
        with pytest.raises(HermesApiReadError) as exc:
            client.capabilities()
        assert exc.value.code == expected


def test_client_does_not_coerce_malformed_upstream_capabilities_or_ids(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "object": "hermes.api_server.capabilities",
                    "model": "codex-local",
                    "features": {"session_resources": "false"},
                },
            )
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "x" * 257, "message_count": 1},
                        {"id": "valid-session", "message_count": True},
                    ],
                    "has_more": False,
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = HermesApiReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    capabilities = client.capabilities()
    sessions = client.list_sessions()

    assert capabilities["features"]["session_resources"] is False
    assert [row["id"] for row in sessions["data"]] == ["valid-session"]
    assert sessions["data"][0]["message_count"] is None


def test_not_found_error_distinguishes_missing_endpoint_from_missing_session(
    tmp_path: Path,
) -> None:
    client = HermesApiReadClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )

    with pytest.raises(HermesApiReadError) as capability_error:
        client.capabilities()
    with pytest.raises(HermesApiReadError) as session_error:
        client.session_detail("session-1")

    assert capability_error.value.code == "upstream_endpoint_unavailable"
    assert session_error.value.code == "session_not_found"


# --- V1.5: transcript empty-message / compaction drop + DLP redaction ---


def _messages_client(tmp_path: Path, rows: list[dict], max_messages: int = 50):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"object": "list", "session_id": "s1", "data": rows},
        )

    return HermesApiReadClient(
        _settings(tmp_path, max_messages=max_messages),
        transport=httpx.MockTransport(handler),
    )


def test_message_history_drops_empty_and_whitespace_only_messages(
    tmp_path: Path,
) -> None:
    client = _messages_client(
        tmp_path,
        [
            {"id": 1, "role": "user", "content": ""},
            {"id": 2, "role": "assistant", "content": "   \n\t  "},
            {"id": 3, "role": "user", "content": "real question"},
            {"id": 4, "role": "assistant", "content": "real answer"},
        ],
    )
    result = client.session_messages("s1")

    contents = [m["content"] for m in result["data"]]
    assert contents == ["real question", "real answer"]
    # Empty/whitespace rows are omitted from the rendered transcript.
    assert all(c.strip() != "" for c in contents)


def test_message_history_exposes_only_authoritative_positive_integer_fork_points(
    tmp_path: Path,
) -> None:
    client = _messages_client(
        tmp_path,
        [
            {"id": 41, "role": "user", "content": "authoritative"},
            {"id": "42", "role": "assistant", "content": "numeric string"},
            {"id": 0, "role": "user", "content": "zero"},
            {"id": -1, "role": "assistant", "content": "negative"},
            {"role": "user", "content": "missing"},
            {"id": True, "role": "assistant", "content": "boolean"},
            {"id": 10**300, "role": "user", "content": "oversized"},
        ],
    )

    result = client.session_messages("s1")

    assert [message["id"] for message in result["data"]] == [
        "41",
        "42",
        "0",
        "-1",
        "4",
        "True",
        "6",
    ]
    assert [message.get("fork_point") for message in result["data"]] == [
        "message:41",
        None,
        None,
        None,
        None,
        None,
        None,
    ]


def test_message_history_drops_internal_compaction_entries(tmp_path: Path) -> None:
    client = _messages_client(
        tmp_path,
        [
            {"id": 1, "role": "user", "content": "before"},
            {"id": 2, "role": "assistant", "content": ""},  # compaction stub
            {"id": 3, "role": "assistant", "content": "  "},  # compaction stub
            {"id": 4, "role": "user", "content": "after"},
        ],
    )
    result = client.session_messages("s1")

    assert [m["content"] for m in result["data"]] == ["before", "after"]
    assert [m["id"] for m in result["data"]] == ["1", "4"]


def test_message_history_strips_discord_trigger_transport_metadata(
    tmp_path: Path,
) -> None:
    client = _messages_client(
        tmp_path,
        [
            {
                "id": 1,
                "role": "user",
                "content": (
                    "[Triggering message id: `1524779911535923341` — use as "
                    "`message_id` for reply/react/pin via the discord tools.]\n\n"
                    "推荐一个这两周的 NVDA sell put"
                ),
            },
            {
                "id": 2,
                "role": "user",
                "content": (
                    "[Triggering message id: `1524779911535923342` — use as "
                    "`message_id` for reply/react/pin via the discord tools.]"
                ),
            },
            {
                "id": 3,
                "role": "assistant",
                "content": "Explain the phrase Triggering message id normally",
            },
        ],
    )

    result = client.session_messages("s1")

    assert [message["id"] for message in result["data"]] == ["1", "3"]
    assert result["data"][0]["content"] == "推荐一个这两周的 NVDA sell put"
    assert result["data"][1]["content"] == (
        "Explain the phrase Triggering message id normally"
    )
    assert "152477991153592334" not in json.dumps(result, ensure_ascii=False)


def test_message_history_redacts_secrets_in_kept_messages(tmp_path: Path) -> None:
    client = _messages_client(
        tmp_path,
        [
            {"id": 1, "role": "user", "content": "use Bearer abc.def~+-_ghi please"},
            {"id": 7, "role": "user", "content": "use bearer lower.case-token please"},
            {"id": 8, "role": "user", "content": "use BEARER UPPER.CASE-TOKEN please"},
            {"id": 2, "role": "assistant", "content": "set token=abc123 now"},
            {"id": 3, "role": "user", "content": "aws key AKIAIOSFODNN7EXAMPLE here"},
            {"id": 4, "role": "assistant", "content": "-----BEGIN PRIVATE KEY----- x"},
            {"id": 5, "role": "user", "content": "the api_key=secret-value leaked"},
            {"id": 6, "role": "user", "content": "this message has no secrets"},
        ],
    )
    result = client.session_messages("s1")
    blob = json.dumps(result)

    # No secret literal survives serialization.
    for secret in (
        "abc.def~+-_ghi",
        "lower.case-token",
        "UPPER.CASE-TOKEN",
        "abc123",
        "AKIAIOSFODNN7EXAMPLE",
        "BEGIN PRIVATE KEY",
        "secret-value",
    ):
        assert secret not in blob
    assert "***" in blob
    # Non-secret text is preserved; the no-secret message is untouched.
    assert "this message has no secrets" in blob
    by_id = {m["id"]: m["content"] for m in result["data"]}
    assert by_id["6"] == "this message has no secrets"
    assert by_id["1"] == "use *** please"
    assert by_id["2"] == "set *** now"
    assert by_id["3"] == "aws key *** here"


def test_bearer_redaction_covers_base64_without_overmatching_boundaries(
    tmp_path: Path,
) -> None:
    client = _messages_client(
        tmp_path,
        [
            {
                "id": 1,
                "role": "user",
                "content": "authorization: bearer abc/def==, continue normally.",
            },
            {
                "id": 2,
                "role": "assistant",
                "content": "prebearer innocent text must remain",
            },
            {
                "id": 3,
                "role": "user",
                "content": "BEARER jwt.header/signature=. Next sentence",
            },
            {
                "id": 4,
                "role": "user",
                "content": "bearer .abc/def==; keep semicolon",
            },
            {"id": 5, "role": "assistant", "content": "bearer .==, keep comma"},
            {"id": 6, "role": "user", "content": "bearer ."},
            {
                "id": 7,
                "role": "assistant",
                "content": "bearer .abc. Next sentence",
            },
        ],
    )

    result = client.session_messages("s1")
    by_id = {message["id"]: message["content"] for message in result["data"]}

    assert by_id["1"] == "authorization: ***, continue normally."
    assert by_id["2"] == "prebearer innocent text must remain"
    assert by_id["3"] == "***. Next sentence"
    assert by_id["4"] == "***; keep semicolon"
    assert by_id["5"] == "***, keep comma"
    assert by_id["6"] == "***"
    assert by_id["7"] == "***. Next sentence"
