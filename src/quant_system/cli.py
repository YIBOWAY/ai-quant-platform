from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
import typer

from quant_system import __version__
from quant_system.agent.llm.base import LLMClient
from quant_system.agent.llm.fixed import FixedContentLLMClient
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.agent.paths import (
    resolve_agent_output_dir,
    resolve_candidates_dir,
    resolve_legacy_candidates_dir,
)
from quant_system.agent.promotion import (
    CandidateLoadError,
    inspect_factor_candidate,
    load_approved_factor_candidate,
)
from quant_system.agent.runner import AgentRunner
from quant_system.api.safety.local_session import (
    bootstrap_token_path,
    issue_bootstrap_token,
)
from quant_system.backtest.pipeline import BacktestRunResult, run_sample_backtest
from quant_system.config.settings import load_settings, reload_settings
from quant_system.d34.cli import d34_app
from quant_system.data.pipeline import IngestionResult, run_sample_ingestion, run_tiingo_ingestion
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    read_historical_prices,
)
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.execution.pipeline import PaperTradingRunResult, run_sample_paper_trading
from quant_system.experiments.config import load_experiment_config
from quant_system.experiments.models import (
    CandidateResearchBinding,
    FactorBlendConfig,
    FactorWeight,
)
from quant_system.experiments.runner import (
    ExperimentResult,
    run_experiment,
    run_sample_experiment,
)
from quant_system.factors.lab import build_factor_lab_dashboard
from quant_system.factors.pipeline import FactorResearchResult, run_sample_factor_research
from quant_system.factors.registry import build_default_factor_registry, register_alpha101_library
from quant_system.hermes.connector_cli import hermes_app
from quant_system.logging.setup import configure_logging
from quant_system.options.buy_side_decision import (
    BuySideDecisionRequest,
    run_buy_side_decision,
)
from quant_system.options.data_refresh import (
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.market_regime import (
    VixRegimeSnapshot,
    load_market_regime,
)
from quant_system.options.models import (
    BuySideEventRisk,
    BuySideRiskPreference,
    BuySideViewType,
    BuySideVolatilityView,
    OptionsScreenerConfig,
)
from quant_system.options.radar import OptionsRadarConfig, run_options_radar
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.rate_limiter import RateLimitedFutuProvider, TokenBucket
from quant_system.options.sample_provider import SampleOptionsProvider
from quant_system.options.scan_lock import OptionsRadarScanLocked, options_radar_scan_lock
from quant_system.options.universe import OptionsUniverse
from quant_system.prediction_market.charts import (
    write_prediction_market_timeseries_charts,
)
from quant_system.prediction_market.collector import (
    PredictionMarketSnapshotCollector,
    ensure_no_polymarket_credentials_in_env,
    seed_sample_history_dataset,
)
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub
from quant_system.prediction_market.pipeline import run_dry_arbitrage, scan_market
from quant_system.prediction_market.provider_factory import build_prediction_market_provider
from quant_system.prediction_market.reporting import (
    write_phase12_timeseries_report,
    write_prediction_market_report,
)
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore
from quant_system.prediction_market.timeseries_backtest import (
    PredictionMarketTimeseriesBacktestConfig,
    run_prediction_market_timeseries_backtest,
)
from quant_system.storage.database import (
    get_database as _migrate_get_database,
)
from quant_system.storage.database import (
    list_migration_files,
    run_migrations,
    schema_fingerprint,
)
from quant_system.storage.options_cache import OptionQuotesCache

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
        "api_key",
    }
)
_MANUAL_SECRET_FIELDS: frozenset[str] = frozenset({"manual_live_trading_confirmation"})

app = typer.Typer(
    help="AI quant research, backtesting, and paper-trading platform CLI.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Inspect local configuration.")
data_app = typer.Typer(help="Run Phase 1 data-layer commands.")
factor_app = typer.Typer(help="Run Phase 2 factor-research commands.")
backtest_app = typer.Typer(help="Run Phase 3 backtest commands.")
experiment_app = typer.Typer(help="Run Phase 4 experiment-management commands.")
paper_app = typer.Typer(help="Run Phase 5 paper-trading commands.")
paper_strategies_app = typer.Typer(help="Manage Paper Strategy Sleeves strategy workflows.")
agent_app = typer.Typer(help="Run Phase 7 AI research assistant commands.")
prediction_market_app = typer.Typer(help="Run Phase 8 prediction-market dry scanning commands.")
options_app = typer.Typer(help="Run read-only options research commands.")
news_app = typer.Typer(help="Read-only AI news maintenance commands.")
brief_app = typer.Typer(help="Archive the daily morning brief into durable storage.")


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


def _parse_universe(value: str) -> list[str]:
    return [symbol.strip().upper() for symbol in value.split(",") if symbol.strip()]


def _parse_strategies(value: str) -> tuple[Literal["sell_put", "covered_call"], ...]:
    allowed = {"sell_put", "covered_call"}
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    invalid = [item for item in parsed if item not in allowed]
    if invalid:
        raise typer.BadParameter(f"unsupported strategies: {', '.join(invalid)}")
    return parsed or ("sell_put", "covered_call")


def _build_agent_llm(name: Literal["stub", "openai"]) -> LLMClient:
    if name == "stub":
        return StubLLMClient()
    from quant_system.agent.llm.openai_client import OpenAIClient

    try:
        return OpenAIClient()
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc


@config_app.command("show")
def show_config() -> None:
    """Print the effective local settings as JSON, with secrets masked."""
    settings = reload_settings()
    masked = _mask_secrets(settings.model_dump(mode="json"))
    typer.echo(json.dumps(masked, indent=2, sort_keys=True))


def _runtime_log_dir(settings) -> Path:
    return settings.data.data_dir / "_runtime" / "logs"


def _emit_json(payload: dict[str, Any]) -> None:
    """D-22 machine contract: exactly one JSON object on the last stdout line."""
    typer.echo(json.dumps(payload, sort_keys=True))


@contextmanager
def _futu_json_stdout_guard():
    """Keep Futu SDK lifecycle logs off a machine-readable stdout stream."""
    futu_console_logger = logging.getLogger("FTConsoleLog")
    was_disabled = futu_console_logger.disabled
    for handler in futu_console_logger.handlers:
        set_stream = getattr(handler, "setStream", None)
        if callable(set_stream) and sys.__stderr__ is not None:
            set_stream(sys.__stderr__)
    futu_console_logger.disabled = True
    try:
        yield
    finally:
        # The SDK may be imported lazily while the guarded call runs.
        for handler in futu_console_logger.handlers:
            set_stream = getattr(handler, "setStream", None)
            if callable(set_stream) and sys.__stderr__ is not None:
                set_stream(sys.__stderr__)
        futu_console_logger.disabled = was_disabled


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Append a machine-readable JSON summary line."),
    ] = False,
) -> None:
    """Print an offline local platform health summary."""
    settings = load_settings()
    logger = configure_logging(settings.log_level, log_dir=_runtime_log_dir(settings))
    logger.info("doctor health check started")

    log_path = _runtime_log_dir(settings) / "backend.jsonl"
    database_url_state = "configured" if settings.database.url else "unset"
    tiingo_state = "configured" if settings.api_keys.tiingo_api_token else "unset"

    typer.echo("Quant System local health")
    typer.echo(f"environment={settings.environment}")
    typer.echo(f"safety.dry_run={str(settings.safety.dry_run).lower()}")
    typer.echo(f"safety.paper_trading={str(settings.safety.paper_trading).lower()}")
    typer.echo(f"safety.live_trading_enabled={str(settings.safety.live_trading_enabled).lower()}")
    typer.echo(f"safety.kill_switch={str(settings.safety.kill_switch).lower()}")
    typer.echo(f"data.default_provider={settings.data.default_data_provider}")
    typer.echo(f"data.data_dir={settings.data.data_dir}")
    typer.echo(
        f"futu.enabled={str(settings.futu.enabled).lower()} "
        f"host={settings.futu.host} port={settings.futu.port} "
        f"market={settings.futu.market}"
    )
    typer.echo(f"tiingo.token={tiingo_state}")
    typer.echo(
        f"database.enabled={str(settings.database.enabled).lower()} "
        f"url={database_url_state} "
        f"connect_timeout_seconds={settings.database.connect_timeout_seconds} "
        f"auto_migrate={str(settings.database.auto_migrate).lower()}"
    )
    typer.echo(f"runtime.log={log_path}")
    if json_output:
        _emit_json(
            {
                "environment": settings.environment,
                "safety": {
                    "dry_run": settings.safety.dry_run,
                    "paper_trading": settings.safety.paper_trading,
                    "live_trading_enabled": settings.safety.live_trading_enabled,
                    "kill_switch": settings.safety.kill_switch,
                },
                "ok": True,
            }
        )


@app.command("owner-bootstrap-token")
def owner_bootstrap_token(
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Backend data directory that owns the 0600 security token file.",
        ),
    ] = None,
    rotate: Annotated[
        bool,
        typer.Option(
            "--rotate",
            help="Invalidate the current one-time token and create a replacement.",
        ),
    ] = False,
) -> None:
    """Print an owner-only one-time token for explicit Web bootstrap."""

    settings = reload_settings()
    output_dir = data_dir if data_dir is not None else settings.data.data_dir
    token = issue_bootstrap_token(output_dir, force_rotate=rotate)
    typer.echo(
        f"owner bootstrap token file: {bootstrap_token_path(output_dir)} (0600)",
        err=True,
    )
    # This explicit operator command is the only secret-output boundary. Keep
    # stdout to the token alone so a browser can exchange it exactly once.
    typer.echo(token)


@app.command("migrate")
def migrate(
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Actually apply the allowlisted migrations (default is a dry-run plan).",
        ),
    ] = False,
    allow: Annotated[
        list[str] | None,
        typer.Option(
            "--allow",
            help="Migration file name to apply (repeatable). Required for --apply.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Confirm a non-interactive apply. Required for --apply when stdin is not a TTY.",
        ),
    ] = False,
) -> None:
    """Plan or apply database migrations explicitly (fail-closed; V1.1).

    Startup never auto-applies migrations (``QS_DATABASE_AUTO_MIGRATE`` defaults
    to false). By default this command is a **dry-run**: it lists the migration
    files an apply would touch and prints the current schema fingerprint without
    changing anything. Applying requires ``--apply`` plus an explicit ``--allow``
    allowlist, and a non-interactive apply additionally requires ``--yes``. The
    schema fingerprint is printed before and after so an authorized apply can be
    audited against exactly what changed.
    """
    settings = load_settings()
    database = _migrate_get_database(settings)

    candidates = list_migration_files(only=allow if allow else None)
    fingerprint_before = schema_fingerprint(database)

    if not apply:
        typer.echo("migrate: dry-run (no changes applied)")
        typer.echo(f"database.enabled={str(settings.database.enabled).lower()}")
        typer.echo(f"schema_fingerprint_before={fingerprint_before}")
        if allow:
            typer.echo("allowlist=" + ",".join(allow))
        if not candidates:
            typer.echo("no migration files matched")
        for name in candidates:
            typer.echo(f"would_apply={name}")
        typer.echo("re-run with --apply --allow <file> [--yes] to apply an allowlist")
        return

    # Fail-closed apply path.
    if not allow:
        typer.echo("error: --apply requires at least one --allow <file> allowlist entry")
        raise typer.Exit(code=2)
    if not sys.stdin.isatty() and not yes:
        typer.echo("error: non-interactive --apply requires --yes")
        raise typer.Exit(code=2)

    matched = set(candidates)
    unknown = [name for name in allow if name not in matched]
    if unknown:
        typer.echo(
            "error: allowlist entries did not match any migration file: "
            + ", ".join(sorted(unknown))
        )
        raise typer.Exit(code=2)

    unavailable_fingerprints = {"<db-disabled>", "<unavailable>"}
    if fingerprint_before in unavailable_fingerprints:
        typer.echo(f"schema_fingerprint_before={fingerprint_before}")
        typer.echo(
            "error: schema fingerprint unavailable before apply; "
            "no migrations were applied"
        )
        raise typer.Exit(code=2)

    typer.echo(f"schema_fingerprint_before={fingerprint_before}")
    for name in candidates:
        typer.echo(f"applying={name}")
    run_migrations(database, only=set(allow))
    fingerprint_after = schema_fingerprint(database)
    typer.echo(f"schema_fingerprint_after={fingerprint_after}")
    if fingerprint_after in unavailable_fingerprints:
        typer.echo(
            "error: schema fingerprint unavailable after apply; "
            "migration outcome requires operator review"
        )
        raise typer.Exit(code=1)
    typer.echo("migrate: applied allowlisted migration(s)")


