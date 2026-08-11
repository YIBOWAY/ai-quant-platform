from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from quant_system.d34.market_data_snapshot import create_market_data_snapshot


class _Futu:
    provider_name = "futu"

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        assert symbols == ["SPY", "QQQ", "IWM", "DIA"]
        assert (start, end, interval) == ("2026-01-01", "2026-01-03", "1d")
        rows = []
        for offset, symbol in enumerate(symbols):
            for day in (1, 2, 3):
                close = 100.0 + offset + day
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": pd.Timestamp(f"2026-01-0{day}", tz="UTC"),
                        "open": close - 1,
                        "high": close + 1,
                        "low": close - 2,
                        "close": close,
                        "volume": 1_000_000 + offset,
                        "provider": "futu",
                        "interval": "1d",
                        "event_ts": pd.Timestamp(f"2026-01-0{day}", tz="UTC"),
                        "knowledge_ts": pd.Timestamp("2026-01-04", tz="UTC"),
                        "price_adjustment": "qfq",
                    }
                )
        return pd.DataFrame(rows)


def test_futu_snapshot_is_canonical_digest_bound_parquet(tmp_path) -> None:
    first = create_market_data_snapshot(
        provider=_Futu(),
        symbols=("SPY", "QQQ", "IWM", "DIA"),
        start="2026-01-01",
        end="2026-01-03",
        output_root=tmp_path,
        now=lambda: datetime(2026, 1, 4, tzinfo=UTC),
    )
    second = create_market_data_snapshot(
        provider=_Futu(),
        symbols=("SPY", "QQQ", "IWM", "DIA"),
        start="2026-01-01",
        end="2026-01-03",
        output_root=tmp_path,
        now=lambda: datetime(2026, 1, 4, tzinfo=UTC),
    )

    assert second == first
    assert first.contract == "hqa.market_data_snapshot/v1"
    assert first.provider == "futu"
    assert first.row_count == 12
    assert first.universe == ("SPY", "QQQ", "IWM", "DIA")
    assert first.symbol_codes == {
        "SPY": "US.SPY",
        "QQQ": "US.QQQ",
        "IWM": "US.IWM",
        "DIA": "US.DIA",
    }
    assert first.timezone == "America/New_York"
    assert first.calendar == "XNYS"
    assert first.adjustment == "qfq"
    assert first.parquet_path.is_file()
    assert first.manifest_path.is_file()
    assert len(first.snapshot_digest) == 64
    assert len(first.parquet_digest) == 64
    assert len(first.provider_receipt_digest) == 64

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_digest"] == first.snapshot_digest
    assert manifest["parquet_digest"] == first.parquet_digest
    assert manifest["missing_values"] == 0
    assert manifest["rows_by_symbol"] == {"DIA": 3, "IWM": 3, "QQQ": 3, "SPY": 3}
    persisted = pd.read_parquet(first.parquet_path)
    assert persisted["provider"].unique().tolist() == ["futu"]
    assert persisted["symbol"].drop_duplicates().tolist() == ["SPY", "QQQ", "IWM", "DIA"]
