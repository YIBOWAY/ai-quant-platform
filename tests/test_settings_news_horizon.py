from quant_system.config.settings import Settings


def test_news_and_horizon_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("QS_NEWS_SOURCE_PREFERENCE", raising=False)
    monkeypatch.delenv("QS_HORIZON_ENABLED", raising=False)
    monkeypatch.delenv("QS_HORIZON_INBOX_DIR", raising=False)
    settings = Settings()
    assert settings.news.source_preference == "auto"
    assert settings.news.failover_enabled is True
    assert settings.horizon.enabled is True
    assert settings.horizon.max_age_seconds == 129_600
    assert settings.horizon.provider_beta is False
    assert settings.horizon.ingest_on_read is False
    assert "horizon_inbox" in settings.horizon.inbox_dir.replace("\\", "/")


def test_horizon_settings_env_override(monkeypatch):
    monkeypatch.setenv("QS_NEWS_SOURCE_PREFERENCE", "horizon")
    monkeypatch.setenv("QS_NEWS_FAILOVER_ENABLED", "false")
    monkeypatch.setenv("QS_HORIZON_ENABLED", "false")
    monkeypatch.setenv("QS_HORIZON_MAX_AGE_SECONDS", "3600")
    monkeypatch.setenv("QS_HORIZON_INBOX_DIR", "/tmp/hz-inbox")
    settings = Settings()
    assert settings.news.source_preference == "horizon"
    assert settings.news.failover_enabled is False
    assert settings.horizon.enabled is False
    assert settings.horizon.max_age_seconds == 3600
    assert settings.horizon.inbox_dir == "/tmp/hz-inbox"
