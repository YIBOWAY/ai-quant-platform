# Phase 11 交付 - Polymarket 只读研究

## 概述

Phase 11 增加了对 Polymarket 只读研究的支持：

- 公开只读数据源 (provider)
- 数据源工厂 (provider factory)
- JSONL 快照持久化与回放
- 简易扫描器/准回测
- SVG 图表
- markdown 与 JSON 报告
- 后端 API 集成
- 前端数据源选择与结果展示

它不包含实盘交易、钱包签名、私钥处理、代币转账、赎回或真实下单。

## 风险提示 (Red Flags)

- `src/quantum-core-algorithmic-trading-platform.zip` 仍未纳入版本控制。未经
  人工检查，请勿提交该文件。
- `.env` 包含本地密钥且仍被忽略。请勿将其中的值复制到文档、测试或日志中。

## API 示例

```powershell
curl "http://127.0.0.1:8765/api/prediction-market/markets?provider=sample"
curl -X POST "http://127.0.0.1:8765/api/prediction-market/backtest" ^
  -H "Content-Type: application/json" ^
  -d "{\"provider\":\"sample\",\"min_edge_bps\":200}"
```

## 输出目录

回测产物写入以下目录：

```text
data/api_runs/prediction_market/backtests/<run_id>/
```

每次运行包含：

- `result.json`
- `chart_index.json`
- `report.md`
- SVG 图表文件

## 验证日志

最终验证应包含：

```text
python -m pytest -q
ruff check .
cd src/frontend && npm run lint
cd src/frontend && npm run build
PW_E2E=1 npx playwright test
```

2026-05-01 最近一次本地验证：

```text
python -m pytest -q                      exit 0
ruff check .                             All checks passed!
cd src/frontend && npm run lint          exit 0
cd src/frontend && npm run build         exit 0, 13 Next.js routes generated
PW_E2E=1 npx playwright test             11 passed, production-style Next server
real Polymarket read-only smoke          success, live market list + order book + price history + trades
live/cache smoke                         refresh -> live, prefer_cache -> cache
```

API 冒烟测试输出：

```text
GET /api/health                          200, dry_run=true, paper_trading=true, live_trading_enabled=false, kill_switch=true
GET /api/prediction-market/markets       200, provider=polymarket, cache_status=live, question="Russia-Ukraine Ceasefire before GTA VI?"
GET /api/prediction-market/markets       200, provider=polymarket, cache_status=cache, same market replayed from local cache
POST /api/prediction-market/scan         200, provider=polymarket, cache_status=cache, candidate_count=1
POST /api/prediction-market/backtest     200, provider=polymarket, cache_status=live, opportunity_count=2, chart_count=4
POST /api/prediction-market/scan
  with extra.api_key                     400, credential-like fields rejected
GET /api/orders/submit                   404, no order route exists
```

最近生成的真实数据产物：

```text
data/api_runs/prediction_market/backtests/pm-backtest-20260501T145426Z-9943f775/
  chart_index.json
  cumulative_estimated_edge.svg
  edge_histogram.svg
  opportunity_count.svg
  parameter_sensitivity.svg
  report.md
  result.json
```

最近生成的缓存目录：

```text
data/prediction_market/http_cache/markets/
data/prediction_market/http_cache/order_book/
data/prediction_market/http_cache/prices_history/
data/prediction_market/snapshots/2026-05-01/polymarket/
```

早前出现 HTTP 403 的根本原因：

- Gamma 与 CLOB 公开端点拒绝了原始的请求方式。
- 在本环境中，添加一个普通的只读 `User-Agent` 请求头即可解除该拦截。
- 该数据源现已改用 `/markets/keyset`（取代已弃用的 `/markets` 端点），并将成功
  的响应写入本地 HTTP 缓存。

实盘修复后观察到的后续行为：

- 之后仅走网络的检查变得时好时坏，从 Polymarket 公开主机返回了超时 / 连接
  失败。
- 由于此前的实盘抓取已经填充了 HTTP 缓存，API 仍通过 `cache_status=stale_cache`
  或 `cache_status=cache` 返回最后一次真实的市场数据。
- 这正是 Phase 11 现在同时具备实盘读取逻辑与缓存回退的原因，而不是假设上游
  端点会全天保持可达。

## 安全声明

Phase 11 严格限定为只读的研究/回测功能，不包含实盘交易、钱包签名或真实下单。