@app.command("serve")
def serve_api(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address for the local API server."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port for the local API server."),
    ] = 8765,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Reload the API server when source files change."),
    ] = False,
    bind_public: Annotated[
        bool,
        typer.Option(
            "--bind-public",
            help="Allow binding to 0.0.0.0 after explicit environment confirmation.",
        ),
    ] = False,
) -> None:
    """Start the Phase 9 localhost HTTP API."""
    settings = load_settings()
    logger = configure_logging(settings.log_level, log_dir=_runtime_log_dir(settings))
    logger.info("api server starting", extra={"host": host, "port": port})
    if host == "0.0.0.0":
        if not bind_public:
            raise typer.BadParameter("0.0.0.0 requires --bind-public")
        if os.getenv("QS_API_ALLOW_PUBLIC_BIND") != "I_UNDERSTAND":
            raise typer.BadParameter("0.0.0.0 requires QS_API_ALLOW_PUBLIC_BIND=I_UNDERSTAND")
        os.environ["QS_API_BIND_PUBLIC_CONFIRMED"] = "I_UNDERSTAND"
    os.environ["QS_API_BIND_ADDRESS"] = host

    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter(
            'API dependencies are missing. Install with: pip install -e ".[api]"'
        ) from exc
    uvicorn.run(
        "quant_system.api.server:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


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


@data_app.command("asia-radar-refresh")
def data_asia_radar_refresh(
    snapshot_dir: Annotated[
        str | None,
        typer.Option(
            "--snapshot-dir",
            help=(
                "Directory for daily Asia Radar overview snapshots. "
                "Defaults to <data>/api_runs/asia_radar."
            ),
        ),
    ] = None,
    cache_path: Annotated[
        str | None,
        typer.Option(
            "--cache-path",
            help="Override EquityBarCache DuckDB path. Defaults to <data>/futu_equity_bars.duckdb.",
        ),
    ] = None,
    write_snapshot: Annotated[
        bool,
        typer.Option(
            "--write-snapshot/--no-write-snapshot",
            help="Persist the daily overview JSON snapshot after refreshing bars.",
        ),
    ] = True,
) -> None:
    """Refresh the fixed 12-ETF Asia Radar universe into the bar cache and persist today's overview.

    Read-only research utility: it never places orders, mutates accounts, or
    falls back to sample data. Failure exits non-zero and keeps the previous
    snapshot.
    """
    from quant_system.factors.asia_radar import read_asia_radar_overview

    try:
        settings = load_settings()
    except Exception as exc:
        error = HistoricalPriceReadError(
            code="historical_prices_configuration_error",
            message="platform settings are invalid for Asia Radar refresh",
            provider_code=type(exc).__name__,
        )
        _emit_json({"ok": False, "error": error.to_dict()})
        raise typer.Exit(code=1) from exc

    output_root = (
        Path(snapshot_dir)
        if snapshot_dir is not None
        else Path(settings.data.data_dir) / "api_runs" / "asia_radar"
    )
    try:
        with _futu_json_stdout_guard():
            overview = read_asia_radar_overview(
                settings=settings,
                cache=True,
                cache_path=cache_path,
            )
    except HistoricalPriceReadError as exc:
        _emit_json({"ok": False, "error": exc.to_dict()})
        raise typer.Exit(code=1) from exc

    snapshot_path: str | None = None
    if write_snapshot:
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            target = output_root / f"{overview['as_of']}.json"
            payload = dict(overview)
            payload["snapshot_written_at"] = pd.Timestamp.now(tz="UTC").isoformat()
            target.write_text(
                json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
                encoding="utf-8",
            )
            snapshot_path = str(target)
        except OSError as exc:
            error = HistoricalPriceReadError(
                code="asia_radar_snapshot_write_failed",
                message=f"failed to persist Asia Radar snapshot: {exc}",
            )
            _emit_json({"ok": False, "error": error.to_dict()})
            raise typer.Exit(code=1) from exc

    _emit_json(
        {
            "ok": True,
            "as_of": overview["as_of"],
            "timezone": overview["timezone"],
            "provenance": overview["provenance"],
            "market_count": len(overview.get("markets", [])),
            "snapshot_path": snapshot_path,
        }
    )


@data_app.command("etf-bars-backup-refresh")
def data_etf_bars_backup_refresh(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help=(
                "US-listed ETF to refresh. Repeat for multiple symbols. "
                "Defaults to the 12-ETF Asia Radar universe."
            ),
        ),
    ] = None,
    start: Annotated[
        str,
        typer.Option("--start", help="Inclusive start date, YYYY-MM-DD. Default: lookback window."),
    ] = "",
    end: Annotated[
        str,
        typer.Option(
            "--end",
            help="Inclusive end date, YYYY-MM-DD. Default: last completed US session.",
        ),
    ] = "",
    backup_providers: Annotated[
        list[str] | None,
        typer.Option(
            "--backup-provider",
            help=(
                "Explicit backup lane, in fallback order (twelvedata, tiingo). "
                "Repeat for multiple lanes. Backups only run after Futu fails."
            ),
        ),
    ] = None,
    lookback_days: Annotated[
        int,
        typer.Option(
            "--lookback-days",
            help="Calendar days of history when --start/--end are not given.",
        ),
    ] = 419,
    cache_path: Annotated[
        str | None,
        typer.Option(
            "--cache-path",
            help="Override EquityBarCache DuckDB path. Defaults to <data>/futu_equity_bars.duckdb.",
        ),
    ] = None,
) -> None:
    """Refresh Asia ETF daily bars through the explicit backup chain (disaster recovery).

    On-demand operator command: it is NOT wired into the daily LaunchAgent.
    Futu is always tried first; the named backup lanes run only after Futu
    fails, and the JSON output records exactly which lane served and why each
    earlier lane was skipped. Read-only: never places orders, never falls back
    to sample data. Failure exits non-zero.
    """
    from quant_system.data.backup_bars import (
        SUPPORTED_BACKUP_PROVIDERS,
        default_backup_window,
        read_daily_bars_with_backup,
    )
    from quant_system.data.equity_bar_cache import EquityBarCache
    from quant_system.factors.asia_radar import ASIA_ETF_SYMBOLS

    try:
        settings = load_settings()
    except Exception as exc:
        error = HistoricalPriceReadError(
            code="historical_prices_configuration_error",
            message="platform settings are invalid for ETF bars backup refresh",
            provider_code=type(exc).__name__,
        )
        _emit_json({"ok": False, "error": error.to_dict()})
        raise typer.Exit(code=1) from exc

    if not start or not end:
        default_start, default_end = default_backup_window(
            lookback_calendar_days=lookback_days
        )
        start = start or default_start
        end = end or default_end

    active_cache: EquityBarCache | None
    try:
        active_cache = EquityBarCache(
            Path(cache_path)
            if cache_path is not None
            else Path(settings.data.duckdb_path).parent / "futu_equity_bars.duckdb"
        )
    except Exception:  # noqa: BLE001 - optional cache must never block the refresh
        active_cache = None

    try:
        with _futu_json_stdout_guard():
            result = read_daily_bars_with_backup(
                settings=settings,
                symbols=list(symbols or ASIA_ETF_SYMBOLS),
                start=start,
                end=end,
                backup_providers=tuple(backup_providers or SUPPORTED_BACKUP_PROVIDERS),
                cache=active_cache,
            )
    except HistoricalPriceReadError as exc:
        _emit_json({"ok": False, "error": exc.to_dict()})
        raise typer.Exit(code=2 if exc.code == "historical_prices_invalid_request" else 1) from exc

    snapshot = result.snapshot
    _emit_json(
        {
            "ok": True,
            "served_by": result.served_by,
            "provider": snapshot.provider,
            "source": snapshot.source,
            "adjustment": snapshot.adjustment,
            "start": snapshot.start,
            "end": snapshot.end,
            "fetched_at": snapshot.fetched_at,
            "symbols": snapshot.symbols,
            "row_counts": {
                item["symbol"]: item["row_count"] for item in snapshot.series
            },
            "fallbacks": result.fallbacks,
        }
    )


@data_app.command("prices")
def data_prices(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="US ticker to read. Repeat for multiple symbols (max 25).",
        ),
    ] = None,
    start: Annotated[
        str,
        typer.Option("--start", help="Inclusive start date, YYYY-MM-DD."),
    ] = "",
    end: Annotated[
        str,
        typer.Option("--end", help="Inclusive end date, YYYY-MM-DD."),
    ] = "",
    provider: Annotated[
        str,
        typer.Option("--provider", help="Must be explicit: futu."),
    ] = "",
    adjustment: Annotated[
        str,
        typer.Option("--adjustment", help="Must be qfq."),
    ] = "qfq",
    output_format: Annotated[
        Literal["json"],
        typer.Option("--format", help="Machine-readable output format."),
    ] = "json",
) -> None:
    """Read strict multi-symbol Futu QFQ daily history without persistence."""
    del output_format  # Literal keeps the CLI contract JSON-only.
    try:
        settings = load_settings()
    except Exception as exc:
        error = HistoricalPriceReadError(
            code="historical_prices_configuration_error",
            message="platform settings are invalid for historical price reads",
            provider_code=type(exc).__name__,
        )
        typer.echo(
            json.dumps(
                {"error": error.to_dict()},
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from exc
    try:
        with _futu_json_stdout_guard():
            snapshot = read_historical_prices(
                settings=settings,
                symbols=symbols or [],
                start=start,
                end=end,
                provider=provider,
                interval="1d",
                adjustment=adjustment,
            )
    except HistoricalPriceReadError as exc:
        typer.echo(
            json.dumps(
                {"error": exc.to_dict()},
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2 if exc.code == "historical_prices_invalid_request" else 1) from exc
    except Exception as exc:
        error = HistoricalPriceReadError(
            code="historical_prices_internal_error",
            message=f"historical price read failed: {type(exc).__name__}",
        )
        typer.echo(
            json.dumps(
                {"error": error.to_dict()},
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            snapshot.to_dict(),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )


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


@factor_app.command("list")
def list_factors() -> None:
    """List registered Phase 2 research factors."""
    registry = build_default_factor_registry()
    for metadata in registry.list_metadata():
        typer.echo(
            " ".join(
                [
                    f"factor_id={metadata.factor_id}",
                    f"name={metadata.factor_name}",
                    f"version={metadata.factor_version}",
                    f"lookback={metadata.lookback}",
                    f"direction={metadata.direction}",
                ]
            )
        )


@factor_app.command("register-library")
def register_factor_library(
    name: Annotated[
        Literal["alpha101"],
        typer.Option("--name", help="Optional factor library to register explicitly."),
    ],
) -> None:
    """Register and display an optional factor library for this CLI invocation."""
    registry = build_default_factor_registry()
    before = set(registry.factor_ids())
    if name == "alpha101":
        register_alpha101_library(registry)
    registered_ids = [factor_id for factor_id in registry.factor_ids() if factor_id not in before]
    typer.echo(
        f"library={name} registered_factors={len(registered_ids)} "
        f"total_factors={len(registry.factor_ids())}"
    )
    for factor_id in registered_ids:
        metadata = registry.create(factor_id).metadata
        typer.echo(
            " ".join(
                [
                    f"factor_id={metadata.factor_id}",
                    f"name={metadata.factor_name}",
                    f"version={metadata.factor_version}",
                    f"lookback={metadata.lookback}",
                    f"direction={metadata.direction}",
                ]
            )
        )


@factor_app.command("run-sample")
def run_sample_factors(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-02-15.")] = "",
    lookback: Annotated[
        int,
        typer.Option(help="Trailing window used by the example factors."),
    ] = 20,
    quantiles: Annotated[
        int,
        typer.Option(help="Number of buckets for quantile return analysis."),
    ] = 5,
    source: Annotated[
        Literal["sample"],
        typer.Option("--source", help="Data source for this sample research run."),
    ] = "sample",
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
) -> None:
    """Run the Phase 2 sample factor research pipeline."""
    if source == "sample":
        typer.secho(
            "sample data 是确定性合成序列，RSI/MACD 等振荡类因子的统计意义有限，"
            "请用 Tiingo 数据复核",
            fg=typer.colors.YELLOW,
            err=True,
        )
    result = run_sample_factor_research(
        symbols=symbols or ["SPY", "AAPL", "QQQ"],
        start=start,
        end=end,
        output_dir=output_dir,
        lookback=lookback,
        quantiles=quantiles,
    )
    _emit_factor_summary(result)


@factor_app.command("refresh-lab")
def refresh_factor_lab(
    provider: Annotated[
        Literal["sample", "futu", "tiingo"],
        typer.Option("--provider", help="Read-only OHLCV provider for the refresh."),
    ] = "sample",
    universe_id: Annotated[
        str,
        typer.Option("--universe-id", help="Registered universe id to diagnose."),
    ] = "etf",
    symbol: Annotated[
        str,
        typer.Option("--symbol", help="Single-symbol timing ticker."),
    ] = "QQQ",
    benchmark_symbol: Annotated[
        str,
        typer.Option("--benchmark-symbol", help="Display benchmark ticker."),
    ] = "QQQ",
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "2024-01-02",
    end: Annotated[str, typer.Option(help="End date, for example 2024-12-31.")] = "2024-12-31",
    lookback: Annotated[
        int,
        typer.Option(help="Trailing window used by registered factors."),
    ] = 20,
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR setting.",
        ),
    ] = None,
) -> None:
    """Refresh the read-only Factor Lab dashboard cache for scheduled jobs."""
    settings = reload_settings()
    payload = build_factor_lab_dashboard(
        settings=settings,
        output_dir=output_dir or settings.data.data_dir,
        provider=provider,
        universe_id=universe_id,
        symbol=symbol,
        benchmark_symbol=benchmark_symbol,
        start=start,
        end=end,
        lookback=lookback,
        force_refresh=True,
    )
    typer.echo(
        " ".join(
            [
                f"cache_status={payload.get('cache', {}).get('status', '<unknown>')}",
                f"cache_path={payload.get('cache', {}).get('path', '<unknown>')}",
                f"universe={payload.get('universe', {}).get('id', universe_id)}",
                f"symbol={payload.get('timing', {}).get('symbol', symbol.upper())}",
                f"benchmark={payload.get('benchmark_symbol', benchmark_symbol.upper())}",
                f"cross_rows={len(payload.get('cross_sectional', {}).get('rows', []))}",
                f"timing_rows={len(payload.get('timing', {}).get('rows', []))}",
            ]
        )
    )


@backtest_app.command("run-sample")
def run_sample_backtest_command(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-02-15.")] = "",
    lookback: Annotated[
        int,
        typer.Option(help="Trailing window used by the Phase 2 factors."),
    ] = 20,
    top_n: Annotated[
        int,
        typer.Option("--top-n", help="Number of highest-scoring symbols to hold."),
    ] = 3,
    initial_cash: Annotated[
        float,
        typer.Option("--initial-cash", help="Starting cash for the backtest."),
    ] = 100_000.0,
    commission_bps: Annotated[
        float,
        typer.Option("--commission-bps", help="Commission in basis points."),
    ] = 1.0,
    slippage_bps: Annotated[
        float,
        typer.Option("--slippage-bps", help="Slippage in basis points."),
    ] = 5.0,
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
) -> None:
    """Run the Phase 3 sample backtest pipeline."""
    result = run_sample_backtest(
        symbols=symbols or ["SPY", "AAPL", "QQQ"],
        start=start,
        end=end,
        output_dir=output_dir,
        lookback=lookback,
        top_n=top_n,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    _emit_backtest_summary(result)


@experiment_app.command("run-sample")
def run_sample_experiment_command(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-03-15.")] = "",
    lookbacks: Annotated[
        list[int] | None,
        typer.Option("--lookback", help="Lookback value. Repeat for parameter sweep."),
    ] = None,
    top_ns: Annotated[
        list[int] | None,
        typer.Option("--top-n", help="Top N value. Repeat for parameter sweep."),
    ] = None,
    rebalance_every_n_bars: Annotated[
        int,
        typer.Option(
            "--rebalance-every-n-bars",
            help="Keep one rebalance date every N available bars.",
        ),
    ] = 1,
    initial_cash: Annotated[
        float,
        typer.Option("--initial-cash", help="Starting cash for each backtest."),
    ] = 100_000.0,
    commission_bps: Annotated[
        float,
        typer.Option("--commission-bps", help="Commission in basis points."),
    ] = 1.0,
    slippage_bps: Annotated[
        float,
        typer.Option("--slippage-bps", help="Slippage in basis points."),
    ] = 5.0,
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
) -> None:
    """Run a Phase 4 sample parameter-sweep experiment."""
    result = run_sample_experiment(
        symbols=symbols or ["SPY", "AAPL", "QQQ"],
        start=start,
        end=end,
        lookbacks=lookbacks or [3, 5],
        top_ns=top_ns or [1, 2],
        output_dir=output_dir,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        rebalance_every_n_bars=rebalance_every_n_bars,
    )
    _emit_experiment_summary(result)


@experiment_app.command("run-config")
def run_config_experiment_command(
    config_path: Annotated[
        str,
        typer.Option("--config", help="Path to an experiment JSON config file."),
    ],
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
    provider: Annotated[
        Literal["sample", "futu", "tiingo"],
        typer.Option("--provider", help="OHLCV data provider for the experiment."),
    ] = "sample",
    candidate_id: Annotated[
        str | None,
        typer.Option(
            "--candidate-id",
            help="Exact approved candidate to load for one-shot research.",
        ),
    ] = None,
    expected_candidate_digest: Annotated[
        str | None,
        typer.Option(
            "--expected-digest",
            help="Exact manifest digest of --candidate-id.",
        ),
    ] = None,
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent output root used with the exact candidate selector. "
                "Normalized by resolve_agent_output_dir; candidates live under "
                "agent/candidates. Defaults to QS_AGENT_OUTPUT_DIR or the repo "
                "canonical agent_run root."
            ),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Append a machine-readable JSON summary line."),
    ] = False,
) -> None:
    """Run a Phase 4 experiment from a JSON config file."""
    if (
        expected_candidate_digest is not None
        and re.fullmatch(r"[0-9a-f]{64}", expected_candidate_digest) is None
    ):
        raise typer.BadParameter(
            "--expected-digest must be a lowercase 64-character SHA-256 digest"
        )
    if (candidate_id is None) != (expected_candidate_digest is None):
        raise typer.BadParameter(
            "--candidate-id and --expected-digest must be supplied together"
        )
    config = load_experiment_config(config_path)
    if config.candidate_binding is not None and candidate_id is None:
        raise typer.BadParameter(
            "candidate_binding is derived evidence; supply --candidate-id and "
            "--expected-digest instead of declaring it in an ordinary config"
        )
    settings = reload_settings()
    provider_instance, data_source = build_ohlcv_provider(settings, requested=provider)
    factor_registry = None
    loaded: list[str] = []
    candidate_binding: CandidateResearchBinding | None = None
    if candidate_id is not None and expected_candidate_digest is not None:
        from quant_system.agent.candidate_manifest import (
            CandidateIntegrityError,
            CandidateStaleError,
        )

        factor_registry = build_default_factor_registry()
        active_agent_root = resolve_agent_output_dir(agent_output_dir)
        try:
            binding = load_approved_factor_candidate(
                factor_registry,
                agent_output_dir=active_agent_root,
                candidate_id=candidate_id,
                expected_manifest_digest=expected_candidate_digest,
            )
        except (
            CandidateIntegrityError,
            CandidateLoadError,
            CandidateStaleError,
            OSError,
            UnicodeDecodeError,
        ) as exc:
            typer.echo(f"candidate_load_refused reason={exc}")
            raise typer.Exit(code=1) from exc
        candidate_binding = CandidateResearchBinding(
            candidate_id=binding.candidate_id,
            manifest_digest=binding.manifest_digest,
            factor_id=binding.factor_id,
        )
        config = config.model_copy(
            update={
                "factor_blend": FactorBlendConfig(
                    factors=[FactorWeight(factor_id=binding.factor_id)],
                    rebalance_every_n_bars=config.factor_blend.rebalance_every_n_bars,
                ),
                "candidate_binding": candidate_binding,
            }
        )
        loaded = [binding.factor_id]
        typer.echo(f"approved_candidate_loaded={binding.factor_id}")
    result = run_experiment(
        config,
        output_dir=output_dir,
        provider=provider_instance,
        data_source=data_source,
        factor_registry=factor_registry,
    )
    _emit_experiment_summary(result)
    if json_output:
        config_bytes = result.config_path.read_bytes()
        agent_summary_bytes = result.agent_summary_path.read_bytes()
        report_bytes = result.report_path.read_bytes()
        _emit_json(
            {
                "experiment_id": result.experiment_id,
                "run_count": result.run_count,
                "best_run_id": result.best_run_id,
                "data_source": result.data_source,
                "config": str(result.config_path),
                "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
                "agent_summary": str(result.agent_summary_path),
                "agent_summary_sha256": hashlib.sha256(
                    agent_summary_bytes
                ).hexdigest(),
                "report": str(result.report_path),
                "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                "approved_candidates_loaded": loaded,
                "candidate_binding": (
                    candidate_binding.model_dump(mode="json")
                    if candidate_binding is not None
                    else None
                ),
            }
        )


@paper_app.command("run-sample")
def run_sample_paper_command(
    symbols: Annotated[
        list[str] | None,
        typer.Option(
            "--symbol",
            "-s",
            help="Symbol to include. Repeat the option for multiple symbols.",
        ),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date, for example 2024-01-02.")] = "",
    end: Annotated[str, typer.Option(help="End date, for example 2024-01-12.")] = "",
    initial_cash: Annotated[
        float,
        typer.Option("--initial-cash", help="Starting cash for the paper account."),
    ] = 100_000.0,
    max_position_size: Annotated[
        float,
        typer.Option("--max-position-size", help="Maximum single-symbol position share."),
    ] = 0.50,
    max_order_value: Annotated[
        float,
        typer.Option("--max-order-value", help="Maximum notional value per order."),
    ] = 20_000.0,
    max_daily_loss: Annotated[
        float,
        typer.Option("--max-daily-loss", help="Maximum daily loss share."),
    ] = 0.02,
    max_drawdown: Annotated[
        float,
        typer.Option("--max-drawdown", help="Maximum drawdown share."),
    ] = 0.10,
    allowed_symbols: Annotated[
        list[str] | None,
        typer.Option("--allowed-symbol", help="Allowed symbol. Repeat to build allowlist."),
    ] = None,
    blocked_symbols: Annotated[
        list[str] | None,
        typer.Option("--blocked-symbol", help="Blocked symbol. Repeat to build blocklist."),
    ] = None,
    kill_switch: Annotated[
        bool | None,
        typer.Option(
            "--kill-switch/--no-kill-switch",
            help=(
                "Set replay kill switch for this paper run. "
                "--no-kill-switch is rejected while QS_KILL_SWITCH is true."
            ),
        ),
    ] = None,
    max_fill_ratio_per_tick: Annotated[
        float,
        typer.Option("--max-fill-ratio-per-tick", help="Partial fill ratio per tick."),
    ] = 1.0,
    output_dir: Annotated[
        str | None,
        typer.Option(
            help="Override output directory. Defaults to QS_DATA_DIR/QS_REPORTS_DIR settings.",
        ),
    ] = None,
) -> None:
    """Run the Phase 5 sample paper-trading loop."""
    settings = load_settings()
    if settings.safety.kill_switch and kill_switch is False:
        typer.echo("Global kill switch is enabled; CLI paper replay cannot disable the kill switch")
        raise typer.Exit(code=1)

    result = run_sample_paper_trading(
        symbols=symbols or ["SPY", "AAPL"],
        start=start,
        end=end,
        output_dir=output_dir,
        initial_cash=initial_cash,
        max_position_size=max_position_size,
        max_order_value=max_order_value,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
        allowed_symbols=allowed_symbols or [],
        blocked_symbols=blocked_symbols or [],
        kill_switch=kill_switch,
        max_fill_ratio_per_tick=max_fill_ratio_per_tick,
    )
    _emit_paper_summary(result)


@paper_app.command("rebalance")
def paper_account_rebalance_command(
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help="Strategy id: cross_sectional_top_n or mean_reversion_top_n.",
        ),
    ] = "cross_sectional_top_n",
    account_id: Annotated[
        str,
        typer.Option("--account", help="Account id to rebalance."),
    ] = "default",
    symbols: Annotated[
        list[str] | None,
        typer.Option("--symbol", "-s", help="Candidate symbol. Repeat for multiple."),
    ] = None,
    lookback: Annotated[int, typer.Option("--lookback", help="Factor lookback window.")] = 20,
    top_n: Annotated[int, typer.Option("--top-n", help="Number of names to hold.")] = 3,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Real-data provider: futu or tiingo."),
    ] = None,
) -> None:
    """Rebalance a persistent paper ACCOUNT to a strategy's latest target weights.

    Designed to be run on a schedule (e.g. Windows Task Scheduler) so the
    account auto-trades each trading day. Simulation only: no real orders.
    """
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.account_service import (
        AccountFrozenError,
        PaperAccountService,
        StrategyDataUnavailableError,
    )
    from quant_system.execution.price_source import PriceUnavailableError

    settings = load_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    storage = build_paper_account_repository(
        api_runs_dir,
        settings=settings,
        account_id=account_id,
    )
    service = PaperAccountService(settings=settings)
    with storage.mutation_lock():
        account = storage.load_or_open()
        try:
            outcome = service.rebalance_to_strategy(
                account,
                strategy_id=strategy,
                symbols=symbols or ["SPY", "QQQ", "IWM", "DIA"],
                lookback=lookback,
                top_n=top_n,
                provider=provider,
            )
        except AccountFrozenError as exc:
            typer.echo(f"account frozen: {exc}")
            raise typer.Exit(code=1) from exc
        except (PriceUnavailableError, StrategyDataUnavailableError, ValueError) as exc:
            typer.echo(f"rebalance unavailable: {exc}")
            raise typer.Exit(code=1) from exc
        storage.save(account)
    if outcome.aborted:
        typer.echo(f"rebalance ABORTED, no orders applied: {outcome.note}")
        raise typer.Exit(code=1)
    failed = [o for o in outcome.orders if o.status not in ("filled", "skipped")]
    filled = sum(1 for order in outcome.orders if order.status == "filled")
    typer.echo(
        f"rebalanced account {account_id!r} to {outcome.strategy_id} "
        f"(as_of={outcome.as_of}): {filled}/{len(outcome.orders)} legs filled"
    )
    if outcome.note:
        typer.echo(outcome.note)
    typer.echo(f"cash={account.cash:.2f} positions={len(account.positions)}")
    if failed:
        for order in failed:
            typer.echo(
                f"  FAILED {order.symbol} {order.side} {order.status}: {order.rejected_reason}"
            )
        raise typer.Exit(code=1)


