from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import HistoricalPriceSnapshot
from quant_system.data.providers.futu import FutuProviderError
from quant_system.factors.asia_radar import (
    ASIA_ETF_SYMBOLS,
    DRIVER_BASKET_PENDING,
    DRIVER_BASKET_SPECS,
    _DriverLaneError,
    _polygon_grouped_daily,
    attach_driver_basket_overlays,
    build_asia_radar_overview,
    read_asia_radar_overview,
    read_asia_radar_summary,
    read_driver_basket_overlays,
)

_NOW = datetime(2026, 8, 12, 2, 0, tzinfo=UTC)  # Wed; US/HK sessions of 08-11 closed
_ADR_SYMBOLS = ["TM", "SONY", "MUFG", "HMC", "TSM", "UMC"]
_HK_SYMBOLS = ["HK.00700", "HK.09988", "HK.00005"]


class _LocalMarketProvider:
    """Fake Futu provider exposing the opt-in local-market fetch lane."""

    provider_name = "futu"

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.frames = frames
        self.failures = failures or {}
        self.calls: list[str] = []

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        raise AssertionError("driver lane must not use the US-only fetch_ohlcv")

    def fetch_local_market_ohlcv(self, symbols, *, start, end, interval="1d"):
        symbol = symbols[0]
        self.calls.append(symbol)
        if symbol in self.failures:
            raise self.failures[symbol]
        return self.frames[symbol].copy()


class _PolygonFetcher:
    """Fake Polygon grouped-daily fetcher (one call per session date)."""

    def __init__(
        self,
        bars_by_date: dict[str, list[dict]],
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.bars_by_date = bars_by_date
        self.failures = failures or {}
        self.calls: list[dict[str, object]] = []

    def __call__(self, session_date, symbols, *, api_key):
        self.calls.append({"date": session_date, "symbols": list(symbols)})
        if session_date in self.failures:
            raise self.failures[session_date]
        return [dict(bar) for bar in self.bars_by_date.get(session_date, [])]


def _hk_frame(symbol: str, *, periods: int = 100, end: str = "2026-08-11") -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=periods)
    rows = []
    for index, day in enumerate(dates):
        close = 300.0 + index * 1.5
        rows.append(
            {
                "symbol": symbol,
                "timestamp": day.tz_localize("UTC"),
                "open": close - 1.0,
                "high": close + 1.0,
                "low": close - 2.0,
                "close": close,
                "volume": 0.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "event_ts": day.tz_localize("UTC"),
                "knowledge_ts": pd.Timestamp("2026-08-11T09:00:00Z"),
            }
        )
    return pd.DataFrame(rows)


def _adr_bars_by_date(*, periods: int = 100, end: str = "2026-08-11") -> dict[str, list[dict]]:
    dates = pd.bdate_range(end=end, periods=periods)
    bars: dict[str, list[dict]] = {}
    for index, day in enumerate(dates):
        iso = day.date().isoformat()
        bars[iso] = [
            {
                "symbol": symbol,
                "date": iso,
                "open": 99.0 + index + offset,
                "high": 101.0 + index + offset,
                "low": 98.0 + index + offset,
                "close": 100.0 + index + offset,
                "volume": 1_000_000.0,
            }
            for offset, symbol in enumerate(_ADR_SYMBOLS)
        ]
    return bars


def _hk_provider(**overrides) -> _LocalMarketProvider:
    frames = {symbol: _hk_frame(symbol) for symbol in _HK_SYMBOLS}
    frames.update(overrides)
    return _LocalMarketProvider(frames)


def _builder(provider):
    def builder(settings, *, requested):
        assert requested == "futu"
        return provider, "futu"

    return builder


def _settings_with_key() -> SimpleNamespace:
    return SimpleNamespace(
        api_keys=SimpleNamespace(polygon_api_key="unit-test-polygon-key")
    )


def _read_baskets(provider, fetcher, **overrides):
    kwargs = {
        "settings": _settings_with_key(),
        "now": _NOW,
        "cache": None,
        "provider_builder": _builder(provider),
        "polygon_fetcher": fetcher,
        "polygon_max_calls": 400,
        "polygon_attempted_dates": set(),
    }
    kwargs.update(overrides)
    return read_driver_basket_overlays(**kwargs)


