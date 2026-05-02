from pydantic import SecretStr

from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider


def _settings(
    *,
    default_provider: str = "sample",
    token: str | None = None,
    futu_enabled: bool = True,
) -> Settings:
    return Settings(
        data=DataSettings(default_data_provider=default_provider),
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr(token) if token else None),
        futu=FutuSettings(enabled=futu_enabled),
    )


def test_build_provider_uses_futu_when_requested() -> None:
    provider, source = build_ohlcv_provider(_settings(default_provider="sample"), requested="futu")

    assert isinstance(provider, FutuMarketDataProvider)
    assert source == "futu"


def test_build_provider_falls_back_when_futu_disabled() -> None:
    provider, source = build_ohlcv_provider(
        _settings(default_provider="futu", futu_enabled=False)
    )

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample (futu: disabled)"


def test_build_provider_uses_tiingo_when_token_is_present() -> None:
    provider, source = build_ohlcv_provider(
        _settings(default_provider="tiingo", token="test-token")
    )

    assert isinstance(provider, TiingoEODProvider)
    assert source == "tiingo"


def test_build_provider_falls_back_when_tiingo_token_missing() -> None:
    provider, source = build_ohlcv_provider(_settings(default_provider="tiingo"))

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample (tiingo: missing token)"


def test_build_provider_respects_explicit_sample_request() -> None:
    provider, source = build_ohlcv_provider(
        _settings(default_provider="tiingo", token="test-token"),
        requested="sample",
    )

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample"


def test_build_provider_uses_default_sample() -> None:
    provider, source = build_ohlcv_provider(_settings(default_provider="sample"))

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample"
