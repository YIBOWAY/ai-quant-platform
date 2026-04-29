from quant_system.config.settings import reload_settings


def test_llm_settings_accept_unprefixed_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    monkeypatch.setenv("LLM_API_KEY", "alias-test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_TIMEOUT", "17")

    settings = reload_settings()

    assert settings.llm.provider == "xai"
    assert settings.llm.api_key is not None
    assert settings.llm.api_key.get_secret_value() == "alias-test-key"
    assert settings.llm.base_url == "https://example.test/v1"
    assert settings.llm.model == "test-model"
    assert settings.llm.timeout == 17
