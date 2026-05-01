# Phase 11 Learning Notes

## Core Idea

Prediction markets have outcomes whose prices can be interpreted as market
prices for conditional payoff tokens. A complete binary market has YES and NO
outcomes. If both asks sum far below or above 1.0, the scanner records a pricing
inconsistency for research.

## What This Phase Builds

- Read-only market and order book ingestion.
- Cached snapshots for replay.
- Scanner output.
- Quasi-backtest metrics.
- SVG charts and markdown reports.

## What It Does Not Build

- No real orders.
- No wallet signing.
- No private keys.
- No token transfer.
- No settlement or redemption.

## Quasi-Backtest Assumptions

This is not a fill simulator. It treats each snapshot as one observation and
estimates hypothetical edge after simple fee assumptions. It does not prove that
the displayed size could be filled.

## Common Mistakes

- Treating sample opportunities as real market opportunities.
- Treating scanner output as guaranteed profit.
- Ignoring fees, latency, and partial fills.
- Mixing read-only research code with execution code.

## Self Check

- Can the workflow run with `provider=sample` and no network?
- Does the UI say read-only?
- Does every response include the safety footer?
- Are credential-like request fields rejected?
