# Phase 3 执行文档

## 环境要求

- Python 3.11+
- 推荐使用 `ai-quant` 独立环境
- 本阶段不需要真实 API key
- 本阶段不会真实下单

## 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

本阶段可以不修改 `.env`。

默认安全配置仍然是：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_KILL_SWITCH=true`

## 启动步骤

运行样例回测：

```powershell
python -m quant_system.cli backtest run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --top-n 2 --initial-cash 100000 --commission-bps 1 --slippage-bps 5 --output-dir data/phase3_sample
```

成功后会生成：

- `data/phase3_sample/backtests/equity_curve.parquet`
- `data/phase3_sample/backtests/trade_blotter.parquet`
- `data/phase3_sample/backtests/orders.parquet`
- `data/phase3_sample/backtests/positions.parquet`
- `data/phase3_sample/backtests/metrics.json`
- `data/phase3_sample/reports/backtest_report.md`
- `data/phase3_sample/quant_system.duckdb`

## 测试步骤

运行全部测试：

```powershell
python -m pytest
```

运行代码检查：

```powershell
ruff check .
```

只运行 Phase 3 测试：

```powershell
python -m pytest tests/test_backtest_broker_portfolio.py tests/test_backtest_strategy_orders.py tests/test_backtest_engine_metrics.py tests/test_backtest_storage_reporting_cli.py
```

## 成功运行标志

- 命令行输出包含 `total_return`、`sharpe`、`max_drawdown`
- 输出目录里有资金曲线、订单、成交、持仓、指标和报告
- 报告里写明 next bar open 成交假设
- `python -m pytest` 全部通过
- `ruff check .` 无报错

## 常见报错排查

### 没有交易

常见原因：

- 日期范围太短
- `lookback` 太大
- 信号表里没有正 score

可以先用：

```powershell
--lookback 3
```

并确保至少有 3 个 symbol。

### 回测收益很奇怪

先检查：

- 手续费是否设置过高
- 滑点是否设置过高
- 日期范围是否太短
- 样例数据是否过于简单

本阶段使用的是确定性样例数据，只用于验证流程。

### 找不到 quant_system

说明当前环境没有安装本项目：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 验收标准

- 订单、成交、现金、持仓和绩效指标都有测试覆盖
- 回测报告可通过 CLI 生成
- 手续费和滑点可配置
- 成交假设明确为 next bar open
- 策略逻辑不直接下单
- 当前阶段没有实盘和 paper trading 功能
