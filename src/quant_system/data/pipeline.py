from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from quant_system.config.settings import load_settings
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider
from quant_system.data.storage import LocalDataStorage
from quant_system.data.validation import validate_ohlcv


class IngestionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    row_count: int
    quality_passed: bool
    parquet_path: Path | None
    duckdb_path: Path | None
    quality_report_path: Path


def _build_storage(output_dir: str | Path | None) -> LocalDataStorage:
    """Build a :class:`LocalDataStorage` honoring ``DataSettings`` overrides."""
    if output_dir is not None:
        return LocalDataStorage(base_dir=output_dir)
    data_settings = load_settings().data
    return LocalDataStorage(
        base_dir=data_settings.data_dir,
        parquet_dir=data_settings.parquet_dir,
        duckdb_path=data_settings.duckdb_path,
        reports_dir=data_settings.reports_dir,
    )


def _ingest(
    *,
    provider_name: str,
    frame,
    output_dir: str | Path | None,
    allow_failed_quality: bool,
) -> IngestionResult:
    storage = _build_storage(output_dir)
    quality_report = validate_ohlcv(frame)
    report_path = storage.save_quality_report(
        quality_report,
        filename=f"data_quality_report_{provider_name}.md",
    )

    if not quality_report.passed and not allow_failed_quality:
        return IngestionResult(
            row_count=len(frame),
            quality_passed=False,
            parquet_path=None,
            duckdb_path=None,
            quality_report_path=report_path,
        )

    artifacts = storage.save_ohlcv(frame)
    return IngestionResult(
        row_count=len(frame),
        quality_passed=quality_report.passed,
        parquet_path=artifacts.parquet_path,
        duckdb_path=artifacts.duckdb_path,
        quality_report_path=report_path,
    )


def run_sample_ingestion(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    allow_failed_quality: bool = False,
) -> IngestionResult:
    provider = SampleOHLCVProvider()
    frame = provider.fetch_ohlcv(symbols, start=start, end=end)
    return _ingest(
        provider_name="sample",
        frame=frame,
        output_dir=output_dir,
        allow_failed_quality=allow_failed_quality,
    )


def run_tiingo_ingestion(
    *,
    api_token: str,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    allow_failed_quality: bool = False,
) -> IngestionResult:
    provider = TiingoEODProvider(api_token=api_token)
    frame = provider.fetch_ohlcv(symbols, start=start, end=end)
    return _ingest(
        provider_name="tiingo",
        frame=frame,
        output_dir=output_dir,
        allow_failed_quality=allow_failed_quality,
    )