@paper_app.command("account-show")
def paper_account_show_command(
    account_id: Annotated[
        str,
        typer.Option("--account", help="Account id to display."),
    ] = "default",
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", help="Output format."),
    ] = "text",
) -> None:
    """Print a persistent paper account's cash and positions."""
    from quant_system.execution.account_repository import (
        PaperAccountBootstrapRequired,
    )
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.account_snapshot import (
        PaperAccountSnapshotReader,
        PaperAccountSnapshotReadError,
    )

    settings = load_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    try:
        storage = build_paper_account_repository(
            api_runs_dir,
            settings=settings,
            account_id=account_id,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    futu_console_logger = logging.getLogger("FTConsoleLog")
    futu_console_was_disabled = futu_console_logger.disabled
    if output_format == "json":
        # Futu OpenAPI binds its own console handler to stdout. Keep a machine-
        # readable CLI contract by moving lifecycle logs to stderr and silencing
        # synchronous provider logs while the payload is materialised.
        for handler in futu_console_logger.handlers:
            set_stream = getattr(handler, "setStream", None)
            if callable(set_stream) and sys.__stderr__ is not None:
                set_stream(sys.__stderr__)
        futu_console_logger.disabled = True
    try:
        snapshot = PaperAccountSnapshotReader(
            repository=storage,
            settings=settings,
        ).read()
    except (PaperAccountSnapshotReadError, PaperAccountBootstrapRequired) as exc:
        if output_format == "json":
            typer.echo(
                json.dumps(
                    {"error": {"code": exc.code, "message": str(exc)}},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(f"{exc.code}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if output_format == "json":
            # The SDK is imported lazily during the read, so its handler may
            # only exist now. Rebind it before asynchronous disconnect logs run.
            for handler in futu_console_logger.handlers:
                set_stream = getattr(handler, "setStream", None)
                if callable(set_stream) and sys.__stderr__ is not None:
                    set_stream(sys.__stderr__)
            futu_console_logger.disabled = futu_console_was_disabled
    if output_format == "json":
        typer.echo(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return
    account = snapshot.account
    if not snapshot.account_exists or account is None:
        typer.echo(f"account={snapshot.account_id} status=missing")
        return
    typer.echo(
        f"account={account['account_id']} cash={account['cash']:.2f} "
        f"realized_pnl={account['realized_pnl']:.2f} "
        f"positions={len(account['positions'])} "
        f"kill_switch={account['kill_switch']}"
    )
    for position in account["positions"]:
        typer.echo(
            f"  {position['symbol']}: qty={position['quantity']:.4f} "
            f"avg_cost={position['avg_cost']:.2f}"
        )
    for warning in account["warnings"]:
        typer.echo(f"warning={warning}")


def _paper_strategy_operations_runner(settings):
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.paper_strategy_operations import (
        PaperStrategyOperationsRunner,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    api_runs_dir = settings.data.data_dir / "api_runs"
    return PaperStrategyOperationsRunner(
        account_storage=build_paper_account_repository(
            api_runs_dir,
            settings=settings,
        ),
        sleeve_storage=PaperStrategySleeveStorage(api_runs_dir),
        settings=settings,
    )


def _paper_strategy_ops_observer(settings):
    from quant_system.execution.paper_strategy_operations import (
        PaperStrategyOpsObserver,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    api_runs_dir = settings.data.data_dir / "api_runs"
    return PaperStrategyOpsObserver(
        sleeve_storage=PaperStrategySleeveStorage(api_runs_dir),
    )


@paper_strategies_app.command("generate-signal")
def paper_strategy_generate_signal_command(
    sleeve_id: Annotated[
        str,
        typer.Option("--sleeve", help="Strategy sleeve id to generate a signal for."),
    ],
    signal_date: Annotated[
        str | None,
        typer.Option("--signal-date", help="Signal date, for example 2024-03-20."),
    ] = None,
    history_days: Annotated[
        int,
        typer.Option("--history-days", help="Number of calendar days to request."),
    ] = 180,
) -> None:
    """Generate and persist one daily Paper Strategy Sleeve signal."""
    from quant_system.execution.account import PaperAccount
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.paper_strategy_signal_service import (
        PaperStrategySignalService,
        StrategySignalGenerationError,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    settings = load_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(api_runs_dir, settings=settings)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    service = PaperStrategySignalService(storage=sleeve_storage, settings=settings)
    with account_storage.mutation_lock(), sleeve_storage.mutation_lock():
        persisted_account = account_storage.load()
        sleeve_storage.reconcile_pending_sleeves(persisted_account)
        account = persisted_account or PaperAccount.open_new(account_id=account_storage.account_id)
        try:
            sleeve = sleeve_storage.load_sleeve(sleeve_id)
            config = sleeve_storage.load_strategy_config(
                sleeve.strategy_config_id,
                version=sleeve.strategy_config_version,
            )
            signal = service.generate_daily_signal(
                sleeve=sleeve,
                config=config,
                account=account,
                signal_date=signal_date,
                history_days=history_days,
            )
        except FileNotFoundError as exc:
            typer.echo(f"strategy sleeve not found: {sleeve_id}")
            raise typer.Exit(code=1) from exc
        except StrategySignalGenerationError as exc:
            typer.echo(f"signal generation unavailable: {exc}")
            raise typer.Exit(code=1) from exc

    typer.echo(
        " ".join(
            [
                f"sleeve={sleeve_id}",
                f"signal_id={signal.signal_id}",
                f"status={signal.status}",
                f"data_provider={signal.data_provider}",
                f"data_as_of={signal.data_as_of or '<none>'}",
                f"targets={len(signal.target_weights)}",
                f"proposed_orders={len(signal.proposed_orders)}",
            ]
        )
    )


@paper_strategies_app.command("generate-due-signals")
def paper_strategy_generate_due_signals_command(
    signal_date: Annotated[
        str | None,
        typer.Option("--date", help="Signal date, for example 2024-03-20."),
    ] = None,
    history_days: Annotated[
        int,
        typer.Option("--history-days", help="Number of calendar days to request."),
    ] = 180,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum sleeves to generate for."),
    ] = 50,
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", help="Output format."),
    ] = "text",
) -> None:
    """Generate due Paper Strategy Sleeve daily signals once."""
    settings = load_settings()
    runner = _paper_strategy_operations_runner(settings)
    try:
        result = runner.generate_due_signals_once(
            signal_date=signal_date,
            history_days=history_days,
            limit=limit,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_format == "json":
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    typer.echo(
        f"signal_date={result.signal_date} "
        f"generated={result.generated_count} skipped={result.skipped_count}"
    )
    for signal in result.signals:
        typer.echo(
            " ".join(
                [
                    f"sleeve={signal.sleeve_id}",
                    f"signal_id={signal.signal_id}",
                    f"status={signal.status}",
                    f"data_provider={signal.data_provider}",
                ]
            )
        )


@paper_strategies_app.command("create-execution")
def paper_strategy_create_execution_command(
    sleeve_id: Annotated[
        str,
        typer.Option("--sleeve", help="Strategy sleeve id that owns the signal."),
    ],
    signal_id: Annotated[
        str,
        typer.Option("--signal", help="Signal id to promote to a pending execution."),
    ],
    target_date: Annotated[
        str | None,
        typer.Option("--target-date", help="Execution target date, YYYY-MM-DD."),
    ] = None,
    window: Annotated[
        str,
        typer.Option("--window", help="Execution window. Currently next_open."),
    ] = "next_open",
) -> None:
    """Create one pending Paper Strategy Sleeve execution from a signal."""
    from quant_system.execution.account import PaperAccount
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )
    from quant_system.execution.paper_strategy_sleeves import (
        PaperStrategySleeveService,
        StrategyExecutionPlanError,
    )

    settings = load_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(api_runs_dir, settings=settings)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    execution_window = window.replace("-", "_")
    with account_storage.mutation_lock(), sleeve_storage.mutation_lock():
        persisted_account = account_storage.load()
        sleeve_storage.reconcile_pending_sleeves(persisted_account)
        account = persisted_account or PaperAccount.open_new(account_id=account_storage.account_id)
        try:
            sleeve = sleeve_storage.load_sleeve(sleeve_id)
        except FileNotFoundError as exc:
            typer.echo(f"strategy sleeve not found: {sleeve_id}")
            raise typer.Exit(code=1) from exc
        signal = next(
            (
                item
                for item in sleeve_storage.load_signals(sleeve_id)
                if item.signal_id == signal_id
            ),
            None,
        )
        if signal is None:
            typer.echo(f"strategy signal not found: {signal_id}")
            raise typer.Exit(code=1)
        try:
            execution = service.create_execution_plan(
                account,
                sleeve=sleeve,
                signal=signal,
                execution_window=execution_window,
                target_date=target_date,
            )
        except StrategyExecutionPlanError as exc:
            typer.echo(f"execution unavailable: {exc.code}")
            raise typer.Exit(code=1) from exc

    typer.echo(
        " ".join(
            [
                f"sleeve={sleeve_id}",
                f"signal_id={signal_id}",
                f"execution_id={execution.execution_id}",
                f"status={execution.status}",
                f"window={execution.execution_window}",
                f"target_date={execution.target_date or '<none>'}",
            ]
        )
    )


@paper_strategies_app.command("execute-pending")
def paper_strategy_execute_pending_command(
    sleeve_id: Annotated[
        str | None,
        typer.Option("--sleeve", help="Optional sleeve id filter."),
    ] = None,
    target_date: Annotated[
        str | None,
        typer.Option("--target-date", help="Execution target date, YYYY-MM-DD."),
    ] = None,
    window: Annotated[
        str,
        typer.Option("--window", help="Execution window. Currently next_open."),
    ] = "next_open",
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum pending executions to process."),
    ] = 50,
) -> None:
    """Process due pending Paper Strategy Sleeve executions once."""
    settings = load_settings()
    runner = _paper_strategy_operations_runner(settings)
    execution_window = window.replace("-", "_")
    try:
        result = runner.process_pending_executions_once(
            sleeve_id=sleeve_id,
            execution_window=execution_window,
            target_date=target_date,
            limit=limit,
        )
    except FileNotFoundError as exc:
        typer.echo(f"strategy sleeve not found: {sleeve_id}")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(
        f"processed={result.processed_count} "
        f"filled={result.filled_count} blocked={result.blocked_count}"
    )
    for execution in result.executions:
        typer.echo(
            " ".join(
                [
                    f"execution_id={execution.execution_id}",
                    f"sleeve={execution.sleeve_id}",
                    f"status={execution.status}",
                    f"blocked_reason={execution.blocked_reason or '<none>'}",
                ]
            )
        )
    if result.blocked_count:
        raise typer.Exit(code=1)


@paper_strategies_app.command("execute-due")
def paper_strategy_execute_due_command(
    sleeve_id: Annotated[
        str | None,
        typer.Option("--sleeve", help="Optional sleeve id filter."),
    ] = None,
    target_date: Annotated[
        str | None,
        typer.Option("--target-date", help="Execution target date, YYYY-MM-DD."),
    ] = None,
    window: Annotated[
        str,
        typer.Option("--window", help="Execution window. Currently next_open."),
    ] = "next_open",
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum pending executions to process."),
    ] = 50,
) -> None:
    """Scheduler-friendly alias for processing due strategy executions once."""
    paper_strategy_execute_pending_command(
        sleeve_id=sleeve_id,
        target_date=target_date,
        window=window,
        limit=limit,
    )


@paper_strategies_app.command("ops-status")
def paper_strategy_ops_status_command(
    target_date: Annotated[
        str | None,
        typer.Option("--target-date", help="Status target date, YYYY-MM-DD."),
    ] = None,
    window: Annotated[
        str,
        typer.Option("--window", help="Execution window. Currently next_open."),
    ] = "next_open",
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", help="Output format."),
    ] = "text",
) -> None:
    """Print Paper Strategy Sleeves local operations status."""
    settings = load_settings()
    observer = _paper_strategy_ops_observer(settings)
    try:
        status = observer.observe(
            target_date=target_date,
            execution_window=window.replace("-", "_"),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = status.to_dict()
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(
        " ".join(
            [
                f"target_date={status.target_date}",
                f"sleeves={status.sleeve_count}",
                f"pending_sleeves={status.pending_sleeve_count}",
                f"pending_due={status.pending_due_count}",
                f"pending_executions={status.pending_execution_count}",
                f"blocked={status.blocked_count}",
                f"recovery_required={status.recovery_required_count}",
                f"pending_journals={status.pending_journal_count}",
                f"corrupt_journals={status.corrupt_journal_count}",
            ]
        )
    )


@paper_strategies_app.command("observations")
def paper_strategy_observations_command(
    from_date: Annotated[
        str | None,
        typer.Option("--from-date", help="Inclusive signal date, YYYY-MM-DD."),
    ] = None,
    to_date: Annotated[
        str | None,
        typer.Option("--to-date", help="Inclusive signal date, YYYY-MM-DD."),
    ] = None,
    signal_id: Annotated[
        str | None,
        typer.Option("--signal-id", help="Optional exact strategy signal id."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum observations to return (1-500)."),
    ] = 200,
    output_format: Annotated[
        Literal["json"],
        typer.Option("--format", help="Machine-readable output format."),
    ] = "json",
) -> None:
    """Read bounded strategy signal/action facts without recovery or mutation."""
    from quant_system.execution.paper_strategy_observations import (
        PaperStrategyObservationReader,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    del output_format
    try:
        settings = load_settings()
    except Exception:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "strategy_observations_unavailable",
                        "message": "strategy observation configuration is unavailable",
                    }
                },
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise typer.Exit(code=1) from None
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    try:
        payload = PaperStrategyObservationReader(storage).read(
            from_date=from_date,
            to_date=to_date,
            signal_id=signal_id,
            limit=limit,
        )
    except ValueError as exc:
        typer.echo(
            json.dumps(
                {
                    "error": {
                        "code": "strategy_observations_invalid_request",
                        "message": str(exc),
                    }
                },
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            payload,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )
    if payload["read_status"] == "degraded":
        raise typer.Exit(code=1)


@paper_strategies_app.command("recover-pending")
def paper_strategy_recover_pending_command(
    output_format: Annotated[
        Literal["text", "json"],
        typer.Option("--format", help="Output format."),
    ] = "text",
) -> None:
    """Explicitly recover Paper Strategy Sleeve crash journals only."""
    from quant_system.execution.account_repository import (
        PaperAccountBootstrapRequired,
    )

    settings = load_settings()
    try:
        result = _paper_strategy_operations_runner(settings).recover_pending_once()
    except PaperAccountBootstrapRequired as exc:
        if output_format == "json":
            typer.echo(
                json.dumps(
                    {"error": {"code": exc.code, "message": str(exc)}},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(f"{exc.code}: {exc}")
        raise typer.Exit(code=1) from exc
    payload = result.to_dict()
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(
        " ".join(
            [
                f"reconciled_sleeves={result.reconciled_sleeve_count}",
                f"discarded_sleeves={result.discarded_sleeve_count}",
                f"recovered_executions={result.recovered_execution_count}",
                (f"remaining_pending_sleeves={result.remaining_pending_sleeve_count}"),
                (f"remaining_pending_journals={result.remaining_pending_journal_count}"),
                f"corrupt_journals={result.corrupt_journal_count}",
            ]
        )
    )


@agent_app.command("propose-factor")
def agent_propose_factor(
    goal: Annotated[str, typer.Option("--goal", help="Research goal for the candidate factor.")],
    universe: Annotated[
        str,
        typer.Option("--universe", help="Comma-separated symbols, for example SPY,QQQ."),
    ] = "SPY,QQQ",
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Defaults to QS_AGENT_OUTPUT_DIR or "
                "the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
    source_file: Annotated[
        str | None,
        typer.Option(
            "--source-file",
            help="Externally generated factor source to ingest as a pending candidate.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Append a machine-readable JSON summary line."),
    ] = False,
) -> None:
    """Create an inert candidate factor file for human review."""
    metadata_extra = None
    external_source_sha256: str | None = None
    if source_file is not None:
        path = Path(source_file)
        # Read once in binary mode so universal-newline translation cannot
        # silently change the exact bytes that a human reviewed at HQA Gate 1.
        source_bytes = path.read_bytes()
        source_text = source_bytes.decode("utf-8", errors="strict")
        external_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        llm = FixedContentLLMClient(source_text)
        metadata_extra = {
            "generator": "external-source",
            "source_file_name": path.name,
            "source_sha256": external_source_sha256,
        }
    else:
        llm = _build_agent_llm(llm_name)
    runner = AgentRunner(
        agent_output_dir=resolve_agent_output_dir(agent_output_dir),
        llm=llm,
    )
    artifact = runner.propose_factor(
        goal=goal,
        universe=_parse_universe(universe),
        metadata_extra=metadata_extra,
    )
    snapshot = runner.candidates.get(artifact.candidate_id)
    candidate_source = snapshot.artifact_bytes.get("factor.py.candidate")
    if candidate_source is None:
        raise typer.BadParameter("verified candidate is missing factor.py.candidate")
    candidate_source_sha256 = hashlib.sha256(candidate_source).hexdigest()
    if (
        external_source_sha256 is not None
        and candidate_source_sha256 != external_source_sha256
    ):
        raise typer.BadParameter(
            "candidate source bytes differ from the external source bytes"
        )
    _emit_agent_artifact(
        artifact.candidate_id,
        artifact.path,
        artifact.metadata_path,
        manifest_digest=artifact.manifest_digest,
    )
    if json_output:
        _emit_json(
            {
                "candidate_id": artifact.candidate_id,
                "status": "pending",
                "path": str(artifact.path),
                "metadata_path": str(artifact.metadata_path),
                "manifest_digest": artifact.manifest_digest,
                "source_sha256": candidate_source_sha256,
            }
        )


@agent_app.command("propose-experiment")
def agent_propose_experiment(
    goal: Annotated[str, typer.Option("--goal", help="Research goal for the experiment.")],
    universe: Annotated[
        str,
        typer.Option("--universe", help="Comma-separated symbols, for example SPY,QQQ."),
    ] = "SPY,QQQ",
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Defaults to QS_AGENT_OUTPUT_DIR or "
                "the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Create an experiment config candidate for human review."""
    artifact = AgentRunner(
        agent_output_dir=resolve_agent_output_dir(agent_output_dir),
        llm=_build_agent_llm(llm_name),
    ).propose_experiment(goal=goal, universe=_parse_universe(universe))
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("summarize")
def agent_summarize(
    experiment_id: Annotated[
        str,
        typer.Option("--experiment-id", help="Experiment id to summarize."),
    ],
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root for candidates/audit. Defaults to "
                "QS_AGENT_OUTPUT_DIR or the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
    result_output_dir: Annotated[
        str | None,
        typer.Option(
            "--result-output-dir",
            help=(
                "Experiment result root to read when summarizing. Defaults to the "
                "resolved agent output root when omitted."
            ),
        ),
    ] = None,
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Summarize a local experiment for human review only."""
    active_agent_root = resolve_agent_output_dir(agent_output_dir)
    artifact = AgentRunner(
        agent_output_dir=active_agent_root,
        result_output_dir=(
            Path(result_output_dir) if result_output_dir is not None else active_agent_root
        ),
        llm=_build_agent_llm(llm_name),
    ).summarize(experiment_id=experiment_id)
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("audit-leakage")
def agent_audit_leakage(
    factor_id: Annotated[str, typer.Option("--factor-id", help="Factor id to inspect.")],
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Defaults to QS_AGENT_OUTPUT_DIR or "
                "the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Write a point-in-time and look-ahead checklist candidate."""
    artifact = AgentRunner(
        agent_output_dir=resolve_agent_output_dir(agent_output_dir),
        llm=_build_agent_llm(llm_name),
    ).audit_leakage(factor_id=factor_id)
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("list-candidates")
def agent_list_candidates(
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Defaults to QS_AGENT_OUTPUT_DIR or "
                "the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
) -> None:
    """List diagnostic candidate evidence without emitting review authority."""
    active_agent_root = resolve_agent_output_dir(agent_output_dir)
    candidates = AgentRunner(agent_output_dir=active_agent_root).list_candidates()
    if not candidates:
        typer.echo("no_candidates=true")
        return
    for candidate in candidates:
        path = resolve_candidates_dir(active_agent_root) / candidate["candidate_id"]
        integrity = candidate.get("integrity_state")
        parts = [
            f"candidate_id={candidate['candidate_id']}",
            f"type={candidate.get('artifact_type')}",
            f"status={candidate.get('status')}",
            f"integrity={integrity}",
            f"approval_enabled={candidate.get('approval_enabled')}",
        ]
        # Never substitute observed digest for the authoritative approval digest.
        if integrity == "verified" and candidate.get("manifest_digest"):
            parts.append(f"manifest_digest={candidate['manifest_digest']}")
            if candidate.get("status") == "pending" and candidate.get(
                "approval_enabled"
            ):
                # Listing is evidence only. In particular, do not create a
                # copyable raw Gate-2 command that bypasses HQA Scene-B Gate 1.
                parts.append("review_authority=withheld_use_exact_detail")
        elif integrity == "migration_required":
            observed = candidate.get("observed_manifest_digest")
            if observed:
                parts.append(f"observed_manifest_digest={observed}")
            parts.append("note=migration_evidence_approval_disabled")
        # corrupt: intentionally no digest/source fields
        parts.append(f"path={path}")
        typer.echo(" ".join(parts))


@agent_app.command("inspect-factor-candidate")
def agent_inspect_factor_candidate(
    candidate_id: Annotated[
        str,
        typer.Option("--candidate-id", help="Verified candidate id to inspect."),
    ],
    expected_manifest_digest: Annotated[
        str | None,
        typer.Option(
            "--expected-digest",
            help="Optional exact digest to compare before returning the bundle.",
        ),
    ] = None,
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help="Agent artifact output root containing the candidate pool.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Append a machine-readable JSON bundle."),
    ] = False,
) -> None:
    """Inspect source and identity from one verified snapshot without compiling it."""
    from quant_system.agent.candidate_manifest import (
        CandidateIntegrityError,
        CandidateStaleError,
    )

    try:
        bundle = inspect_factor_candidate(
            agent_output_dir=resolve_agent_output_dir(agent_output_dir),
            candidate_id=candidate_id,
            expected_manifest_digest=expected_manifest_digest,
        )
    except (
        CandidateIntegrityError,
        CandidateLoadError,
        CandidateStaleError,
        OSError,
        UnicodeDecodeError,
    ) as exc:
        typer.echo(f"candidate_inspect_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(
        " ".join(
            [
                f"candidate_id={bundle.candidate_id}",
                f"manifest_digest={bundle.manifest_digest}",
                f"factor_id={bundle.factor_id}",
                f"approval_binding={bundle.approval_binding}",
                f"source_path={bundle.source_path}",
            ]
        )
    )
    if json_output:
        _emit_json(
            {
                "candidate_id": bundle.candidate_id,
                "manifest_digest": bundle.manifest_digest,
                "factor_id": bundle.factor_id,
                "approval_binding": bundle.approval_binding,
                "source_path": str(bundle.source_path),
                "source": bundle.source,
            }
        )


@agent_app.command("review")
def agent_review(
    candidate_id: Annotated[
        str,
        typer.Option("--candidate-id", help="Candidate id from list-candidates."),
    ],
    decision: Annotated[
        Literal["approve", "reject"],
        typer.Option("--decision", help="Manual review decision."),
    ],
    note: Annotated[str, typer.Option("--note", help="Manual review note.")],
    expected_manifest_digest: Annotated[
        str,
        typer.Option(
            "--expected-digest",
            help="Exact lowercase SHA-256 manifest digest from list-candidates.",
        ),
    ],
    expected_status: Annotated[
        Literal["pending"],
        typer.Option(
            "--expected-status",
            help="Must be the literal status pending (CAS precondition).",
        ),
    ],
    agent_output_dir: Annotated[
        str | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Defaults to QS_AGENT_OUTPUT_DIR or "
                "the repo-anchored canonical agent_run root."
            ),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Append a machine-readable JSON summary line."),
    ] = False,
) -> None:
    """Record a digest-bound manual review; approve only writes a structured lock."""
    from quant_system.agent.candidate_pool import (
        CandidateIntegrityError,
        CandidateMigrationRequiredError,
        CandidateReviewStateStaleError,
        CandidateStaleError,
    )

    try:
        record = AgentRunner(
            agent_output_dir=resolve_agent_output_dir(agent_output_dir),
        ).review(
            candidate_id=candidate_id,
            decision=decision,
            note=note,
            expected_manifest_digest=expected_manifest_digest,
            expected_status=expected_status,
        )
    except (
        CandidateIntegrityError,
        CandidateMigrationRequiredError,
        CandidateStaleError,
        CandidateReviewStateStaleError,
        FileNotFoundError,
    ) as exc:
        typer.echo(f"review_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(
        " ".join(
            [
                f"candidate_id={record.candidate_id}",
                f"decision={record.decision}",
                "registration=manual_required",
            ]
        )
    )
    if json_output:
        _emit_json(
            {
                "candidate_id": record.candidate_id,
                "decision": record.decision,
                "registration": "manual_required",
                "manifest_digest": record.manifest_digest,
            }
        )


@agent_app.command("auto-review")
def agent_auto_review(
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    expected_manifest_digest: Annotated[str, typer.Option("--expected-digest")],
    expected_status: Annotated[Literal["pending"], typer.Option("--expected-status")],
    policy_digest: Annotated[str, typer.Option("--policy-digest")],
    intake_contract_digest: Annotated[
        str, typer.Option("--intake-contract-digest")
    ],
    agent_output_dir: Annotated[str | None, typer.Option("--agent-output-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Machine Gate 2 for the paper-only automation path.

    The normal ``agent review`` command remains manual and byte-compatible.
    This separate surface is fail-closed when the Platform automation flag is
    off and binds both versioned policy and paper-intake contract digests into
    the immutable approval lock note.
    """
    from quant_system.agent.candidate_manifest import load_verified_candidate_snapshot
    from quant_system.agent.candidate_pool import (
        CandidateIntegrityError,
        CandidateMigrationRequiredError,
        CandidateReviewStateStaleError,
        CandidateStaleError,
    )

    settings = reload_settings()
    if settings.factor_automation.mode is not True:
        typer.echo("auto_review_refused reason=factor_automation_disabled")
        raise typer.Exit(code=1)
    digest_re = re.compile(r"^[0-9a-f]{64}$")
    if (
        digest_re.fullmatch(policy_digest) is None
        or digest_re.fullmatch(intake_contract_digest) is None
    ):
        typer.echo("auto_review_refused reason=invalid_automation_lineage")
        raise typer.Exit(code=1)
    note = f"auto:policy:{policy_digest}:intake:{intake_contract_digest}"
    try:
        record = AgentRunner(
            agent_output_dir=resolve_agent_output_dir(agent_output_dir),
        ).review(
            candidate_id=candidate_id,
            decision="approve",
            note=note,
            expected_manifest_digest=expected_manifest_digest,
            expected_status=expected_status,
            reviewer="auto",
        )
    except CandidateReviewStateStaleError:
        try:
            snapshot = load_verified_candidate_snapshot(
                agent_output_dir=resolve_agent_output_dir(agent_output_dir),
                candidate_id=candidate_id,
            )
            recovered = snapshot.review_record
            if (
                snapshot.approval_binding != "approved"
                or snapshot.manifest_digest != expected_manifest_digest
                or recovered is None
                or recovered.candidate_id != candidate_id
                or recovered.decision != "approve"
                or recovered.manifest_digest != expected_manifest_digest
                or recovered.reviewer != "auto"
                or recovered.note != note
            ):
                raise CandidateIntegrityError(
                    "existing decision does not match automation lineage"
                )
            record = recovered
        except (
            CandidateIntegrityError,
            CandidateMigrationRequiredError,
            CandidateStaleError,
            FileNotFoundError,
        ) as recovery_exc:
            typer.echo(f"auto_review_refused reason={recovery_exc}")
            raise typer.Exit(code=1) from recovery_exc
    except (
        CandidateIntegrityError,
        CandidateMigrationRequiredError,
        CandidateStaleError,
        FileNotFoundError,
    ) as exc:
        typer.echo(f"auto_review_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    payload = {
        "candidate_id": record.candidate_id,
        "decision": record.decision,
        "registration": "auto_promote",
        "manifest_digest": record.manifest_digest,
        "reviewer": "auto",
        "policy_digest": policy_digest,
        "intake_contract_digest": intake_contract_digest,
    }
    typer.echo(
        " ".join(
            [
                f"candidate_id={record.candidate_id}",
                "decision=approve",
                "registration=auto_promote",
                "reviewer=auto",
            ]
        )
    )
    if json_output:
        _emit_json(payload)


@agent_app.command("promote-candidate")
def agent_promote_candidate(
    candidate_id: Annotated[
        str,
        typer.Option("--candidate-id", help="Approved candidate id from list-candidates."),
    ],
    expected_digest: Annotated[
        str,
        typer.Option(
            "--expected-digest",
            help="Exact manifest SHA-256 bound by Gate 2 approval (CAS).",
        ),
    ],
    final_backtest_receipt: Annotated[
        str,
        typer.Option(
            "--final-backtest-receipt",
            help="Exact successful full-window receipt verified by the HQA Gate 3 caller.",
        ),
    ],
    base_commit: Annotated[
        str,
        typer.Option(
            "--base-commit",
            help="Main-worktree HEAD commit the isolated review worktree must match.",
        ),
    ],
) -> None:
    """Prepare an isolated Gate-3 review worktree and scoped patch; NEVER commits."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        _human_instructions,
        default_promotion_root,
        prepare_cli_payload,
        prepare_promotion_workspace,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    try:
        agent_root = resolve_agent_output_dir()
        result = prepare_promotion_workspace(
            repo_dir=resolve_platform_repo(),
            agent_output_dir=agent_root,
            candidate_id=candidate_id,
            expected_candidate_digest=expected_digest,
            final_backtest_receipt_id=final_backtest_receipt,
            base_commit=base_commit,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"promotion_refused reason={exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(prepare_cli_payload(result), sort_keys=True))
    typer.echo(
        _human_instructions(
            result.promotion_id,
            result.scoped_paths,
            final_backtest_receipt,
        ),
        err=True,
    )


@agent_app.command("promote-auto-prepare")
def agent_promote_auto_prepare(
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    expected_digest: Annotated[str, typer.Option("--expected-digest")],
    final_backtest_receipt: Annotated[
        str, typer.Option("--final-backtest-receipt")
    ],
    base_commit: Annotated[str, typer.Option("--base-commit")],
    policy_digest: Annotated[str, typer.Option("--policy-digest")],
    intake_contract_digest: Annotated[
        str, typer.Option("--intake-contract-digest")
    ],
) -> None:
    """Prepare Gate 3 with immutable paper-only qualification; never commits."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        default_promotion_root,
        prepare_cli_payload,
        prepare_promotion_workspace,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    settings = reload_settings()
    if settings.factor_automation.mode is not True:
        typer.echo("auto_promotion_refused reason=factor_automation_disabled")
        raise typer.Exit(code=1)
    try:
        agent_root = resolve_agent_output_dir()
        result = prepare_promotion_workspace(
            repo_dir=resolve_platform_repo(),
            agent_output_dir=agent_root,
            candidate_id=candidate_id,
            expected_candidate_digest=expected_digest,
            final_backtest_receipt_id=final_backtest_receipt,
            base_commit=base_commit,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            promotion_scope="paper_only",
            reviewer="auto",
            automation_policy_digest=policy_digest,
            intake_contract_digest=intake_contract_digest,
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"auto_promotion_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(prepare_cli_payload(result), sort_keys=True))


def _require_auto_land_flags() -> None:
    settings = reload_settings()
    if (
        settings.factor_automation.mode is not True
        or settings.factor_automation.auto_land is not True
    ):
        typer.echo("auto_promotion_refused reason=factor_automation_disabled")
        raise typer.Exit(code=1)


def _automatic_promotion_status(promotion_id: str) -> dict[str, Any]:
    from quant_system.agent.promotion_workspace import (
        default_promotion_root,
        promotion_status,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    agent_root = resolve_agent_output_dir()
    return promotion_status(
        promotion_id=promotion_id,
        agent_output_dir=agent_root,
        promotion_root=default_promotion_root(agent_root),
        worktree_root=resolve_managed_worktree_root(),
        repo_dir=resolve_platform_repo(),
    )


@agent_app.command("promote-auto-commit")
def agent_promote_auto_commit(
    promotion_id: Annotated[str, typer.Option("--promotion-id")],
) -> None:
    """Second Gate-3 phase: commit the exact prepared patch locally."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        commit_automatic_promotion,
        default_promotion_root,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    _require_auto_land_flags()
    try:
        agent_root = resolve_agent_output_dir()
        result = commit_automatic_promotion(
            promotion_id=promotion_id,
            agent_output_dir=agent_root,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            repo_dir=resolve_platform_repo(),
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"auto_promotion_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    _emit_json(result)


@agent_app.command("promote-auto-land")
def agent_promote_auto_land(
    promotion_id: Annotated[str, typer.Option("--promotion-id")],
    expected_base_commit: Annotated[str, typer.Option("--expected-base-commit")],
    expected_reviewed_commit: Annotated[
        str, typer.Option("--expected-reviewed-commit")
    ],
) -> None:
    """Fast-forward local main only; this command has no push implementation."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        default_promotion_root,
        land_automatic_promotion,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    _require_auto_land_flags()
    try:
        agent_root = resolve_agent_output_dir()
        result = land_automatic_promotion(
            promotion_id=promotion_id,
            expected_base_commit=expected_base_commit,
            expected_reviewed_commit=expected_reviewed_commit,
            agent_output_dir=agent_root,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            repo_dir=resolve_platform_repo(),
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"auto_promotion_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    _emit_json(result)


@agent_app.command("factor-automation-authorize-land")
def factor_automation_authorize_land_command(
    automation_id: Annotated[str, typer.Option("--automation-id")],
    promotion_id: Annotated[str, typer.Option("--promotion-id")],
    policy_digest: Annotated[str, typer.Option("--policy-digest")],
    intake_contract_digest: Annotated[
        str, typer.Option("--intake-contract-digest")
    ],
    gate1_digest: Annotated[str, typer.Option("--gate1-digest")],
    gate2_digest: Annotated[str, typer.Option("--gate2-digest")],
) -> None:
    """Consume the DB daily quota after exact automatic Gate-3 commit review."""
    from dataclasses import asdict

    from quant_system.execution.factor_automation_activation import (
        AutomaticLandAuthorizationRequest,
        FactorAutomationActivationError,
        authorize_automatic_land,
    )
    from quant_system.execution.factor_automation_authority import (
        FactorAutomationAuthorityError,
    )

    _require_auto_land_flags()
    settings = reload_settings()
    try:
        lineage, receipt = authorize_automatic_land(
            settings,
            AutomaticLandAuthorizationRequest(
                automation_id=automation_id,
                promotion_id=promotion_id,
                automation_policy_digest=policy_digest,
                intake_contract_digest=intake_contract_digest,
                gate1_digest=gate1_digest,
                gate2_digest=gate2_digest,
            ),
            promotion_status=_automatic_promotion_status(promotion_id),
        )
    except (FactorAutomationActivationError, FactorAutomationAuthorityError) as exc:
        typer.echo(f"factor_automation_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    _emit_json(
        {
            "state": "land_authorized",
            "lineage": asdict(lineage),
            "audit": {
                "event_seq": receipt.event_seq,
                "event_day": receipt.event_day.isoformat(),
                "idempotent_replay": receipt.idempotent_replay,
            },
        }
    )


@agent_app.command("factor-automation-activate-sleeve")
def factor_automation_activate_sleeve_command(
    automation_id: Annotated[str, typer.Option("--automation-id")],
    promotion_id: Annotated[str, typer.Option("--promotion-id")],
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    candidate_digest: Annotated[str, typer.Option("--candidate-digest")],
    factor_id: Annotated[str, typer.Option("--factor-id")],
    manifest_digest: Annotated[str, typer.Option("--manifest-digest")],
    policy_digest: Annotated[str, typer.Option("--policy-digest")],
    intake_contract_digest: Annotated[
        str, typer.Option("--intake-contract-digest")
    ],
    gate1_digest: Annotated[str, typer.Option("--gate1-digest")],
    gate2_digest: Annotated[str, typer.Option("--gate2-digest")],
    gate3_digest: Annotated[str, typer.Option("--gate3-digest")],
    commit_sha: Annotated[str, typer.Option("--commit-sha")],
    symbols: Annotated[list[str], typer.Option("--symbol")],
    provider: Annotated[Literal["futu", "tiingo"], typer.Option("--provider")],
) -> None:
    """Create one deterministic allocated paper sleeve after local ff-land."""
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.account_snapshot import resolve_account_quotes
    from quant_system.execution.factor_automation_activation import (
        AccountValuation,
        AutomaticSleeveRequest,
        FactorAutomationActivationError,
        create_automatic_paper_sleeve,
    )
    from quant_system.execution.factor_automation_authority import (
        FactorAutomationAuthorityError,
        FactorAutomationLineage,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    _require_auto_land_flags()
    settings = reload_settings()
    status = _automatic_promotion_status(promotion_id)
    if (
        status.get("status") != "landed"
        or status.get("reviewed_commit") != commit_sha
        or status.get("candidate_id") != candidate_id
        or status.get("candidate_digest") != candidate_digest
        or status.get("manifest_sha256") != manifest_digest
        or status.get("patch_sha256") != gate3_digest
    ):
        typer.echo("factor_automation_refused reason=landed_status_mismatch")
        raise typer.Exit(code=1)
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(
        api_runs_dir,
        settings=settings,
    )
    account = account_storage.load()
    if account is None:
        typer.echo("factor_automation_refused reason=paper_account_missing")
        raise typer.Exit(code=1)
    try:
        quotes = resolve_account_quotes(account, settings=settings)
        prices = {symbol: quote.price for symbol, quote in quotes.items()}
        valuation = AccountValuation(
            account_id=account.account_id,
            account_updated_at=account.updated_at,
            nav=account.equity(prices),
            prices=prices,
            price_metadata={
                symbol: {"kind": quote.price_kind, "as_of": quote.as_of}
                for symbol, quote in quotes.items()
            },
        )
        sleeve, receipt = create_automatic_paper_sleeve(
            settings,
            AutomaticSleeveRequest(
                lineage=FactorAutomationLineage(
                    automation_id=automation_id,
                    candidate_id=candidate_id,
                    candidate_digest=candidate_digest,
                    factor_id=factor_id,
                    manifest_digest=manifest_digest,
                    automation_policy_digest=policy_digest,
                    intake_contract_digest=intake_contract_digest,
                    gate1_digest=gate1_digest,
                    gate2_digest=gate2_digest,
                    gate3_digest=gate3_digest,
                    commit_sha=commit_sha,
                ),
                promotion_id=promotion_id,
                universe=tuple(symbol.upper() for symbol in symbols),
                provider=provider,
            ),
            valuation=valuation,
            account_storage=account_storage,
            sleeve_storage=PaperStrategySleeveStorage(api_runs_dir),
        )
    except (FactorAutomationActivationError, FactorAutomationAuthorityError) as exc:
        typer.echo(f"factor_automation_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    _emit_json(
        {
            "state": "sleeve_created",
            "sleeve_id": sleeve.sleeve_id,
            "allocated_cash": sleeve.initial_allocated_cash,
            "promotion_scope": sleeve.metadata.get("promotion_scope"),
            "audit": {
                "event_seq": receipt.event_seq,
                "event_day": receipt.event_day.isoformat(),
                "idempotent_replay": receipt.idempotent_replay,
            },
        }
    )


@agent_app.command("factor-automation-maintain")
def factor_automation_maintain_command() -> None:
    """Pause breached sleeves and quarantine automation factors missing from paper."""
    from quant_system.execution.account_repository_factory import (
        build_paper_account_repository,
    )
    from quant_system.execution.account_snapshot import resolve_account_quotes
    from quant_system.execution.factor_automation_activation import (
        AccountValuation,
        FactorAutomationActivationError,
        maintain_automatic_paper_sleeves,
        run_automatic_paper_cycle,
    )
    from quant_system.execution.factor_automation_authority import (
        FactorAutomationAuthorityError,
    )
    from quant_system.execution.paper_strategy_sleeve_storage import (
        PaperStrategySleeveStorage,
    )

    _require_auto_land_flags()
    settings = reload_settings()
    api_runs_dir = settings.data.data_dir / "api_runs"
    account_storage = build_paper_account_repository(
        api_runs_dir,
        settings=settings,
    )
    account = account_storage.load()
    if account is None:
        typer.echo("factor_automation_refused reason=paper_account_missing")
        raise typer.Exit(code=1)
    try:
        quotes = resolve_account_quotes(account, settings=settings)
        prices = {symbol: quote.price for symbol, quote in quotes.items()}
        sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
        result = maintain_automatic_paper_sleeves(
            settings,
            valuation=AccountValuation(
                account_id=account.account_id,
                account_updated_at=account.updated_at,
                nav=account.equity(prices),
                prices=prices,
                price_metadata={
                    symbol: {"kind": quote.price_kind, "as_of": quote.as_of}
                    for symbol, quote in quotes.items()
                },
            ),
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
        )
        cycle = run_automatic_paper_cycle(
            settings,
            now=datetime.now().astimezone(),
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
        )
    except (FactorAutomationActivationError, FactorAutomationAuthorityError) as exc:
        typer.echo(f"factor_automation_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    _emit_json({"state": "maintained", **result, "paper_cycle": cycle})


@agent_app.command("promotion-status")
def agent_promotion_status(
    promotion_id: Annotated[
        str,
        typer.Option("--promotion-id", help="Immutable Gate 3 promotion id."),
    ],
) -> None:
    """Report whether the human review commit matches the prepared scoped patch."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        default_promotion_root,
        promotion_status,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    try:
        agent_root = resolve_agent_output_dir()
        payload = promotion_status(
            promotion_id=promotion_id,
            agent_output_dir=agent_root,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            repo_dir=resolve_platform_repo(),
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"promotion_status_refused reason={exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(payload, sort_keys=True))


@agent_app.command("cleanup-promotion")
def agent_cleanup_promotion(
    promotion_id: Annotated[
        str,
        typer.Option("--promotion-id", help="Immutable Gate 3 promotion id."),
    ],
    abandon: Annotated[
        bool,
        typer.Option(
            "--abandon",
            help="Force-remove an unreviewed workspace and mark state abandoned.",
        ),
    ] = False,
) -> None:
    """Remove the managed review worktree after durable review evidence or --abandon."""
    from quant_system.agent.promotion_workspace import (
        PromotionWorkspaceError,
        cleanup_promotion_workspace,
        default_promotion_root,
        resolve_managed_worktree_root,
        resolve_platform_repo,
    )

    try:
        agent_root = resolve_agent_output_dir()
        payload = cleanup_promotion_workspace(
            promotion_id=promotion_id,
            agent_output_dir=agent_root,
            promotion_root=default_promotion_root(agent_root),
            worktree_root=resolve_managed_worktree_root(),
            repo_dir=resolve_platform_repo(),
            abandon=abandon,
        )
    except PromotionWorkspaceError as exc:
        typer.echo(f"promotion_cleanup_refused reason={exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(payload, sort_keys=True))


@agent_app.command("migrate-candidates")
def agent_migrate_candidates(
    legacy_dir: Annotated[
        Path | None,
        typer.Option(
            "--legacy-dir",
            help=(
                "Legacy candidates root to audit/copy from. Defaults to the "
                "repo-anchored data/agent/candidates path."
            ),
        ),
    ] = None,
    agent_output_dir: Annotated[
        Path | None,
        typer.Option(
            "--agent-output-dir",
            help=(
                "Agent artifact output root. Canonical candidates are always "
                "agent/candidates under this root via resolve_candidates_dir."
            ),
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Apply migration writes. Requires --backup-dir. Default is dry-run.",
        ),
    ] = False,
    backup_dir: Annotated[
        Path | None,
        typer.Option(
            "--backup-dir",
            help="Backup root required with --apply; never overlaps legacy/canonical.",
        ),
    ] = None,
) -> None:
    """Audit (default) or apply conflict-safe legacy→canonical candidate migration."""
    from quant_system.agent.candidate_migration import (
        CandidateMigrationConflict,
        apply_candidate_migration,
        audit_candidate_roots,
    )
    from quant_system.agent.candidate_pool import CandidateIntegrityError

    resolved_legacy = resolve_legacy_candidates_dir(legacy_dir)
    resolved_agent_output = resolve_agent_output_dir(agent_output_dir)
    try:
        report = audit_candidate_roots(
            legacy_dir=resolved_legacy,
            agent_output_dir=resolved_agent_output,
        )
        if apply:
            if backup_dir is None:
                raise typer.BadParameter("--backup-dir is required with --apply")
            report = apply_candidate_migration(report, backup_dir=backup_dir)
    except (CandidateIntegrityError, CandidateMigrationConflict) as exc:
        typer.echo(f"migration_refused reason={exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(report.model_dump_json())


@prediction_market_app.command("scan-sample")
def prediction_market_scan_sample(
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Prediction market artifact output directory."),
    ] = "data/pm_sample",
) -> None:
    """Scan deterministic sample prediction-market data."""
    provider = SamplePredictionMarketProvider()
    candidates = scan_market(provider=provider)
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=[],
        output_dir=output_dir,
    )
    typer.echo(f"candidates={len(candidates)} report={report_path}")
    for candidate in candidates:
        typer.echo(
            " ".join(
                [
                    f"candidate_id={candidate.candidate_id}",
                    f"market_id={candidate.market_id}",
                    f"scanner={candidate.scanner_id}",
                    f"edge_bps={candidate.edge_bps:.2f}",
                    f"direction={candidate.direction}",
                ]
            )
        )


@prediction_market_app.command("dry-arbitrage")
def prediction_market_dry_arbitrage(
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Prediction market artifact output directory."),
    ] = "data/pm_sample",
    optimizer_name: Annotated[
        Literal["greedy"],
        typer.Option("--optimizer", help="Dry optimizer stub to use."),
    ] = "greedy",
) -> None:
    """Write dry proposed trades from sample data; never submit orders."""
    provider = SamplePredictionMarketProvider()
    optimizer = GreedyStub()
    threshold = ProfitThresholdChecker(ExecutionThresholdConfig())
    candidates = scan_market(provider=provider)
    trades = run_dry_arbitrage(
        provider=provider,
        optimizer=optimizer,
        threshold=threshold,
        output_dir=output_dir,
    )
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=trades,
        output_dir=output_dir,
    )
    typer.echo(f"proposed_trades={len(trades)} report={report_path}")
    for trade in trades:
        typer.echo(
            " ".join(
                [
                    f"proposal_id={trade.proposal_id}",
                    f"dry_run={trade.dry_run}",
                    f"capital={trade.capital:.2f}",
                    f"expected_profit={trade.expected_profit:.2f}",
                ]
            )
        )


@prediction_market_app.command("collect")
def prediction_market_collect(
    provider: Annotated[
        Literal["sample", "polymarket"],
        typer.Option("--provider", help="Read-only provider to collect from."),
    ] = "sample",
    cache_mode: Annotated[
        Literal["prefer_cache", "refresh", "network_only"],
        typer.Option("--cache-mode", help="Cache behavior for polymarket read-only GETs."),
    ] = "prefer_cache",
    duration: Annotated[
        float,
        typer.Option("--duration", help="Total collection duration in seconds."),
    ] = 0.0,
    interval: Annotated[
        float | None,
        typer.Option("--interval", help="Polling interval in seconds."),
    ] = None,
    out_dir: Annotated[
        str | None,
        typer.Option("--out-dir", help="Override history snapshot output directory."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of markets per polling round."),
    ] = 10,
) -> None:
    """Collect read-only prediction-market snapshots into partitioned history files."""
    settings = reload_settings()
    ensure_no_polymarket_credentials_in_env()
    provider_instance, provider_label = build_prediction_market_provider(
        settings,
        requested=provider,
        cache_mode=cache_mode,
    )
    history_root = Path(out_dir) if out_dir else settings.prediction_market.history_dir
    collector = PredictionMarketSnapshotCollector(
        provider=provider_instance,
        provider_label=provider_label,
        store=PredictionMarketSnapshotStore(history_root),
        interval_seconds=interval or settings.prediction_market.collector_default_interval_seconds,
        duration_seconds=duration,
        limit=limit,
    )
    summary = collector.run()
    typer.echo(
        " ".join(
            [
                f"provider={summary.provider}",
                f"iterations={summary.iteration_count}",
                f"markets={summary.market_count}",
                f"records={summary.snapshot_record_count}",
                f"history_dir={summary.output_root}",
                f"first_timestamp={summary.first_timestamp or '<none>'}",
                f"last_timestamp={summary.last_timestamp or '<none>'}",
            ]
        )
    )


@prediction_market_app.command("timeseries-backtest")
def prediction_market_timeseries_backtest(
    provider: Annotated[
        Literal["sample", "polymarket"],
        typer.Option("--provider", help="History provider partition to replay."),
    ] = "sample",
    start_time: Annotated[
        str | None,
        typer.Option("--start-time", help="Optional ISO timestamp lower bound."),
    ] = None,
    end_time: Annotated[
        str | None,
        typer.Option("--end-time", help="Optional ISO timestamp upper bound."),
    ] = None,
    min_edge_bps: Annotated[
        float,
        typer.Option("--min-edge-bps", help="Minimum edge threshold in basis points."),
    ] = 200.0,
    capital_limit: Annotated[
        float,
        typer.Option("--capital-limit", help="Maximum notional per simulated complete set."),
    ] = 1_000.0,
    max_legs: Annotated[
        int,
        typer.Option("--max-legs", help="Maximum legs allowed by the threshold checker."),
    ] = 3,
    max_markets: Annotated[
        int,
        typer.Option("--max-markets", help="Maximum markets per snapshot timestamp."),
    ] = 50,
    fee_bps: Annotated[
        float | None,
        typer.Option("--fee-bps", help="Optional fee assumption in basis points."),
    ] = None,
    display_size_multiplier: Annotated[
        float,
        typer.Option("--display-size-multiplier", help="Multiplier applied to top-of-book size."),
    ] = 1.0,
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Directory for report and chart artifacts."),
    ] = "data/pm_timeseries",
    history_dir: Annotated[
        str | None,
        typer.Option("--history-dir", help="Optional override for the history snapshot root."),
    ] = None,
) -> None:
    """Replay stored snapshot history with a read-only quasi-backtest."""
    settings = reload_settings()
    history_root = Path(history_dir) if history_dir else settings.prediction_market.history_dir
    if provider == "sample":
        store = PredictionMarketSnapshotStore(history_root)
        if not store.load_history_records(provider="sample"):
            seed_sample_history_dataset(history_root)
    result = run_prediction_market_timeseries_backtest(
        store=PredictionMarketSnapshotStore(history_root),
        config=PredictionMarketTimeseriesBacktestConfig(
            provider=provider,
            start_time=start_time,
            end_time=end_time,
            min_edge_bps=min_edge_bps,
            capital_limit=capital_limit,
            max_legs=max_legs,
            max_markets=max_markets,
            fee_bps=(
                fee_bps
                if fee_bps is not None
                else settings.prediction_market.backtest_default_fee_bps
            ),
            display_size_multiplier=display_size_multiplier,
        ),
    )
    output_root = Path(output_dir)
    chart_index = write_prediction_market_timeseries_charts(
        result=result,
        output_dir=output_root,
    )
    report_path = write_phase12_timeseries_report(
        result=result,
        chart_index=chart_index,
        output_dir=output_root,
        run_id="cli",
    )
    typer.echo(
        " ".join(
            [
                f"provider={result.metrics.provider}",
                f"snapshots={result.metrics.snapshot_count}",
                f"opportunities={result.metrics.opportunity_count}",
                f"simulated_trades={result.metrics.simulated_trade_count}",
                f"cumulative_estimated_profit={result.metrics.cumulative_estimated_profit:.4f}",
                f"report={report_path}",
                f"charts={output_root / 'chart_index.json'}",
            ]
        )
    )


@prediction_market_app.command("doctor")
def prediction_market_doctor() -> None:
    """Print Phase 8 optional dependency and live-integration status."""
    scipy_available = importlib.util.find_spec("scipy") is not None
    typer.echo("prediction_market_phase=8")
    typer.echo(f"scipy_available={scipy_available}")
    typer.echo("live_api_disabled=yes")
    typer.echo("orders_disabled=yes")
    typer.echo("signing_disabled=yes")


@options_app.command("daily-scan")
def options_daily_scan(
    top: Annotated[
        int,
        typer.Option("--top", help="Number of universe symbols to scan."),
    ] = 100,
    strategies: Annotated[
        str,
        typer.Option("--strategies", help="Comma-separated sell_put,covered_call list."),
    ] = "sell_put,covered_call",
    run_date: Annotated[
        str | None,
        typer.Option("--date", help="Run date label, YYYY-MM-DD. Defaults to US date."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate the plan/provider without writing output."),
    ] = False,
    provider: Annotated[
        Literal["futu", "sample"] | None,
        typer.Option("--provider", help="Read-only options data provider."),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", help="Override radar snapshot output directory."),
    ] = None,
) -> None:
    """Run the Phase 13 read-only daily seller-options radar."""
    settings = reload_settings()
    active_provider_name = provider or settings.options_radar.provider
    selected_strategies = _parse_strategies(strategies)
    universe = OptionsUniverse.load(
        settings.options_radar.universe_path,
        top_n=top,
    )
    active_output_dir = Path(output_dir) if output_dir else settings.options_radar.output_dir
    typer.echo(
        " ".join(
            [
                f"dry_run={str(dry_run).lower()}",
                f"provider={active_provider_name}",
                f"top={len(universe)}",
                f"strategies={','.join(selected_strategies)}",
                f"output_dir={active_output_dir}",
            ]
        )
    )
    active_provider = _build_options_radar_provider(settings, active_provider_name)
    if dry_run:
        if active_provider_name == "futu":
            try:
                active_provider.fetch_option_expirations(universe[0].ticker)
            except Exception as exc:
                typer.echo(f"provider_check=failed reason={type(exc).__name__}: {exc}")
                raise typer.Exit(code=3) from exc
        provider_check = (
            "provider_check=skipped" if active_provider_name == "sample" else "provider_check=ok"
        )
        typer.echo(provider_check)
        return

    try:
        with options_radar_scan_lock(active_output_dir):
            market_regime = _load_market_regime(settings, run_date)
            if market_regime is not None:
                typer.echo(
                    " ".join(
                        [
                            f"market_regime={market_regime.volatility_regime}",
                            f"w_vix={market_regime.w_vix}",
                            f"vix_density={market_regime.vix_density}",
                            f"term_ratio={market_regime.term_ratio}",
                        ]
                    )
                )
            else:
                typer.echo("market_regime=Unknown reason=no_vix_history")
            report = run_options_radar(
                provider=active_provider,
                universe=universe,
                config=OptionsRadarConfig(
                    base_screen_config=_build_radar_screen_config(settings),
                    strategies=selected_strategies,
                    universe_top_n=top,
                    top_per_ticker=5,
                ),
                iv_history_dir=active_output_dir / "iv_history",
                earnings_calendar=EarningsCalendar.load(
                    settings.options_radar.earnings_calendar_path
                ),
                run_date=run_date,
                market_regime=market_regime,
            )
            data_path, meta_path = RadarSnapshotStore(active_output_dir).write(report)
    except OptionsRadarScanLocked as exc:
        typer.echo(f"scan status=failed reason={type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(
        " ".join(
            [
                f"run_date={report.run_date}",
                f"universe_size={report.universe_size}",
                f"scanned_tickers={report.scanned_tickers}",
                f"failed_tickers={len(report.failed_tickers)}",
                f"candidates={len(report.candidates)}",
                f"data={data_path}",
                f"meta={meta_path}",
            ]
        )
    )
    if report.scanned_tickers == 0:
        raise typer.Exit(code=3)
    if report.failed_tickers:
        raise typer.Exit(code=2)


@options_app.command("daily-task")
def options_daily_task(
    top: Annotated[
        int,
        typer.Option("--top", help="Number of universe symbols to scan."),
    ] = 100,
    strategies: Annotated[
        str,
        typer.Option("--strategies", help="Comma-separated sell_put,covered_call list."),
    ] = "sell_put,covered_call",
    run_date: Annotated[
        str | None,
        typer.Option("--date", help="Run date label, YYYY-MM-DD. Defaults to US date."),
    ] = None,
    provider: Annotated[
        Literal["futu", "sample"] | None,
        typer.Option("--provider", help="Read-only options data provider."),
    ] = None,
    universe_source: Annotated[
        Literal["public", "github", "sample"],
        typer.Option("--universe-source", help="Universe refresh source."),
    ] = "public",
    earnings_source: Annotated[
        Literal["public", "nasdaq", "yfinance", "sample"],
        typer.Option("--earnings-source", help="Earnings calendar refresh source."),
    ] = "public",
    vix_source: Annotated[
        Literal["public", "sample"],
        typer.Option("--vix-source", help="VIX history refresh source."),
    ] = "public",
    universe_path: Annotated[
        Path | None,
        typer.Option("--universe-path", help="Override universe CSV path."),
    ] = None,
    earnings_path: Annotated[
        Path | None,
        typer.Option("--earnings-path", help="Override earnings calendar CSV path."),
    ] = None,
    vix_path: Annotated[
        Path | None,
        typer.Option("--vix-path", help="Override VIX history CSV path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Override radar snapshot output directory."),
    ] = None,
    vix_lookback_days: Annotated[
        int,
        typer.Option("--vix-lookback-days", help="VIX history lookback window."),
    ] = 400,
) -> None:
    """Refresh Phase 13 radar inputs, then run the read-only daily scan."""
    settings = reload_settings()
    active_provider_name = provider or settings.options_radar.provider
    selected_strategies = _parse_strategies(strategies)
    active_universe_path = universe_path or settings.options_radar.universe_path
    active_earnings_path = earnings_path or settings.options_radar.earnings_calendar_path
    active_vix_path = vix_path or settings.options_radar.vix_history_path
    active_output_dir = output_dir or settings.options_radar.output_dir
    task_date = date.fromisoformat(run_date) if run_date else None
    started_at = datetime.now(UTC).isoformat()
    steps: dict[str, dict[str, Any]] = {}
    current_step = "lock"
    scan_lock = options_radar_scan_lock(active_output_dir)
    lock_acquired = False

    try:
        scan_lock.__enter__()
        lock_acquired = True
        current_step = "universe"
        steps["universe"] = refresh_options_universe(
            active_universe_path,
            source=universe_source,
        )
        _echo_options_daily_task_step("universe", steps["universe"])

        current_step = "earnings"
        steps["earnings"] = refresh_earnings_calendar(
            universe_path=active_universe_path,
            output_path=active_earnings_path,
            source=earnings_source,
            top=top,
            today=task_date,
        )
        _echo_options_daily_task_step("earnings", steps["earnings"])

        current_step = "vix"
        steps["vix"] = refresh_vix_history(
            active_vix_path,
            source=vix_source,
            lookback_days=vix_lookback_days,
            end=task_date,
        )
        _echo_options_daily_task_step("vix", steps["vix"])

        current_step = "scan"
        market_regime = load_market_regime(active_vix_path, run_date=run_date)
        universe = OptionsUniverse.load(active_universe_path, top_n=top)
        report = run_options_radar(
            provider=_build_options_radar_provider(settings, active_provider_name),
            universe=universe,
            config=OptionsRadarConfig(
                base_screen_config=_build_radar_screen_config(settings),
                strategies=selected_strategies,
                universe_top_n=top,
                top_per_ticker=5,
            ),
            iv_history_dir=active_output_dir / "iv_history",
            earnings_calendar=EarningsCalendar.load(active_earnings_path),
            run_date=run_date,
            market_regime=market_regime,
        )
        data_path, meta_path = RadarSnapshotStore(active_output_dir).write(report)
        steps["scan"] = {
            "status": "completed",
            "run_date": report.run_date,
            "universe_size": report.universe_size,
            "scanned_tickers": report.scanned_tickers,
            "failed_tickers": len(report.failed_tickers),
            "candidate_count": len(report.candidates),
            "data_path": str(data_path),
            "meta_path": str(meta_path),
        }
        _echo_options_daily_task_step("scan", steps["scan"])

        current_step = "status"
        status_value = "completed_with_warnings" if report.failed_tickers else "completed"
        status_path = _write_options_daily_task_status(
            active_output_dir,
            {
                "status": status_value,
                "run_date": steps["scan"]["run_date"],
                "provider": active_provider_name,
                "strategies": list(selected_strategies),
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "steps": steps,
            },
        )
    except Exception as exc:
        if not lock_acquired:
            typer.echo(f"step={current_step} status=failed reason={type(exc).__name__}: {exc}")
            raise typer.Exit(code=1) from exc
        status_path = _write_options_daily_task_status(
            active_output_dir,
            {
                "status": "failed",
                "run_date": run_date,
                "provider": active_provider_name,
                "strategies": list(selected_strategies),
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "failed_step": current_step,
                "error": f"{type(exc).__name__}: {exc}",
                "steps": steps,
            },
        )
        typer.echo(f"step={current_step} status=failed reason={type(exc).__name__}: {exc}")
        typer.echo(f"task_status={status_path}")
        raise typer.Exit(code=1) from exc
    finally:
        if lock_acquired:
            scan_lock.__exit__(None, None, None)

    typer.echo(f"task_status={status_path}")
    if report.scanned_tickers == 0:
        raise typer.Exit(code=3)
    if report.failed_tickers:
        typer.echo(f"warning=partial_scan failed_tickers={len(report.failed_tickers)}")


@options_app.command("buyside-screen")
def options_buyside_screen(
    ticker: Annotated[str, typer.Option("--ticker", help="Underlying ticker.")],
    view: Annotated[
        BuySideViewType,
        typer.Option("--view", help="Buy-side thesis view type."),
    ],
    target_price: Annotated[
        float,
        typer.Option("--target-price", help="User thesis target price."),
    ],
    target_date: Annotated[
        str,
        typer.Option("--target-date", help="User thesis target date, YYYY-MM-DD."),
    ],
    max_loss_budget: Annotated[
        float | None,
        typer.Option("--max-loss-budget", help="Optional max loss budget."),
    ] = None,
    risk_preference: Annotated[
        BuySideRiskPreference,
        typer.Option("--risk-preference", help="aggressive, balanced, or conservative."),
    ] = "balanced",
    allow_capped_upside: Annotated[
        bool,
        typer.Option(
            "--allow-capped-upside/--no-allow-capped-upside",
            help="Allow call-spread structures with capped upside.",
        ),
    ] = True,
    avoid_high_iv: Annotated[
        bool,
        typer.Option("--avoid-high-iv", help="Penalize naked long premium in high IV."),
    ] = False,
    volatility_view: Annotated[
        BuySideVolatilityView,
        typer.Option("--volatility-view", help="Volatility thesis."),
    ] = "auto",
    event_risk: Annotated[
        BuySideEventRisk,
        typer.Option("--event-risk", help="Known event risk type."),
    ] = "none",
    expected_iv_change_vol_points: Annotated[
        float | None,
        typer.Option(
            "--expected-iv-change-vol-points",
            help="Optional expected IV change in volatility points.",
        ),
    ] = None,
    iv_rank: Annotated[
        float | None,
        typer.Option("--iv-rank", help="Optional current IV rank, 0-100."),
    ] = None,
    historical_volatility: Annotated[
        float | None,
        typer.Option("--historical-volatility", help="Optional HV decimal value."),
    ] = None,
    as_of_date: Annotated[
        str | None,
        typer.Option("--as-of-date", help="Decision date, YYYY-MM-DD."),
    ] = None,
    max_recommendations: Annotated[
        int,
        typer.Option("--max-recommendations", help="Maximum recommendations to return."),
    ] = 10,
) -> None:
    """Run the Phase 14 read-only buy-side options assistant."""
    settings = reload_settings()
    provider = _build_options_radar_provider(settings, "futu")
    try:
        spot_price = _resolve_options_spot(provider.fetch_underlying_snapshot(ticker), ticker)
        start_expiration, end_expiration = _buyside_expiration_window(view, as_of_date)
        option_chain = provider.fetch_option_quotes_range(
            ticker,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type="CALL",
        )
        result = run_buy_side_decision(
            option_chain,
            BuySideDecisionRequest(
                ticker=ticker,
                spot_price=spot_price,
                view_type=view,
                target_price=target_price,
                target_date=target_date,
                max_loss_budget=max_loss_budget,
                risk_preference=risk_preference,
                allow_capped_upside=allow_capped_upside,
                avoid_high_iv=avoid_high_iv,
                volatility_view=volatility_view,
                event_risk=event_risk,
                expected_iv_change_vol_points=expected_iv_change_vol_points,
                iv_rank=iv_rank,
                historical_volatility=historical_volatility,
                as_of_date=as_of_date,
            ),
            market_regime=_load_market_regime(settings, as_of_date),
            max_recommendations=max_recommendations,
        )
    except Exception as exc:
        typer.echo(f"buy_side_assistant=failed reason={type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


@options_app.command("refresh-universe")
def options_refresh_universe() -> None:
    """Print the manual universe refresh command."""
    typer.echo(
        "python scripts/refresh_options_universe.py --bootstrap-github "
        "--output data/options_universe/sp500_nasdaq100.csv"
    )


@options_app.command("refresh-earnings")
def options_refresh_earnings() -> None:
    """Print the manual earnings refresh command."""
    typer.echo(
        "python scripts/refresh_earnings_calendar.py "
        "--universe data/options_universe/sp500_nasdaq100.csv "
        "--output data/options_universe/earnings_calendar.csv"
    )


@options_app.command("refresh-vix")
def options_refresh_vix() -> None:
    """Print the manual VIX history refresh command (Yahoo source, read-only)."""
    typer.echo(
        "python scripts/refresh_vix_history.py "
        "--output data/options_universe/vix_history.csv --lookback-days 400"
    )


@options_app.command("prune-cache")
def options_prune_cache(
    cache_path: Annotated[
        Path | None,
        typer.Option("--cache-path", help="Override the Futu options DuckDB cache path."),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="UTC timestamp used to decide expiration."),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Delete expired snapshots. Default is dry-run."),
    ] = False,
) -> None:
    """Report or delete expired Futu option quote cache snapshots."""
    settings = reload_settings()
    resolved_cache_path = cache_path or settings.futu.cache_dir / "options_cache.duckdb"
    cache = OptionQuotesCache(resolved_cache_path)
    as_of_timestamp = pd.Timestamp(as_of) if as_of else None
    expired_snapshot_ids = cache.expired_snapshot_ids(as_of=as_of_timestamp)
    removed = cache.prune_expired(as_of=as_of_timestamp) if apply else 0
    typer.echo(
        json.dumps(
            {
                "cache_path": str(resolved_cache_path),
                "mode": "apply" if apply else "dry_run",
                "expired_snapshots": len(expired_snapshot_ids),
                "removed_snapshots": removed,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _build_options_radar_provider(settings, provider: Literal["futu", "sample"]):
    if provider == "sample":
        return SampleOptionsProvider()
    futu_provider = FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
        option_quotes_cache_path=(
            settings.futu.cache_dir / "options_cache.duckdb" if settings.futu.use_cache else None
        ),
    )
    futu_provider.snapshot_batch_size = settings.options_radar.snapshot_batch_size
    return RateLimitedFutuProvider(
        futu_provider,
        bucket=TokenBucket(
            max_tokens=1,
            refill_seconds=settings.options_radar.futu_request_pause_seconds,
        ),
    )


def _load_market_regime(settings, run_date: str | None) -> VixRegimeSnapshot | None:
    """Thin wrapper around :func:`load_market_regime` for the CLI."""
    return load_market_regime(
        settings.options_radar.vix_history_path,
        run_date=run_date,
    )


def _echo_options_daily_task_step(name: str, payload: dict[str, Any]) -> None:
    fields = [f"step={name}", f"status={payload.get('status', 'completed')}"]
    if "source" in payload:
        fields.append(f"source={payload['source']}")
    if "row_count" in payload:
        fields.append(f"rows={payload['row_count']}")
    if "candidate_count" in payload:
        fields.append(f"candidates={payload['candidate_count']}")
    if "output_path" in payload:
        fields.append(f"path={payload['output_path']}")
    if "data_path" in payload:
        fields.append(f"data={payload['data_path']}")
    typer.echo(" ".join(fields))


def _write_options_daily_task_status(
    output_dir: Path,
    payload: dict[str, Any],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "daily_task_status.json"
    status_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return status_path


def _build_radar_screen_config(settings) -> OptionsScreenerConfig:
    return OptionsScreenerConfig(
        ticker="SPY",
        strategy_type="sell_put",
        min_dte=settings.options_radar.min_dte_for_radar,
        max_dte=settings.options_radar.max_dte_for_radar,
        max_delta=settings.options_radar.max_delta_for_radar,
        min_premium=0.10,
        min_apr=0.0,
        max_spread_pct=0.25,
        min_open_interest=20,
        max_hv_iv=1.0,
        trend_filter=True,
        hv_iv_filter=False,
        provider="futu",
        top_n=100,
        min_mid_price=0.10,
        min_avg_daily_volume=100_000,
        min_market_cap=0.0,
        avoid_earnings_within_days=7,
    )


def _resolve_options_spot(snapshot: dict[str, object], ticker: str) -> float:
    for key in ("last", "close", "price"):
        value = snapshot.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    raise ValueError(f"no usable underlying price for {ticker}")


def _buyside_expiration_window(
    view: BuySideViewType,
    as_of_date: str | None,
) -> tuple[str, str]:
    start = date.fromisoformat(as_of_date) if as_of_date else date.today()
    if view.startswith("long_term"):
        min_dte, max_dte = 180, 760
    elif view == "short_term_speculative_bullish":
        min_dte, max_dte = 7, 60
    else:
        min_dte, max_dte = 14, 120
    return (
        (start + timedelta(days=min_dte)).isoformat(),
        (start + timedelta(days=max_dte)).isoformat(),
    )


app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(factor_app, name="factor")
app.add_typer(backtest_app, name="backtest")
app.add_typer(experiment_app, name="experiment")
paper_app.add_typer(paper_strategies_app, name="strategies")
app.add_typer(paper_app, name="paper")
app.add_typer(agent_app, name="agent")
app.add_typer(prediction_market_app, name="prediction-market")
app.add_typer(options_app, name="options")
app.add_typer(hermes_app, name="hermes")
app.add_typer(news_app, name="news")
app.add_typer(d34_app, name="d34")
app.add_typer(brief_app, name="brief")


@brief_app.command("auto-archive")
def brief_auto_archive(
    locale: Annotated[
        str,
        typer.Option(
            "--locale",
            help="Brief locale to archive (zh or en).",
        ),
    ] = "zh",
    base_url: Annotated[
        str,
        typer.Option(
            "--base-url",
            help="Local FastAPI base URL used to collect brief facts.",
        ),
    ] = "http://127.0.0.1:8765",
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--timeout-seconds",
            help="Per-request timeout while collecting brief facts.",
        ),
    ] = 30.0,
) -> None:
    """Build today's brief snapshot from backend facts and upsert it into Postgres.

    Idempotent: re-running on the same day updates the existing
    (owner, issue_date, locale) issue with a new snapshot version. Fails
    closed — if the paper account, equity curve, or performance master is
    unavailable, or the archive database is down, nothing is written and the
    command exits non-zero. Never touches the live brief page.
    """
    from quant_system.brief.auto_archive import (
        AutoArchiveUnavailable,
        build_auto_archive_snapshot,
    )
    from quant_system.brief.repository import (
        BriefDatabaseUnavailable,
        BriefRepository,
    )
    from quant_system.brief.service import BriefService

    normalized_locale = locale.strip().lower()
    if normalized_locale not in {"zh", "en"}:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_auto_archive_invalid_locale",
                    "message": f"unsupported locale {locale!r}; expected zh or en",
                },
            }
        )
        raise typer.Exit(code=2)

    try:
        settings = load_settings()
    except Exception as exc:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_auto_archive_configuration_error",
                    "message": "platform settings are invalid for brief auto-archive",
                    "provider_code": type(exc).__name__,
                },
            }
        )
        raise typer.Exit(code=1) from exc

    try:
        snapshot = build_auto_archive_snapshot(
            base_url=base_url,
            locale=normalized_locale,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
        )
    except AutoArchiveUnavailable as exc:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_auto_archive_source_unavailable",
                    "message": str(exc),
                },
            }
        )
        raise typer.Exit(code=1) from exc

    service = BriefService(BriefRepository(settings))
    try:
        envelope = service.generate_issue(
            issue_date=snapshot.payload.issue_date,
            locale=normalized_locale,
            payload=snapshot.payload,
            source_watermark=snapshot.source_watermark,
        )
    except BriefDatabaseUnavailable as exc:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_database_unavailable",
                    "message": f"brief archive database is unavailable: {exc}",
                },
            }
        )
        raise typer.Exit(code=1) from exc

    _emit_json(
        {
            "ok": True,
            "issue_date": envelope.issue.issue_date.isoformat(),
            "locale": envelope.issue.locale,
            "public_id": envelope.issue.public_id,
            "snapshot_version": envelope.snapshot.version,
            "warnings": snapshot.warnings,
        }
    )


