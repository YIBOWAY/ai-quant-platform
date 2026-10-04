import pandas as pd
import pytest
from pydantic import SecretStr

from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.data.provider_factory import (
    CachedOHLCVProvider,
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.longbridge import LongbridgeMarketDataProvider
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider
from quant_system.data.storage import LocalDataStorage


def _settings(
    *,
    default_provider: str = "sample",
    token: str | None = None,
    futu_enabled: bool = True,
    data_dir=None,
) -> Settings:
    return Settings(
        data=DataSettings(
            default_data_provider=default_provider,
            data_dir=data_dir or DataSettings().data_dir,
            parquet_dir=(data_dir / "parquet") if data_dir else DataSettings().parquet_dir,
            duckdb_path=(
                data_dir / "quant_system.duckdb" if data_dir else DataSettings().duckdb_path
            ),
            reports_dir=(data_dir / "reports") if data_dir else DataSettings().reports_dir,
        ),
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr(token) if token else None),
        futu=FutuSettings(enabled=futu_enabled),
    )


def test_build_provider_uses_futu_when_requested() -> None:
    provider, source = build_ohlcv_provider(_settings(default_provider="sample"), requested="futu")

    assert isinstance(provider, FutuMarketDataProvider)
    assert source == "futu"


def test_build_provider_supports_explicit_longbridge_without_changing_default() -> None:
    settings = _settings(default_provider="futu")
    provider, source = build_ohlcv_provider(settings, requested="longbridge")
    assert isinstance(provider, LongbridgeMarketDataProvider)
    assert source == "longbridge"
    primary, source = build_ohlcv_provider(settings)
    assert isinstance(primary, FutuMarketDataProvider)
    assert source == "futu"


def test_build_provider_rejects_default_futu_when_disabled() -> None:
    with pytest.raises(DataProviderUnavailableError, match="futu provider unavailable: disabled"):
        build_ohlcv_provider(_settings(default_provider="futu", futu_enabled=False))


def test_build_provider_uses_tiingo_when_token_is_present() -> None:
    provider, source = build_ohlcv_provider(
        _settings(default_provider="tiingo", token="test-token")
    )

    assert isinstance(provider, CachedOHLCVProvider)
    assert isinstance(provider.upstream, TiingoEODProvider)
    assert source == "tiingo"


def test_build_provider_wraps_tiingo_with_read_through_cache(tmp_path) -> None:
    settings = _settings(
        default_provider="tiingo",
        token="test-token",
        data_dir=tmp_path,
    )
    provider, source = build_ohlcv_provider(settings)

    assert isinstance(provider, CachedOHLCVProvider)
    assert source == "tiingo"


def test_cached_provider_reuses_complete_local_ohlcv_window(tmp_path) -> None:
    class CountingProvider:
        provider_name = "tiingo"

        def __init__(self) -> None:
            self.calls = 0
            self.delegate = SampleOHLCVProvider()

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            self.calls += 1
            frame = self.delegate.fetch_ohlcv(
                symbols,
                start=start,
                end=end,
                interval=interval,
            )
            frame["provider"] = self.provider_name
            frame["price_adjustment"] = "adjusted"
            return frame

    upstream = CountingProvider()
    provider = CachedOHLCVProvider(
        upstream=upstream,
        storage=LocalDataStorage(base_dir=tmp_path),
    )

    first = provider.fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")
    second = provider.fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")

    assert upstream.calls == 1
    assert len(second) == len(first)


@pytest.mark.parametrize("legacy_adjustment", [None, "split_adjusted"])
def test_cached_provider_refetches_legacy_tiingo_cache_without_valid_adjustment_label(
    tmp_path,
    legacy_adjustment,
) -> None:
    class CountingProvider:
        provider_name = "tiingo"

        def __init__(self) -> None:
            self.calls = 0
            self.delegate = SampleOHLCVProvider()

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            self.calls += 1
            frame = self.delegate.fetch_ohlcv(
                symbols,
                start=start,
                end=end,
                interval=interval,
            )
            frame["provider"] = self.provider_name
            frame["price_adjustment"] = "adjusted"
            return frame

    storage = LocalDataStorage(base_dir=tmp_path)
    legacy_cached = SampleOHLCVProvider().fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")
    legacy_cached["provider"] = "tiingo"
    if legacy_adjustment is not None:
        legacy_cached["price_adjustment"] = legacy_adjustment
    storage.save_ohlcv(legacy_cached)

    upstream = CountingProvider()
    provider = CachedOHLCVProvider(upstream=upstream, storage=storage)

    frame = provider.fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")

    assert upstream.calls == 1
    assert set(frame["price_adjustment"]) == {"adjusted"}


