# Futu Environment Setup

## 1. Purpose

This guide verifies the local read-only Futu market-data environment for this project.

It covers:

- activating the correct conda environment
- checking whether OpenD GUI is already running
- verifying the Python SDK inside `ai-quant`
- running a safe quote-only verification script

It does **not** enable trading.

## 2. Safety Boundary

This setup is for **read-only market data** only.

Do not:

- unlock trading
- create trading contexts
- place orders
- modify orders
- expose credentials

## 3. Official Skills Status In This Codex Environment

The official Futu OpenD skills mentioned in the product docs were **not available** in the current local Codex skills/plugins directories during verification.

Manual equivalent path used here:

1. verify the existing local OpenD GUI first
2. verify the Python package inside `ai-quant`
3. install `futu-api` only into `ai-quant` if missing
4. run a local read-only verification script

## 4. Activate The Correct Environment

```powershell
conda activate ai-quant
python -V
python -c "import sys; print(sys.executable)"
```

Expected:

- Python points to `D:\anaconda3\envs\ai-quant\python.exe`
- version is Python 3.11+

## 5. Confirm OpenD GUI Is Running

### 5.1 Visual check

Open the already installed GUI and confirm you are logged in:

`E:\Quant_data\Futu_OpenD_10.4.6408_Windows\Futu_OpenD-GUI_10.4.6408_Windows`

### 5.2 Process check

```powershell
conda activate ai-quant
Get-Process | Where-Object { $_.ProcessName -like '*OpenD*' -or $_.ProcessName -like '*Futu*' } | Select-Object ProcessName,Id,Path
```

### 5.3 Port check

```powershell
conda activate ai-quant
Test-NetConnection -ComputerName 127.0.0.1 -Port 11111 | Select-Object ComputerName,RemotePort,TcpTestSucceeded
```

Expected:

- `TcpTestSucceeded = True`

## 6. Install / Verify Python SDK In `ai-quant`

Check first:

```powershell
conda activate ai-quant
python -m pip show futu-api
```

If missing, install with the required mirror:

```powershell
conda activate ai-quant
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

Official package reference:

- Futu docs show Python installation via `pip install futu-api`

## 7. Run The Verification Script

Script:

- `scripts/verify_futu_connection.py`

Command:

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

Default checks:

- SDK import
- quote context creation
- OpenD global state
- historical daily K-line for:
  - `US.AAPL`
  - `US.NVDA`
  - `US.MSFT`
  - `US.SPY`
- option expiry list for `US.AAPL`
- option chain for one expiry
- option snapshot for one option contract

## 8. Example Successful Output

Sanitized example:

```text
verify_futu_connection
host=127.0.0.1 port=11111
tickers=US.AAPL,US.NVDA,US.MSFT,US.SPY
global_state=qot_logined=True qot_connect_status=None
history_kline_checks
  US.AAPL: rows=9 first={'code': 'US.AAPL', 'time_key': '2024-01-02 00:00:00', ...}
  US.NVDA: rows=9 first={...}
  US.MSFT: rows=9 first={...}
  US.SPY: rows=9 first={...}
options_checks
  expiries=rows=26 selected_expiry=2026-05-08 distance=6
  chain_rows=148 first={'code': 'US.AAPL260508C110000', ...}
  option_snapshot={'code': 'US.AAPL260508C110000', 'bid_price': ..., 'ask_price': ...}
PASS read_only_quote_connectivity
```

## 9. Common Errors

### 9.1 `Package(s) not found: futu-api`

Meaning:

- SDK is not installed in `ai-quant`

Fix:

```powershell
conda activate ai-quant
python -m pip install futu-api -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 9.2 Cannot connect to `127.0.0.1:11111`

Meaning:

- OpenD GUI is not running
- or it is listening on a different host/port

Fix:

- start OpenD GUI
- confirm login completed
- confirm the API port is `11111`

### 9.3 Quote login false / permission errors

Meaning:

- OpenD is open, but quote service is not fully logged in
- or this account lacks the required market-data entitlement

Check:

- US stock LV3 access
- US options LV1 access

### 9.4 Empty stock data

Possible reasons:

- invalid symbol format
- requested date range has no bars
- permission / market-data delay issue

Use Futu symbol format:

- `US.AAPL`
- `US.NVDA`
- `US.MSFT`
- `US.SPY`

### 9.5 Option fields missing or zero

Possible reasons:

- field not included in the returned quote
- permission tier does not expose it
- selected contract is stale / expired / illiquid

The platform must treat missing option fields as missing data, not fabricate them.

## 10. Permission Verification Checklist

What should be checked manually:

- US stock historical K-line is returned
- US option expiry dates are returned
- US option chain is returned
- snapshot fields such as bid/ask/volume return real values when available

If IV / Greeks / open interest are absent or zero for certain contracts, document it as a data limitation instead of guessing.

## 11. Notes For This Repository

- All verification must run inside `ai-quant`
- OpenD GUI should be reused if already working
- this phase remains read-only
- no trading contexts should be added to the codebase

## 12. Official References

- OpenD overview: https://openapi.futunn.com/futu-api-doc/en/opend/opend-intro.html
- Python environment and install: https://openapi.futunn.com/futu-api-doc/en/quick/env.html
- Python example install notes: https://openapi.futunn.com/futu-api-doc/en/quick/demo.html
- Historical K-line: https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html
- Option expiration dates: https://openapi.futunn.com/futu-api-doc/en/quote/get-option-expiration-date.html
- Option chain: https://openapi.futunn.com/futu-api-doc/en/quote/get-option-chain.html
