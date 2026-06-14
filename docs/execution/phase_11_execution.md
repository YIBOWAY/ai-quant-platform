# Phase 11 执行指南

## 环境

```powershell
conda activate ai-quant
pip install -e ".[api]"
cd src/frontend
npm install
```

## 安全默认值

```text
QS_PREDICTION_MARKET_PROVIDER=sample
QS_POLYMARKET_READ_ONLY=true
QS_POLYMARKET_REQUEST_TIMEOUT_SECONDS=10
QS_POLYMARKET_CACHE_TTL_SECONDS=300
QS_POLYMARKET_CACHE_STALE_IF_ERROR_SECONDS=86400
QS_POLYMARKET_USER_AGENT=ai-quant-platform/phase11
```

无需也不接受任何 Polymarket API 密钥。

## 运行后端与前端

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

```powershell
cd src/frontend
npm run dev -- -H 127.0.0.1 -p 3001
```

打开：

```text
http://127.0.0.1:3001/order-book
```

## API 冒烟测试

```powershell
curl "http://127.0.0.1:8765/api/prediction-market/markets?provider=polymarket&cache_mode=refresh&limit=2"
curl -X POST "http://127.0.0.1:8765/api/prediction-market/backtest" ^
  -H "Content-Type: application/json" ^
  -d "{\"provider\":\"polymarket\",\"cache_mode\":\"prefer_cache\",\"min_edge_bps\":50,\"max_markets\":2}"
```

缓存模式：

- `refresh`：强制发起一次新的公开只读请求，然后覆盖本地缓存。
- `prefer_cache`：优先使用新鲜缓存，必要时再走网络。
- `network_only`：跳过缓存读取；便于调试，但弹性较差。

## 测试

```powershell
conda activate ai-quant
python -m pytest -q
ruff check .
cd src/frontend
npm run lint
npm run build
$env:PW_E2E="1"; npx playwright test
```

Playwright 冒烟测试使用生产风格的前端服务器（先 `next build` 再
`next start`），以避免 `next dev` 首次运行时热刷新的时序噪声。进行手动
开发时，请继续使用 `npm run dev -- -H 127.0.0.1 -p 3001`。

## 成功标志

- 后端安全页脚显示 `live_trading_enabled=false`。
- `/api/orders/submit` 返回 404。
- 预测市场回测响应包含 `run_id`、`metrics`、`chart_index`
  以及 `report_path`。
- 首次 `provider=polymarket&cache_mode=refresh` 请求返回
  `cache_status=live`。
- 第二次 `provider=polymarket&cache_mode=prefer_cache` 请求返回
  `cache_status=cache`。
- 前端显示为只读，且不展示任何钱包或下单控件。
