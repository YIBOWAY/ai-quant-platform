from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, time
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
    read_historical_prices,
)
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.data.providers.futu import FutuProviderError
from quant_system.factors.asia_radar import (
    _MIN_LOCAL_INDEX_BARS,
    ASIA_ETF_SYMBOLS,
    LOCAL_INDEX_PENDING,
    LOCAL_INDEX_SPECS,
    _last_completed_local_session,
    _last_completed_us_session,
    attach_local_index_overlays,
    build_asia_radar_overview,
    read_asia_radar_overview,
    read_asia_radar_summary,
    read_local_index_overlays,
)

_NOW = datetime(2026, 8, 12, 2, 0, tzinfo=UTC)  # Wed; HK 10:00 / TYO 11:00 pre-close
_EXPECTED_INDEX_END = "2026-08-11"  # last completed HK/TYO session before _NOW


class _LocalIndexProvider:
    """Fake Futu provider exposing the opt-in local-market fetch lane."""

    provider_name = "futu"

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.frames = frames
        self.failures = failures or {}
        self.calls: list[dict[str, object]] = []
        self.us_calls: list[dict[str, object]] = []

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.us_calls.append(
            {"symbols": list(symbols), "start": start, "end": end, "interval": interval}
        )
        raise AssertionError("local index lane must not use the US-only fetch_ohlcv")

    def fetch_local_market_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.calls.append(
            {"symbols": list(symbols), "start": start, "end": end, "interval": interval}
        )
        symbol = symbols[0]
        if symbol in self.failures:
            raise self.failures[symbol]
        return self.frames[symbol].copy()


def _index_frame(symbol: str, *, periods: int = 100, end: str = "2026-08-11") -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=periods)
    fetched_at = pd.Timestamp("2026-08-11T09:00:00Z")
    rows = []
    for index, day in enumerate(dates):
        close = 1000.0 + index * 2.5
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
                "knowledge_ts": fetched_at,
            }
        )
    return pd.DataFrame(rows)


def _builder(provider: _LocalIndexProvider):
    def builder(settings, *, requested):
        assert requested == "futu"
        return provider, "futu"

    return builder


def _read_overlays(provider: _LocalIndexProvider, **overrides):
    kwargs = {
        "settings": SimpleNamespace(),
        "now": _NOW,
        "cache": None,
        "provider_builder": _builder(provider),
    }
    kwargs.update(overrides)
    return read_local_index_overlays(**kwargs)


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


def test_local_session_calendar_uses_each_market_close() -> None:
    # Hong Kong 16:00 close.
    assert (
        _last_completed_local_session(
            datetime(2026, 8, 12, 7, 0, tzinfo=UTC), "Asia/Hong_Kong", time(16, 0)
        ).isoformat()
        == "2026-08-11"  # 15:00 HKT, still trading
    )
    assert (
        _last_completed_local_session(
            datetime(2026, 8, 12, 9, 0, tzinfo=UTC), "Asia/Hong_Kong", time(16, 0)
        ).isoformat()
        == "2026-08-12"  # 17:00 HKT, closed
    )
    # Tokyo 15:00 close.
    assert (
        _last_completed_local_session(
            datetime(2026, 8, 12, 5, 30, tzinfo=UTC), "Asia/Tokyo", time(15, 0)
        ).isoformat()
        == "2026-08-11"  # 14:30 JST
    )
    assert (
        _last_completed_local_session(
            datetime(2026, 8, 12, 6, 30, tzinfo=UTC), "Asia/Tokyo", time(15, 0)
        ).isoformat()
        == "2026-08-12"  # 15:30 JST
    )
    # Sunday rolls back to Friday.
    assert (
        _last_completed_local_session(
            datetime(2026, 8, 16, 12, 0, tzinfo=UTC), "Asia/Hong_Kong", time(16, 0)
        ).isoformat()
        == "2026-08-14"
    )
    # The US rule is unchanged and equals the parameterized helper.
    probe = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
    assert _last_completed_us_session(probe) == _last_completed_local_session(
        probe, "America/New_York", time(16, 0)
    )


