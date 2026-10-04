from __future__ import annotations

import pandas as pd
import pytest

from quant_system.config.settings import Settings
from quant_system.data.backup_bars import (
    BackupChainResult,
    build_backup_provider,
    default_backup_window,
    read_daily_bars_with_backup,
)
from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
)
from quant_system.data.providers.longbridge import LongbridgeProviderError
from quant_system.data.providers.tiingo import TiingoProviderError
from quant_system.data.providers.twelvedata import TwelveDataProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe

START = "2026-08-03"
END = "2026-08-10"
SYMBOLS = ["EWH", "EWJ"]


def _frame(
    provider: str,
    symbols: list[str] = SYMBOLS,
    *,
    adjustment: str,
    close: float = 100.0,
    days: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    if days is None:
        days = (
            tuple(day.date().isoformat() for day in pd.bdate_range(START, END))
            if provider == "longbridge"
            else ("2026-08-03", "2026-08-10")
        )
    rows = [
        {
            "symbol": symbol,
            "timestamp": f"{day}T00:00:00Z",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000_000.0,
            "price_adjustment": adjustment,
            "event_ts": f"{day}T00:00:00Z",
            "knowledge_ts": f"{day}T22:00:00Z",
        }
        for symbol in symbols
        for day in days
    ]
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider=provider, interval="1d")


def _futu_snapshot() -> HistoricalPriceSnapshot:
    return HistoricalPriceSnapshot(
        provider="futu",
        source="futu",
        interval="1d",
        adjustment="qfq",
        start=START,
        end=END,
        fetched_at="2026-08-10T22:00:00+00:00",
        symbols=list(SYMBOLS),
        series=[
            {
                "symbol": symbol,
                "row_count": 2,
                "first_date": "2026-08-03",
                "last_date": "2026-08-10",
                "rows": [
                    {"date": "2026-08-03", "close": 100.0},
                    {"date": "2026-08-10", "close": 101.0},
                ],
            }
            for symbol in SYMBOLS
        ],
    )


def _futu_failure(**_kwargs):
    raise HistoricalPriceReadError(
        code="historical_prices_provider_error",
        message="Futu OpenD is unavailable",
        provider="futu",
        provider_code="opend_unavailable",
    )


class _FakeBackupProvider:
    def __init__(
        self,
        name: str,
        *,
        frame: pd.DataFrame | None = None,
        error: Exception | None = None,
    ):
        self.provider_name = name
        self.frame = frame
        self.error = error
        self.calls = 0

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.frame is not None
        return self.frame


def _settings() -> Settings:
    # Deterministic, keyless settings: never let a developer's local .env turn
    # a unit test into a real network call.
    settings = Settings()
    settings.api_keys.twelvedata_api_key = None
    settings.api_keys.tiingo_api_token = None
    return settings


def test_longbridge_chain_is_not_touched_when_futu_succeeds() -> None:
    def forbidden(*_args):
        pytest.fail("a successful primary must not create or call any backup")

    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("longbridge",),
        provider_builder=forbidden,
        primary_reader=lambda **_: _futu_snapshot(),
    )
    assert result.served_by == "futu"
    assert result.fallbacks == []


def test_longbridge_backup_has_forward_provenance() -> None:
    backup = _FakeBackupProvider("longbridge", frame=_frame("longbridge", adjustment="forward"))
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("longbridge",),
        provider_builder=lambda *_: backup,
        primary_reader=_futu_failure,
    )
    assert backup.calls == 1
    assert result.served_by == "longbridge"
    assert result.snapshot.adjustment == "forward"
    assert result.snapshot.source == "longbridge"
    assert result.fallbacks[0]["provider"] == "futu"
    assert result.fallbacks[0]["code"] == "opend_unavailable"


