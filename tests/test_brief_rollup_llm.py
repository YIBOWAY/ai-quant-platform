from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from quant_system.brief.rollup_llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN,
    RollupLlmClient,
    RollupLlmUnavailable,
)


def _facts(locale: str = "zh") -> dict[str, Any]:
    return {
        "kind": "weekly",
        "period_key": "2026-W33",
        "locale": locale,
        "days": [],
        "items": [{"id": "n1", "title": "标题", "issue_date": "2026-08-10"}],
        "stats": {"daily_count": 1},
    }


def _chat_response(payload: Any, status: int = 200) -> httpx.Response:
    return _sse_response(
        {"choices": [{"index": 0, "delta": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        status=status,
    )


def _sse_response(*events: Any, done: bool = True, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
        + ("data: [DONE]\n\n" if done else ""),
    )


def _client_with_capture(
    handler: Any,
    **kwargs: Any,
) -> RollupLlmClient:
    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://rollup.test",
    )
    kwargs.setdefault("token", "tok-123")
    kwargs.setdefault("model", "grok-test")
    return RollupLlmClient(client=http, **kwargs)


def test_draft_posts_openai_compatible_json_object_request() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _chat_response({"title": "t", "main_storyline": "m", "topics": []})

    client = _client_with_capture(handler)
    result = client.draft(_facts())

    assert result == {"title": "t", "main_storyline": "m", "topics": []}
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer tok-123"
    body = json.loads(request.content)
    assert body["model"] == "grok-test"
    assert body["reasoning_effort"] == "xhigh"
    assert body["stream"] is True
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "周报" in body["messages"][0]["content"]
    assert "普通中文" in body["messages"][0]["content"]
    assert "不把推测或关注建议写成事实" in body["messages"][0]["content"]
    assert "保留必要的金融术语和原始引用" in body["messages"][0]["content"]
    assert "归档日报期数" in body["messages"][0]["content"]
    assert "n1" in body["messages"][1]["content"]


def test_editorial_prompts_define_financial_units_and_rounded_display_without_model_call():
    from quant_system.brief.rollup_llm import _critique_messages, _draft_messages

    for messages in (_draft_messages(_facts()), _critique_messages(_facts(), {"title": "draft"})):
        prompt = messages[0]["content"]
        assert "两位小数" in prompt
        assert "pnl_pct" in prompt and "invested_pct" in prompt
        assert "0.0325" in prompt and "3.25%" in prompt
        assert "period_change_pct" in prompt and "已经是百分数" in prompt
        assert "字段名" in prompt
        assert "缺少市场报价" in prompt


def test_draft_uses_english_prompts_for_en_locale() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _chat_response({"title": "t", "main_storyline": "m", "topics": []})

    client = _client_with_capture(handler)
    client.draft(_facts(locale="en"))

    body = json.loads(captured[0].content)
    assert "weekly review" in body["messages"][0]["content"]
    assert "item_refs" in body["messages"][0]["content"]


def test_critique_returns_ok_and_violations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "审核" in body["messages"][0]["content"]
        return _chat_response({"ok": False, "violations": ["引用了不存在的 id"]})

    client = _client_with_capture(handler)
    result = client.critique(_facts(), {"title": "t"})

    assert result == {"ok": False, "violations": ["引用了不存在的 id"]}


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": "yes", "violations": []},  # ok must be bool
        {"ok": True, "violations": "none"},  # violations must be a list
        {"ok": True, "violations": [1]},  # violations entries must be strings
        {"violations": []},  # ok missing
    ],
)
def test_critique_rejects_malformed_verdicts(payload: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(payload)

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="critique payload"):
        client.critique(_facts(), {"title": "t"})


def test_non_2xx_response_raises_without_leaking_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "bad gateway"})

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="HTTP 502") as excinfo:
        client.draft(_facts())
    assert "tok-123" not in str(excinfo.value)


def test_network_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="ConnectError"):
        client.draft(_facts())


def test_invalid_envelope_json_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=b"data: not json\n\n"
        )

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="invalid JSON"):
        client.draft(_facts())


def test_missing_choices_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response({"unexpected": True})

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="choices"):
        client.draft(_facts())


