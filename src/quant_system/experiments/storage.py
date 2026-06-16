from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.experiments.models import ExperimentConfig
from quant_system.storage.artifacts import save_parquet_artifact

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_]+")


def _sanitize_id(value: str) -> str:
    cleaned = _SAFE_ID_PATTERN.sub("_", value).strip("_")
    return cleaned or "experiment"


class LocalExperimentStorage:
    """Stores experiment artifacts under a per-experiment subdirectory.

    Each ``run_experiment`` call writes to ``<base>/experiments/<experiment_id>``
    so subsequent experiments do not overwrite earlier results. DuckDB tables
    are also suffixed with the sanitized experiment id for the same reason.
    """

    def __init__(
        self,
        base_dir: str | Path = "data",
        *,
        experiments_dir: str | Path | None = None,
        reports_dir: str | Path | None = None,
        duckdb_path: str | Path | None = None,
        experiment_id: str | None = None,
        write_duckdb: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.experiment_id = experiment_id
        sanitized = _sanitize_id(experiment_id) if experiment_id else None

        root_experiments_dir = (
            Path(experiments_dir) if experiments_dir else self.base_dir / "experiments"
        )
        root_reports_dir = Path(reports_dir) if reports_dir else self.base_dir / "reports"
        self.experiments_dir = (
            root_experiments_dir / sanitized if sanitized else root_experiments_dir
        )
        self.reports_dir = root_reports_dir / sanitized if sanitized else root_reports_dir
        self.duckdb_path = (
            Path(duckdb_path) if duckdb_path else self.base_dir / "quant_system.duckdb"
        )
        self._table_suffix = f"_{sanitized}" if sanitized else ""
        self.write_duckdb = write_duckdb

    def save_config(self, config: ExperimentConfig) -> Path:
        return self.save_json(
            config.model_dump(mode="json"),
            filename="experiment_config.json",
        )

    def save_json(self, payload: dict[str, Any], *, filename: str) -> Path:
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        path = self.experiments_dir / filename
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def save_frame(self, frame: pd.DataFrame, *, filename: str, table_name: str) -> Path:
        return save_parquet_artifact(
            frame,
            directory=self.experiments_dir,
            filename=filename,
            duckdb_path=self.duckdb_path,
            table_name=f"{table_name}{self._table_suffix}",
            write_duckdb=self.write_duckdb,
            quote_table_name=True,
        )

    def save_report(self, markdown: str, filename: str = "experiment_comparison_report.md") -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.reports_dir / filename
        path.write_text(markdown, encoding="utf-8")
        return path