def test_longbridge_permission_error_is_recorded_before_next_backup() -> None:
    backups = {
        "longbridge": _FakeBackupProvider(
            "longbridge", error=LongbridgeProviderError("permission_denied")
        ),
        "tiingo": _FakeBackupProvider("tiingo", frame=_frame("tiingo", adjustment="adjusted")),
    }
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("longbridge", "tiingo"),
        provider_builder=lambda _, name: backups[name],
        primary_reader=_futu_failure,
    )
    assert result.served_by == "tiingo"
    assert result.fallbacks[1]["code"] == "permission_denied"


@pytest.mark.parametrize("origin", ["futu", "sample"])
def test_longbridge_backup_rejects_mixed_or_sample_source(origin) -> None:
    frame = _frame("longbridge", adjustment="forward")
    frame.loc[0, "provider"] = origin
    backup = _FakeBackupProvider("longbridge", frame=frame)
    with pytest.raises(HistoricalPriceReadError) as error:
        read_daily_bars_with_backup(
            settings=_settings(),
            symbols=SYMBOLS,
            start=START,
            end=END,
            backup_providers=("longbridge",),
            provider_builder=lambda *_: backup,
            primary_reader=_futu_failure,
        )
    assert error.value.code == "historical_prices_backup_chain_exhausted"


def test_longbridge_cache_refreshes_when_a_new_requested_session_has_closed(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "longbridge-bars.duckdb")
    days = ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
    before_close = pd.Timestamp("2024-01-05T15:00:00Z")
    after_close = pd.Timestamp("2024-01-05T22:00:00Z")
    cache.write(
        _frame("longbridge", ["AAPL"], adjustment="forward", days=days[:-1]),
        provider="longbridge", symbols=["AAPL"], interval="1d", adjustment="forward",
        start=days[0], end=days[-1], fetched_at=before_close,
    )
    backup = _FakeBackupProvider(
        "longbridge", frame=_frame("longbridge", ["AAPL"], adjustment="forward", days=days),
    )
    request = dict(
        settings=_settings(), symbols=["AAPL"], start=days[0], end=days[-1],
        backup_providers=("longbridge",), provider_builder=lambda *_: backup,
        cache=cache, primary_reader=_futu_failure,
    )
    before = read_daily_bars_with_backup(**request, as_of=before_close)
    assert before.snapshot.source == "longbridge_cache"
    assert before.snapshot.series[0]["last_date"] == "2024-01-04"
    assert backup.calls == 0

    after = read_daily_bars_with_backup(**request, as_of=after_close)
    assert after.snapshot.source == "longbridge"
    assert after.snapshot.series[0]["row_count"] == 4
    assert after.snapshot.series[0]["last_date"] == "2024-01-05"
    assert backup.calls == 1
    assert after.fallbacks[1]["code"] == "contract_invalid"
    assert "cached longbridge rows failed validation" in after.fallbacks[1]["message"]

    refreshed = read_daily_bars_with_backup(
        **request, as_of=after_close + pd.Timedelta(minutes=1),
    )
    assert refreshed.snapshot.source == "longbridge_cache"
    assert refreshed.snapshot.series[0]["last_date"] == "2024-01-05"
    assert backup.calls == 1


def test_longbridge_cache_with_matching_edges_but_missing_middle_sessions_is_miss(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "longbridge-bars.duckdb")
    days = ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
    as_of = pd.Timestamp("2024-01-06T06:00:00+08:00")
    cache.write(
        _frame("longbridge", ["AAPL"], adjustment="forward", days=(days[0], days[-1])),
        provider="longbridge", symbols=["AAPL"], interval="1d", adjustment="forward",
        start=days[0], end=days[-1], fetched_at=as_of,
    )
    backup = _FakeBackupProvider(
        "longbridge", frame=_frame("longbridge", ["AAPL"], adjustment="forward", days=days),
    )
    result = read_daily_bars_with_backup(
        settings=_settings(), symbols=["AAPL"], start=days[0], end=days[-1],
        backup_providers=("longbridge",), provider_builder=lambda *_: backup,
        cache=cache, primary_reader=_futu_failure, as_of=as_of,
    )
    assert result.snapshot.source == "longbridge"
    assert result.snapshot.series[0]["row_count"] == 4
    assert backup.calls == 1
    assert result.fallbacks[1]["code"] == "contract_invalid"


