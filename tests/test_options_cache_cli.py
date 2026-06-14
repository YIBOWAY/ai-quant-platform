from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.storage.options_cache import OptionQuotesCache, OptionQuotesCacheKey

runner = CliRunner()


def _write_cached_window(
    cache: OptionQuotesCache,
    *,
    underlying: str,
    fetched_at: str,
    ttl_seconds: int,
) -> None:
    cache.write_option_quotes(
        OptionQuotesCacheKey(
            provider="futu",
            host="127.0.0.1",
            port=11111,
            underlying=underlying,
            start_expiration="2026-05-08",
            end_expiration="2026-05-15",
            option_type="CALL",
        ),
        pd.DataFrame(
            [
                {
                    "symbol": f"US.{underlying}260508C200000",
                    "underlying": f"US.{underlying}",
                    "option_type": "CALL",
                    "expiry": "2026-05-08",
                    "strike": 200.0,
                }
            ]
        ),
        ttl_seconds=ttl_seconds,
        fetched_at=pd.Timestamp(fetched_at),
    )


def test_options_prune_cache_dry_run_reports_without_deleting(tmp_path: Path) -> None:
    cache_path = tmp_path / "options_cache.duckdb"
    cache = OptionQuotesCache(cache_path)
    _write_cached_window(
        cache,
        underlying="AAPL",
        fetched_at="2026-05-01T14:30:00Z",
        ttl_seconds=60,
    )

    result = runner.invoke(
        app,
        [
            "options",
            "prune-cache",
            "--cache-path",
            str(cache_path),
            "--as-of",
            "2026-05-01T14:45:00Z",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "dry_run"
    assert payload["expired_snapshots"] == 1
    assert payload["removed_snapshots"] == 0
    assert cache.read_option_quotes(
        OptionQuotesCacheKey(
            provider="futu",
            host="127.0.0.1",
            port=11111,
            underlying="AAPL",
            start_expiration="2026-05-08",
            end_expiration="2026-05-15",
            option_type="CALL",
        ),
        as_of=pd.Timestamp("2026-05-01T14:30:59Z"),
    ) is not None


def test_options_prune_cache_apply_removes_expired_only(tmp_path: Path) -> None:
    cache_path = tmp_path / "options_cache.duckdb"
    cache = OptionQuotesCache(cache_path)
    _write_cached_window(
        cache,
        underlying="AAPL",
        fetched_at="2026-05-01T14:30:00Z",
        ttl_seconds=60,
    )
    _write_cached_window(
        cache,
        underlying="MSFT",
        fetched_at="2026-05-01T14:30:00Z",
        ttl_seconds=3600,
    )

    result = runner.invoke(
        app,
        [
            "options",
            "prune-cache",
            "--cache-path",
            str(cache_path),
            "--as-of",
            "2026-05-01T14:45:00Z",
            "--apply",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "apply"
    assert payload["expired_snapshots"] == 1
    assert payload["removed_snapshots"] == 1
    assert cache.prune_expired(as_of=pd.Timestamp("2026-05-01T14:45:00Z")) == 0
