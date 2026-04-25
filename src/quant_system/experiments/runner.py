from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.config.settings import load_settings
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.experiments.config import create_sample_experiment_config
from quant_system.experiments.models import (
    ExperimentConfig,
    ExperimentRunSummary,
    ParameterCombination,
    WalkForwardSplit,
)
from quant_system.experiments.reporting import generate_experiment_comparison_report
from quant_system.experiments.scoring import build_multifactor_score_frame
from quant_system.experiments.storage import LocalExperimentStorage
from quant_system.experiments.sweep import expand_parameter_grid
from quant_system.experiments.walk_forward import build_walk_forward_splits
from quant_system.factors.pipeline import compute_factor_pipeline
from quant_system.factors.registry import build_default_factor_registry


class ExperimentResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    experiment_id: str
    config_path: Path
    runs_path: Path
    folds_path: Path
    agent_summary_path: Path
    report_path: Path
    run_count: int
    best_run_id: str | None


def run_sample_experiment(
    *,
    symbols: list[str],
    start: str,
    end: str,
    lookbacks: list[int],
    top_ns: list[int],
    output_dir: str | Path | None = None,
    initial_cash: float = 100_000.0,
    commission_bps: float = 1.0,
    slippage_bps: float = 5.0,
    rebalance_every_n_bars: int = 1,
) -> ExperimentResult:
    config = create_sample_experiment_config(
        symbols=symbols,
        start=start,
        end=end,
        lookbacks=lookbacks,
        top_ns=top_ns,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        rebalance_every_n_bars=rebalance_every_n_bars,
    )
    return run_experiment(config, output_dir=output_dir)


def run_experiment(
    config: ExperimentConfig,
    *,
    output_dir: str | Path | None = None,
) -> ExperimentResult:
    now_utc = datetime.now(UTC)
    created_at = now_utc.isoformat()
    experiment_id = f"{config.experiment_name}-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    provider = SampleOHLCVProvider()
    ohlcv = provider.fetch_ohlcv(config.symbols, start=config.start, end=config.end)
    combinations = expand_parameter_grid(config.sweep)
    runs: list[ExperimentRunSummary] = []
    fold_records: list[dict[str, Any]] = []

    for combination in combinations:
        run, folds = _run_combination(
            config=config,
            combination=combination,
            ohlcv=ohlcv,
            created_at=created_at,
        )
        runs.append(run)
        fold_records.extend(folds)

    storage = _build_storage(output_dir, experiment_id=experiment_id)
    config_path = storage.save_config(config)
    runs_frame = pd.DataFrame([run.flat_record() for run in runs])
    runs_path = storage.save_frame(
        runs_frame,
        filename="experiment_runs.parquet",
        table_name="experiment_runs",
    )
    folds_frame = pd.DataFrame(
        fold_records,
        columns=[
            "run_id",
            "fold_id",
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "total_return",
            "annualized_return",
            "volatility",
            "sharpe",
            "max_drawdown",
            "turnover",
        ],
    )
    folds_path = storage.save_frame(
        folds_frame,
        filename="walk_forward_folds.parquet",
        table_name="experiment_walk_forward_folds",
    )
    report = generate_experiment_comparison_report(
        experiment_id=experiment_id,
        config=config,
        runs=runs,
    )
    report_path = storage.save_report(report)
    agent_summary_path = storage.save_json(
        _build_agent_summary(
            experiment_id=experiment_id,
            created_at=created_at,
            config=config,
            runs=runs,
        ),
        filename="agent_summary.json",
    )
    best_run = max(runs, key=lambda run: run.sharpe, default=None)
    return ExperimentResult(
        experiment_id=experiment_id,
        config_path=config_path,
        runs_path=runs_path,
        folds_path=folds_path,
        agent_summary_path=agent_summary_path,
        report_path=report_path,
        run_count=len(runs),
        best_run_id=best_run.run_id if best_run else None,
    )


def _run_combination(
    *,
    config: ExperimentConfig,
    combination: ParameterCombination,
    ohlcv: pd.DataFrame,
    created_at: str,
) -> tuple[ExperimentRunSummary, list[dict[str, Any]]]:
    if config.walk_forward.enabled:
        return _run_walk_forward_combination(
            config=config,
            combination=combination,
            ohlcv=ohlcv,
            created_at=created_at,
        )

    metrics = _run_single_backtest(
        config=config,
        combination=combination,
        ohlcv=ohlcv,
        signal_filter=None,
    )
    return (
        _summary_from_metrics(
            combination=combination,
            created_at=created_at,
            metrics=metrics,
            fold_count=0,
        ),
        [],
    )


def _run_walk_forward_combination(
    *,
    config: ExperimentConfig,
    combination: ParameterCombination,
    ohlcv: pd.DataFrame,
    created_at: str,
) -> tuple[ExperimentRunSummary, list[dict[str, Any]]]:
    timestamps = ohlcv["timestamp"].drop_duplicates().sort_values()
    splits = build_walk_forward_splits(timestamps, config.walk_forward)
    fold_metrics: list[PerformanceMetrics] = []
    fold_records: list[dict[str, Any]] = []
    for split in splits:
        metrics = _run_single_backtest(
            config=config,
            combination=combination,
            ohlcv=ohlcv[
                (ohlcv["timestamp"] >= split.train_start)
                & (ohlcv["timestamp"] <= split.validation_end)
            ],
            signal_filter=split,
        )
        fold_metrics.append(metrics)
        record = _fold_record(combination=combination, split=split, metrics=metrics)
        fold_records.append(record)

    aggregate = _aggregate_fold_metrics(fold_metrics)
    return (
        _summary_from_metrics(
            combination=combination,
            created_at=created_at,
            metrics=aggregate,
            fold_count=len(fold_metrics),
        ),
        fold_records,
    )