def test_longbridge_live_backup_cannot_serve_an_incomplete_session_window() -> None:
    backup = _FakeBackupProvider(
        "longbridge", frame=_frame(
            "longbridge", ["AAPL"], adjustment="forward", days=("2024-01-02", "2024-01-05"),
        ),
    )
    with pytest.raises(HistoricalPriceReadError) as error:
        read_daily_bars_with_backup(
            settings=_settings(), symbols=["AAPL"], start="2024-01-02", end="2024-01-05",
            backup_providers=("longbridge",), provider_builder=lambda *_: backup,
            primary_reader=_futu_failure, as_of=pd.Timestamp("2024-01-05T22:00:00Z"),
        )
    assert error.value.code == "historical_prices_backup_chain_exhausted"
    assert backup.calls == 1


def test_chain_requires_explicit_opt_in() -> None:
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_daily_bars_with_backup(
            settings=_settings(),
            symbols=SYMBOLS,
            start=START,
            end=END,
            backup_providers=(),
        )
    assert excinfo.value.code == "historical_prices_invalid_request"


def test_chain_rejects_unknown_or_duplicate_backup() -> None:
    for chain in (("polygon",), ("twelvedata", "TWELVEDATA")):
        with pytest.raises(HistoricalPriceReadError) as excinfo:
            read_daily_bars_with_backup(
                settings=_settings(),
                symbols=SYMBOLS,
                start=START,
                end=END,
                backup_providers=chain,
            )
        assert excinfo.value.code == "historical_prices_invalid_request"


def test_futu_primary_serves_and_backups_never_run() -> None:
    backup = _FakeBackupProvider("twelvedata", frame=_frame("twelvedata", adjustment="splits"))
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata", "tiingo"),
        provider_builder=lambda _settings, _name: backup,
        primary_reader=lambda **kwargs: _futu_snapshot(),
    )
    assert isinstance(result, BackupChainResult)
    assert result.served_by == "futu"
    assert result.fallbacks == []
    assert backup.calls == 0


def test_backup_serves_with_honest_provenance_and_recorded_fallback() -> None:
    backup = _FakeBackupProvider("twelvedata", frame=_frame("twelvedata", adjustment="splits"))
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata",),
        provider_builder=lambda _settings, _name: backup,
        primary_reader=_futu_failure,
    )
    snapshot = result.snapshot
    assert result.served_by == "twelvedata"
    assert snapshot.provider == "twelvedata"
    assert snapshot.source == "twelvedata"
    assert snapshot.adjustment == "splits"
    assert [item["symbol"] for item in snapshot.series] == SYMBOLS
    assert result.fallbacks == [
        {
            "provider": "futu",
            "code": "opend_unavailable",
            "message": "Futu OpenD is unavailable",
        }
    ]
    payload = result.to_dict()
    assert payload["served_by"] == "twelvedata"
    assert payload["fallbacks"][0]["provider"] == "futu"


def test_chain_falls_through_failed_backup_to_next_lane() -> None:
    twelvedata = _FakeBackupProvider(
        "twelvedata",
        error=TwelveDataProviderError("rate_limited", "credits exhausted"),
    )
    tiingo = _FakeBackupProvider("tiingo", frame=_frame("tiingo", adjustment="adjusted"))
    builders = {"twelvedata": twelvedata, "tiingo": tiingo}
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata", "tiingo"),
        provider_builder=lambda _settings, name: builders[name],
        primary_reader=_futu_failure,
    )
    assert result.served_by == "tiingo"
    assert result.snapshot.adjustment == "adjusted"
    assert [item["provider"] for item in result.fallbacks] == ["futu", "twelvedata"]
    assert result.fallbacks[1]["code"] == "rate_limited"