def _etf_snapshot(*, start: str = "2025-12-31", periods: int = 64) -> HistoricalPriceSnapshot:
    dates = pd.bdate_range(start, periods=periods)
    series = []
    for offset, symbol in enumerate(ASIA_ETF_SYMBOLS):
        rows = [
            {
                "date": day.date().isoformat(),
                "close": round(100.0 + offset + index * 0.1, 6),
            }
            for index, day in enumerate(dates)
        ]
        series.append(
            {
                "symbol": symbol,
                "row_count": len(rows),
                "first_date": rows[0]["date"],
                "last_date": rows[-1]["date"],
                "rows": rows,
            }
        )
    return HistoricalPriceSnapshot(
        provider="futu",
        source="futu",
        interval="1d",
        adjustment="qfq",
        start=dates[0].date().isoformat(),
        end=dates[-1].date().isoformat(),
        fetched_at=datetime(2026, 3, 30, 20, 0, tzinfo=UTC).isoformat(),
        symbols=list(ASIA_ETF_SYMBOLS),
        series=series,
    )


def _available_basket_overlay() -> dict:
    return {
        "status": "available",
        "label_en": "DRIVER BASKET — not an index substitute",
        "label_zh": "龙头篮子——非指数替代",
        "basket_note": "unweighted display; no point-in-time index weights",
        "leaders": [
            {
                "status": "available",
                "symbol": "TSM",
                "name_en": "TSMC (ADR)",
                "name_zh": "台积电 (ADR)",
                "listing": "us_adr",
                "currency": "USD",
                "timezone": "America/New_York",
                "provider": "polygon",
                "provenance": "polygon",
                "fetched_at": "2026-03-30T20:00:00+00:00",
                "adjustment": "adjusted",
                "as_of": "2026-03-30",
                "series": [
                    {"date": "2026-03-30", "close": 1.0, "indexed_return_pct": 0.0}
                ],
                "reason_code": None,
                "reason": None,
                "provider_code": None,
            }
        ],
        "reason_code": None,
        "reason": None,
        "provider_code": None,
    }


def test_driver_specs_cover_only_verified_markets_and_lanes() -> None:
    assert set(DRIVER_BASKET_SPECS) == {"hong-kong", "japan", "taiwan"}
    for spec in DRIVER_BASKET_SPECS["hong-kong"]:
        assert spec.provider == "futu"
        assert spec.listing == "hk_local"
        assert spec.symbol.startswith("HK.")
    for market_id in ("japan", "taiwan"):
        for spec in DRIVER_BASKET_SPECS[market_id]:
            assert spec.provider == "polygon"
            assert spec.listing == "us_adr"
            assert spec.currency == "USD"
            assert spec.timezone == "America/New_York"
    assert set(DRIVER_BASKET_PENDING) == {
        "south-korea",
        "china-a",
        "india",
        "indonesia",
        "singapore",
        "thailand",
        "malaysia",
        "australia",
        "philippines",
    }


def test_overlays_available_for_hk_and_adr_leaders() -> None:
    provider = _hk_provider()
    fetcher = _PolygonFetcher(_adr_bars_by_date())

    overlays = _read_baskets(provider, fetcher)

    hong_kong = overlays["hong-kong"]
    assert hong_kong["status"] == "available"
    assert hong_kong["label_zh"] == "龙头篮子——非指数替代"
    assert "unweighted" in hong_kong["basket_note"]
    assert len(hong_kong["leaders"]) == 3
    tencent = hong_kong["leaders"][0]
    assert tencent["status"] == "available"
    assert tencent["symbol"] == "HK.00700"
    assert tencent["listing"] == "hk_local"
    assert tencent["currency"] == "HKD"
    assert tencent["timezone"] == "Asia/Hong_Kong"
    assert tencent["provider"] == "futu"
    assert tencent["provenance"] == "futu"
    assert tencent["adjustment"] == "qfq"
    assert tencent["as_of"] == "2026-08-11"
    assert len(tencent["series"]) == 90
    assert tencent["series"][0]["indexed_return_pct"] == 0.0
    last = tencent["series"][-1]
    first = tencent["series"][0]
    assert last["indexed_return_pct"] == round(
        (last["close"] / first["close"] - 1.0) * 100.0, 4
    )

    japan = overlays["japan"]
    assert japan["status"] == "available"
    assert [leader["symbol"] for leader in japan["leaders"]] == [
        "TM",
        "SONY",
        "MUFG",
        "HMC",
    ]
    toyota = japan["leaders"][0]
    assert toyota["listing"] == "us_adr"
    assert toyota["currency"] == "USD"
    assert toyota["timezone"] == "America/New_York"
    assert toyota["provider"] == "polygon"
    assert toyota["provenance"] == "polygon"
    assert toyota["adjustment"] == "adjusted"
    assert toyota["as_of"] == "2026-08-11"
    assert len(toyota["series"]) == 90

    taiwan = overlays["taiwan"]
    assert taiwan["status"] == "available"
    assert [leader["symbol"] for leader in taiwan["leaders"]] == ["TSM", "UMC"]

    # One grouped-daily call covers every ADR leader for a session, and the
    # API key is never exposed in any payload field.
    assert fetcher.calls
    assert {frozenset(call["symbols"]) for call in fetcher.calls} == {
        frozenset(_ADR_SYMBOLS)
    }
    assert "unit-test-polygon-key" not in json.dumps(overlays)


