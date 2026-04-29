from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import LLMSettings, Settings


def test_agent_llm_config_masks_api_key(tmp_path) -> None:
    settings = Settings(
        llm=LLMSettings(
            provider="xai",
            api_key=SecretStr("test-llm-key"),
            base_url="https://example.test/v1",
            model="test-model",
            timeout=12,
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/agent/llm-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "xai"
    assert payload["model"] == "test-model"
    assert payload["base_url"] == "https://example.test/v1"
    assert payload["timeout"] == 12
    assert payload["has_api_key"] is True
    assert "api_key" not in payload
    assert "test-llm-key" not in response.text
