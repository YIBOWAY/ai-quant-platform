from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_system.storage.artifacts import save_parquet_artifact


class LocalFactorStorage:
    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        factors_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
        write_duckdb: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.factors_dir = Path(factors_dir) if factors_dir else self.base_dir / "factors"
        self.reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )
        self.write_duckdb = write_duckdb

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
        return save_parquet_artifact(
            frame,
            directory=self.factors_dir,
            filename=filename,
            duckdb_path=self.duckdb_path,
            table_name=table_name,
            write_duckdb=self.write_duckdb,
        )
