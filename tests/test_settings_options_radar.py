from __future__ import annotations

from pathlib import Path

from quant_system.cli import _build_radar_screen_config as build_cli_radar_screen_config
from quant_system.config.settings import OptionsRadarSettings, Settings


def test_options_radar_settings_defaults_are_safe() -> None:
    options = OptionsRadarSettings(_env_file=None)

    assert options.enabled is True
    assert options.provider == "futu"
    assert options.universe_top_n == 100
    assert options.curated_universe_path == Path(
        "data/options_universe/curated_wheel.csv"
    )
    assert options.min_dte_for_radar == 5
    assert options.max_delta_for_radar == 0.35
    assert options.risk_free_rate == 0.0387
    assert options.equity_risk_premium == 0.04
    assert options.dividend_events_path == Path(
        "data/options_universe/dividend_events.csv"
    )
    assert options.futu_rate_limit_per_30s == 10
    assert options.output_dir == Path("data/options_scans")
    assert "startup_catchup_enabled" not in OptionsRadarSettings.model_fields
    settings = Settings()
    assert settings.safety.live_trading_enabled is False
    assert settings.safety.kill_switch is True


def test_options_radar_settings_accept_qs_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("QS_OPTIONS_RADAR_PROVIDER", "sample")
    monkeypatch.setenv("QS_OPTIONS_RADAR_UNIVERSE_TOP_N", "25")
    monkeypatch.setenv("QS_OPTIONS_RADAR_MAX_DELTA_FOR_RADAR", "0.42")
    monkeypatch.setenv("QS_OPTIONS_RADAR_CURATED_UNIVERSE_PATH", "inputs/wheel.csv")
    monkeypatch.setenv("QS_OPTIONS_RADAR_RISK_FREE_RATE", "0.041")
    monkeypatch.setenv("QS_OPTIONS_RADAR_EQUITY_RISK_PREMIUM", "0.05")
    monkeypatch.setenv("QS_OPTIONS_RADAR_DIVIDEND_EVENTS_PATH", "inputs/dividends.csv")
    monkeypatch.setenv("QS_OPTIONS_RADAR_OUTPUT_DIR", "tmp/options_scans")
    monkeypatch.setenv("QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED", "true")

    settings = Settings()

    assert settings.options_radar.provider == "sample"
    assert settings.options_radar.universe_top_n == 25
    assert settings.options_radar.max_delta_for_radar == 0.42
    assert settings.options_radar.curated_universe_path == Path("inputs/wheel.csv")
    assert settings.options_radar.risk_free_rate == 0.041
    assert settings.options_radar.equity_risk_premium == 0.05
    assert settings.options_radar.dividend_events_path == Path("inputs/dividends.csv")
    assert settings.options_radar.output_dir == Path("tmp/options_scans")
    assert "startup_catchup_enabled" not in settings.options_radar.model_dump()


def test_options_radar_cli_screening_thresholds() -> None:
    settings = Settings()

    config = build_cli_radar_screen_config(settings)
    assert config.min_dte == 5
    assert config.max_dte == 60
    assert config.max_delta == 0.35
    assert config.min_premium == 0.05
    assert config.min_mid_price == 0.05
    assert config.max_spread_pct == 0.05
    assert config.min_open_interest == 100
    assert config.trend_filter is False
    assert config.min_avg_daily_volume == 0