def test_pending_reasons_for_markets_without_verified_channel() -> None:
    overlays = _read_baskets(_hk_provider(), _PolygonFetcher(_adr_bars_by_date()))

    assert set(overlays) == {
        "south-korea",
        "taiwan",
        "japan",
        "china-a",
        "india",
        "indonesia",
        "hong-kong",
        "singapore",
        "thailand",
        "malaysia",
        "australia",
        "philippines",
    }
    korea = overlays["south-korea"]
    assert korea["status"] == "unavailable"
    assert korea["reason_code"] == "no_liquid_us_listing"
    assert "Samsung" in korea["reason"]
    assert korea["leaders"] == []
    assert overlays["china-a"]["reason_code"] == "permission_not_granted"
    for market_id in (
        "india",
        "indonesia",
        "singapore",
        "thailand",
        "malaysia",
        "australia",
        "philippines",
    ):
        overlay = overlays[market_id]
        assert overlay["status"] == "unavailable"
        assert overlay["reason_code"] == "no_verified_channel"
        assert overlay["leaders"] == []


def test_missing_polygon_key_degrades_only_adr_markets() -> None:
    overlays = _read_baskets(
        _hk_provider(),
        _PolygonFetcher(_adr_bars_by_date()),
        settings=SimpleNamespace(),  # no api_keys at all
    )

    for market_id in ("japan", "taiwan"):
        basket = overlays[market_id]
        assert basket["status"] == "unavailable"
        assert basket["reason_code"] == "provider_error"
        for leader in basket["leaders"]:
            assert leader["status"] == "unavailable"
            assert leader["reason_code"] == "provider_error"
            assert leader["provider_code"] == "missing_api_key"
            assert leader["series"] == []
            # The failed leader still names itself honestly.
            assert leader["provider"] == "polygon"
    assert overlays["hong-kong"]["status"] == "available"


def test_polygon_payload_error_is_contained_per_market() -> None:
    failure = _DriverLaneError(
        "polygon_error",
        "Polygon grouped-daily returned an error payload: Unknown API Key",
    )
    fetcher = _PolygonFetcher(_adr_bars_by_date(), failures={"2026-08-11": failure})

    overlays = _read_baskets(_hk_provider(), fetcher)

    for market_id in ("japan", "taiwan"):
        basket = overlays[market_id]
        assert basket["status"] == "unavailable"
        for leader in basket["leaders"]:
            assert leader["provider_code"] == "polygon_error"
            assert "error payload" in leader["reason"]
    assert overlays["hong-kong"]["status"] == "available"
    # The lane stops at the first failure instead of burning the call budget.
    assert len(fetcher.calls) == 1


