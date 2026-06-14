from __future__ import annotations

import pandas as pd

from quant_system.storage.options_cache import OptionQuotesCache, OptionQuotesCacheKey


def test_option_quotes_cache_returns_fresh_rows_and_ignores_stale_rows(tmp_path) -> None:
    cache = OptionQuotesCache(tmp_path / "options_cache.duckdb")
    key = OptionQuotesCacheKey(
        provider="futu",
        host="127.0.0.1",
        port=11111,
        underlying="AAPL",
        start_expiration="2026-05-08",
        end_expiration="2026-05-15",
        option_type="CALL",
    )
    frame = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260508C200000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-05-08",
                "strike": 200.0,
                "bid": 3.9,
                "ask": 4.1,
                "volume": 120,
                "open_interest": 450,
            }
        ]
    )
    fetched_at = pd.Timestamp("2026-05-01T14:30:00Z")

    cache.write_option_quotes(
        key,
        frame,
        ttl_seconds=900,
        fetched_at=fetched_at,
    )

    fresh = cache.read_option_quotes(
        key,
        as_of=pd.Timestamp("2026-05-01T14:40:00Z"),
    )
    stale = cache.read_option_quotes(
        key,
        as_of=pd.Timestamp("2026-05-01T14:46:00Z"),
    )

    assert fresh is not None
    assert fresh.to_dict(orient="records") == frame.to_dict(orient="records")
    assert stale is None


def test_option_quotes_cache_prunes_expired_snapshots_only(tmp_path) -> None:
    cache = OptionQuotesCache(tmp_path / "options_cache.duckdb")
    expired_key = OptionQuotesCacheKey(
        provider="futu",
        host="127.0.0.1",
        port=11111,
        underlying="AAPL",
        start_expiration="2026-05-08",
        end_expiration="2026-05-15",
        option_type="CALL",
    )
    fresh_key = OptionQuotesCacheKey(
        provider="futu",
        host="127.0.0.1",
        port=11111,
        underlying="MSFT",
        start_expiration="2026-05-08",
        end_expiration="2026-05-15",
        option_type="CALL",
    )
    frame = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260508C200000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-05-08",
                "strike": 200.0,
            }
        ]
    )

    cache.write_option_quotes(
        expired_key,
        frame,
        ttl_seconds=60,
        fetched_at=pd.Timestamp("2026-05-01T14:30:00Z"),
    )
    cache.write_option_quotes(
        fresh_key,
        frame,
        ttl_seconds=3600,
        fetched_at=pd.Timestamp("2026-05-01T14:30:00Z"),
    )

    removed = cache.prune_expired(as_of=pd.Timestamp("2026-05-01T14:45:00Z"))

    assert removed == 1
    assert cache.read_option_quotes(
        expired_key,
        as_of=pd.Timestamp("2026-05-01T14:45:00Z"),
    ) is None
    assert cache.read_option_quotes(
        fresh_key,
        as_of=pd.Timestamp("2026-05-01T14:45:00Z"),
    ) is not None