def test_non_json_message_content_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(
            {
                "choices": [
                    {"index": 0, "delta": {"content": "prose, not json"}, "finish_reason": "stop"}
                ]
            }
        )

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="not JSON"):
        client.draft(_facts())


def test_non_object_message_content_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(["a", "list"])

    client = _client_with_capture(handler)
    with pytest.raises(RollupLlmUnavailable, match="not a JSON object"):
        client.draft(_facts())


def test_stream_collects_only_content_across_transport_chunks() -> None:
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            data = _sse_response(
                {"choices": [{"index": 0, "delta": {"reasoning_content": "private reasoning"}}]},
                {"choices": [{"index": 0, "delta": {"content": '{"title":"中'}}]},
                {"choices": [{"index": 0, "delta": {"content": '文"}'}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"completion_tokens": 5}},
            ).content
            for index in range(0, len(data), 7):
                yield data[index : index + 7]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Chunks())

    assert _client_with_capture(handler).draft(_facts()) == {"title": "中文"}


@pytest.mark.parametrize(
    "finish_reason,done",
    [("stop", False), (None, True), ("length", True), ("content_filter", True)],
)
def test_stream_rejects_incomplete_generation_even_with_valid_json(finish_reason, done) -> None:
    response = _sse_response(
        {
            "choices": [
                {"index": 0, "delta": {"content": '{"ok":true}'}, "finish_reason": finish_reason}
            ]
        },
        done=done,
    )
    with pytest.raises(RollupLlmUnavailable, match="incomplete"):
        _client_with_capture(lambda _: response).draft(_facts())


def test_stream_error_event_cannot_return_preceding_valid_json() -> None:
    response = _sse_response(
        {"choices": [{"index": 0, "delta": {"content": '{"ok":true}'}, "finish_reason": "stop"}]},
        {"error": {"message": "private request text tok-123", "code": "internal_error"}},
    )
    with pytest.raises(RollupLlmUnavailable, match="error event") as excinfo:
        _client_with_capture(lambda _: response).draft(_facts())
    assert "private" not in str(excinfo.value)
    assert "tok-123" not in str(excinfo.value)


def test_stream_disconnect_raises_unavailable() -> None:
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"{\\"ok\\":true}"}}]}\n\n'
            raise httpx.ReadError("stream disconnected")

    response = httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=BrokenStream()
    )
    with pytest.raises(RollupLlmUnavailable, match="ReadError"):
        _client_with_capture(lambda _: response).draft(_facts())


def test_environment_defaults_match_local_hermes_xai_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "QS_BRIEF_ROLLUP_LLM_BASE_URL",
        "QS_BRIEF_ROLLUP_LLM_TOKEN",
        "QS_BRIEF_ROLLUP_LLM_MODEL",
        "QS_BRIEF_ROLLUP_LLM_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)

    client = RollupLlmClient()

    assert client._base_url == DEFAULT_BASE_URL == "http://127.0.0.1:8645"
    assert client._token == DEFAULT_TOKEN == "local-d34-proxy"
    assert client.model == DEFAULT_MODEL == "grok-4.6"
    assert client.reasoning_effort == DEFAULT_REASONING_EFFORT == "xhigh"
    assert client.critic_model == DEFAULT_MODEL
    assert client._timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 300.0


def test_environment_overrides_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_BASE_URL", "http://10.0.0.9:9999/")
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_TOKEN", "env-token")
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_MODEL", "grok-env")
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_TIMEOUT", "45")

    client = RollupLlmClient()

    assert client._base_url == "http://10.0.0.9:9999"
    assert client._token == "env-token"
    assert client.model == "grok-env"
    assert client._timeout_seconds == 45.0

    explicit = RollupLlmClient(base_url="http://override:1", timeout_seconds=5.0)
    assert explicit._base_url == "http://override:1"
    assert explicit._timeout_seconds == 5.0


def test_invalid_timeout_falls_back_without_logging_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_TIMEOUT", "not-a-number")
    monkeypatch.setenv("QS_BRIEF_ROLLUP_LLM_TOKEN", "super-secret-token")

    with caplog.at_level(logging.WARNING):
        client = RollupLlmClient()

    assert client._timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert "super-secret-token" not in caplog.text