def _run_single_backtest(
    *,
    config: ExperimentConfig,
    combination: ParameterCombination,
    ohlcv: pd.DataFrame,
    signal_filter: WalkForwardSplit | None,
) -> PerformanceMetrics:
    lookback = int(combination.parameters.get("lookback", 20))
    top_n = int(combination.parameters.get("top_n", 3))
    factors = _create_factors(config, lookback=lookback)
    factor_results = compute_factor_pipeline(ohlcv, factors=factors)
    score_frame = build_multifactor_score_frame(factor_results, config.factor_blend)

    backtest_ohlcv = ohlcv
    if signal_filter is not None:
        score_frame = score_frame[
            (score_frame["tradeable_ts"] >= signal_filter.validation_start)
            & (score_frame["tradeable_ts"] <= signal_filter.validation_end)
        ].reset_index(drop=True)
        backtest_ohlcv = ohlcv[
            (ohlcv["timestamp"] >= signal_filter.validation_start)
            & (ohlcv["timestamp"] <= signal_filter.validation_end)
        ].reset_index(drop=True)

    strategy = ScoreSignalStrategy(
        score_frame,
        top_n=top_n,
        target_gross_exposure=config.target_gross_exposure,
    )
    backtest_config = BacktestConfig(
        initial_cash=float(combination.parameters.get("initial_cash", config.initial_cash)),
        commission_bps=float(
            combination.parameters.get("commission_bps", config.commission_bps)
        ),
        slippage_bps=float(combination.parameters.get("slippage_bps", config.slippage_bps)),
    )
    return BacktestEngine(backtest_config).run(backtest_ohlcv, strategy).metrics


def _create_factors(config: ExperimentConfig, *, lookback: int):
    registry = build_default_factor_registry()
    return [
        registry.create(factor.factor_id, lookback=lookback)
        for factor in config.factor_blend.factors
    ]


def _summary_from_metrics(
    *,
    combination: ParameterCombination,
    created_at: str,
    metrics: PerformanceMetrics,
    fold_count: int,
) -> ExperimentRunSummary:
    return ExperimentRunSummary(
        run_id=combination.run_id,
        created_at=created_at,
        parameters=combination.parameters,
        total_return=metrics.total_return,
        annualized_return=metrics.annualized_return,
        volatility=metrics.volatility,
        sharpe=metrics.sharpe,
        max_drawdown=metrics.max_drawdown,
        turnover=metrics.turnover,
        fold_count=fold_count,
    )


def _aggregate_fold_metrics(metrics: list[PerformanceMetrics]) -> PerformanceMetrics:
    if not metrics:
        return PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            volatility=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            turnover=0.0,
        )
    compounded_return = 1.0
    for item in metrics:
        compounded_return *= 1 + item.total_return
    return PerformanceMetrics(
        total_return=compounded_return - 1,
        annualized_return=float(pd.Series([item.annualized_return for item in metrics]).mean()),
        volatility=float(pd.Series([item.volatility for item in metrics]).mean()),
        sharpe=float(pd.Series([item.sharpe for item in metrics]).mean()),
        max_drawdown=max(item.max_drawdown for item in metrics),
        turnover=sum(item.turnover for item in metrics),
    )


def _fold_record(
    *,
    combination: ParameterCombination,
    split: WalkForwardSplit,
    metrics: PerformanceMetrics,
) -> dict[str, Any]:
    record = {
        "run_id": combination.run_id,
        "fold_id": split.fold_id,
        "train_start": split.train_start,
        "train_end": split.train_end,
        "validation_start": split.validation_start,
        "validation_end": split.validation_end,
        "total_return": metrics.total_return,
        "annualized_return": metrics.annualized_return,
        "volatility": metrics.volatility,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "turnover": metrics.turnover,
    }
    record.update(combination.parameters)
    return record


def _build_agent_summary(
    *,
    experiment_id: str,
    created_at: str,
    config: ExperimentConfig,
    runs: list[ExperimentRunSummary],
) -> dict[str, Any]:
    best_run = max(runs, key=lambda run: run.sharpe, default=None)
    return {
        "experiment_id": experiment_id,
        "experiment_name": config.experiment_name,
        "created_at": created_at,
        "purpose": "Research experiment comparison for human review.",
        "safety": {
            "live_trading": False,
            "paper_trading": False,
            "auto_promotion": False,
        },
        "data": {
            "source": "sample",
            "symbols": config.symbols,
            "start": config.start,
            "end": config.end,
        },
        "walk_forward": config.walk_forward.model_dump(mode="json"),
        "best_run_id": best_run.run_id if best_run else None,
        "runs": [run.model_dump(mode="json") for run in runs],
        "notes": [
            "Scores are standardized cross-sectionally at each signal timestamp.",
            "Backtests execute on tradeable timestamps only.",
            "This summary is for AI-assisted review, not automatic deployment.",
        ],
    }


def _build_storage(
    output_dir: str | Path | None,
    *,
    experiment_id: str,
) -> LocalExperimentStorage:
    if output_dir is not None:
        return LocalExperimentStorage(base_dir=output_dir, experiment_id=experiment_id)
    data_settings = load_settings().data
    return LocalExperimentStorage(
        base_dir=data_settings.data_dir,
        reports_dir=data_settings.reports_dir,
        duckdb_path=data_settings.duckdb_path,
        experiment_id=experiment_id,
    )
