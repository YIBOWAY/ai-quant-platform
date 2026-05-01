# Polymarket Read-Only Integration Guide

Phase 11 supports public, read-only Polymarket market data for research.

## Supported

- Market list discovery.
- Order book snapshot retrieval.
- Local JSONL snapshot cache.
- Scanner and quasi-backtest runs.
- Chart and markdown report output.

## Not Supported

- Live trading.
- Wallet connection.
- Signing.
- Private keys.
- Order placement.
- Token transfers.
- Redemption.

## Provider Selection

Use sample data:

```json
{"provider":"sample","min_edge_bps":200}
```

Use Polymarket read-only data:

```json
{"provider":"polymarket","min_edge_bps":200,"max_markets":10}
```

No API key is accepted.

## Cache

Snapshots are written under:

```text
data/prediction_market/snapshots/YYYY-MM-DD/<provider>/<market_id>.jsonl
```

Each record includes provider, market id, condition id, fetched time, market
payload, order books, and source label.

## Troubleshooting

- `HTTP 403`: the public endpoint rejected access from the current environment.
  This can happen because of provider-side access controls or regional/network
  restrictions. Use `provider=sample` or replay fixtures for development, and
  verify endpoint access from the intended deployment network before relying on
  real read-only ingestion.
- `provider_timeout`: public endpoint did not respond before the timeout.
- `provider_http_error`: public endpoint returned a non-2xx response.
- `provider_invalid_response`: response shape did not match the expected schema.
- `Credential-like fields are not accepted`: remove key/secret/token/password
  fields from the request.
