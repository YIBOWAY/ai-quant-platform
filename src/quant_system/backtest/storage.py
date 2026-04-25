from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from quant_system.backtest.metrics import PerformanceMetrics


class LocalBacktestStorage:
    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        backtests_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.backtests_dir = (
            Path(backtests_dir) if backtests_dir else self.base_dir / "backtests"
        )
        self.reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )

    def save_frame(self, frame: pd.DataFrame, *, filename: str, table_name: str) -> Path:
        self.backtests_dir.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        path = self.backtests_dir / filename
        persisted = frame.reset_index(drop=True)
        persisted.to_parquet(path, index=False)
        with duckdb.connect(str(self.duckdb_path)) as connection:
            connection.register("persisted_frame", persisted)
            connection.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM persisted_frame"
            )
        return path

    def save_metrics(self, metrics: PerformanceMetrics, filename: str = "metrics.json") -> Path:
        self.backtests_dir.mkdir(parents=True, exist_ok=True)
        path = self.backtests_dir / filename
        path.write_text(
            json.dumps(metrics.model_dump(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def save_report(self, markdown: str, filename: str = "backtest_report.md") -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.reports_dir / filename
        path.write_text(markdown, encoding="utf-8")
        return path
