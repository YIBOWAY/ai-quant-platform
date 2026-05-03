# Phase 13 Learning Notes

## Why Options Radar Exists

The single-ticker Options Screener answers: "What looks reasonable for this one
stock?" The Options Radar answers: "Across a broad universe, which contracts
rank highest today?"

## Why This Is Not Trading Advice

The radar only filters and ranks contracts using quotes, IV, liquidity, DTE, and
simple risk labels. It does not know your account, tax situation, assignment
risk tolerance, or portfolio. It cannot place orders.

## IV Rank Cold Start

IV Rank needs a history of daily ATM IV. Until at least 30 samples exist for a
ticker, IV Rank is `null` and contributes zero points to the global score.

## Earnings Calendar

Futu OpenAPI does not provide a complete earnings calendar in this project.
Phase 13 reads an offline CSV instead. The refresh script is manual so runtime
scans stay deterministic.

## VIX Regime

The imported VIX idea is useful, but Futu did not return `US.VIX` or `US.VIX3M`
in the local verification. The code therefore keeps the classification module
and score hook, but does not fetch VIX at runtime yet.

## Rate Limits

Full-market scans can be slow by design. The limit is intentional: the scanner
should respect Futu quote pacing rather than trying to be low-latency.

