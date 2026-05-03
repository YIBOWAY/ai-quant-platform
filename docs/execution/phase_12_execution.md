# Phase 12 执行文档

## 1. 环境要求

- Windows
- conda 环境 `ai-quant`
- Python 3.11
- Node.js 18+

---

## 2. 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"

cd src/frontend
npm install
```

---

## 3. 配置步骤

预测市场历史功能默认安全配置：

```text
QS_PREDICTION_MARKET_PROVIDER=sample
QS_PREDICTION_MARKET_HISTORY_DIR=data/prediction_market/history
QS_PREDICTION_MARKET_COLLECTOR_DEFAULT_INTERVAL_SECONDS=30
QS_PREDICTION_MARKET_BACKTEST_DEFAULT_FEE_BPS=0
QS_POLYMARKET_READ_ONLY=true
```

股票真实历史数据如果要走 Tiingo，需要本地已经配置好 Tiingo token。

---

## 4. 启动步骤

### 启动后端

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

### 启动前端

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

---

## 5. 运行股票真实数据链

### 因子研究

```powershell
curl -X POST http://127.0.0.1:8765/api/factors/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\"}"
```

### 股票回测

```powershell
curl -X POST http://127.0.0.1:8765/api/backtests/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\"}"
```

### Paper Trading

```powershell
curl -X POST http://127.0.0.1:8765/api/paper/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\",\"lookback\":20,\"top_n\":2}"
```

成功标志：

- 响应里 `source` 是 `tiingo`
- 页面能看到最新 run_id 和结果表格

---

## 6. 运行预测市场历史采集

### sample 模式

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
```

### polymarket 只读模式

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider polymarket --duration 0 --limit 5
```

成功标志：

- 控制台返回 `snapshot_record_count`
- 历史目录下出现 `date=.../market_id=.../token_id=...jsonl`

---

## 7. 运行预测市场时间序列回放

```powershell
conda activate ai-quant
quant-system prediction-market timeseries-backtest --provider sample
```

成功标志：

- 输出 run_id
- 生成 `result.json`
- 生成 `report.md`
- 生成四张 PNG 图

---

## 8. 前端操作步骤

打开：

```text
http://127.0.0.1:3001/order-book
```

页面里的顺序建议：

1. 先看当前市场和盘口
2. 点 `Collect snapshots`
3. 再点 `Run historical replay`
4. 查看：
   - snapshots
   - opportunities
   - simulated trades
   - estimated profit
   - 四张图

---

## 9. 测试步骤

### 后端

```powershell
conda activate ai-quant
python -m pytest -q
ruff check .
```

### 前端

```powershell
cd src/frontend
npm run lint
npm run build
$env:PW_E2E = "1"
npx playwright test
```

---

## 10. 常见报错排查

### `no historical prediction-market snapshots matched the requested range`

先采集历史，或者把开始结束时间留空，先用现有样本跑一遍。

### `Credential-like fields are not accepted`

请求里带了不允许的凭据字段，删掉。

### `provider_timeout`

公开接口超时。先用 sample，或者稍后重试。

### 股票页面仍显示 sample

说明真实 provider 没生效。先查：

- 本地 Tiingo 配置是否存在
- 响应里的 `source` 字段是什么
- `/data-explorer` 页的 source 标签是什么
