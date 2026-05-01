# Polymarket Safety Boundaries

Phase 11 is strictly read-only research/backtest functionality.

It does not include:

- live trading
- wallet signing
- private key handling
- real order placement
- token transfers
- redemption
- broker adapter integration

## API Rules

- Credential-like fields are rejected.
- Unknown providers are rejected.
- Default provider remains `sample`.
- Safety footer remains attached to JSON responses.

## UI Rules

- UI must say read-only research mode.
- UI must not show wallet, sign, submit order, redeem, or live controls.
- Scanner and quasi-backtest results must be described as hypothetical.

## Operational Rule

Do not run this system with real funds or as an execution bot. Any future move
toward paper simulation or live execution requires a separate safety review.
