from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from pydantic import SecretStr

from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.execution.price_source import PaperPriceSource, PriceUnavailableError


def _settings(
    tmp_path: Path,
    *,
    futu_enabled: bool = False,
    tiingo_token: str | None = None,
) -> Settings:
    return Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=tmp_path / "parquet",
            duckdb_path=tmp_path / "quant_system.duckdb",
            reports_dir=tmp_path / "reports",
        ),
        futu=FutuSettings(enabled=futu_enabled),
        api_keys=ApiKeySettings(
            tiingo_api_token=SecretStr(tiingo_token) if tiingo_token else None
        ),
    )


def _write_local_ohlcv(settings: Settings, rows: list[dict[str, object]]) -> None:
    settings.data.parquet_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(settings.data.parquet_dir / "ohlcv.parquet")


def test_price_source_prefers_futu_snapshot_over_local_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, futu_enabled=True)
    _write_local_ohlcv(
        settings,
        [
            {
                "symbol": "AAPL",
                "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1),
                "close": 123.0,
                "provider": "tiingo",
            }
        ],
    )
    captured: dict[str, list[str]] = {}

    def fake_fetch_market_snapshots(self, symbols: list[str]) -> pd.DataFrame:
        captured["symbols"] = symbols
        return pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL",
                    "last": 250.5,
                    "update_time": "2026-06-15 09:30:00",
                }
            ]
        )

    def fail_tiingo_fallback(*_args, **_kwargs):
        raise AssertionError("Tiingo fallback should not run after a Futu snapshot")

    monkeypatch.setattr(
        "quant_system.data.providers.futu.FutuMarketDataProvider.fetch_market_snapshots",
        fake_fetch_market_snapshots,
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.build_ohlcv_provider",
        fail_tiingo_fallback,
    )

    quote = PaperPriceSource(settings).get_price("aapl")

    assert captured == {"symbols": ["US.AAPL"]}
    assert quote.symbol == "AAPL"
    assert quote.price == 250.5
    assert quote.price_kind == "futu_snapshot"
    assert quote.source == "futu"


def test_price_source_uses_recent_real_local_close_and_ignores_sample_and_stale(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False)
    now = pd.Timestamp.now(tz="UTC")
    _write_local_ohlcv(
        settings,
        [
            {
                "symbol": "AAPL",
                "timestamp": now - pd.Timedelta(days=1),
                "close": 999.0,
                "provider": "sample",
            },
            {
                "symbol": "AAPL",
                "timestamp": now - pd.Timedelta(days=60),
                "close": 111.0,
                "provider": "tiingo",
            },
            {
                "symbol": "AAPL",
                "timestamp": now - pd.Timedelta(days=2),
                "close": 222.0,
                "provider": "tiingo",
            },
        ],
    )

    quote = PaperPriceSource(settings).get_price("AAPL", lookback_days=5)

    assert quote.price == 222.0
    assert quote.price_kind == "last_close"
    assert quote.source == "local:tiingo"


def test_price_source_uses_real_local_historical_range_and_ignores_sample(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False)
    _write_local_ohlcv(
        settings,
        [
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-03T00:00:00Z",
                "low": 1.0,
                "high": 999.0,
                "close": 500.0,
                "provider": "sample",
            },
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-03T00:00:00Z",
                "low": 145.0,
                "high": 160.0,
                "close": 155.0,
                "provider": "tiingo",
            },
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-04T00:00:00Z",
                "low": 150.0,
                "high": 170.0,
                "close": 165.0,
                "provider": "tiingo",
            },
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-05T00:00:00Z",
                "low": 120.0,
                "high": 180.0,
                "close": 175.0,
                "provider": "tiingo",
            },
            {
                "symbol": "MSFT",
                "timestamp": "2024-01-04T00:00:00Z",
                "low": 10.0,
                "high": 20.0,
                "close": 15.0,
                "provider": "tiingo",
            },
        ],
    )

    price_range = PaperPriceSource(settings).get_price_range(
        "aapl",
        start="2024-01-03",
        end="2024-01-04",
    )

    assert price_range.symbol == "AAPL"
    assert price_range.low == pytest.approx(145.0)
    assert price_range.high == pytest.approx(170.0)
    assert price_range.close == pytest.approx(165.0)
    assert price_range.price_kind == "historical_range"
    assert price_range.source == "local:tiingo"


