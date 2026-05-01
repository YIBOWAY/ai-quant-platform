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