@brief_app.command("rollup")
def brief_rollup(
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="Rollup kind: weekly or monthly.",
        ),
    ] = "weekly",
    period: Annotated[
        str | None,
        typer.Option(
            "--period",
            help=(
                "Explicit period key: 2026-W33 (weekly) or 2026-08 (monthly). "
                "Defaults to the current ISO week / previous calendar month."
            ),
        ),
    ] = None,
    locale: Annotated[
        str,
        typer.Option(
            "--locale",
            help="Brief locale to roll up (zh or en).",
        ),
    ] = "zh",
    timeout_seconds: Annotated[
        float,
        typer.Option(
            "--timeout-seconds",
            help="Rollup LLM request timeout in seconds.",
        ),
    ] = 120.0,
) -> None:
    """Roll a period of archived daily briefs into a weekly/monthly issue.

    Reads daily snapshots straight from the archive database (no HTTP), runs
    the two-pass local-LLM draft + critique pipeline, and writes the validated
    rollup as a new snapshot. Fail-closed: an empty period, a rejected draft,
    an unreachable LLM proxy, or a down database all exit non-zero without
    writing anything.
    """
    from quant_system.brief.auto_archive import BRIEF_TIME_ZONE
    from quant_system.brief.repository import (
        BriefDatabaseUnavailable,
        BriefRepository,
    )
    from quant_system.brief.rollup import (
        RollupEmpty,
        RollupRejected,
        default_period,
        parse_period,
    )
    from quant_system.brief.rollup_llm import RollupLlmClient, RollupLlmUnavailable
    from quant_system.brief.rollup_repository import (
        BriefRollupDatabaseUnavailable,
        BriefRollupRepository,
    )
    from quant_system.brief.rollup_service import BriefRollupService

    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"weekly", "monthly"}:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_rollup_invalid_kind",
                    "message": f"unsupported kind {kind!r}; expected weekly or monthly",
                },
            }
        )
        raise typer.Exit(code=2)

    normalized_locale = locale.strip().lower()
    if normalized_locale not in {"zh", "en"}:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_rollup_invalid_locale",
                    "message": f"unsupported locale {locale!r}; expected zh or en",
                },
            }
        )
        raise typer.Exit(code=2)

    if period is not None and period.strip():
        try:
            period_key, period_start, period_end = parse_period(normalized_kind, period)
        except ValueError as exc:
            _emit_json(
                {
                    "ok": False,
                    "error": {
                        "code": "brief_rollup_invalid_period",
                        "message": str(exc),
                    },
                }
            )
            raise typer.Exit(code=2) from exc
    else:
        today = datetime.now(tz=BRIEF_TIME_ZONE).date()
        period_key, period_start, period_end = default_period(normalized_kind, today)

    try:
        settings = load_settings()
    except Exception as exc:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_rollup_configuration_error",
                    "message": "platform settings are invalid for brief rollup",
                    "provider_code": type(exc).__name__,
                },
            }
        )
        raise typer.Exit(code=1) from exc

    llm = RollupLlmClient(timeout_seconds=timeout_seconds)
    service = BriefRollupService(
        BriefRepository(settings),
        BriefRollupRepository(settings),
        llm,
    )
    try:
        envelope = service.generate_rollup(
            kind=normalized_kind,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
            locale=normalized_locale,
        )
    except RollupEmpty as exc:
        _emit_json(
            {
                "ok": False,
                "error": {"code": "brief_rollup_empty", "message": str(exc)},
            }
        )
        raise typer.Exit(code=1) from exc
    except RollupRejected as exc:
        _emit_json(
            {
                "ok": False,
                "error": {"code": "brief_rollup_rejected", "message": str(exc)},
            }
        )
        raise typer.Exit(code=1) from exc
    except RollupLlmUnavailable as exc:
        _emit_json(
            {
                "ok": False,
                "error": {"code": "brief_rollup_llm_unavailable", "message": str(exc)},
            }
        )
        raise typer.Exit(code=1) from exc
    except (BriefDatabaseUnavailable, BriefRollupDatabaseUnavailable) as exc:
        _emit_json(
            {
                "ok": False,
                "error": {
                    "code": "brief_database_unavailable",
                    "message": f"brief archive database is unavailable: {exc}",
                },
            }
        )
        raise typer.Exit(code=1) from exc

    _emit_json(
        {
            "ok": True,
            "public_id": envelope.issue.public_id,
            "kind": envelope.issue.kind,
            "period_key": envelope.issue.period_key,
            "snapshot_version": envelope.snapshot.version,
            "warnings": envelope.warnings,
        }
    )


