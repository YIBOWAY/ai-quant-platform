# API Audit — Phase 9 Backend (read-only)

> Probed live backend on `127.0.0.1:8765` with `curl.exe`. Source files cross-checked under [src/quant_system/api/](../src/quant_system/api/). **No code changes in this round.**

## 1. 实际存在的 endpoint（全部 200 OK）

| Method | Path | Source file | 备注 |
| --- | --- | --- | --- |
| GET | `/api/health` | [health.py](../src/quant_system/api/routes/health.py) | 返回 status/app_name/environment + safety footer |
| GET | `/api/settings` | [settings.py](../src/quant_system/api/routes/settings.py) | 返回 masked Settings dump（API key 自动 `**********`）|
| GET | `/api/symbols` | [data.py](../src/quant_system/api/routes/data.py) | **fallback 到硬编码 `["SPY","QQQ","IWM","TLT","GLD"]`** |
| GET | `/api/ohlcv` | [data.py](../src/quant_system/api/routes/data.py) | local parquet 优先 → fallback `SampleOHLCVProvider`，**永远不打 Tiingo/Polygon** |
| GET | `/api/benchmark` | [benchmark.py](../src/quant_system/api/routes/benchmark.py) | 直接调 `SampleOHLCVProvider`，无真实 provider 路径 |
| GET | `/api/factors` | [factors.py](../src/quant_system/api/routes/factors.py) | 真实 registry |
| POST | `/api/factors/run` | factors.py | 调 `run_sample_factor_research` |
| GET | `/api/factors/{run_id}` | factors.py | 读盘 |
| POST | `/api/backtests/run` | [backtest.py](../src/quant_system/api/routes/backtest.py) | 调 `run_sample_backtest`（**注意：还是 sample**）|
| GET | `/api/backtests` | backtest.py | 列出 api_runs/backtests |
| GET | `/api/backtests/{run_id}` | backtest.py | 读盘 |
| POST | `/api/paper/run` | [paper.py](../src/quant_system/api/routes/paper.py) | 调 `run_sample_paper_trading`；kill_switch=true 时拒绝 |
| GET | `/api/paper` | paper.py | 列出 |
| GET | `/api/paper/{run_id}` | paper.py | 读盘 |
| GET | `/api/experiments` | experiments.py | TBD（200 但内容未深入） |
| GET | `/api/experiments/{id}` | experiments.py | TBD |
| GET | `/api/agent/candidates` | [agent.py](../src/quant_system/api/routes/agent.py) | 真实 candidate pool |
| GET | `/api/agent/candidates/{id}` | agent.py | 读取 metadata + source preview（**只读为字符串，不 import**）|
| POST | `/api/agent/tasks` | agent.py | propose-factor / propose-experiment / summarize / audit-leakage |
| POST | `/api/agent/candidates/{id}/review` | agent.py | 写 approved.lock / rejected.lock，**不动 FactorRegistry** |
| GET | `/api/prediction-market/markets` | [prediction_market.py](../src/quant_system/api/routes/prediction_market.py) | 仅 `SamplePredictionMarketProvider` |
| POST | `/api/prediction-market/scan` | prediction_market.py | live key → 400 |
| POST | `/api/prediction-market/dry-arbitrage` | prediction_market.py | live key → 400 |

## 2. 前端正在调用的 endpoint（来自 [lib/api.ts](../src/frontend/lib/api.ts)）

`getHealth / getSymbols / getOhlcv / getFactors / getBacktests / getBenchmark / getPaperRuns / getExperiments / getAgentCandidates / getPredictionMarkets`

每个都对应到上面表中的 **GET** 方法，**且没有调用任何 POST**。也就是说：**前端只读、不会触发任何 backtest/paper/factor/agent 任务**。

## 3. 缺失的 endpoint（前端将来需要、目前 backend 没有）

| 前端预期能力 | 缺的 endpoint | 优先级 |
| --- | --- | --- |
| 主题切换持久化 | （前端本地存储即可，无需 API） | — |
| 系统资源（CPU/RAM）真实数据 | `GET /api/health/system`（或干脆移除前端假占用条）| P1（建议移除而不是新增）|
| 真实 SPY market data | 让 `/api/ohlcv` 接 `TiingoEODProvider`（或 polygon）；不需要新路由，但要扩展逻辑 | **P0** |
| Data quality 真实指标 | `GET /api/data/quality?symbol=&start=&end=` | P1 |
| Agent task 进度 / WebSocket | （Phase 9 决议不做 ws）；POST /api/agent/tasks 同步即可 | OK |
| LLM 配置探针 | `GET /api/agent/llm-config`（masked） | P1 |
| Audit log 拉取 | `GET /api/agent/audit/{task_id}` | P1 |

## 4. 返回结构 vs 前端预期 schema 对照

[lib/api.ts](../src/frontend/lib/api.ts) 中定义的 TypeScript schema 与后端实际响应基本一致（手工核对几条）：

