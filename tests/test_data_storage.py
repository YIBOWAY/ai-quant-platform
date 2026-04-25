from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.storage import LocalDataStorage
from quant_system.data.validation import validate_ohlcv


def test_local_storage_saves_and_reloads_parquet_and_duckdb(tmp_path) -> None:
    provider = SampleOHLCVProvider()
    frame = provider.fetch_ohlcv(["SPY", "AAPL"], start="2024-01-02", end="2024-01-05")
    storage = LocalDataStorage(base_dir=tmp_path)

    artifacts = storage.save_ohlcv(frame)
    reloaded = storage.load_ohlcv()
    duckdb_count = storage.count_duckdb_rows()

    assert artifacts.parquet_path.exists()
    assert artifacts.duckdb_path.exists()
    assert len(reloaded) == len(frame)
    assert duckdb_count == len(frame)
    assert set(reloaded["symbol"]) == {"AAPL", "SPY"}


def test_local_storage_writes_quality_report(tmp_path) -> None:
    provider = SampleOHLCVProvider()
    frame = provider.fetch_ohlcv(["SPY"], start="2024-01-02", end="2024-01-03")
    storage = LocalDataStorage(base_dir=tmp_path)
    report = validate_ohlcv(frame)

    report_path = storage.save_quality_report(report)

    assert report_path.exists()
    assert "Data Quality Report" in report_path.read_text(encoding="utf-8")
    assert "passed: true" in report_path.read_text(encoding="utf-8")

