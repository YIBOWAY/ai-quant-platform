import httpx
from pydantic import SecretStr

from quant_system.agent.llm import build_llm_client
from quant_system.agent.llm.openai_client import OpenAICompatLLMClient
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.config.settings import LLMSettings, Settings


def test_llm_factory_returns_stub_by_default() -> None:
    client = build_llm_client(Settings(llm=LLMSettings(provider="stub")))

    assert isinstance(client, StubLLMClient)


def test_llm_factory_returns_openai_compatible_for_xai() -> None:
    client = build_llm_client(
        Settings(
            llm=LLMSettings(
                provider="xai",
                api_key=SecretStr("test-llm-key"),
                base_url="https://example.test/v1",
                model="test-model",
            )
        )
    )

    assert isinstance(client, OpenAICompatLLMClient)
    assert client.base_url == "https://example.test/v1"
    assert client.model == "test-model"


def test_openai_compatible_client_uses_injected_http_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "offline response"}}]},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatLLMClient(
        api_key="test-llm-key",
        base_url="https://example.test/v1",
        model="test-model",
        http_client=http_client,
    )

    assert (
        client.generate("hello", system="system", max_tokens=32, temperature=0.0)
        == "offline response"
    )
