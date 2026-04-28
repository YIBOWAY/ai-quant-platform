# Phase 5 执行文档

## 环境要求

- Python 3.11+
- 推荐使用 `ai-quant` 独立环境
- 本阶段不需要真实 API key
- 本阶段不会连接真实券商

## 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

默认安全配置保持：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_KILL_SWITCH=true`

Phase 5 的样例 CLI 会显式传入 paper trading 风控参数，不需要修改 `.env`。

## 启动步骤

运行样例模拟交易：

```powershell
python -m quant_system.cli paper run-sample --symbol SPY --symbol AAPL --start 2024-01-02 --end 2024-01-12 --initial-cash 100000 --max-order-value 20000 --max-position-size 0.60 --no-kill-switch --output-dir data/phase5_sample
```

测试 kill switch：

```powershell
python -m quant_system.cli paper run-sample --symbol SPY --start 2024-01-02 --end 2024-01-08 --kill-switch --output-dir data/phase5_kill_switch
```

成功后会生成：

- `data/phase5_sample/paper/orders.parquet`
- `data/phase5_sample/paper/order_events.parquet`
- `data/phase5_sample/paper/trades.parquet`
- `data/phase5_sample/paper/risk_breaches.parquet`
- `data/phase5_sample/reports/paper_trading_report.md`
- `data/phase5_sample/quant_system.duckdb`

## 测试步骤

运行全部测试：

```powershell
python -m pytest
```

运行代码检查：

```powershell
ruff check .
```

只运行 Phase 5 测试：

```powershell
python -m pytest tests/test_risk_engine_phase5.py tests/test_order_manager_paper_broker.py tests/test_paper_trading_pipeline_cli.py
```

## 成功运行标志

- CLI 输出包含 `paper_report`
- 输出目录里有 orders、order_events、trades、risk_breaches 和 report
- kill switch 模式下 trades 为空，risk_breaches 非空
- 正常模式下 trades 非空
- 测试和代码检查通过

## 常见报错排查

### 所有订单都被拒绝

检查：

- 是否开启了 `--kill-switch`
- `--max-order-value` 是否太小
- `--max-position-size` 是否太小
- symbol 是否在 blocked list 中

### 没有部分成交

默认会一次成交。可以设置：

```powershell
--max-fill-ratio-per-tick 0.5
```

### risk_breaches 为空

正常成交时可以为空。要验证风控日志，可以用 kill switch 或故意设置很小的 `max-order-value`。

## 验收标准

- 所有订单必须经过风控
- risk engine 独立于 strategy
- kill switch 可以阻止所有新订单
- paper broker 和未来 live broker 共用接口
- 所有订单状态变化有日志
- partial fill 有最小模拟
- 测试覆盖风控拒单、正常成交、kill switch、partial fill
- 不包含真实 broker API 或真实资金交易