def test_overlays_available_for_hk_and_jp_with_own_calendar_fields() -> None:
    provider = _LocalIndexProvider(
        {
            "HK.800000": _index_frame("HK.800000"),
            "JP..N225": _index_frame("JP..N225"),
        }
    )

    overlays = _read_overlays(provider)

    hong_kong = overlays["hong-kong"]
    assert hong_kong["status"] == "available"
    assert hong_kong["index_symbol"] == "HK.800000"
    assert hong_kong["index_name_en"] == "Hang Seng Index"
    assert hong_kong["currency"] == "HKD"
    assert hong_kong["timezone"] == "Asia/Hong_Kong"
    assert hong_kong["as_of"] == "2026-08-11"  # index's own last session
    assert hong_kong["provider"] == "futu"
    assert hong_kong["provenance"] == "futu"
    assert hong_kong["fetched_at"] == "2026-08-11T09:00:00+00:00"
    assert hong_kong["reason_code"] is None
    # Display window is trimmed to the latest 90 sessions, self-normalized.
    assert len(hong_kong["series"]) == 90
    first = hong_kong["series"][0]
    last = hong_kong["series"][-1]
    assert first["indexed_return_pct"] == 0.0
    assert last["date"] == "2026-08-11"
    assert last["indexed_return_pct"] == round(
        (last["close"] / first["close"] - 1.0) * 100.0, 4
    )

    japan = overlays["japan"]
    assert japan["status"] == "available"
    assert japan["index_symbol"] == "JP..N225"
    assert japan["currency"] == "JPY"
    assert japan["timezone"] == "Asia/Tokyo"

    # The double-dot code passes through the whole read path unchanged, and
    # the request window ends at the last completed *local* session. Japan's
    # ETF (EWJ) precedes Hong Kong's (EWH) in the universe order.
    assert provider.calls == [
        {
            "symbols": ["JP..N225"],
            "start": "2025-06-18",
            "end": _EXPECTED_INDEX_END,
            "interval": "1d",
        },
        {
            "symbols": ["HK.800000"],
            "start": "2025-06-18",
            "end": _EXPECTED_INDEX_END,
            "interval": "1d",
        },
    ]
    assert provider.us_calls == []


def test_overlays_pending_reasons_for_other_ten_markets() -> None:
    provider = _LocalIndexProvider({})

    overlays = _read_overlays(provider)

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
    assert LOCAL_INDEX_PENDING["china-a"][0] == "permission_not_granted"
    assert overlays["china-a"]["reason_code"] == "permission_not_granted"
    assert overlays["china-a"]["index_name_zh"] == "沪深300"
    for market_id in ("south-korea", "taiwan"):
        assert overlays[market_id]["reason_code"] == "market_format_unsupported"
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
        assert overlay["series"] == []
        assert overlay["as_of"] is None
    # Pending markets never reach the provider; only the two whitelisted
    # index codes are ever requested (they fail here and are contained).
    assert provider.us_calls == []
    assert {call["symbols"][0] for call in provider.calls} <= {
        "HK.800000",
        "JP..N225",
    }


def test_overlay_provider_failure_is_explicit_and_per_market() -> None:
    provider = _LocalIndexProvider(
        {"JP..N225": _index_frame("JP..N225")},
        failures={
            "HK.800000": FutuProviderError(
                "opend_unavailable", "unable to connect to OpenD at 127.0.0.1:11111"
            )
        },
    )

    overlays = _read_overlays(provider)

    hong_kong = overlays["hong-kong"]
    assert hong_kong["status"] == "unavailable"
    assert hong_kong["reason_code"] == "provider_error"
    assert hong_kong["provider_code"] == "opend_unavailable"
    assert "OpenD" in hong_kong["reason"]
    assert hong_kong["series"] == []
    # The failed market still names its index honestly instead of vanishing.
    assert hong_kong["index_symbol"] == "HK.800000"
    assert hong_kong["currency"] == "HKD"
    # The other market is unaffected.
    assert overlays["japan"]["status"] == "available"


