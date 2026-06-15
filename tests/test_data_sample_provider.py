import pytest

from quant_system.data.providers.sample import SampleOHLCVProvider


def test_sample_provider_rejects_intraday_interval() -> None:
    provider = SampleOHLCVProvider()

    with pytest.raises(ValueError, match="sample provider only supports daily"):
        provider.fetch_ohlcv(
            ["SPY"],
            start="2024-01-02",
            end="2024-01-05",
            interval="1h",
        )
