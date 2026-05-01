# Polymarket Troubleshooting

## `provider_timeout`

The public endpoint did not respond before the timeout. Use `provider=sample`,
reduce `max_markets`, or retry later.

## `provider_invalid_response`

The public response shape changed or did not include expected fields. Run the
mocked tests first, then verify the endpoint manually before changing parser
logic.

## Credential Rejected

Phase 11 does not accept API keys, tokens, private keys, cookies, or wallet
material. Remove any field containing key, secret, token, password, or private.

## No Opportunities

This can be normal. Increase the market count, lower `min_edge_bps`, or inspect
the order books. Do not interpret no opportunities as a system failure.

## Frontend Button Disabled

Run buttons stay disabled until the page is ready. If they remain disabled,
confirm the frontend is running on `127.0.0.1:3001` and the backend is running on
`127.0.0.1:8765`.
