import pytest

from quant_system.config.settings import PredictionMarketSettings


def test_prediction_market_settings_accept_safe_env_alias(monkeypatch) -> None:
    monkeypatch.setenv("QS_PREDICTION_MARKET_PROVIDER", "polymarket")
    monkeypatch.setenv("QS_POLYMARKET_REQUEST_TIMEOUT_SECONDS", "5")

    settings = PredictionMarketSettings()

    assert settings.provider == "polymarket"
    assert settings.polymarket_request_timeout_seconds == 5


def test_prediction_market_settings_require_read_only(monkeypatch) -> None:
    monkeypatch.setenv("QS_POLYMARKET_READ_ONLY", "false")

    with pytest.raises(ValueError, match="read_only"):
        PredictionMarketSettings()


def test_prediction_market_phase12_settings_accept_history_and_backtest_defaults(
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_PREDICTION_MARKET_HISTORY_DIR", "data/pm_history")
    monkeypatch.setenv("QS_PREDICTION_MARKET_COLLECTOR_DEFAULT_INTERVAL_SECONDS", "45")
    monkeypatch.setenv("QS_PREDICTION_MARKET_BACKTEST_DEFAULT_FEE_BPS", "7.5")

    settings = PredictionMarketSettings()

    assert str(settings.history_dir).endswith("data\\pm_history") or str(
        settings.history_dir
    ).endswith("data/pm_history")
    assert settings.collector_default_interval_seconds == 45
    assert settings.backtest_default_fee_bps == 7.5
