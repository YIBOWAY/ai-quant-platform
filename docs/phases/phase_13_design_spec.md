# Phase 13 Design Spec - Options Radar

## Scope

Phase 13 adds a read-only daily options radar for seller-style screening. It scans
a committed `S&P 500 ∪ Nasdaq 100` universe, runs the existing single-ticker
Options Screener for `sell_put` and `covered_call`, ranks candidates globally,
stores the snapshot locally, exposes it through the local API, and displays it in
the frontend at `/options-radar`.

## Non-goals

- No order placement.
- No Futu trade context.
- No account unlock.
- No wallet, signing, private key, or live trading.
- No runtime web scraping for universe or earnings data.
- No guarantee that a candidate is tradable at the shown price.

## Data Flow

```text
Committed universe CSV
        |
        v
OptionsUniverse.load()
        |
        v
RateLimitedFutuProvider or SampleOptionsProvider
        |
        v
run_options_screener() per ticker / strategy
        |
        v
IV history + earnings calendar + VIX regime penalty hook
        |
        v
OptionsRadarReport
        |
        v
RadarSnapshotStore
        |
        v
GET /api/options/daily-scan
        |
        v
/options-radar frontend table + CSV export
```

## Provider Switching

- `futu`: default production research provider. Uses only `OpenQuoteContext`
  through the existing read-only Futu provider.
- `sample`: deterministic offline provider for tests, demos, and CI.

`QS_OPTIONS_RADAR_PROVIDER=sample` can be used for offline runs. The CLI also
accepts `--provider sample`.

## Storage

Daily output is written under `data/options_scans/`:

- `{YYYY-MM-DD}.jsonl`: one candidate per line
- `{YYYY-MM-DD}_meta.json`: run metadata and failures
- `iv_history/{ticker}.jsonl`: accumulated IV samples

The store is idempotent by `(run_date, ticker, contract_symbol, strategy)`.

## Scoring

The global score is:

```text
rating weight + clipped APR score + 0.4 * IV Rank
- earnings-window penalty - wide-spread penalty + market-regime penalty
```

Rating weights are `Strong=100`, `Watch=30`, `Avoid=0`.

## Market Regime

The local project `E:\programs\APEXUSTech_Inter\quantplatform` uses VIX, VIX3M,
and market trend to classify market risk into `Normal`, `Elevated`, and `Panic`.
Phase 13 ports the VIX classification logic as a reusable, tested module.

Manual Futu probe on 2026-05-03:

- `US.VIX`: returned "unknown stock"
- `US.VIX3M`: returned "unknown stock"
- `US.SPY`: returned historical K-line data

Therefore the radar has a market-regime penalty hook, but does not wire runtime
VIX data yet. This avoids mixing Yahoo Finance into the daily runtime path.

## Safety Boundaries

All Phase 13 code is read-only. It never imports or calls Futu trade APIs and
does not expose any route that can submit, modify, sign, or place orders.