| Endpoint | 前端期望字段 | 后端实际返回 | 是否一致 |
| --- | --- | --- | --- |
| `/api/health` | `status, app_name, environment, safety` | 一致 | ✅ |
| `/api/symbols` | `symbols, source` | 一致 | ✅ |
| `/api/ohlcv` | `symbol, source, rows[]` | 一致 | ✅ |
| `/api/factors` | `factors[].factor_id/name/version/lookback/direction/description` | 一致（`registry.list_metadata()`）| ✅ |
| `/api/backtests` | `backtests[].id, metrics{total_return,sharpe,max_drawdown}` | 一致 | ✅ |
| `/api/paper` | `paper_runs[].id, summary{order_count,trade_count,risk_breach_count,final_equity}` | 后端 `summary` 是整个 metadata，**包含 order_count 等字段**，类型上也一致 | ✅（弱）|
| `/api/agent/candidates` | `candidates[].candidate_id, artifact_type, status, goal?` | 一致 | ✅ |
| `/api/prediction-market/markets` | `markets[], order_books[], provider` | 一致 | ✅ |
| `/api/benchmark` | `symbol, equity_curve[], metrics{...}` | 一致 | ✅ |

**没有发现 schema mismatch**。但有两个细节：

1. 所有响应都加了 `safety` footer（由 [safety/middleware.py](../src/quant_system/api/safety/middleware.py) 注入），前端 `ApiEnvelope` 类型支持 optional `safety`，OK。
2. `apiError` 字段是**前端在 fetch 失败时本地补上**的，后端不会返回；前端逻辑 OK。

## 5. CORS / 网络

- 前端运行在 `127.0.0.1:3001`，但 [Settings.api_cors_origins](../src/quant_system/config/settings.py#L113) 默认只允许 `127.0.0.1:3000` 和 `localhost:3000`。
- 因为前端是 **Server Component fetch**（在 Node 进程里直接 fetch backend），所以浏览器其实不参与 CORS——目前能跑是绕过的。
- 一旦改成 client component（必须改，否则按钮永远死的），浏览器会发起 OPTIONS，**会被 CORS 拒绝**。
- **建议**：把默认 CORS 改成 `["http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://localhost:3000", "http://localhost:3001"]`，或在 [.env](../.env) 里加 `QS_API_CORS_ORIGINS='["http://127.0.0.1:3001"]'`。

## 6. LLM 配置审计（用户重点）

`.env` 里有：

```
LLM_API_KEY=<redacted>
LLM_BASE_URL=https://api.xairouter.com/v1
LLM_MODEL=gpt-5.4
LLM_TIMEOUT=60
LLM_PROVIDER=xai
```

但 [Settings](../src/quant_system/config/settings.py) 的字段定义里**根本没有 `llm_*` 字段**（前缀是 `QS_`，且 `extra="ignore"` 会丢弃所有 `LLM_*`）。

- 用 `curl /api/settings` 验证：返回 payload 里没有任何 `llm` 字段。
- [src/quant_system/agent/llm.py](../src/quant_system/agent/llm.py) 默认实例是 `StubLLMClient`（确定性）。
- 即便用户配置了 xai 路由，**当前后端绝对不会拨打那个 endpoint**。Agent 路径走的还是 stub。

> **结论**：LLM_API_KEY 不会泄露（因为根本没用），但用户对 "Agent 已经接 LLM" 的预期不成立。**这是 P0 信息隔离风险（虚假 affordance）**。

## 7. 必查的失败模式（fallback / silent degrade）

| 场景 | 当前行为 | 是否合理 | 建议 |
| --- | --- | --- | --- |
| Tiingo token 存在 + provider=sample | 走 SampleOHLCVProvider | **不合理**：用户付了费却被 mock 替代 | 当 token 存在时优先调 Tiingo；fallback 时在 response 加 `source="sample (tiingo failed: ...)"` |
| Tiingo token 缺失 | 走 sample | 合理 | 在 response source 标 `"sample (no token)"` |
| Local parquet 不存在 | 走 sample | 合理 | OK |
| Backend 不可达（前端） | [api.ts](../src/frontend/lib/api.ts) `apiGet` 捕获后吐 `apiError`；但**前端页面没有任何位置展示 `apiError`** | 不合理：silent failure | 在每页顶部加 `<ErrorBanner>` 显示 |

## 8. 安全/隔离 invariant 仍然守得住

- `safety` footer 中间件挂载正常（每个响应带 `kill_switch=true, live_trading_enabled=false`）。
- `/api/orders/*` / `/api/broker/*` 不存在（手测 `/api/orders/submit` 返回 404）。
- `/api/agent/candidates/{id}` 返回的 `source_preview` 是字符串读盘，没有 import / exec。
- `/api/prediction-market/scan?polymarket_api_key=xxx` 直接 400。
- 全部正确，**这些不要改**。

## 9. 总结

backend 自身**作为只读 + dry-run 的 Phase 9 收尾**是健康的。问题集中在：

1. **数据源没接真**——`/api/symbols` 和 `/api/ohlcv` 只走 sample provider，详见 [MARKET_DATA_SOURCE_AUDIT.md](MARKET_DATA_SOURCE_AUDIT.md)。
2. **LLM 配置完全没有进 Settings 模型**，前端"Agent 已接 LLM"预期落空。
3. **前端没有调用任何 POST endpoint**（按钮全部 DEAD），见 [UI_FUNCTION_MATRIX.md](UI_FUNCTION_MATRIX.md)。
4. **CORS 默认 origin 不含 3001**，未来改 client component 会立刻撞墙。
