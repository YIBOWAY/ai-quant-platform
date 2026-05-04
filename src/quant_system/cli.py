from __future__ import annotations

import importlib.util
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from quant_system import __version__
from quant_system.agent.llm.base import LLMClient
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.agent.runner import AgentRunner
from quant_system.backtest.pipeline import BacktestRunResult, run_sample_backtest
from quant_system.config.settings import load_settings, reload_settings
from quant_system.data.pipeline import IngestionResult, run_sample_ingestion, run_tiingo_ingestion
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.execution.pipeline import PaperTradingRunResult, run_sample_paper_trading
from quant_system.experiments.config import load_experiment_config
from quant_system.experiments.runner import (
    ExperimentResult,
    run_experiment,
    run_sample_experiment,
)
from quant_system.factors.pipeline import FactorResearchResult, run_sample_factor_research
from quant_system.factors.registry import build_default_factor_registry, register_alpha101_library
from quant_system.logging.setup import configure_logging
from quant_system.options.buy_side_decision import (
    BuySideDecisionRequest,
    run_buy_side_decision,
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
agent_app = typer.Typer(help="Run Phase 7 AI research assistant commands.")
prediction_market_app = typer.Typer(
    help="Run Phase 8 prediction-market dry scanning commands."
)
options_app = typer.Typer(help="Run read-only options research commands.")


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
    if host == "0.0.0.0":
        if not bind_public:
            raise typer.BadParameter("0.0.0.0 requires --bind-public")
        if os.getenv("QS_API_ALLOW_PUBLIC_BIND") != "I_UNDERSTAND":
            raise typer.BadParameter(
                "0.0.0.0 requires QS_API_ALLOW_PUBLIC_BIND=I_UNDERSTAND"
            )
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
    registered_ids = [
        factor_id for factor_id in registry.factor_ids() if factor_id not in before
    ]
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
) -> None:
    """Run a Phase 4 experiment from a JSON config file."""
    config = load_experiment_config(config_path)
    result = run_experiment(config, output_dir=output_dir)
    _emit_experiment_summary(result)


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
            help="Override the global kill switch for this paper run.",
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


@agent_app.command("propose-factor")
def agent_propose_factor(
    goal: Annotated[str, typer.Option("--goal", help="Research goal for the candidate factor.")],
    universe: Annotated[
        str,
        typer.Option("--universe", help="Comma-separated symbols, for example SPY,QQQ."),
    ] = "SPY,QQQ",
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Create an inert candidate factor file for human review."""
    artifact = AgentRunner(
        output_dir=output_dir,
        llm=_build_agent_llm(llm_name),
    ).propose_factor(goal=goal, universe=_parse_universe(universe))
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("propose-experiment")
def agent_propose_experiment(
    goal: Annotated[str, typer.Option("--goal", help="Research goal for the experiment.")],
    universe: Annotated[
        str,
        typer.Option("--universe", help="Comma-separated symbols, for example SPY,QQQ."),
    ] = "SPY,QQQ",
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Create an experiment config candidate for human review."""
    artifact = AgentRunner(
        output_dir=output_dir,
        llm=_build_agent_llm(llm_name),
    ).propose_experiment(goal=goal, universe=_parse_universe(universe))
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("summarize")
def agent_summarize(
    experiment_id: Annotated[
        str,
        typer.Option("--experiment-id", help="Experiment id to summarize."),
    ],
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Summarize a local experiment for human review only."""
    artifact = AgentRunner(
        output_dir=output_dir,
        llm=_build_agent_llm(llm_name),
    ).summarize(experiment_id=experiment_id)
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("audit-leakage")
def agent_audit_leakage(
    factor_id: Annotated[str, typer.Option("--factor-id", help="Factor id to inspect.")],
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
    llm_name: Annotated[
        Literal["stub", "openai"],
        typer.Option("--llm", help="LLM backend. Defaults to deterministic stub."),
    ] = "stub",
) -> None:
    """Write a point-in-time and look-ahead checklist candidate."""
    artifact = AgentRunner(
        output_dir=output_dir,
        llm=_build_agent_llm(llm_name),
    ).audit_leakage(factor_id=factor_id)
    _emit_agent_artifact(artifact.candidate_id, artifact.path, artifact.metadata_path)


@agent_app.command("list-candidates")
def agent_list_candidates(
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
) -> None:
    """List candidate artifacts and their review status."""
    candidates = AgentRunner(output_dir=output_dir).list_candidates()
    if not candidates:
        typer.echo("no_candidates=true")
        return
    for candidate in candidates:
        path = Path(output_dir, "agent", "candidates", candidate["candidate_id"])
        typer.echo(
            " ".join(
                [
                    f"candidate_id={candidate['candidate_id']}",
                    f"type={candidate['artifact_type']}",
                    f"status={candidate['status']}",
                    f"path={path}",
                ]
            )
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
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", help="Agent artifact output directory."),
    ] = "data/agent_run",
) -> None:
    """Record a manual review; approve only writes an approval lock."""
    record = AgentRunner(output_dir=output_dir).review(
        candidate_id=candidate_id,
        decision=decision,
        note=note,
    )
    typer.echo(
        " ".join(
            [
                f"candidate_id={record.candidate_id}",
                f"decision={record.decision}",
                "registration=manual_required",
            ]
        )
    )


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
            "provider_check=skipped"
            if active_provider_name == "sample"
            else "provider_check=ok"
        )
        typer.echo(provider_check)
        return

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
        earnings_calendar=EarningsCalendar.load(settings.options_radar.earnings_calendar_path),
        run_date=run_date,
        market_regime=market_regime,
    )
    data_path, meta_path = RadarSnapshotStore(active_output_dir).write(report)
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


def _build_options_radar_provider(settings, provider: Literal["futu", "sample"]):
    if provider == "sample":
        return SampleOptionsProvider()
    futu_provider = FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
    )
    futu_provider.snapshot_batch_size = settings.options_radar.snapshot_batch_size
    return RateLimitedFutuProvider(
        futu_provider,
        bucket=TokenBucket(
            max_tokens=settings.options_radar.futu_rate_limit_per_30s,
            refill_seconds=30,
        ),
    )


def _load_market_regime(settings, run_date: str | None) -> VixRegimeSnapshot | None:
    """Thin wrapper around :func:`load_market_regime` for the CLI."""
    return load_market_regime(
        settings.options_radar.vix_history_path,
        run_date=run_date,
    )


def _build_radar_screen_config(settings) -> OptionsScreenerConfig:
    return OptionsScreenerConfig(
        ticker="SPY",
        strategy_type="sell_put",
        min_dte=settings.options_radar.min_dte_for_radar,
        max_dte=settings.options_radar.max_dte_for_radar,
        max_delta=0.45,
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
    start = (
        date.fromisoformat(as_of_date)
        if as_of_date
        else date.today()
    )
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
app.add_typer(paper_app, name="paper")
app.add_typer(agent_app, name="agent")
app.add_typer(prediction_market_app, name="prediction-market")
app.add_typer(options_app, name="options")


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
                f"orders_path={result.orders_path}",
                f"order_events={result.order_events_path}",
                f"trades_path={result.trades_path}",
                f"risk_breaches_path={result.risk_breaches_path}",
                f"paper_report={result.report_path}",
            ]
        )
    )


def _emit_agent_artifact(candidate_id: str, path: Any, metadata_path: Any) -> None:
    typer.echo(
        " ".join(
            [
                f"candidate_id={candidate_id}",
                "status=pending",
                f"path={path}",
                f"metadata={metadata_path}",
            ]
        )
    )


if __name__ == "__main__":
    app()
