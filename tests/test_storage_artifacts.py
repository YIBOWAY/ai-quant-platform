import duckdb
import pandas as pd

from quant_system.storage.artifacts import save_parquet_artifact


def test_save_parquet_artifact_resets_index_and_writes_quoted_duckdb_table(
    tmp_path,
) -> None:
    frame = pd.DataFrame({"symbol": ["SPY", "QQQ"], "value": [1.5, 2.5]}, index=[5, 9])
    duckdb_path = tmp_path / "db" / "artifacts.duckdb"

    path = save_parquet_artifact(
        frame,
        directory=tmp_path / "artifacts",
        filename="frame.parquet",
        duckdb_path=duckdb_path,
        table_name="experiment table",
        quote_table_name=True,
    )

    persisted = pd.read_parquet(path)
    assert list(persisted.columns) == ["symbol", "value"]
    assert persisted.to_dict(orient="records") == [
        {"symbol": "SPY", "value": 1.5},
        {"symbol": "QQQ", "value": 2.5},
    ]

    with duckdb.connect(str(duckdb_path)) as connection:
        rows = connection.execute(
            'SELECT symbol, value FROM "experiment table" ORDER BY symbol'
        ).fetchall()
    assert rows == [("QQQ", 2.5), ("SPY", 1.5)]
