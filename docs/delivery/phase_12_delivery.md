# Phase 12 交付文档

## 1. 阶段目标

Phase 12 的目标有两部分：

1. 把股票的 Factor Lab、Backtester、Paper Trading 三条运行链路统一到真实历史数据源。
2. 把预测市场模块从“当前快照研究”升级到“历史快照采集 + 时间序列回放”。

---

## 2. 本阶段交付内容

- 股票三条主链支持真实历史数据 provider
- 预测市场历史快照采集器
- 预测市场历史快照本地落盘
- 预测市场时间序列 simulated replay
- 图表与报告输出
- 新 API
- 前端历史采集与回放面板
- 新增测试与浏览器联调覆盖

---

## 3. 目录树

重点新增或扩展的路径：

```text
src/quant_system/
  factors/pipeline.py
  backtest/pipeline.py
  execution/pipeline.py
  prediction_market/
    collector.py
    storage.py
    timeseries_backtest.py
    charts.py
    reporting.py
  api/routes/prediction_market.py

src/frontend/
  app/order-book/page.tsx
  components/forms/PMHistoryBacktestForm.tsx
  components/forms/FactorRunForm.tsx
  components/forms/BacktestForm.tsx
  components/forms/PaperRunForm.tsx
```

---

## 4. 验收清单

- [x] 股票因子运行可走真实 provider
- [x] 股票回测可走真实 provider
- [x] 股票 paper trading 可走真实 provider
- [x] 预测市场可做历史采集
- [x] 预测市场可做时间序列回放
- [x] 生成图表与报告
- [x] 前端页面可触发并展示结果
- [x] 默认安全边界保持不变

---

## 5. 测试与运行结果

### 后端

```powershell
conda activate ai-quant
python -m pytest --tb=no
ruff check .
```

实际结果：

- `202 passed in 25.85s`
- `All checks passed!`

### 前端

```powershell
cd src/frontend
npm run lint
npm run build
$env:PW_E2E = "1"
npx playwright test
```

实际结果：

- lint 通过
- build 通过
- Playwright `11 passed`

### 手工接口冒烟

#### 股票真实数据

- `GET /api/ohlcv?symbol=SPY&...&provider=tiingo` 返回 `source=tiingo`
- `POST /api/factors/run` 返回 `source=tiingo`
- `POST /api/backtests/run` 返回 `source=tiingo`
- `POST /api/paper/run` 返回 `source=tiingo`

#### 预测市场 sample 历史链

- `POST /api/prediction-market/collect` 返回：
  - `provider=sample`
  - `market_count=2`
  - `snapshot_record_count=5`
- `POST /api/prediction-market/timeseries-backtest` 返回：
  - `provider=sample`
  - `market_count=2`
  - `snapshot_count=4`
  - `opportunity_count=12`
  - `simulated_trade_count=8`
  - `cumulative_estimated_profit≈200`

#### 安全冒烟

- `POST /api/prediction-market/scan` 带 `polymarket_api_key` 返回 `400`
- `GET /api/orders/submit` 返回 `404`

#### 真实 Polymarket 只读链

- 本轮再次手工请求真实公开市场接口时，出现超时
- 结论：历史采集与时间序列回放在 sample / fixture 路径下可稳定复现；真实公开接口仍要按“可能波动”的前提使用

---

## 6. 已知限制

- 预测市场仍然是只读研究，不是交易能力
- 时间回放仍然是 simulated / quasi，不是真实成交回放
- 真实公开接口可能波动，sample 仍然是离线兜底
- 当前仓库里存在未跟踪压缩包 `src/quantum-core-algorithmic-trading-platform.zip`，建议后续人工确认是否应保留

---

## 7. 安全自检结果

已验证通过：

- `/api/health` 返回 `live_trading_enabled=false`
- `/api/orders/submit` 返回 `404`
- 带 `polymarket_api_key` 的预测市场请求返回 `400`
- 结果页和预测市场页都保留 read-only / simulated / no real fills 提示
- 默认 provider 仍是 `sample`

需要单独说明的一点：

- 关键词搜索 `private_key|wallet|sign_typed_data|eth_account|web3|submit_order|place_order`
  在当前仓库里仍然会命中一些老文件和既有命名，比如：
  - paper broker 的 `submit_order`
  - 前端已有的 `Wallet` 图标名
  - 旧阶段文档的安全说明

这不代表本阶段引入了真实交易能力。实际验证结果仍然是：

- 没有真实下单路由
- 没有钱包连接能力
- 没有签名逻辑
- 没有私钥处理

---

## 7. 暂停点

Phase 12 结束后，可以继续做：

- 更长窗口的真实历史积累
- 更多 scanner
- 更细的模拟撮合假设
