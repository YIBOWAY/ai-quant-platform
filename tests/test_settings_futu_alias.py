from pathlib import Path

from quant_system.config.settings import reload_settings


def test_futu_settings_accept_qs_futu_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_FUTU_ENABLED", "false")
    monkeypatch.setenv("QS_FUTU_HOST", "192.0.2.10")
    monkeypatch.setenv("QS_FUTU_PORT", "22222")
    monkeypatch.setenv("QS_FUTU_MARKET", "US")
    monkeypatch.setenv("QS_FUTU_REQUEST_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("QS_FUTU_DEFAULT_KLINE_FREQ", "K_DAY")
    monkeypatch.setenv("QS_FUTU_CACHE_DIR", "tmp/futu-cache")
    monkeypatch.setenv("QS_FUTU_USE_CACHE", "false")
    monkeypatch.setenv("QS_FUTU_OPTIONS_ENABLED", "false")

    settings = reload_settings()

    assert settings.futu.enabled is False
    assert settings.futu.host == "192.0.2.10"
    assert settings.futu.port == 22222
    assert settings.futu.market == "US"
    assert settings.futu.request_timeout_seconds == 9
    assert settings.futu.default_kline_freq == "K_DAY"
    assert settings.futu.cache_dir == Path("tmp/futu-cache")
    assert settings.futu.use_cache is False
    assert settings.futu.options_enabled is False


def test_futu_settings_keep_legacy_qs_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_HOST", "192.0.2.20")
    monkeypatch.setenv("QS_PORT", "33333")
    monkeypatch.setenv("QS_REQUEST_TIMEOUT_SECONDS", "11")

    settings = reload_settings()

    assert settings.futu.host == "192.0.2.20"
    assert settings.futu.port == 33333
    assert settings.futu.request_timeout_seconds == 11
