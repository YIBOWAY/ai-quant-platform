from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.storage.artifacts import save_parquet_artifact


class LocalBacktestStorage:
    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        backtests_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
        write_duckdb: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.backtests_dir = (
            Path(backtests_dir) if backtests_dir else self.base_dir / "backtests"
        )
        self.reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )
        self.write_duckdb = write_duckdb

    def save_frame(self, frame: pd.DataFrame, *, filename: str, table_name: str) -> Path:
        return save_parquet_artifact(
            frame,
            directory=self.backtests_dir,
            filename=filename,
            duckdb_path=self.duckdb_path,
            table_name=table_name,
            write_duckdb=self.write_duckdb,
        )

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