def test_cold_start_accumulates_then_serves_cache(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    fetcher = _PolygonFetcher(_adr_bars_by_date(periods=25))
    attempted: set[str] = set()
    kwargs = {
        "settings": _settings_with_key(),
        "now": _NOW,
        "cache": cache,
        "provider_builder": _builder(_hk_provider()),
        "polygon_fetcher": fetcher,
        "polygon_max_calls": 5,
        "polygon_attempted_dates": attempted,
    }

    first = read_driver_basket_overlays(**kwargs)
    tsm = first["taiwan"]["leaders"][0]
    assert tsm["status"] == "unavailable"
    assert tsm["provider_code"] == "insufficient_history"
    assert "5 Polygon grouped-daily sessions" in tsm["reason"]
    assert len(fetcher.calls) == 5

    read_driver_basket_overlays(**kwargs)
    read_driver_basket_overlays(**kwargs)
    fourth = read_driver_basket_overlays(**kwargs)
    tsm = fourth["taiwan"]["leaders"][0]
    assert tsm["status"] == "available"
    assert tsm["provenance"] == "polygon"
    assert len(tsm["series"]) == 20
    assert tsm["as_of"] == "2026-08-11"
    assert len(fetcher.calls) == 20

    # Warm lane (>= min bars): no backfill rescan and no newer sessions to
    # top up, so this read is served entirely from accumulated bars.
    fifth = read_driver_basket_overlays(**kwargs)
    tsm = fifth["taiwan"]["leaders"][0]
    assert tsm["status"] == "available"
    assert tsm["provenance"] == "polygon_cache"
    assert len(fetcher.calls) == 20


def test_warm_lane_marks_holidays_and_never_refetches(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    # 20 sessions ending 2026-08-10; 2026-08-11 behaves as a holiday (empty).
    fetcher = _PolygonFetcher(_adr_bars_by_date(periods=20, end="2026-08-10"))
    attempted: set[str] = set()
    kwargs = {
        "settings": _settings_with_key(),
        "now": _NOW,
        "cache": cache,
        "provider_builder": _builder(_hk_provider()),
        "polygon_fetcher": fetcher,
        "polygon_max_calls": 21,
        "polygon_attempted_dates": attempted,
    }

    first = read_driver_basket_overlays(**kwargs)
    tsm = first["taiwan"]["leaders"][0]
    assert tsm["status"] == "available"
    assert tsm["as_of"] == "2026-08-10"  # last real session, honestly reported
    assert len(fetcher.calls) == 21  # 20 sessions + 1 holiday probe
    assert "2026-08-11" in attempted

    calls_after_first = len(fetcher.calls)
    second = read_driver_basket_overlays(**kwargs)
    assert second["taiwan"]["leaders"][0]["status"] == "available"
    assert len(fetcher.calls) == calls_after_first  # holiday not re-fetched


def test_polygon_bars_never_mix_with_futu_cache_keys(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    fetcher = _PolygonFetcher(_adr_bars_by_date(periods=25))
    read_driver_basket_overlays(
        settings=_settings_with_key(),
        now=_NOW,
        cache=cache,
        provider_builder=_builder(_hk_provider()),
        polygon_fetcher=fetcher,
        polygon_max_calls=25,
        polygon_attempted_dates=set(),
    )

    # Polygon ADR bars live under provider=polygon/adjustment=adjusted; the
    # Futu ETF/index lane (provider=futu, qfq) can never see them.
    assert (
        cache.read(
            provider="futu",
            symbols=["TSM"],
            interval="1d",
            adjustment="qfq",
            start="2025-06-18",
            end="2026-08-11",
        )
        is None
    )
    assert (
        cache.read_bars(
            provider="futu",
            symbols=["TSM"],
            interval="1d",
            adjustment="adjusted",
            start="2025-06-18",
            end="2026-08-11",
        )
        is None
    )
    polygon_bars = cache.read_bars(
        provider="polygon",
        symbols=["TSM"],
        interval="1d",
        adjustment="adjusted",
        start="2025-06-18",
        end="2026-08-11",
    )
    assert polygon_bars is not None
    assert set(polygon_bars["symbol"]) == {"TSM"}


def test_hk_leader_failure_is_per_leader_and_keeps_basket_honest() -> None:
    provider = _LocalMarketProvider(
        {symbol: _hk_frame(symbol) for symbol in _HK_SYMBOLS},
        failures={
            "HK.00005": FutuProviderError(
                "opend_unavailable", "unable to connect to OpenD at 127.0.0.1:11111"
            )
        },
    )

    overlays = _read_baskets(provider, _PolygonFetcher(_adr_bars_by_date()))

    basket = overlays["hong-kong"]
    assert basket["status"] == "available"  # remaining leaders still serve
    by_symbol = {leader["symbol"]: leader for leader in basket["leaders"]}
    assert by_symbol["HK.00700"]["status"] == "available"
    assert by_symbol["HK.09988"]["status"] == "available"
    hsbc = by_symbol["HK.00005"]
    assert hsbc["status"] == "unavailable"
    assert hsbc["reason_code"] == "provider_error"
    assert hsbc["provider_code"] == "opend_unavailable"
    assert hsbc["series"] == []
    # The failed leader is listed, never silently dropped.
    assert len(basket["leaders"]) == 3


def test_polygon_grouped_daily_payload_level_error_detection() -> None:
    symbols = ["TSM", "UMC"]

    def ok_payload(url):
        return {
            "status": "OK",
            "resultsCount": 3,
            "results": [
                {"T": "TSM", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0},
                {"T": "AAPL", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0},
                {"T": "UMC", "o": 3.0, "h": 4.0, "l": 2.5, "c": 3.5, "v": 20.0},
            ],
        }

    bars = _polygon_grouped_daily("2026-08-11", symbols, api_key="k", get_json=ok_payload)
    assert [bar["symbol"] for bar in bars] == ["TSM", "UMC"]  # AAPL filtered out
    assert bars[0]["close"] == 1.5

    # HTTP 200 with an error status body must raise, never produce bars.
    with pytest.raises(_DriverLaneError) as excinfo:
        _polygon_grouped_daily(
            "2026-08-11",
            symbols,
            api_key="k",
            get_json=lambda url: {"status": "ERROR", "error": "Unknown API Key"},
        )
    assert excinfo.value.provider_code == "polygon_error"
    assert "Unknown API Key" in str(excinfo.value)

    # Malformed rows are contract errors, not silent skips.
    with pytest.raises(_DriverLaneError) as excinfo:
        _polygon_grouped_daily(
            "2026-08-11",
            symbols,
            api_key="k",
            get_json=lambda url: {"status": "OK", "results": [{"T": "TSM", "c": "x"}]},
        )
    assert excinfo.value.provider_code == "polygon_contract_invalid"

    # Holidays answer OK with no results: an empty bar list, not an error.
    assert (
        _polygon_grouped_daily(
            "2026-07-04",
            symbols,
            api_key="k",
            get_json=lambda url: {"status": "OK", "resultsCount": 0},
        )
        == []
    )


def test_attach_sets_schema_13_and_never_touches_etf_metrics() -> None:
    overview = build_asia_radar_overview(_etf_snapshot())
    assert overview["schema_version"] == "1.1"
    serialized_before = json.dumps(overview, sort_keys=True)

    attached = attach_driver_basket_overlays(
        overview,
        {"taiwan": _available_basket_overlay()},
    )

    assert attached["schema_version"] == "1.3"
    assert len(attached["markets"]) == 12
    for market in attached["markets"]:
        assert "driver_basket" in market
    taiwan = next(m for m in attached["markets"] if m["market_id"] == "taiwan")
    assert taiwan["driver_basket"]["status"] == "available"
    # Markets without a loaded overlay get an explicit unavailable state.
    korea = next(m for m in attached["markets"] if m["market_id"] == "south-korea")
    assert korea["driver_basket"]["status"] == "unavailable"
    assert korea["driver_basket"]["reason_code"] == "overlay_missing"
    # Serialization-level invariance: minus driver_basket/schema_version the
    # overview is byte-for-byte the pre-attach payload.
    stripped = deepcopy(attached)
    stripped["schema_version"] = "1.1"
    for market in stripped["markets"]:
        del market["driver_basket"]
    assert json.dumps(stripped, sort_keys=True) == serialized_before


def test_read_overview_never_lets_driver_lane_break_the_etf_main_path(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )

    def exploding_reader(*, settings, now, cache):
        raise RuntimeError("driver lane exploded")

    overview = read_asia_radar_overview(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
        local_index_reader=lambda **_: {},
        driver_basket_reader=exploding_reader,
    )

    assert overview["schema_version"] == "1.3"
    assert overview["as_of"] == "2026-03-30"
    assert [market["symbol"] for market in overview["markets"]] == list(ASIA_ETF_SYMBOLS)
    for market in overview["markets"]:
        assert market["driver_basket"]["status"] == "unavailable"
        assert market["driver_basket"]["reason_code"] == "overlay_missing"
        assert market["driver_basket"]["leaders"] == []


def test_etf_payload_identical_with_driver_lane_on_or_off(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )

    read_kwargs = {
        "settings": SimpleNamespace(),
        "now": datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        "cache": False,
        "local_index_reader": lambda **_: {},
    }
    with_lane = read_asia_radar_overview(
        driver_basket_reader=lambda **_: {"taiwan": _available_basket_overlay()},
        **read_kwargs,
    )
    without_lane = read_asia_radar_overview(
        driver_basket_reader=lambda **_: {},
        **read_kwargs,
    )

    def etf_part(payload):
        clean = deepcopy(payload)
        clean.pop("schema_version")
        for market in clean["markets"]:
            market.pop("local_index")
            market.pop("driver_basket")
        return clean

    assert json.dumps(etf_part(with_lane), sort_keys=True) == json.dumps(
        etf_part(without_lane), sort_keys=True
    )
    taiwan_on = next(m for m in with_lane["markets"] if m["market_id"] == "taiwan")
    taiwan_off = next(m for m in without_lane["markets"] if m["market_id"] == "taiwan")
    assert taiwan_on["driver_basket"]["status"] == "available"
    assert taiwan_off["driver_basket"]["status"] == "unavailable"


def test_summary_path_never_touches_the_driver_lane(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_driver_basket_overlays",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("summary path must not fetch driver basket overlays")
        ),
    )

    summary = read_asia_radar_summary(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
    )
    assert summary["status"] == "available"
    assert summary["market_count"] == 12
    assert "driver_basket" not in json.dumps(summary)
