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

Futu does not expose CBOE indices (`US.VIX` returns `unknown stock`), so the
radar fetches `^VIX` and `^VIX3M` daily closes from the Yahoo Chart REST
endpoint (`query1.finance.yahoo.com/v8/finance/chart/{ticker}`) via
`quant_system.options.vix_data`. The implementation mirrors the reference
project `quantplatform`'s `_fetch_yahoo_single` and is read-only.

The fetched series are cached as `data/options_universe/vix_history.csv`
(`date,vix,vix3m`) by `scripts/refresh_vix_history.py`. The CLI loads this
CSV at the start of each daily scan, calls `compute_vix_regime` (V5 dual
factor: Density + term structure), and passes the resulting snapshot into
`run_options_radar(market_regime=...)`. Per-strategy penalties
(`seller_regime_penalty`) flow through to the `global_score` and are
surfaced as `market_regime` / `market_regime_penalty` on every candidate.

When the CSV is missing or empty, the radar still runs but emits
`market_regime=Unknown reason=no_vix_history` and applies no penalty,
rather than failing the scan.

## Rate Limits

Full-market scans can be slow by design. The limit is intentional: the scanner
should respect Futu quote pacing rather than trying to be low-latency.

