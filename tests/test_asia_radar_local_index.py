from __future__ import annotations

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
from quant_system.data.providers.futu import FutuProviderError
from quant_system.factors.asia_radar import (
    ASIA_ETF_SYMBOLS,
    LOCAL_INDEX_PENDING,
    LOCAL_INDEX_SPECS,
    _last_completed_local_session,
    _last_completed_us_session,
    attach_local_index_overlays,
    build_asia_radar_overview,
    read_asia_radar_overview,
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
    metrics_before = [
        {
            "symbol": market["symbol"],
            "returns": market["returns"],
            "volatility_pct": market["volatility_pct"],
            "max_drawdown_pct": market["max_drawdown_pct"],
            "history": market["history"],
            "rank": market["rank"],
            "k_leg": market["k_leg"],
            "meta": market["meta"],
        }
        for market in overview["markets"]
    ]
    k_shape_before = overview["k_shape"]

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
    # ETF metrics, history and K-shape are bit-for-bit untouched by the lane.
    metrics_after = [
        {
            "symbol": market["symbol"],
            "returns": market["returns"],
            "volatility_pct": market["volatility_pct"],
            "max_drawdown_pct": market["max_drawdown_pct"],
            "history": market["history"],
            "rank": market["rank"],
            "k_leg": market["k_leg"],
            "meta": market["meta"],
        }
        for market in attached["markets"]
    ]
    assert metrics_after == metrics_before
    assert attached["k_shape"] == k_shape_before


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
    )

    assert overview["schema_version"] == "1.2"
    assert overview["as_of"] == "2026-03-30"
    assert [market["symbol"] for market in overview["markets"]] == list(ASIA_ETF_SYMBOLS)
    for market in overview["markets"]:
        assert market["local_index"]["status"] == "unavailable"
        assert market["local_index"]["reason_code"] == "overlay_missing"
        assert market["local_index"]["series"] == []


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