def test_overlay_unexpected_exception_is_contained_as_provider_error() -> None:
    provider = _LocalIndexProvider(
        {},
        failures={
            "HK.800000": ValueError("boom"),
            "JP..N225": ValueError("boom"),
        },
    )

    overlays = _read_overlays(provider)

    assert overlays["hong-kong"]["reason_code"] == "provider_error"
    assert overlays["hong-kong"]["provider_code"] == "ValueError"
    assert overlays["japan"]["reason_code"] == "provider_error"


def test_overlay_cache_marks_provenance_and_keys_never_mix_with_us_etfs(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    frames = {
        "HK.800000": _index_frame("HK.800000"),
        "JP..N225": _index_frame("JP..N225"),
    }
    provider = _LocalIndexProvider(frames)

    first = read_local_index_overlays(
        settings=SimpleNamespace(),
        now=_NOW,
        cache=cache,
        provider_builder=_builder(provider),
    )
    assert first["hong-kong"]["provenance"] == "futu"
    assert first["japan"]["provenance"] == "futu"
    assert len(provider.calls) == 2

    second_provider = _LocalIndexProvider(frames)
    second = read_local_index_overlays(
        settings=SimpleNamespace(),
        now=_NOW,
        cache=cache,
        provider_builder=_builder(second_provider),
    )
    assert second["hong-kong"]["provenance"] == "futu_cache"
    assert second["japan"]["provenance"] == "futu_cache"
    assert second_provider.calls == []
    assert second["hong-kong"]["series"] == first["hong-kong"]["series"]

    # The cached index bars are keyed by the prefixed symbol: an ETF-window
    # read in the same cache file never sees them, and vice versa.
    assert (
        cache.read(
            provider="futu",
            symbols=["EWH"],
            interval="1d",
            adjustment="qfq",
            start="2025-06-18",
            end=_EXPECTED_INDEX_END,
        )
        is None
    )
    assert (
        cache.read(
            provider="futu",
            symbols=["HK.800000"],
            interval="1d",
            adjustment="qfq",
            start="2025-06-18",
            end=_EXPECTED_INDEX_END,
        )
        is not None
    )
    # The default US-only read path cannot even address the local code.
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_historical_prices(
            settings=SimpleNamespace(),
            symbols=["HK.800000"],
            start="2026-08-10",
            end=_EXPECTED_INDEX_END,
            provider="futu",
            provider_builder=_builder(provider),
            cache=cache,
        )
    assert excinfo.value.code == "historical_prices_invalid_request"


def test_local_market_read_requires_provider_lane_support() -> None:
    class _UsOnlyProvider:
        provider_name = "futu"

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            raise AssertionError("must not be called")

    def builder(settings, *, requested):
        return _UsOnlyProvider(), "futu"

    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_historical_prices(
            settings=SimpleNamespace(),
            symbols=["JP..N225"],
            start="2026-08-10",
            end="2026-08-11",
            provider="futu",
            provider_builder=builder,
            allow_local_markets=True,
        )
    assert excinfo.value.code == "historical_prices_contract_invalid"


def test_attach_sets_schema_12_and_never_touches_etf_metrics() -> None:
    overview = build_asia_radar_overview(_etf_snapshot())
    assert overview["schema_version"] == "1.1"
    serialized_before = json.dumps(overview, sort_keys=True)

    attached = attach_local_index_overlays(
        overview,
        {
            "hong-kong": {
                "status": "available",
                "index_symbol": "HK.800000",
                "series": [{"date": "2026-08-11", "close": 1.0, "indexed_return_pct": 0.0}],
            }
        },
    )

    assert attached["schema_version"] == "1.2"
    assert len(attached["markets"]) == 12
    for market in attached["markets"]:
        assert "local_index" in market
    assert attached["markets"][6]["symbol"] == "EWH"
    assert attached["markets"][6]["local_index"]["status"] == "available"
    # Markets without a loaded overlay get an explicit unavailable state.
    assert attached["markets"][0]["local_index"]["status"] == "unavailable"
    assert attached["markets"][0]["local_index"]["reason_code"] == "overlay_missing"
    # Serialization-level invariance: minus local_index/schema_version the
    # overview is byte-for-byte the pre-attach payload (field-enumeration-proof).
    stripped = deepcopy(attached)
    stripped["schema_version"] = "1.1"
    for market in stripped["markets"]:
        del market["local_index"]
    assert json.dumps(stripped, sort_keys=True) == serialized_before


def test_read_overview_never_lets_index_lane_break_the_etf_main_path(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )

    def exploding_reader(*, settings, now, cache):
        raise RuntimeError("index lane exploded")

    overview = read_asia_radar_overview(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
        local_index_reader=exploding_reader,
        driver_basket_reader=lambda **_: {},
    )

    assert overview["schema_version"] == "1.3"
    assert overview["as_of"] == "2026-03-30"
    assert [market["symbol"] for market in overview["markets"]] == list(ASIA_ETF_SYMBOLS)
    for market in overview["markets"]:
        assert market["local_index"]["status"] == "unavailable"
        assert market["local_index"]["reason_code"] == "overlay_missing"
        assert market["local_index"]["series"] == []
        assert market["driver_basket"]["status"] == "unavailable"
        assert market["driver_basket"]["reason_code"] == "overlay_missing"
        assert market["driver_basket"]["leaders"] == []


def test_read_overview_attaches_reader_overlays(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )
    captured = {}

    def fake_reader(*, settings, now, cache):
        captured["now"] = now
        return {
            spec.market_id: {
                "status": "available",
                "index_symbol": spec.symbol,
                "index_name_en": spec.name_en,
                "index_name_zh": spec.name_zh,
                "currency": spec.currency,
                "timezone": spec.timezone,
                "as_of": "2026-03-30",
                "provider": "futu",
                "provenance": "futu",
                "fetched_at": "2026-03-30T20:00:00+00:00",
                "adjustment": "qfq",
                "series": [],
                "reason_code": None,
                "reason": None,
                "provider_code": None,
            }
            for spec in LOCAL_INDEX_SPECS
        }

    overview = read_asia_radar_overview(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
        local_index_reader=fake_reader,
    )

    by_market = {market["market_id"]: market for market in overview["markets"]}
    assert by_market["hong-kong"]["local_index"]["index_symbol"] == "HK.800000"
    assert by_market["japan"]["local_index"]["currency"] == "JPY"
    assert by_market["south-korea"]["local_index"]["reason_code"] == "overlay_missing"
    assert captured["now"] == datetime(2026, 3, 30, 21, 0, tzinfo=UTC)


def test_overlay_builder_failure_is_contained_per_market() -> None:
    def unavailable_builder(settings, *, requested):
        raise DataProviderUnavailableError("futu", "opend_unavailable")

    overlays = read_local_index_overlays(
        settings=SimpleNamespace(),
        now=_NOW,
        cache=None,
        provider_builder=unavailable_builder,
    )

    for market_id in ("hong-kong", "japan"):
        overlay = overlays[market_id]
        assert overlay["status"] == "unavailable"
        assert overlay["reason_code"] == "provider_error"
        assert overlay["provider_code"] == "opend_unavailable"
        assert overlay["series"] == []
    # Pending markets still report their curated reasons, untouched.
    assert overlays["china-a"]["reason_code"] == "permission_not_granted"


def test_overlay_short_history_is_honestly_unavailable() -> None:
    short = {
        "HK.800000": _index_frame("HK.800000", periods=_MIN_LOCAL_INDEX_BARS - 1),
        "JP..N225": _index_frame("JP..N225"),
    }
    provider = _LocalIndexProvider(short)

    overlays = _read_overlays(provider)

    hong_kong = overlays["hong-kong"]
    assert hong_kong["status"] == "unavailable"
    assert hong_kong["reason_code"] == "provider_error"
    assert hong_kong["provider_code"] == "insufficient_history"
    assert hong_kong["series"] == []
    assert overlays["japan"]["status"] == "available"


def test_read_summary_never_touches_the_index_lane(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )

    def forbidden_reader(*, settings, now, cache):
        raise AssertionError("summary path must not fetch local index overlays")

    summary = read_asia_radar_summary(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
    )
    assert summary["status"] == "available"
    assert summary["market_count"] == 12
    # read_asia_radar_summary always skips overlays; prove the parameter path too.
    overview = read_asia_radar_overview(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
        local_index_reader=forbidden_reader,
    )
    assert all(
        market["local_index"]["reason_code"] == "overlay_missing"
        for market in overview["markets"]
    )


def test_summary_route_path_never_touches_the_index_lane(monkeypatch) -> None:
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_local_index_overlays",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("summary path must not fetch local index overlays")
        ),
    )

    summary = read_asia_radar_summary(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
    )
    assert summary["status"] == "available"
    assert summary["market_count"] == 12