def test_missing_backup_key_is_recorded_and_skipped() -> None:
    # No keys configured on a default Settings: both backups are unavailable.
    tiingo = _FakeBackupProvider("tiingo", frame=_frame("tiingo", adjustment="adjusted"))

    def builder(settings: Settings, name: str):
        if name == "tiingo":
            return tiingo
        return build_backup_provider(settings, name)

    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata", "tiingo"),
        provider_builder=builder,
        primary_reader=_futu_failure,
    )
    assert result.served_by == "tiingo"
    assert result.fallbacks[1] == {
        "provider": "twelvedata",
        "code": "missing_api_key",
        "message": "QS_TWELVEDATA_API_KEY is not configured",
    }


def test_chain_exhaustion_fails_closed_with_reasons() -> None:
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_daily_bars_with_backup(
            settings=_settings(),
            symbols=SYMBOLS,
            start=START,
            end=END,
            backup_providers=("twelvedata", "tiingo"),
            provider_builder=lambda _settings, name: _FakeBackupProvider(
                name,
                error=TiingoProviderError("provider_unavailable", "network down"),
            ),
            primary_reader=_futu_failure,
        )
    assert excinfo.value.code == "historical_prices_backup_chain_exhausted"
    assert "twelvedata" in excinfo.value.message
    assert "tiingo" in excinfo.value.message


def test_invalid_request_is_never_masked_by_backups() -> None:
    backup = _FakeBackupProvider("twelvedata", frame=_frame("twelvedata", adjustment="splits"))
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_daily_bars_with_backup(
            settings=_settings(),
            symbols=["HK.800000"],
            start=START,
            end=END,
            backup_providers=("twelvedata",),
            provider_builder=lambda _settings, _name: backup,
            primary_reader=_futu_failure,
        )
    assert excinfo.value.code == "historical_prices_invalid_request"
    assert backup.calls == 0


def test_backup_contract_violation_falls_through_to_next_lane() -> None:
    # A frame with foreign provenance must be rejected, never served.
    wrong_provenance = _FakeBackupProvider(
        "twelvedata", frame=_frame("futu", adjustment="splits")
    )
    tiingo = _FakeBackupProvider("tiingo", frame=_frame("tiingo", adjustment="adjusted"))
    builders = {"twelvedata": wrong_provenance, "tiingo": tiingo}
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata", "tiingo"),
        provider_builder=lambda _settings, name: builders[name],
        primary_reader=_futu_failure,
    )
    assert result.served_by == "tiingo"
    assert result.fallbacks[1]["provider"] == "twelvedata"
    assert result.fallbacks[1]["code"] == "contract_invalid"


def test_tiingo_mixed_adjustment_rows_are_rejected_fail_closed() -> None:
    frame = _frame("tiingo", adjustment="adjusted")
    frame.loc[0, "price_adjustment"] = "raw"
    backup = _FakeBackupProvider("tiingo", frame=frame)
    with pytest.raises(HistoricalPriceReadError) as excinfo:
        read_daily_bars_with_backup(
            settings=_settings(),
            symbols=SYMBOLS,
            start=START,
            end=END,
            backup_providers=("tiingo",),
            provider_builder=lambda _settings, _name: backup,
            primary_reader=_futu_failure,
        )
    assert excinfo.value.code == "historical_prices_backup_chain_exhausted"


