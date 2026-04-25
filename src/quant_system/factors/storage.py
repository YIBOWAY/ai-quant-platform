from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


class LocalFactorStorage:
    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        factors_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.factors_dir = Path(factors_dir) if factors_dir else self.base_dir / "factors"
        self.reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )

    def save_factor_results(
        self,
        frame: pd.DataFrame,
        filename: str = "factor_results.parquet",
    ) -> Path:
        return self._save_parquet_and_duckdb(frame, filename, table_name="factor_results")

    def save_signal_frame(
        self,
        frame: pd.DataFrame,
        filename: str = "factor_signals.parquet",
    ) -> Path:
        return self._save_parquet_and_duckdb(frame, filename, table_name="factor_signals")

    def save_information_coefficients(
        self,
        frame: pd.DataFrame,
        filename: str = "factor_ic.parquet",
    ) -> Path:
        return self._save_parquet_and_duckdb(frame, filename, table_name="factor_ic")

    def save_quantile_returns(
        self,
        frame: pd.DataFrame,
        filename: str = "quantile_returns.parquet",
    ) -> Path:
        return self._save_parquet_and_duckdb(frame, filename, table_name="quantile_returns")

    def save_report(self, markdown: str, filename: str = "factor_report.md") -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.reports_dir / filename
        report_path.write_text(markdown, encoding="utf-8")
        return report_path

    def _save_parquet_and_duckdb(
        self,
        frame: pd.DataFrame,
        filename: str,
        *,
        table_name: str,
    ) -> Path:
        self.factors_dir.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        path = self.factors_dir / filename
        persisted = frame.reset_index(drop=True)
        persisted.to_parquet(path, index=False)
        with duckdb.connect(str(self.duckdb_path)) as connection:
            connection.register("persisted_frame", persisted)
            connection.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM persisted_frame"
            )
        return path