def test_etf_and_index_bars_share_cache_file_without_cross_reads(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    index_frames = {
        "HK.800000": _index_frame("HK.800000"),
        "JP..N225": _index_frame("JP..N225"),
    }
    # Populate the local-index lane first.
    read_local_index_overlays(
        settings=SimpleNamespace(),
        now=_NOW,
        cache=cache,
        provider_builder=_builder(_LocalIndexProvider(index_frames)),
    )

    # Write ETF bars into the same file over an overlapping window.
    etf_rows = []
    for day in pd.bdate_range(end="2026-08-11", periods=80):
        etf_rows.append(
            {
                "symbol": "EWH",
                "timestamp": day.tz_localize("UTC"),
                "open": 21.0,
                "high": 21.5,
                "low": 20.5,
                "close": 21.25,
                "volume": 1_000_000.0,
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
                "event_ts": day.tz_localize("UTC"),
                "knowledge_ts": pd.Timestamp("2026-08-11T21:00:00Z"),
            }
        )
    cache.write(
        pd.DataFrame(etf_rows),
        provider="futu",
        symbols=["EWH"],
        interval="1d",
        adjustment="qfq",
        start="2025-06-18",
        end="2026-08-11",
    )

    etf_cached = cache.read(
        provider="futu",
        symbols=["EWH"],
        interval="1d",
        adjustment="qfq",
        start="2025-06-18",
        end="2026-08-11",
    )
    assert etf_cached is not None
    assert set(etf_cached["symbol"]) == {"EWH"}
    assert len(etf_cached) == 80

    index_cached = cache.read(
        provider="futu",
        symbols=["HK.800000"],
        interval="1d",
        adjustment="qfq",
        start="2025-06-18",
        end="2026-08-11",
    )
    assert index_cached is not None
    assert set(index_cached["symbol"]) == {"HK.800000"}
    assert len(index_cached) == 100
    # The lanes see disjoint closes: ETF 21.25 vs index ~1000+.
    assert float(etf_cached["close"].max()) < 100.0
    assert float(index_cached["close"].min()) > 100.0

    # An ETF read through the full read path stays ETF-only with the shared cache.
    class _EtfProvider:
        provider_name = "futu"

        def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
            raise AssertionError("cache hit must short-circuit the provider")

    snapshot = read_historical_prices(
        settings=SimpleNamespace(),
        symbols=["EWH"],
        start="2025-06-18",
        end="2026-08-11",
        provider="futu",
        provider_builder=lambda settings, *, requested: (_EtfProvider(), "futu"),
        cache=cache,
    )
    assert snapshot.source == "futu_cache"
    assert snapshot.series[0]["symbol"] == "EWH"
    assert all(row["close"] == 21.25 for row in snapshot.series[0]["rows"])


def test_etf_overview_deterministic_across_index_lane_cache_states(
    monkeypatch, tmp_path
) -> None:
    # Determinism guard: the ETF payload must be identical whether the index
    # lane's overlay fetch was a cache miss (first run) or a cache hit
    # (second run). Pollution isolation itself is pinned by the shared-file
    # test above and the composed on/off A/B test below.
    cache = EquityBarCache(tmp_path / "futu_equity_bars.duckdb")
    monkeypatch.setattr(
        "quant_system.factors.asia_radar._resolve_cache",
        lambda **kwargs: cache,
    )
    etf_calls = {"count": 0}
    real_read = read_historical_prices

    def etf_read(**kwargs):
        symbols = kwargs.get("symbols") or []
        if "EWH" in symbols:
            etf_calls["count"] += 1
            return _etf_snapshot()
        return real_read(**kwargs)

    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        etf_read,
    )
    index_frames = {
        "HK.800000": _index_frame("HK.800000"),
        "JP..N225": _index_frame("JP..N225"),
    }
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_local_index_overlays",
        lambda **kwargs: read_local_index_overlays(
            settings=kwargs["settings"],
            now=kwargs["now"],
            cache=kwargs["cache"],
            provider_builder=_builder(_LocalIndexProvider(index_frames)),
        ),
    )

    read_kwargs = {
        "settings": SimpleNamespace(),
        "now": datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
    }
    first = read_asia_radar_overview(**read_kwargs)
    second = read_asia_radar_overview(**read_kwargs)

    def etf_part(payload):
        clean = deepcopy(payload)
        clean.pop("schema_version")
        for market in clean["markets"]:
            market.pop("local_index")
        return clean

    assert json.dumps(etf_part(first), sort_keys=True) == json.dumps(
        etf_part(second), sort_keys=True
    )


