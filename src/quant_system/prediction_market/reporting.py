from __future__ import annotations

from pathlib import Path

from quant_system.prediction_market.backtest import PredictionMarketBacktestResult
from quant_system.prediction_market.models import MispricingCandidate, ProposedTrade
from quant_system.prediction_market.timeseries_backtest import (
    PredictionMarketTimeseriesBacktestResult,
)


def write_prediction_market_report(
    *,
    candidates: list[MispricingCandidate],
    trades: list[ProposedTrade],
    output_dir: str | Path,
    filename: str = "prediction_market_report.md",
) -> Path:
    reports_dir = Path(output_dir) / "prediction_market" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / filename
    lines = [
        "# Phase 8 Prediction Market Dry Report",
        "",
        "This report is generated from deterministic sample data only.",
        "No orders, signatures, token transfers, or live Polymarket calls were made.",
        "",
        "## Candidates",
        "",
        "| market_id | scanner | edge_bps | direction |",
        "| --- | --- | ---: | --- |",
    ]
    for candidate in candidates:
        lines.append(
            f"| {candidate.market_id} | {candidate.scanner_id} | "
            f"{candidate.edge_bps:.2f} | {candidate.direction} |"
        )
    lines.extend(
        [
            "",
            "## Proposed Trades",
            "",
            "| proposal_id | capital | expected_profit | dry_run |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for trade in trades:
        lines.append(
            f"| {trade.proposal_id} | {trade.capital:.2f} | "
            f"{trade.expected_profit:.2f} | {trade.dry_run} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_phase11_backtest_report(
    *,
    result: PredictionMarketBacktestResult,
    chart_index: dict,
    output_dir: str | Path,
    run_id: str,
    provider: str,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    result_path = root / "result.json"
    result_path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    path = root / "report.md"
    lines = [
        "# Phase 11 Polymarket Read-Only Research Report",
        "",
        f"- run_id: `{run_id}`",
        f"- provider: `{provider}`",
        "- mode: read-only research / quasi-backtest",
        "- live trading: disabled",
        "- custody signing: not implemented",
        "- real order placement: not implemented",
        "",
        "## Metrics",
        "",
        f"- markets scanned: {result.metrics.market_count}",
        f"- opportunities: {result.metrics.opportunity_count}",
        f"- trigger rate: {result.metrics.trigger_rate:.4f}",
        f"- mean net edge bps: {result.metrics.mean_edge_bps:.2f}",
        f"- total estimated edge: {result.metrics.total_estimated_edge:.2f}",
        "",
        "## Assumptions",
        "",
    ]
    lines.extend(f"- {item}" for item in result.assumptions)
    lines.extend(["", "## Charts", ""])
    for chart in chart_index.get("charts", []):
        lines.append(f"- [{chart['title']}]({chart['path']})")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "These results are hypothetical observations from snapshots. "
            "They are not execution results and are not investment advice.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_phase12_timeseries_report(
    *,
    result: PredictionMarketTimeseriesBacktestResult,
    chart_index: dict,
    output_dir: str | Path,
    run_id: str,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    path = root / "report.md"
    lines = [
        "# Phase 12 Prediction Market Historical Research Report",
        "",
        f"- run_id: `{run_id}`",
        f"- provider: `{result.metrics.provider}`",
        "- mode: read-only historical quasi-backtest",
        "- real order placement: not implemented",
        "- custody signing: not implemented",
        "- execution: simulated snapshot fill assumptions only",
        "",
        "## Metrics",
        "",
        f"- markets: {result.metrics.market_count}",
        f"- snapshots: {result.metrics.snapshot_count}",
        f"- opportunities: {result.metrics.opportunity_count}",
        f"- simulated trades: {result.metrics.simulated_trade_count}",
        f"- trigger rate: {result.metrics.trigger_rate:.4f}",
        f"- cumulative estimated profit: {result.metrics.cumulative_estimated_profit:.4f}",
        f"- max drawdown: {result.metrics.max_drawdown:.4f}",
        "",
        "## Assumptions",
        "",
    ]
    lines.extend(f"- {item}" for item in result.assumptions)
    lines.extend(["", "## Charts", ""])
    for chart in chart_index.get("charts", []):
        lines.append(f"- [{chart['title']}]({chart['path']})")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "These results are hypothetical timeline replays of stored order-book snapshots.",
            "They are for research only and do not imply real fills or guaranteed profit.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
