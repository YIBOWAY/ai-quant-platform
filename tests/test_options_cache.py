from __future__ import annotations

import json

import duckdb
import pandas as pd
import pytest

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


def _iv_key(underlying: str = "AAPL") -> OptionQuotesCacheKey:
    return OptionQuotesCacheKey(
        provider="futu",
        host="127.0.0.1",
        port=11111,
        underlying=underlying,
        start_expiration="2026-05-08",
        end_expiration="2026-05-15",
        option_type="CALL",
    )


def test_option_quotes_cache_writes_and_reads_ratio_iv_with_unit(tmp_path) -> None:
    cache = OptionQuotesCache(tmp_path / "options_cache.duckdb")
    key = _iv_key()
    frame = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260508C200000",
                "implied_volatility": 0.42,
            }
        ]
    )

    cache.write_option_quotes(
        key,
        frame,
        ttl_seconds=900,
        fetched_at=pd.Timestamp("2026-05-01T14:30:00Z"),
    )

    with duckdb.connect(str(tmp_path / "options_cache.duckdb")) as connection:
        unit = connection.execute(
            "SELECT implied_volatility_unit FROM option_chain_snapshots WHERE snapshot_id = ?",
            [key.snapshot_id()],
        ).fetchone()[0]
    assert unit == "ratio"

    fresh = cache.read_option_quotes(key, as_of=pd.Timestamp("2026-05-01T14:40:00Z"))
    assert fresh is not None
    assert fresh["implied_volatility"].tolist() == [pytest.approx(0.42)]


def test_option_quotes_cache_converts_a_declared_percent_frame_to_ratio(tmp_path) -> None:
    cache = OptionQuotesCache(tmp_path / "options_cache.duckdb")
    key = _iv_key()
    frame = pd.DataFrame([{"symbol": "US.AAPL260508C200000", "implied_volatility": 42.0}])
    frame.attrs["implied_volatility_unit"] = "percent"

    cache.write_option_quotes(
        key,
        frame,
        ttl_seconds=900,
        fetched_at=pd.Timestamp("2026-05-01T14:30:00Z"),
    )

    fresh = cache.read_option_quotes(key, as_of=pd.Timestamp("2026-05-01T14:40:00Z"))
    assert fresh is not None
    assert fresh["implied_volatility"].tolist() == [pytest.approx(0.42)]


def test_option_quotes_cache_reads_legacy_percent_rows_as_ratio(tmp_path) -> None:
    """Rows persisted before the unit column existed are a schema-level percent."""
    path = tmp_path / "options_cache.duckdb"
    cache = OptionQuotesCache(path)
    key = _iv_key()
    columns = ["symbol", "implied_volatility"]
    payload = {"symbol": "US.AAPL260508C200000", "implied_volatility": 42.0}
    with duckdb.connect(str(path)) as connection:
        # No implied_volatility_unit value: replicates a pre-migration row.
        connection.execute(
            """
            INSERT INTO option_chain_snapshots (
                snapshot_id, provider, host, port, ticker,
                start_expiration, end_expiration, option_type,
                fetched_at, expires_at, source_label, row_count, columns_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                key.snapshot_id(),
                "futu",
                "127.0.0.1",
                11111,
                "AAPL",
                "2026-05-08",
                "2026-05-15",
                "CALL",
                "2026-05-01T14:30:00+00:00",
                "2099-01-01T00:00:00+00:00",
                "futu_option_quotes",
                1,
                json.dumps(columns),
            ],
        )
        connection.execute(
            """
            INSERT INTO option_contract_quotes (
                snapshot_id, row_index, symbol, implied_volatility, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                key.snapshot_id(),
                0,
                "US.AAPL260508C200000",
                42.0,
                json.dumps(payload),
            ],
        )

    fresh = cache.read_option_quotes(key, as_of=pd.Timestamp("2026-05-01T14:40:00Z"))
    assert fresh is not None
    assert fresh["implied_volatility"].tolist() == [pytest.approx(0.42)]


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
