from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.data.pipeline import run_sample_ingestion
from quant_system.data.providers.csv import CSVDataProvider
from quant_system.data.storage import LocalDataStorage

runner = CliRunner()


def test_run_sample_ingestion_creates_phase_1_artifacts(tmp_path) -> None:
    result = run_sample_ingestion(
        symbols=["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-05",
        output_dir=tmp_path,
    )

    assert result.quality_passed is True
    assert result.row_count > 0
    assert result.parquet_path is not None and result.parquet_path.exists()
    assert result.duckdb_path is not None and result.duckdb_path.exists()
    assert result.quality_report_path.exists()


def test_run_sample_ingestion_skips_persistence_when_quality_fails(
    monkeypatch, tmp_path
) -> None:
    from quant_system.data import pipeline as pipeline_module
    from quant_system.data.validation import DataQualityIssue, DataQualityReport

    failing_report = DataQualityReport(
        passed=False,
        row_count=1,
        symbol_count=1,
        issues=[DataQualityIssue(check="forced", message="forced failure", row_count=1)],
    )
    monkeypatch.setattr(pipeline_module, "validate_ohlcv", lambda _frame: failing_report)

    result = run_sample_ingestion(
        symbols=["SPY"],
        start="2024-01-02",
        end="2024-01-03",
        output_dir=tmp_path,
    )

    assert result.quality_passed is False
    assert result.parquet_path is None
    assert result.duckdb_path is None
    assert result.quality_report_path.exists()
    # Storage should not have been created when quality fails.
    assert not (Path(tmp_path) / "parquet" / "ohlcv.parquet").exists()


def test_csv_provider_reads_local_ohlcv_file(tmp_path) -> None:
    csv_path = tmp_path / "ohlcv.csv"
    pd.DataFrame(
        {
            "symbol": ["SPY", "AAPL"],
            "timestamp": ["2024-01-02", "2024-01-02"],
            "open": [100.0, 190.0],
            "high": [101.0, 191.0],
            "low": [99.0, 189.0],
            "close": [100.5, 190.5],
            "volume": [1000, 2000],
        }
    ).to_csv(csv_path, index=False)

    provider = CSVDataProvider(csv_path)
    frame = provider.fetch_ohlcv(["SPY"], start="2024-01-01", end="2024-01-03")

    assert list(frame["symbol"]) == ["SPY"]
    assert frame.loc[0, "provider"] == "csv"


def test_data_ingest_sample_cli_runs_pipeline(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "data",
            "ingest-sample",
            "--symbol",
            "SPY",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-05",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "quality_passed=True" in result.output
    assert Path(tmp_path, "parquet", "ohlcv.parquet").exists()
    assert Path(tmp_path, "quant_system.duckdb").exists()


def test_local_storage_merges_with_existing_rows(tmp_path) -> None:
    storage = LocalDataStorage(base_dir=tmp_path)
    first = run_sample_ingestion(
        symbols=["SPY"],
        start="2024-01-02",
        end="2024-01-03",
        output_dir=tmp_path,
    )
    initial_rows = first.row_count

    second = run_sample_ingestion(
        symbols=["AAPL"],
        start="2024-01-02",
        end="2024-01-03",
        output_dir=tmp_path,
    )

    combined = storage.load_ohlcv()
    assert second.row_count > 0
    assert set(combined["symbol"]) == {"SPY", "AAPL"}
    assert len(combined) == initial_rows + second.row_count


def test_config_show_redacts_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("QS_ALPHA_VANTAGE_API_KEY", "do-not-print")

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "do-not-print" not in result.output
    assert "**********" in result.output
