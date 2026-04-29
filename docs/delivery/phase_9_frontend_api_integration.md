# Phase 9 Frontend/API Integration Check

## Scope

This check verifies that the Next.js frontend in `src/frontend/` can run locally and read real responses from the Phase 9 backend API.

## Local Ports

- Backend API: `http://127.0.0.1:8765`
- Frontend: `http://127.0.0.1:3000`

## Backend Startup Options

The backend is a FastAPI app. The standard direct startup command is:

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

Meaning:

- `python -m uvicorn`: start the ASGI server used by FastAPI.
- `quant_system.api.server:create_app`: load the app factory from the project.
- `--factory`: tell uvicorn that `create_app` must be called to build the app.
- `--host 127.0.0.1`: bind only to this machine.
- `--port 8765`: expose the backend API on port `8765`.

The project CLI also provides this convenience wrapper:

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

That wrapper still calls `uvicorn` internally. It exists to keep the same project CLI style as `data`, `factor`, `backtest`, `paper`, and to enforce local-safe defaults such as blocking public bind unless explicitly confirmed.

Full web testing needs two services at the same time: backend on `8765`, frontend on `3000`.

## Commands Used

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

```powershell
cd src/frontend
npm install
npm run lint
npm run build
npm run dev -- -p 3000
```

One-command local start from repository root:

```powershell
conda activate ai-quant
.\scripts\start_phase9_full_stack.ps1
```

If port `3000` is already occupied:

```powershell
.\scripts\start_phase9_full_stack.ps1 -FrontendPort 3001
```

Stop:

```powershell
.\scripts\stop_phase9_full_stack.ps1
```

## Backend Smoke Result

The integration run created sample backend artifacts through real API calls:

- `POST /api/backtests/run`
- `POST /api/paper/run`
- `POST /api/agent/tasks`
- `POST /api/prediction-market/scan`
- `POST /api/prediction-market/dry-arbitrage`
- `GET /api/symbols`
- `GET /api/factors`

Observed result:

```json
{
  "backend": "ok",
  "frontend_status": 200,
  "pm_candidates": 3,
  "pm_proposed_trades": 3,
  "symbols": "SPY,QQQ,IWM,TLT,GLD",
  "factors": 5
}
```

## Browser Smoke Result

Playwright screenshots were captured after waiting for backend-driven text:

- `output/playwright/dashboard.png` waited for `API CONNECTED`
- `output/playwright/data-explorer.png` waited for `API source`
- `output/playwright/order-book.png` waited for `Loaded`

## Notes

- The frontend now uses `NEXT_PUBLIC_QUANT_API_BASE_URL`, defaulting to `http://127.0.0.1:8765`.
- No live trading endpoint was added.
- Prediction market views use sample data only.
- Agent views read candidate metadata only; candidate source is not executed.
