# Terminal Trading Surface Style

Last reviewed: 2026-07-01

This note captures the visual direction validated on `/position-map`. The goal is a
neutral trading-terminal surface inspired by market tools, not a copy of any
specific product.

## Core Direction

- Use flat graphite surfaces: `bg-bg-base`, `bg-bg-surface`,
  `bg-bg-surface-muted`, and `border-border-subtle`.
- Keep data dense and scannable: label caps, monospace values, right-aligned
  numeric cells, hairline row dividers, restrained row hover.
- Reserve green/red for financial gain/loss semantics. Zero P&L is neutral.
- Avoid blue/purple AI-dashboard gradients, glow, bokeh, large shadows, and
  decorative hero cards on operational pages.

## Interaction Contract

- If it looks clickable, it must either navigate, mutate state, open a real
  panel, or be visually disabled with `aria-disabled`, muted text, and a clear
  title.
- Do not copy broker-specific chrome such as TradingView delay badges, close
  icons, or action glyphs unless the platform implements that exact meaning.
- Hide unsupported columns instead of rendering permanent `--` cells for future
  concepts such as take-profit/stop-loss.
- Download, filter, account dropdowns, and history tabs should not appear as
  active controls until they are wired to real behavior.

## Reusable Patterns To Extract

- `TerminalMetric`: compact label/value metric with semantic gain/loss tone.
- `TerminalTable`: dense table wrapper with internal horizontal scrolling,
  numeric cell alignment, row hover, and stable test markers. First shared
  implementation lives in `src/frontend/components/ui/primitives.tsx`.
- `ToneBadge`: shared badge contract for source, status, provider, and safety
  labels. First shared implementation lives in
  `src/frontend/components/ui/primitives.tsx`.
- `TerminalToolbarButton`: small operational toolbar action with real disabled
  state and terminal-surface hover behavior.
- `ExposureBarStack`: strategy/manual attribution bar used by account exposure
  and research comparison views.

## AI News Convergence

Keep the AI News product model: feed first, daily report as a secondary tab,
read-only source warnings, and original-link access. Visually, converge it to
the terminal system:

- Replace page/header gradients and shadow glow with flat terminal surfaces.
- Make the header match the `/position-map` shell: title/subtitle left, status
  pills and refresh right.
- Turn filters into a compact toolbar instead of luminous segmented controls.
- Restyle feed cards as dense market-news rows with mono time/source metadata,
  headline text, and a small original-link action.
- Keep errors in danger styling; keep source-readiness/status in warning/info
  styling.

Status: `/ai-news` feed has been migrated from timeline cards to dense terminal
blotter tables using the shared `TerminalTable`, `ToneBadge`, and
`TerminalToolbarButton` primitives. Daily report cards remain compatible with
the same flat terminal surfaces and can be tightened further in a later slice.
`DataPreviewTable` also now composes `TerminalTable`, so backtest, factor,
paper-run, options-radar, and strategy-catalog preview tables inherit the same
scrolling and row-density contract when data is present.

## Paper Trading Convergence

- Manual order, pending-limit check, full-account rebalance, account freeze, and
  strategy sleeve actions now use the shared `TerminalToolbarButton` contract
  instead of heavy filled green buttons.
- Strategy sleeve state chips use `ToneBadge`; the sleeve panel remains
  operational and dense without introducing broker-specific chrome.
- The migration is visual only: manual orders, pending-order processing,
  full-account rebalance behavior, sleeve signal generation, and explicit
  execution processing keep their existing API paths and safety semantics.

## Research Form Controls

- Backtest, Factor Lab, paper replay, experiments, data explorer, and
  prediction-market research controls should share the terminal input classes
  from `primitives.tsx`.
- Primary run/load actions use `TerminalToolbarButton` with info tone; avoid
  filled green submit buttons unless a future workflow needs a truly primary
  global CTA.
- Research handoff links such as "Send to Backtest" should visually match the
  same compact bordered info action instead of becoming large filled CTAs.
- Navigation, tabs, locale toggles, and generic retry/review actions should use
  neutral/info states. Do not use success green for selection or app chrome.
- These migrations are visual-only. They must not change react-hook-form
  field names, validation schemas, request payloads, read-only safety text, or
  route destinations.
