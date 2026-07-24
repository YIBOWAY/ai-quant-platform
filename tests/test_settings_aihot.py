from quant_system.config.settings import AiHotSettings, Settings


def test_aihot_settings_accept_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_AIHOT_ENABLED", "false")
    monkeypatch.setenv("QS_AIHOT_BASE_URL", "https://mirror.example.com/")
    monkeypatch.setenv("QS_AIHOT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("QS_AIHOT_CACHE_TTL_SECONDS", "45")
    monkeypatch.setenv("QS_AIHOT_USER_AGENT", "UnitTestBrowser/1.0")

    settings = AiHotSettings()

    assert settings.enabled is False
    assert settings.base_url == "https://mirror.example.com/"
    assert settings.timeout_seconds == 3
    assert settings.cache_ttl_seconds == 45
    assert settings.user_agent == "UnitTestBrowser/1.0"


def test_settings_include_aihot_defaults() -> None:
    settings = Settings()

    assert settings.aihot.enabled is True
    assert settings.aihot.base_url == "https://aihot.virxact.com"
    assert settings.aihot.timeout_seconds == 8
    assert settings.aihot.cache_ttl_seconds == 120
    assert "Mozilla/5.0" in settings.aihot.user_agent
