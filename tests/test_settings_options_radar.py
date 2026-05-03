from __future__ import annotations

from pathlib import Path

from quant_system.config.settings import Settings


def test_options_radar_settings_defaults_are_safe() -> None:
    settings = Settings()

    assert settings.options_radar.enabled is True
    assert settings.options_radar.provider == "futu"
    assert settings.options_radar.universe_top_n == 100
    assert settings.options_radar.futu_rate_limit_per_30s == 10
    assert settings.options_radar.output_dir == Path("data/options_scans")
    assert settings.safety.live_trading_enabled is False
    assert settings.safety.kill_switch is True


def test_options_radar_settings_accept_qs_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_OPTIONS_RADAR_PROVIDER", "sample")
    monkeypatch.setenv("QS_OPTIONS_RADAR_UNIVERSE_TOP_N", "25")
    monkeypatch.setenv("QS_OPTIONS_RADAR_OUTPUT_DIR", "tmp/options_scans")

    settings = Settings()

    assert settings.options_radar.provider == "sample"
    assert settings.options_radar.universe_top_n == 25
    assert settings.options_radar.output_dir == Path("tmp/options_scans")