def test_cached_provider_fetches_when_any_symbol_window_is_incomplete(tmp_path) -> None:
    class CountingProvider:
        provider_name = "tiingo"

        def __init__(self) -> None:
            self.calls = 0
            self.delegate = SampleOHLCVProvider()

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            self.calls += 1
            frame = self.delegate.fetch_ohlcv(
                symbols,
                start=start,
                end=end,
                interval=interval,
            )
            frame["provider"] = self.provider_name
            return frame

    storage = LocalDataStorage(base_dir=tmp_path)
    cached_spy = SampleOHLCVProvider().fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")
    cached_qqq = SampleOHLCVProvider().fetch_ohlcv(["QQQ"], start="2024-01-03", end="2024-01-04")
    cached = pd.concat([cached_spy, cached_qqq], ignore_index=True)
    cached["provider"] = "tiingo"
    storage.save_ohlcv(cached)

    upstream = CountingProvider()
    provider = CachedOHLCVProvider(upstream=upstream, storage=storage)

    frame = provider.fetch_ohlcv(["SPY", "QQQ"], start="2024-01-02", end="2024-01-05")

    assert upstream.calls == 1
    assert frame[frame["symbol"] == "QQQ"]["timestamp"].min() == pd.Timestamp(
        "2024-01-02", tz="UTC"
    )
    assert frame[frame["symbol"] == "QQQ"]["timestamp"].max() == pd.Timestamp(
        "2024-01-05", tz="UTC"
    )


def test_build_provider_rejects_default_tiingo_when_token_missing() -> None:
    with pytest.raises(
        DataProviderUnavailableError, match="tiingo provider unavailable: missing token"
    ):
        build_ohlcv_provider(_settings(default_provider="tiingo"))


@pytest.mark.parametrize("missing_field", ["provider", "interval"])
def test_cached_provider_does_not_use_unattributed_cache_when_real_source_fails(
    tmp_path,
    missing_field,
) -> None:
    cached = SampleOHLCVProvider().fetch_ohlcv(
        ["SPY"],
        start="2024-01-02",
        end="2024-01-05",
    )
    cached["provider"] = "tiingo"
    cached["price_adjustment"] = "adjusted"
    cached = cached.drop(columns=[missing_field])
    storage = LocalDataStorage(base_dir=tmp_path)
    storage.parquet_path.parent.mkdir(parents=True)
    cached.to_parquet(storage.parquet_path, index=False)

    class UnavailableProvider:
        provider_name = "tiingo"

        def fetch_ohlcv(self, *_args, **_kwargs):
            raise RuntimeError("real data unavailable")

    provider = CachedOHLCVProvider(upstream=UnavailableProvider(), storage=storage)
    with pytest.raises(RuntimeError, match="real data unavailable"):
        provider.fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-05")


def test_build_provider_rejects_explicit_tiingo_when_token_missing() -> None:
    with pytest.raises(DataProviderUnavailableError) as exc_info:
        build_ohlcv_provider(_settings(default_provider="sample"), requested="tiingo")

    assert exc_info.value.provider == "tiingo"


def test_build_provider_respects_explicit_sample_request() -> None:
    provider, source = build_ohlcv_provider(
        _settings(default_provider="tiingo", token="test-token"),
        requested="sample",
    )

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample"


def test_build_provider_rejects_unknown_explicit_provider() -> None:
    with pytest.raises(DataProviderUnavailableError) as exc_info:
        build_ohlcv_provider(_settings(default_provider="sample"), requested="polygon")

    assert exc_info.value.provider == "polygon"
    assert exc_info.value.reason == "unsupported provider"


def test_build_provider_uses_default_sample() -> None:
    provider, source = build_ohlcv_provider(_settings(default_provider="sample"))

    assert isinstance(provider, SampleOHLCVProvider)
    assert source == "sample"