def test_cache_isolation_same_symbol_futu_and_backup_rows(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "bars.duckdb")
    # Pin both clocks: write() anchors fetched_at (and thus the coverage expiry)
    # to the fixture rows' knowledge_ts, which is in the past — without the pins
    # this test time-bombs once wall clock passes knowledge_ts + TTL.
    as_of = pd.Timestamp("2026-08-11T00:00:00Z")
    futu_frame = _frame("futu", adjustment="qfq", close=100.0)
    backup_frame = _frame("twelvedata", adjustment="splits", close=55.5)
    cache.write(
        futu_frame,
        provider="futu",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="qfq",
        start=START,
        end=END,
        fetched_at=as_of,
    )
    cache.write(
        backup_frame,
        provider="twelvedata",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="splits",
        start=START,
        end=END,
        fetched_at=as_of,
    )

    futu_rows = cache.read(
        provider="futu",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="qfq",
        start=START,
        end=END,
        as_of=as_of + pd.Timedelta(hours=1),
    )
    backup_rows = cache.read(
        provider="twelvedata",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="splits",
        start=START,
        end=END,
        as_of=as_of + pd.Timedelta(hours=1),
    )
    tiingo_rows = cache.read(
        provider="tiingo",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="adjusted",
        start=START,
        end=END,
        as_of=as_of + pd.Timedelta(hours=1),
    )
    assert futu_rows is not None and backup_rows is not None
    assert set(futu_rows["provider"]) == {"futu"}
    assert set(backup_rows["provider"]) == {"twelvedata"}
    assert set(futu_rows["close"]) == {100.0}
    assert set(backup_rows["close"]) == {55.5}
    # A lane that never wrote must see nothing — no cross-lane reads.
    assert tiingo_rows is None


def test_backup_cache_hit_serves_without_network(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "bars.duckdb")
    # See the clock-pin note in test_cache_isolation_same_symbol_futu_and_backup_rows.
    as_of = pd.Timestamp("2026-08-11T00:00:00Z")
    cache.write(
        _frame("twelvedata", adjustment="splits"),
        provider="twelvedata",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="splits",
        start=START,
        end=END,
        fetched_at=as_of,
    )

    def builder(_settings, _name):  # pragma: no cover - must never be called
        raise AssertionError("backup provider must not be built on a cache hit")

    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata",),
        provider_builder=builder,
        cache=cache,
        primary_reader=_futu_failure,
        as_of=as_of + pd.Timedelta(hours=1),
    )
    assert result.served_by == "twelvedata"
    assert result.snapshot.source == "twelvedata_cache"
    assert result.snapshot.provider == "twelvedata"


def test_live_backup_rows_are_written_into_provider_tagged_cache(tmp_path) -> None:
    cache = EquityBarCache(tmp_path / "bars.duckdb")
    # See the clock-pin note in test_cache_isolation_same_symbol_futu_and_backup_rows:
    # the live-lane cache write anchors fetched_at to the frame's knowledge_ts.
    as_of = pd.Timestamp("2026-08-11T00:00:00Z")
    backup = _FakeBackupProvider("twelvedata", frame=_frame("twelvedata", adjustment="splits"))
    result = read_daily_bars_with_backup(
        settings=_settings(),
        symbols=SYMBOLS,
        start=START,
        end=END,
        backup_providers=("twelvedata",),
        provider_builder=lambda _settings, _name: backup,
        cache=cache,
        primary_reader=_futu_failure,
    )
    assert result.served_by == "twelvedata"
    cached = cache.read(
        provider="twelvedata",
        symbols=SYMBOLS,
        interval="1d",
        adjustment="splits",
        start=START,
        end=END,
        as_of=as_of + pd.Timedelta(hours=1),
    )
    assert cached is not None
    # The futu lane must remain empty — backup writes never leak into it.
    assert (
        cache.read(
            provider="futu",
            symbols=SYMBOLS,
            interval="1d",
            adjustment="qfq",
            start=START,
            end=END,
            as_of=as_of + pd.Timedelta(hours=1),
        )
        is None
    )


def test_default_backup_window_skips_weekends() -> None:
    from datetime import datetime

    start, end = default_backup_window(now=datetime(2026, 8, 11, 12, 0))  # Tuesday
    assert end == "2026-08-10"
    start, end = default_backup_window(now=datetime(2026, 8, 10, 12, 0))  # Monday
    assert end == "2026-08-07"  # Sunday walks back to Friday
    assert start < end