@news_app.command("horizon-ingest")
def news_horizon_ingest(
    inbox: Annotated[str | None, typer.Option("--inbox")] = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    once: Annotated[bool, typer.Option("--once")] = True,
) -> None:
    """Ingest READY Horizon inbox runs into the local news tables."""

    del once  # reserved for future watch-loop mode; single-shot is default
    settings = load_settings()
    if inbox:
        settings = settings.model_copy(
            update={"horizon": settings.horizon.model_copy(update={"inbox_dir": inbox})}
        )
    from quant_system.news.horizon_ingest import ingest_horizon_inbox

    result = ingest_horizon_inbox(settings=settings, run_id=run_id)
    typer.echo(json.dumps(result, sort_keys=True))
    if result.get("failed"):
        raise typer.Exit(code=1)


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


def _emit_factor_summary(result: FactorResearchResult) -> None:
    typer.echo(
        " ".join(
            [
                f"rows={result.row_count}",
                f"signals={result.signal_count}",
                f"factor_results={result.factor_results_path}",
                f"signals_path={result.signal_frame_path}",
                f"ic={result.ic_path}",
                f"quantiles={result.quantile_returns_path}",
                f"report={result.report_path}",
            ]
        )
    )


def _emit_backtest_summary(result: BacktestRunResult) -> None:
    typer.echo(
        " ".join(
            [
                f"total_return={result.total_return:.6f}",
                f"sharpe={result.sharpe:.6f}",
                f"max_drawdown={result.max_drawdown:.6f}",
                f"equity_curve={result.equity_curve_path}",
                f"trades={result.trade_blotter_path}",
                f"orders={result.orders_path}",
                f"positions={result.positions_path}",
                f"metrics={result.metrics_path}",
                f"report={result.report_path}",
            ]
        )
    )


