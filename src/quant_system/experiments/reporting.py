from __future__ import annotations

from quant_system.experiments.models import ExperimentConfig, ExperimentRunSummary


def generate_experiment_comparison_report(
    *,
    experiment_id: str,
    config: ExperimentConfig,
    runs: list[ExperimentRunSummary],
) -> str:
    lines = [
        "# Phase 4 Experiment Comparison Report",
        "",
        "## Scope",
        "",
        "This report compares research experiments only. It does not select a live "
        "strategy and does not place orders.",
        "",
        "## Experiment",
        "",
        f"- Experiment id: {experiment_id}",
        f"- Name: {config.experiment_name}",
        f"- Symbols: {', '.join(config.symbols)}",
        f"- Date range: {config.start} to {config.end}",
        f"- Walk-forward enabled: {config.walk_forward.enabled}",
        "",
        "## Results",
        "",
    ]
    if not runs:
        lines.extend(["No runs were produced.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "| run_id | total_return | sharpe | max_drawdown | turnover | fold_count | params |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for run in sorted(runs, key=lambda item: item.sharpe, reverse=True):
        lines.append(
            f"| {run.run_id} | {run.total_return:.6f} | {run.sharpe:.6f} | "
            f"{run.max_drawdown:.6f} | {run.turnover:.6f} | {run.fold_count} | "
            f"{run.parameters} |"
        )
    lines.extend(
        [
            "",
            "## Leakage Controls",
            "",
            "- Factor standardization is cross-sectional at each `signal_ts`.",
            "- Composite scores use only factor values already stamped by Phase 2.",
            "- Backtests execute only at `tradeable_ts`.",
            "- Walk-forward validation computes factors with train+validation history but "
            "only evaluates validation dates.",
            "- No run is promoted to live automatically.",
            "",
        ]
    )
    return "\n".join(lines)