def test_etf_payload_identical_with_overlays_on_or_off(monkeypatch) -> None:
    # Composed-level A/B: read_asia_radar_overview with a real overlay reader
    # vs overlays disabled must differ ONLY in local_index / schema_version.
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )
    available_reader = lambda **kwargs: {  # noqa: E731
        spec.market_id: {
            "status": "available",
            "index_symbol": spec.symbol,
            "index_name_en": spec.name_en,
            "index_name_zh": spec.name_zh,
            "currency": spec.currency,
            "timezone": spec.timezone,
            "as_of": "2026-03-30",
            "provider": "futu",
            "provenance": "futu",
            "fetched_at": "2026-03-30T20:00:00+00:00",
            "adjustment": "qfq",
            "series": [
                {"date": "2026-03-30", "close": 1.0, "indexed_return_pct": 0.0}
            ],
            "reason_code": None,
            "reason": None,
            "provider_code": None,
        }
        for spec in LOCAL_INDEX_SPECS
    }

    read_kwargs = {
        "settings": SimpleNamespace(),
        "now": datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        "cache": False,
    }
    with_overlays = read_asia_radar_overview(
        local_index_reader=available_reader, **read_kwargs
    )
    without_overlays = read_asia_radar_overview(
        local_index_reader=lambda **_: {}, **read_kwargs
    )

    def etf_part(payload):
        clean = deepcopy(payload)
        clean.pop("schema_version")
        for market in clean["markets"]:
            market.pop("local_index")
        return clean

    assert json.dumps(etf_part(with_overlays), sort_keys=True) == json.dumps(
        etf_part(without_overlays), sort_keys=True
    )
    assert with_overlays["markets"][6]["local_index"]["status"] == "available"
    assert without_overlays["markets"][6]["local_index"]["status"] == "unavailable"


def test_historical_price_read_error_from_index_lane_never_escapes(monkeypatch) -> None:
    # The route maps HistoricalPriceReadError to 503; the index lane must not
    # leak it even if a future refactor narrows the broad containment except.
    snapshot = _etf_snapshot()
    monkeypatch.setattr(
        "quant_system.factors.asia_radar.read_historical_prices",
        lambda **kwargs: snapshot,
    )

    def typed_explosion(*, settings, now, cache):
        raise HistoricalPriceReadError(
            code="historical_prices_provider_unavailable",
            message="OpenD down",
            provider_code="opend_unavailable",
        )

    overview = read_asia_radar_overview(
        settings=SimpleNamespace(),
        now=datetime(2026, 3, 30, 21, 0, tzinfo=UTC),
        cache=False,
        local_index_reader=typed_explosion,
        driver_basket_reader=lambda **_: {},
    )

    assert overview["schema_version"] == "1.3"
    assert [market["symbol"] for market in overview["markets"]] == list(ASIA_ETF_SYMBOLS)
    for market in overview["markets"]:
        assert market["local_index"]["status"] == "unavailable"
        assert market["local_index"]["reason_code"] == "overlay_missing"
