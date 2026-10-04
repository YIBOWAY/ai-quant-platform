"""Sealed build check for RD-Agent -> LiteLLM -> OpenAI HTTP parameters."""

import json
import os

os.environ.update(
    LITELLM_CHAT_MODEL="openai/grok-4.6",
    LITELLM_REASONING_EFFORT="xhigh",
    LITELLM_CHAT_STREAM="false",
    LITELLM_LOG_LLM_CHAT_CONTENT="false",
)

import httpx  # noqa: E402
from openai import OpenAI  # noqa: E402
from rdagent.oai.backend.litellm import LiteLLMAPIBackend, LiteLLMSettings  # noqa: E402

captured = []


def handle(request):
    captured.append(json.loads(request.content))
    return httpx.Response(200, json={
        "id": "sealed-model-check", "object": "chat.completion", "created": 0,
        "model": "grok-4.6", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "READY"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


client = OpenAI(api_key="sealed-test-key", base_url="http://sealed.local/v1",
                http_client=httpx.Client(transport=httpx.MockTransport(handle)))
backend = LiteLLMAPIBackend.__new__(LiteLLMAPIBackend)
backend._create_chat_completion_inner_function(
    [{"role": "user", "content": "Reply READY."}], client=client,
)
assert len(captured) == 1
assert captured[0]["model"] == "grok-4.6"
assert captured[0]["reasoning_effort"] == "xhigh"
assert LiteLLMSettings(reasoning_effort=None).reasoning_effort is None
assert LiteLLMSettings(reasoning_effort="low").reasoning_effort == "low"
print("PASS sealed RD-Agent HTTP request: grok-4.6 / xhigh; other effort defaults preserved")
