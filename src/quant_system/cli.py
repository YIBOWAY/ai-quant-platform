from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from quant_system import __version__
from quant_system.config.settings import load_settings, reload_settings
from quant_system.data.pipeline import IngestionResult, run_sample_ingestion, run_tiingo_ingestion
from quant_system.logging.setup import configure_logging

_API_SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "finnhub_api_key",
        "alpha_vantage_api_key",
        "tiingo_api_token",
        "twelvedata_api_key",
        "polygon_api_key",
        "newsapi_key",
        "twitter_api_key",
        "twitter_api_key_secret",
        "twitter_bearer_token",
    }
)
_MANUAL_SECRET_FIELDS: frozenset[str] = frozenset({"manual_live_trading_confirmation"})

app = typer.Typer(
    help="AI quant research, backtesting, and paper-trading platform CLI.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Inspect local configuration.")
data_app = typer.Typer(help="Run Phase 1 data-layer commands.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show package version and exit.",
    ),
) -> None:
    """Run platform utility commands."""


def _mask_secrets(payload: Any) -> Any:
    """Recursively replace sensitive fields with a non-revealing marker."""
    if isinstance(payload, dict):
        return {
            key: (
                ("**********" if value else None)
                if key in _API_SECRET_FIELDS
                else ("<set>" if value else "<unset>")
                if key in _MANUAL_SECRET_FIELDS
                else _mask_secrets(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_mask_secrets(item) for item in payload]
    return payload


@config_app.command("show")
def show_config() -> None:
    """Print the effective local settings as JSON, with secrets masked."""
    settings = reload_settings()
    masked = _mask_secrets(settings.model_dump(mode="json"))
    typer.echo(json.dumps(masked, indent=2, sort_keys=True))


@app.command()
def doctor() -> None:
    """Run a lightweight Phase 0 health check."""
    settings = load_settings()
    configure_logging(settings.log_level)

    live_state = (
        "live trading enabled"
        if settings.safety.live_trading_enabled
        else "live trading disabled"
    )
    typer.echo("Phase 0 foundation is available")
    typer.echo(f"Safety mode: dry_run={settings.safety.dry_run}, {live_state}")
    typer.echo(f"Environment: {settings.environment}")


@data_app.command("ingest-sample")
def ingest_sample(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-01-05.")] = "",
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR settings.",
        ),
    ] = None,
    allow_failed_quality: Annotated[
        bool,
        typer.Option(
            "--allow-failed-quality",
            help="Persist Parquet/DuckDB even when data quality checks fail.",
        ),
    ] = False,
) -> None:
    """Generate deterministic sample OHLCV data and store local artifacts."""
    selected_symbols = symbols or ["SPY"]
    result = run_sample_ingestion(
        symbols=selected_symbols,
        start=start,
        end=end,
        output_dir=output_dir,
        allow_failed_quality=allow_failed_quality,
    )
    _emit_ingestion_summary(result)
    if not result.quality_passed and not allow_failed_quality:
        raise typer.Exit(code=1)


@data_app.command("ingest-tiingo")
def ingest_tiingo(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-01-05.")] = "",
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR settings.",
        ),
    ] = None,
    allow_failed_quality: Annotated[
        bool,
        typer.Option(
            "--allow-failed-quality",
            help="Persist Parquet/DuckDB even when data quality checks fail.",
        ),
    ] = False,
) -> None:
    """Download Tiingo EOD OHLCV data and store local artifacts."""
    settings = reload_settings()
    token = settings.api_keys.tiingo_api_token
    if token is None:
        raise typer.BadParameter("QS_TIINGO_API_TOKEN is not configured")
    result = run_tiingo_ingestion(
        api_token=token.get_secret_value(),
        symbols=symbols or ["SPY"],
        start=start,
        end=end,
        output_dir=output_dir,
        allow_failed_quality=allow_failed_quality,
    )
    _emit_ingestion_summary(result)
    if not result.quality_passed and not allow_failed_quality:
        raise typer.Exit(code=1)


app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")


def _emit_ingestion_summary(result: IngestionResult) -> None:
    typer.echo(
        " ".join(
            [
                f"quality_passed={result.quality_passed}",
                f"rows={result.row_count}",
                f"parquet={result.parquet_path or '<skipped>'}",
                f"duckdb={result.duckdb_path or '<skipped>'}",
                f"report={result.quality_report_path}",
            ]
        )
    )


if __name__ == "__main__":
    app()
