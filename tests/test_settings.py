from pydantic import ValidationError

from quant_system.config.settings import (
    SafetySettings,
    Settings,
    load_settings,
    reload_settings,
)


def test_safety_settings_default_to_paper_and_dry_run() -> None:
    settings = SafetySettings()

    assert settings.dry_run is True
    assert settings.paper_trading is True
    assert settings.live_trading_enabled is False
    assert settings.no_live_trade_without_manual_approval is True
    assert settings.kill_switch is True


def test_safety_settings_have_conservative_risk_limits() -> None:
    settings = SafetySettings()

    assert settings.max_position_size == 0.05
    assert settings.max_daily_loss == 0.02
    assert settings.max_drawdown == 0.10
    assert settings.max_order_value == 10_000
    assert settings.max_turnover == 1.0
    assert settings.allowed_symbols == []
    assert settings.blocked_symbols == []


def test_live_trading_requires_manual_confirmation_phrase() -> None:
    try:
        SafetySettings(live_trading_enabled=True)
    except ValidationError as exc:
        assert "manual_live_trading_confirmation" in str(exc)
    else:
        raise AssertionError("live trading should require an explicit confirmation phrase")


def test_live_trading_guard_accepts_exact_confirmation_phrase() -> None:
    settings = SafetySettings(
        live_trading_enabled=True,
        manual_live_trading_confirmation="I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING",
    )

    assert settings.live_trading_enabled is True
    assert settings.dry_run is True


def test_load_settings_returns_nested_settings() -> None:
    settings = load_settings()

    assert isinstance(settings, Settings)
    assert isinstance(settings.safety, SafetySettings)
    assert settings.app_name == "AI Quant Research Platform"


def test_reload_settings_clears_the_cache() -> None:
    first = load_settings()
    second = reload_settings()

    assert isinstance(second, Settings)
    assert first is not second

