# Futu Troubleshooting

## OpenD Not Running

Symptom:

- API returns a connection error.
- `scripts/verify_futu_connection.py` cannot create a quote context.

Fix:

1. Start Futu OpenD GUI.
2. Confirm it is logged in.
3. Confirm the API port is listening:

```powershell
Test-NetConnection 127.0.0.1 -Port 11111
```

Expected:

```text
TcpTestSucceeded : True
```

## Wrong Conda Environment

Symptom:

- `ModuleNotFoundError: No module named 'futu'`

Fix:

```powershell
conda activate ai-quant
python -m pip show futu-api
```

If missing:

```powershell
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## Permission Denied

Symptom:

- Futu returns permission-related errors.
- Stock data works but option fields are empty.

Fix:

1. Confirm the market entitlement in Futu.
2. Run:

```powershell
python scripts/verify_futu_connection.py
```

3. Check whether stock K-lines, option expirations, option chains, and option snapshots each return data.

## Empty Data

Possible causes:

- invalid ticker
- weekend or market holiday range
- unsupported frequency
- symbol has no options
- data permission does not cover requested history

Try:

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

## Frontend Cannot Connect Backend

Check that backend is running:

```powershell
curl http://127.0.0.1:8765/api/health
```

If the frontend runs on `3001`, CORS is already configured for:

- `http://127.0.0.1:3001`
- `http://localhost:3001`

## Dropdown Text Is Hard To Read

The frontend select menus use dark option styling as a temporary compatibility fix.

If a browser ignores option styling, use keyboard selection or switch to a custom Select component in a later frontend cleanup.

## Safety Boundary

Do not troubleshoot by adding trading context, account unlock, order submit, or signing code. This integration is read-only market data only.
