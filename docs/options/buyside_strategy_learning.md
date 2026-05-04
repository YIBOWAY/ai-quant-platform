# Buy-Side US Options Strategy Assistant

Phase 14 adds the Buy-Side US Options Strategy Assistant for bullish long
premium structures. It is decision-support only. It does not place orders,
unlock accounts, or call any trading API.

## Scope

Implemented pieces:

- Normalized option records for read-only Futu option data.
- Buy-side data contracts for thesis, legs, scores, candidates, and scenarios.
- Single-contract quality metrics.
- Candidate generation for:
  - Long Call
  - Bull Call Spread
  - LEAPS Call
- LEAPS Call Spread
- Scenario Lab using a Greek approximation.
- Deterministic decision rules that rank and explain recommendations.
- Local API and CLI wiring for read-only Futu data.
- Frontend page at `/options-buyside`.
- Required risk disclosure and anti-advice language checks.

Not implemented:

- Exact option pricing model.
- Probability of profit.
- Diagonal or calendar spreads.
- Live trading or order placement.

## Main Files

| File | Purpose |
|---|---|
| `src/quant_system/options/option_data.py` | Normalizes provider option rows into platform records. |
| `src/quant_system/options/models.py` | Adds buy-side thesis, leg, score, candidate, and scenario models. |
| `src/quant_system/options/buy_side_metrics.py` | Scores a single option contract and produces warnings. |
| `src/quant_system/options/buy_side_strategy.py` | Builds and ranks buy-side strategy candidates from an option chain. |
| `src/quant_system/options/buy_side_scenarios.py` | Estimates scenario PnL with a Greek approximation. |
| `src/quant_system/options/buy_side_decision.py` | Applies deterministic decision rules and explanations. |
| `src/quant_system/api/routes/options.py` | Exposes `POST /api/options/buy-side/assistant`. |
| `src/quant_system/cli.py` | Exposes `quant-system options buyside-screen`. |
| `src/frontend/app/options-buyside/page.tsx` | Frontend route. |
| `src/frontend/components/forms/BuySideOptionsAssistant.tsx` | Thesis form, recommendations, checklist, and Scenario Lab. |

## Data Flow

```text
Futu read-only option data
  -> option_data.normalize_option_records
  -> BuySideStrategyLeg
  -> buy_side_metrics score
  -> buy_side_strategy candidate ranking
  -> buy_side_decision explanation and demotion labels
  -> buy_side_scenarios scenario matrix
  -> API / CLI / frontend read-only display
```

Every step is pure research output. None of these files can submit, modify, or
cancel orders.

## Important Assumptions

The current Futu mapping uses these conventions:

- `theta` is treated as option price change per contract per day.
- `vega` is treated as option price change per 1 volatility point.
- Contract size defaults to 100 unless provider data says otherwise.
- Missing Greeks, IV, open interest, volume, stale quotes, and invalid bid/ask
  are warnings rather than automatic crashes where possible.

These assumptions are locked by tests. If provider conventions change, update
the tests and documentation together.

## Strategy Logic

Long premium structures are compared by:

- Direction fit versus the target price.
- IV and volatility view.
- Theta burden.
- Liquidity.
- Greek efficiency.
- Reward/risk where definable.
- Market regime penalty from the existing VIX regime module.

High-VIX regimes penalize long premium more than spreads because implied
volatility crush can hurt naked long calls. Spreads receive a smaller penalty
because the short leg offsets part of the vega exposure.

## Scenario Lab Limits

The Scenario Lab uses a first/second order Greek approximation:

```text
new value ~= mid + delta * spot move
                 + 0.5 * gamma * spot move^2
                 + vega * IV change
                 + theta * days passed
```

It is intentionally approximate:

- Accuracy degrades for spot changes above about +/-15%.
- Accuracy degrades when time passed is above 30 days.
- Theta acceleration near expiration is not modeled.
- Vanna, charm, vomma, and other cross-Greeks are ignored.

Each scenario row includes an `approximation_reliability` value:

- `high`
- `medium`
- `low`

## Safety Language

Outputs are quantitative research aids, not investment advice. The module does
not know the user's account, risk tolerance, tax situation, execution quality, or
real fill prices. It must not be described as a trade recommendation engine.

The frontend must show this required disclosure:

```text
This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading.
```

OCC's `Characteristics and Risks of Standardized Options` should be read before
trading options. The disclosure is a required risk control, not decorative text.

## API Contract

Endpoint:

```text
POST /api/options/buy-side/assistant
```

Request body schema: `BuySideAssistantRequest`.

Key fields:

| Field | Required | Notes |
|---|---:|---|
| `ticker` | yes | US underlying ticker, for example `AAPL`. |
| `view_type` | yes | One of the supported bullish thesis views. |
| `target_price` | yes | User thesis target price. |
| `target_date` | yes | ISO date, for example `2026-12-31`. |
| `provider` | no | Defaults to `futu`; other providers return 400. |
| `spot_price` | no | Optional override; when absent, API reads Futu quote snapshot. |
| `iv_rank` | no | Optional 0-100 IV rank. |
| `user_scenarios` | no | Optional subjective scenario EV inputs. |
| `scenario_spot_changes` | no | Optional Scenario Lab spot-change grid. |
| `scenario_iv_changes` | no | Optional Scenario Lab IV-change grid. |
| `scenario_days_passed` | no | Optional Scenario Lab time-passed grid. |
| `max_recommendations` | no | Defaults to 10, max 50. |

Response body schema: `BuySideAssistantResponse`.

Top-level fields:

| Field | Notes |
|---|---|
| `ticker` | Normalized ticker. |
| `thesis` | Echo of the validated decision input. |
| `recommendations` | Ranked strategy results with reasons, risks, scores, scenario summary, demotion badge, and warnings. |
| `recommendations[].legs` | Legs used by the frontend comparison table. |
| `recommendations[].net_debit` | Net premium outlay where defined. |
| `assumptions` | Read-only research and approximation assumptions. |

The API safety middleware also appends the usual `safety` footer to JSON
responses.

Error responses:

| Status | Meaning |
|---:|---|
| 400 | Unsupported provider or invalid parameter combination. |
| 403 | Futu quote permission is insufficient. |
| 404 | Ticker not found, no usable underlying price, or no option chain is available. |
| 422 | Invalid thesis input. |
| 503 | Futu OpenD/provider unavailable or timed out. |

Example request:

```json
{
  "ticker": "AAPL",
  "view_type": "long_term_aggressive_bullish",
  "target_price": 220,
  "target_date": "2026-12-31",
  "provider": "futu",
  "iv_rank": 35,
  "max_recommendations": 5
}
```

Example response shape:

```json
{
  "ticker": "AAPL",
  "recommendations": [
    {
      "strategy_type": "leaps_call",
      "rank": 1,
      "score": 78.2,
      "one_line_summary": "LEAPS Call is more suitable for the stated thesis under the current assumptions.",
      "primary_risk_source": "volatility",
      "warnings": []
    }
  ],
  "assumptions": ["Quantitative decision support only; no order placement is available."]
}
```

## Frontend

Open:

```text
http://127.0.0.1:3001/options-buyside
```

The page includes:

- Trade thesis form.
- Market snapshot panel.
- Strategy recommendation cards.
- Strategy comparison table.
- Anti-pitfall checklist.
- Scenario Lab summary and user-input subjective EV.
- Required risk disclosure.

## Quick Validation

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system/options/buy_side_decision.py src/quant_system/api/routes/options.py src/quant_system/cli.py tests/test_options_buy_side_decision.py tests/test_api_options_buy_side.py tests/test_options_buy_side_cli.py
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```
