# Short-Term Reversals And Longer-Term Momentum Replication

This document describes the local platform replication of:

Short-Term Reversals and Longer-Term Momentum around the World: Theory and
Evidence. DOI: `10.1093/rfs/hhaf057`.

The local PDF used for implementation review is:

```text
C:\Users\86189\Desktop\Short-Term Reversals and Longer-Term Momentum around the world.pdf
```

## What The Platform Implements

The implemented workflow reproduces the paper's core monthly portfolio test:

1. Pull daily OHLCV data from the selected read-only provider.
2. Convert daily closes to month-end closes.
3. Exclude signal observations where the stock was below `US$1` at the end of
   the prior month.
4. Compute the short-term reversal signal from the past 1-month return.
5. Compute the longer-term momentum signal from months `t-12` through `t-2`.
6. Form default decile long-short portfolios.
7. Measure portfolio returns in the subsequent month.

The reversal leg goes long the prior-month losers and short the prior-month
winners. The momentum leg goes long the higher 12-2 momentum names and shorts
the lower 12-2 momentum names.

The UI also reports a local composite strategy that blends the reversal and
momentum ranks. This composite is a platform convenience for inspection; the
paper's primary tests study the reversal and momentum legs separately.

## Where To Use It

Frontend:

```text
http://127.0.0.1:3001/replications
```

Backend:

```http
POST /api/replications/reversal-momentum/run
```

Example body:

```json
{
  "symbols": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE"],
  "start": "2023-01-01",
  "end": "2026-05-22",
  "provider": "futu",
  "initial_cash": 1.0
}
```

## Data Notes

- Use `provider=futu` for local real Futu OpenD data.
- Use `provider=sample` only for stable local smoke tests.
- The paper uses broad global stock universes. A small ETF basket is useful for
  validating platform flow, but it is not a full academic replication.
- The local implementation needs roughly 14 months of monthly closes before it
  can produce 12-2 momentum signals.

## Current Scope Limits

Implemented now:

- Past 1-month reversal signal.
- Past 2-to-12-month momentum signal.
- Prior-month price filter below `US$1`.
- Default decile long-short formation.
- One-month holding period.
- Monthly return table, composite equity curve, positions, and diagnostics.

Not implemented yet:

- Full country-by-country global stock universe.
- NYSE 10% size breakpoint filter.
- Earnings-announcement attenuation tests.
- Institutional ownership and retail order imbalance tests.
- Full paper tables and cross-country regressions.

## Safety

This replication is research-only. It pulls market data and computes portfolio
returns. It does not create orders, unlock accounts, submit trades, or weaken
the platform's paper-only safety settings.
