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


def test_agent_llm_config_allows_missing_optional_model_settings(
    tmp_path,
    monkeypatch,
) -> None:
    # Empty entries are common in a checked-in .env template. They must behave
    # like omitted optional configuration instead of making Settings fail at
    # process startup.
    for name in (
        "QS_LLM_PROVIDER",
        "LLM_PROVIDER",
        "QS_LLM_API_KEY",
        "LLM_API_KEY",
        "QS_LLM_BASE_URL",
        "LLM_BASE_URL",
        "QS_LLM_MODEL",
        "LLM_MODEL",
    ):
        monkeypatch.setenv(name, "")

    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/agent/llm-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "stub"
    assert payload["model"] is None
    assert payload["base_url"] is None
    assert payload["has_api_key"] is False
