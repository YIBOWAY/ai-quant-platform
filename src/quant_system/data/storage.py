from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict

from quant_system.data.schema import REQUIRED_OHLCV_COLUMNS
from quant_system.data.validation import DataQualityReport


class StorageArtifacts(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    parquet_path: Path
    duckdb_path: Path


class LocalDataStorage:
    """Phase 1 local OHLCV storage backed by Parquet + DuckDB.

    Paths default to a single ``base_dir`` layout but each artifact path can
    be overridden, so :class:`DataSettings` (``QS_PARQUET_DIR`` /
    ``QS_DUCKDB_PATH`` / ``QS_REPORTS_DIR``) can drive every location.
    """

    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        parquet_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
        reports_dir: str | Path | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.parquet_dir = Path(parquet_dir) if parquet_dir else self.base_dir / "parquet"
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )
        self.reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.parquet_path = self.parquet_dir / "ohlcv.parquet"

    def save_ohlcv(self, frame: pd.DataFrame) -> StorageArtifacts:
        """Persist the frame, merging with any existing rows on (symbol, ts, provider, interval)."""
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)

        merged = self._merge_with_existing(frame)
        merged.to_parquet(self.parquet_path, index=False)
        with duckdb.connect(str(self.duckdb_path)) as connection:
            connection.register("ohlcv_frame", merged)
            connection.execute("CREATE OR REPLACE TABLE ohlcv AS SELECT * FROM ohlcv_frame")

        return StorageArtifacts(parquet_path=self.parquet_path, duckdb_path=self.duckdb_path)

    def _merge_with_existing(self, frame: pd.DataFrame) -> pd.DataFrame:
        if not self.parquet_path.exists():
            return frame
        existing = pd.read_parquet(self.parquet_path)
        # Be defensive: only merge frames that already follow the canonical schema.
        for column in REQUIRED_OHLCV_COLUMNS:
            if column not in existing.columns:
                return frame
        combined = pd.concat([existing, frame], ignore_index=True)
        # Newer rows win when the same (symbol, ts, provider, interval) appears twice.
        combined = combined.drop_duplicates(
            subset=["symbol", "timestamp", "provider", "interval"],
            keep="last",
        )
        return combined.sort_values(["symbol", "timestamp"], ignore_index=True)

    def load_ohlcv(
        self,
        symbols: list[str] | None = None,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        frame = pd.read_parquet(self.parquet_path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)

        if symbols:
            normalized_symbols = {symbol.upper() for symbol in symbols}
            frame = frame[frame["symbol"].isin(normalized_symbols)]
        if start:
            frame = frame[frame["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            frame = frame[frame["timestamp"] <= pd.Timestamp(end, tz="UTC")]

        return frame.reset_index(drop=True)

    def count_duckdb_rows(self) -> int:
        with duckdb.connect(str(self.duckdb_path)) as connection:
            return int(connection.execute("SELECT count(*) FROM ohlcv").fetchone()[0])

    def save_quality_report(
        self,
        report: DataQualityReport,
        filename: str = "data_quality_report.md",
    ) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / filename
        report_path.write_text(report.to_markdown(), encoding="utf-8")
        return report_path

