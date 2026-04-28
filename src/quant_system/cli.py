from __future__ import annotations

import importlib.util
import json
import os
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
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub
from quant_system.prediction_market.pipeline import run_dry_arbitrage, scan_market
from quant_system.prediction_market.reporting import write_prediction_market_report

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
factor_app = typer.Typer(help="Run Phase 2 factor-research commands.")
backtest_app = typer.Typer(help="Run Phase 3 backtest commands.")
experiment_app = typer.Typer(help="Run Phase 4 experiment-management commands.")
paper_app = typer.Typer(help="Run Phase 5 paper-trading commands.")
agent_app = typer.Typer(help="Run Phase 7 AI research assistant commands.")
prediction_market_app = typer.Typer(
    help="Run Phase 8 prediction-market dry scanning commands."
)


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


@prediction_market_app.command("doctor")
def prediction_market_doctor() -> None:
    """Print Phase 8 optional dependency and live-integration status."""
    scipy_available = importlib.util.find_spec("scipy") is not None
    typer.echo("prediction_market_phase=8")
    typer.echo(f"scipy_available={scipy_available}")
    typer.echo("live_api_disabled=yes")
    typer.echo("orders_disabled=yes")
    typer.echo("signing_disabled=yes")


app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(factor_app, name="factor")
app.add_typer(backtest_app, name="backtest")
app.add_typer(experiment_app, name="experiment")
app.add_typer(paper_app, name="paper")
app.add_typer(agent_app, name="agent")
app.add_typer(prediction_market_app, name="prediction-market")


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
