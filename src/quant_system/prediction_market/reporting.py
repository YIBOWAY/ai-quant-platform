from __future__ import annotations

from pathlib import Path

from quant_system.prediction_market.models import MispricingCandidate, ProposedTrade


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