def _emit_experiment_summary(result: ExperimentResult) -> None:
    typer.echo(
        " ".join(
            [
                f"experiment_id={result.experiment_id}",
                f"run_count={result.run_count}",
                f"best_run_id={result.best_run_id or '<none>'}",
                f"config={result.config_path}",
                f"runs={result.runs_path}",
                f"folds={result.folds_path}",
                f"agent_summary={result.agent_summary_path}",
                f"report={result.report_path}",
            ]
        )
    )


def _emit_paper_summary(result: PaperTradingRunResult) -> None:
    typer.echo(
        " ".join(
            [
                f"orders={result.order_count}",
                f"trades={result.trade_count}",
                f"risk_breaches={result.risk_breach_count}",
                f"final_equity={result.final_equity:.2f}",
                f"execution_status={result.execution_status}",
                f"orders_path={result.orders_path}",
                f"order_events={result.order_events_path}",
                f"trades_path={result.trades_path}",
                f"risk_breaches_path={result.risk_breaches_path}",
                f"paper_report={result.report_path}",
            ]
        )
    )


def _emit_agent_artifact(
    candidate_id: str,
    path: Any,
    metadata_path: Any,
    *,
    manifest_digest: str | None = None,
) -> None:
    parts = [
        f"candidate_id={candidate_id}",
        "status=pending",
        f"path={path}",
        f"metadata={metadata_path}",
    ]
    if manifest_digest:
        parts.append(f"manifest_digest={manifest_digest}")
        parts.append(
            "approve_cmd="
            f"quant-system agent review --candidate-id {candidate_id} "
            f"--decision approve --expected-digest {manifest_digest} "
            f'--expected-status pending --note "<note>"'
        )
    typer.echo(" ".join(parts))


if __name__ == "__main__":
    app()
