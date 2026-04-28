# Phase 9 API Delivery

## 交付内容

Phase 9 已交付本地 HTTP API 层，作为 Web 前端的后端入口。API 复用已有 Phase 1-8 模块，不新增真实交易能力。

## Endpoint Table

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 返回服务状态和安全快照 |
| GET | `/api/settings` | 返回脱敏后的配置 |
| GET | `/api/symbols` | 返回本地或 sample symbol |
| GET | `/api/ohlcv` | 返回 OHLCV 时间序列 |
| GET | `/api/factors` | 返回默认因子注册表 |
| POST | `/api/factors/run` | 跑 sample 因子研究 |
| GET | `/api/factors/{run_id}` | 读取因子结果 |
| POST | `/api/backtests/run` | 跑 sample 回测 |
| GET | `/api/backtests` | 列出 API 回测 |
| GET | `/api/backtests/{id}` | 读取回测详情 |
| GET | `/api/benchmark` | 计算买入持有基准曲线 |
| GET | `/api/experiments` | 列出本地实验 |
| GET | `/api/experiments/{id}` | 读取实验详情 |
| POST | `/api/paper/run` | 跑本地 paper trading |
| GET | `/api/paper` | 列出 paper runs |
| GET | `/api/paper/{id}` | 读取 paper run 详情 |
| GET | `/api/agent/candidates` | 列出 Agent 候选 |
| GET | `/api/agent/candidates/{id}` | 读取候选详情，源码只作文本预览 |
| POST | `/api/agent/tasks` | 触发候选生成或审计任务 |
| POST | `/api/agent/candidates/{id}/review` | 只写 approved/rejected lock |
| GET | `/api/prediction-market/markets` | 返回 sample prediction market 数据 |
| POST | `/api/prediction-market/scan` | 跑 sample scanner |
| POST | `/api/prediction-market/dry-arbitrage` | 写 dry proposal，不下单 |

## 验收标准

- 所有 JSON 响应都有 `safety` 字段。
- `/api/settings` 不泄露 API key、token、secret。
- `/api/orders/submit` 不存在。
- `kill_switch=true` 时，paper API 不允许请求关闭 kill switch。
- Agent review 只写 lock 文件，不注册因子。
- Prediction market API 拒绝任何 Polymarket API key。
- 默认只能绑定 `127.0.0.1`。

## Smoke Run

启动命令：

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -Method Get | ConvertTo-Json -Depth 10
```

实际输出：

```json
{
    "status":  "ok",
    "app_name":  "AI Quant Research Platform",
    "environment":  "local",
    "safety":  {
                   "dry_run":  true,
                   "paper_trading":  true,
                   "live_trading_enabled":  false,
                   "kill_switch":  true,
                   "bind_address":  "127.0.0.1"
               }
}
```

## 与原 prompt 的差异说明

- 现有项目没有 `src/quant_system/config.py`，实际配置在 `src/quant_system/config/settings.py`。
- 现有 Phase 8 没有 `PredictionMarketPipeline` 类，API 复用 `scan_market`、`run_dry_arbitrage` 和报告函数。
- `bootstrap.py` 按用户补充要求保持很薄，只写 settings 和路径到 `app.state`，不构造不存在的服务类。
