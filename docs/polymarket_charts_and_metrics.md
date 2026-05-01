# Polymarket Charts and Metrics

Phase 11 writes deterministic SVG charts and JSON/Markdown reports.

## Charts

- `opportunity_count.svg`: number of scanner triggers.
- `edge_histogram.svg`: distribution of net edge in basis points.
- `cumulative_estimated_edge.svg`: cumulative hypothetical estimated edge.
- `parameter_sensitivity.svg`: opportunity count under different minimum edge
  thresholds.

## Metrics

- `market_count`: number of markets scanned.
- `opportunity_count`: number of hypothetical scanner triggers.
- `trigger_rate`: opportunities divided by markets scanned.
- `mean_edge_bps`: average net edge after fee assumption.
- `max_edge_bps`: largest net edge.
- `total_estimated_edge`: capital limit multiplied by net edge.
- `max_drawdown`: drawdown on the cumulative estimated edge curve.

## Interpretation

These metrics are research estimates from snapshots. They are not realized
trading results and do not imply fillability, settlement correctness, or future
profit.
