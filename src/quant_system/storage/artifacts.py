from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def save_parquet_artifact(
    frame: pd.DataFrame,
    *,
    directory: str | Path,
    filename: str,
    duckdb_path: str | Path,
    table_name: str,
    write_duckdb: bool = True,
    quote_table_name: bool = False,
) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    persisted = frame.reset_index(drop=True)
    persisted.to_parquet(path, index=False)

    if write_duckdb:
        database_path = Path(duckdb_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        table_identifier = f'"{table_name}"' if quote_table_name else table_name
        with duckdb.connect(str(database_path)) as connection:
            connection.register("persisted_frame", persisted)
            connection.execute(
                f"CREATE OR REPLACE TABLE {table_identifier} AS SELECT * FROM persisted_frame"
            )

    return path
