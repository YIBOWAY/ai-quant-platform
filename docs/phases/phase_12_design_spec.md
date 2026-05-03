# Phase 12 设计草案

日期：2026-05-02

Phase 12 的目标有两条：

1. 把股票的 Factor Lab、Backtester、Paper Trading 三条链统一到真实历史数据路径。
2. 把预测市场模块从“当前快照研究”升级到“历史采集 + 时间序列回放”。

---

## 1. 范围

### 本阶段要做

- 股票三条主链支持统一 provider 选择
- 预测市场历史快照采集器
- 预测市场历史快照落盘
- 预测市场按时间推进的 simulated replay
- 图表与报告
- API 和前端接通

### 本阶段明确不做

- 实盘交易
- 钱包连接
- 私钥处理
- 签名
- 链上调用
- 真实订单提交

---

## 2. 安全边界

下面这些边界在 Phase 12 不变：

- `dry_run=true`
- `paper_trading=true`
- `live_trading_enabled=false`
- `kill_switch=true`
- 默认 provider 仍是 `sample`
- `polymarket_api_key` 仍然拒绝
- `/api/orders/submit` 仍然是 404

---

## 3. 数据流图

```text
Sample / Polymarket GET
          |
          v
  Snapshot Collector
          |
          v
   Snapshot Store
          |
          v
 Time-Series Replay
    |          |
    v          v
 Charts      Report
    \          /
     \        /
        API
         |
         v
      Frontend
```

---

## 4. 模块边界

### 股票主链

- `src/quant_system/factors/pipeline.py`
- `src/quant_system/backtest/pipeline.py`
- `src/quant_system/execution/pipeline.py`

这三条链统一走 provider factory，不再偷偷写死 sample。

### 预测市场主链

- `src/quant_system/prediction_market/collector.py`
- `src/quant_system/prediction_market/storage.py`
- `src/quant_system/prediction_market/timeseries_backtest.py`
- `src/quant_system/prediction_market/charts.py`
- `src/quant_system/prediction_market/reporting.py`

---

## 5. 历史数据 schema

目录结构：

```text
<history_dir>/
  date=YYYY-MM-DD/
    market_id=<market_id>/
      market.json
      token_id=<token_id>.jsonl
```

每条 JSONL 记录包含：

- provider
- market_id
- condition_id
- token_id
- question
- snapshot_ts_utc
- fetched_at
- source_endpoint
- best_bid
- best_ask
- bids
- asks

---

## 6. provider 切换规则

### 股票

- 显式请求优先
- 否则用配置里的默认数据源
- 如果 `tiingo` 缺 token，则降级为 sample，并在 `source` 里写清楚

### 预测市场

- 默认 `sample`
- 只有显式写 `polymarket` 才会打真实公开接口

---

## 7. 采集失败策略

- 超时、非 200、网络错误：归一为 provider error
- 采集器遵守限速和重试
- 不做无限重试
- 如果外部接口不稳定，优先保留本地历史样本可回放能力

---

## 8. 时间序列回放假设

这不是实盘成交模拟，只是研究回放。

当前假设：

- 按快照时间顺序扫描机会
- 满足阈值就按当时盘口顶档做 simulated fill
- 每条腿 size 同时受：
  - 顶档显示量
  - `display_size_multiplier`
  - `capital_limit`
  约束

不考虑：

- 网络延迟
- 跨腿失败
- 真实结算
- 真实手续费之外的链上细节

---

## 9. API 设计

新增：

- `POST /api/prediction-market/collect`
- `POST /api/prediction-market/timeseries-backtest`
- `GET /api/prediction-market/timeseries-backtest/{run_id}`

股票三条运行接口也扩展了 provider 入参：

- `POST /api/factors/run`
- `POST /api/backtests/run`
- `POST /api/paper/run`

---

## 10. 前端设计

### 股票页面

- Factor Lab
- Backtester
- Paper Trading

都要能显示真实 `source`，并能直接触发真实数据路径。

### 预测市场页面

历史区块需要支持：

- provider 选择
- 采集
- 回放
- 错误提示
- 指标摘要
- 图表显示

而且页面上必须保留：

- read-only
- simulated
- no real fills

---

## 11. 测试策略

- 股票 provider 透传测试
- 预测市场 collector 测试
- 历史存储读写测试
- 时间序列回放稳定指标测试
- API 路由测试
- 前端浏览器联调测试

自动化测试不依赖真实外网。

---

## 12. 风险与缓解

风险 1：前端看起来像在跑真实数据，其实后端回落到了 sample。  
缓解：所有运行结果都明确写 `source`。

风险 2：真实公开接口波动。  
缓解：保留 sample、历史样本和本地回放。

风险 3：用户误把 simulated replay 当成实盘能力。  
缓解：页面、API、文档都明确写 read-only / simulated / no real fills。
