# Polymarket Strategy and Quasi-Backtest Learning

## Strategy

The Phase 11 strategy checks whether a complete outcome set has prices that
deviate from 1.0 by more than a configured threshold.

Example:

```text
YES ask + NO ask = 0.95
edge = 1.00 - 0.95 = 0.05 = 500 bps
```

## Parameters

- `min_edge_bps`: minimum edge needed to record an opportunity.
- `capital_limit`: hypothetical capital used for estimated edge.
- `max_legs`: maximum legs in a dry proposal.
- `max_markets`: max markets to scan.
- `fee_bps`: conservative deduction from edge.

## Why Quasi-Backtest

Polymarket order books are event-based and sparse. Phase 11 does not yet model
historical fills, latency, partial fills, or settlement. A quasi-backtest is a
reproducible way to evaluate scanner behavior over snapshots without pretending
to be real execution.

## Limitations

- No hit rate unless resolved outcomes are added later.
- No real fill model.
- No settlement risk model.
- No live order management.