def test_price_source_rejects_sample_only_historical_range(tmp_path: Path) -> None:
    settings = _settings(tmp_path, futu_enabled=False)
    _write_local_ohlcv(
        settings,
        [
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-03T00:00:00Z",
                "low": 1.0,
                "high": 999.0,
                "close": 500.0,
                "provider": "sample",
            }
        ],
    )

    with pytest.raises(
        PriceUnavailableError,
        match="no historical price range available for AAPL",
    ):
        PaperPriceSource(settings).get_price_range(
            "AAPL",
            start="2024-01-03",
            end="2024-01-04",
        )


def test_price_source_rejects_sample_only_and_stale_local_prices(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False)
    now = pd.Timestamp.now(tz="UTC")
    _write_local_ohlcv(
        settings,
        [
            {
                "symbol": "AAPL",
                "timestamp": now - pd.Timedelta(days=1),
                "close": 999.0,
                "provider": "sample",
            },
            {
                "symbol": "AAPL",
                "timestamp": now - pd.Timedelta(days=60),
                "close": 111.0,
                "provider": "tiingo",
            },
        ],
    )

    with pytest.raises(PriceUnavailableError, match="no price available for AAPL"):
        PaperPriceSource(settings).get_price("AAPL", lookback_days=5)


def test_price_source_uses_tiingo_fallback_when_local_cache_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False, tiingo_token="token")
    calls: list[dict[str, object]] = []

    class FakeTiingoProvider:
        def fetch_ohlcv(
            self,
            symbols: list[str],
            *,
            start: str,
            end: str,
            interval: str = "1d",
        ) -> pd.DataFrame:
            calls.append(
                {
                    "symbols": symbols,
                    "start": start,
                    "end": end,
                    "interval": interval,
                }
            )
            return pd.DataFrame(
                [
                    {
                        "symbol": "AAPL",
                        "timestamp": "2026-06-14T00:00:00Z",
                        "close": 321.0,
                    }
                ]
            )

    monkeypatch.setattr(
        "quant_system.execution.price_source.build_ohlcv_provider",
        lambda settings, requested: (FakeTiingoProvider(), requested),
    )

    quote = PaperPriceSource(settings).get_price("AAPL", lookback_days=7)

    assert calls and calls[0]["symbols"] == ["AAPL"]
    assert quote.price == 321.0
    assert quote.price_kind == "last_close"
    assert quote.source == "tiingo"


def test_price_source_uses_tiingo_historical_range_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False, tiingo_token="token")
    calls: list[dict[str, object]] = []

    class FakeTiingoProvider:
        def fetch_ohlcv(
            self,
            symbols: list[str],
            *,
            start: str,
            end: str,
            interval: str = "1d",
        ) -> pd.DataFrame:
            calls.append(
                {
                    "symbols": symbols,
                    "start": start,
                    "end": end,
                    "interval": interval,
                }
            )
            return pd.DataFrame(
                [
                    {
                        "symbol": "AAPL",
                        "timestamp": "2024-01-03T00:00:00Z",
                        "low": 141.0,
                        "high": 160.0,
                        "close": 155.0,
                    },
                    {
                        "symbol": "AAPL",
                        "timestamp": "2024-01-04T00:00:00Z",
                        "low": 150.0,
                        "high": 171.0,
                        "close": 166.0,
                    },
                ]
            )

    monkeypatch.setattr(
        "quant_system.execution.price_source.build_ohlcv_provider",
        lambda settings, requested: (FakeTiingoProvider(), requested),
    )

    price_range = PaperPriceSource(settings).get_price_range(
        "AAPL",
        start="2024-01-03",
        end="2024-01-04",
    )

    assert calls == [
        {
            "symbols": ["AAPL"],
            "start": "2024-01-03",
            "end": "2024-01-04",
            "interval": "1d",
        }
    ]
    assert price_range.low == pytest.approx(141.0)
    assert price_range.high == pytest.approx(171.0)
    assert price_range.close == pytest.approx(166.0)
    assert price_range.source == "tiingo"


def test_price_source_never_uses_sample_provider_for_tiingo_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, futu_enabled=False, tiingo_token="token")

    class SampleFallbackProvider:
        def fetch_ohlcv(self, *_args, **_kwargs) -> pd.DataFrame:
            raise AssertionError("sample provider must not be queried for account fills")

    monkeypatch.setattr(
        "quant_system.execution.price_source.build_ohlcv_provider",
        lambda settings, requested: (SampleFallbackProvider(), "sample"),
    )

    with pytest.raises(PriceUnavailableError, match="no price available for AAPL"):
        PaperPriceSource(settings).get_price("AAPL")
