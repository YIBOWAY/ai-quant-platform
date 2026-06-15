from __future__ import annotations

from pathlib import Path

from quant_system.api.routes.options_radar import (
    _build_radar_screen_config as build_api_radar_screen_config,
)
from quant_system.cli import _build_radar_screen_config as build_cli_radar_screen_config
from quant_system.config.settings import Settings


def test_options_radar_settings_defaults_are_safe() -> None:
    settings = Settings()

    assert settings.options_radar.enabled is True
    assert settings.options_radar.provider == "futu"
    assert settings.options_radar.universe_top_n == 100
    assert settings.options_radar.max_delta_for_radar == 0.8
    assert settings.options_radar.futu_rate_limit_per_30s == 10
    assert settings.options_radar.output_dir == Path("data/options_scans")
    assert settings.options_radar.startup_catchup_enabled is False
    assert settings.safety.live_trading_enabled is False
    assert settings.safety.kill_switch is True


def test_options_radar_settings_accept_qs_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_OPTIONS_RADAR_PROVIDER", "sample")
    monkeypatch.setenv("QS_OPTIONS_RADAR_UNIVERSE_TOP_N", "25")
    monkeypatch.setenv("QS_OPTIONS_RADAR_MAX_DELTA_FOR_RADAR", "0.42")
    monkeypatch.setenv("QS_OPTIONS_RADAR_OUTPUT_DIR", "tmp/options_scans")
    monkeypatch.setenv("QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED", "true")

    settings = Settings()

    assert settings.options_radar.provider == "sample"
    assert settings.options_radar.universe_top_n == 25
    assert settings.options_radar.max_delta_for_radar == 0.42
    assert settings.options_radar.output_dir == Path("tmp/options_scans")
    assert settings.options_radar.startup_catchup_enabled is True


def test_options_radar_api_and_cli_share_screening_thresholds() -> None:
    settings = Settings()

    assert build_api_radar_screen_config(settings).max_delta == (
        settings.options_radar.max_delta_for_radar
    )
    assert build_cli_radar_screen_config(settings).max_delta == (
        settings.options_radar.max_delta_for_radar
    )
