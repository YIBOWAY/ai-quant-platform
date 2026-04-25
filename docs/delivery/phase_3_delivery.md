# Phase 3 交付清单

## 阶段目标说明

本阶段实现回测引擎 MVP：

- 支持 signal / score 输入
- 初始化组合账户
- 生成订单
- 模拟券商成交
- 模拟手续费
- 模拟滑点
- 跟踪持仓
- 跟踪现金
- 生成交易记录
- 生成资金曲线
- 计算基础绩效指标
- 生成回测报告

为什么重要：

因子研究只能说明信号是否可能有信息量。回测引擎才开始回答“扣掉成本后，按明确成交假设执行会发生什么”。

本阶段不做：

- 不做多因子权重优化
- 不做 walk-forward
- 不做 paper trading
- 不做 live trading
- 不做 Polymarket order book

如何衔接下一阶段：

Phase 4 会复用当前回测引擎，增加多因子组合、参数搜索、实验记录和结果对比。

## 当前目录树

```text
.
|-- README.md
|-- docs/
|   |-- architecture/
|   |   |-- phase_0_architecture.md
|   |   |-- phase_1_architecture.md
|   |   |-- phase_2_architecture.md
|   |   `-- phase_3_architecture.md
|   |-- delivery/
|   |   |-- phase_0_delivery.md
|   |   |-- phase_1_delivery.md
|   |   |-- phase_2_delivery.md
|   |   `-- phase_3_delivery.md
|   |-- execution/
|   |   |-- phase_0_execution.md
|   |   |-- phase_1_execution.md
|   |   |-- phase_2_execution.md
|   |   `-- phase_3_execution.md
|   `-- learning/
|       |-- phase_0_learning.md
|       |-- phase_1_learning.md
|       |-- phase_2_learning.md
|       `-- phase_3_learning.md
|-- src/
|   `-- quant_system/
|       |-- backtest/
|       |   |-- __init__.py
|       |   |-- models.py
|       |   |-- strategy.py
|       |   |-- order_generation.py
|       |   |-- broker.py
|       |   |-- portfolio.py
|       |   |-- engine.py
|       |   |-- metrics.py
|       |   |-- storage.py
|       |   |-- reporting.py
|       |   `-- pipeline.py
|       |-- cli.py
|       |-- data/
|       `-- factors/
`-- tests/
    |-- test_backtest_broker_portfolio.py
    |-- test_backtest_strategy_orders.py
    |-- test_backtest_engine_metrics.py
    `-- test_backtest_storage_reporting_cli.py
```

## 完整代码文件

完整代码已经落盘到以下文件：

- `src/quant_system/backtest/__init__.py`
- `src/quant_system/backtest/models.py`
- `src/quant_system/backtest/strategy.py`
- `src/quant_system/backtest/order_generation.py`
- `src/quant_system/backtest/broker.py`
- `src/quant_system/backtest/portfolio.py`
- `src/quant_system/backtest/engine.py`
- `src/quant_system/backtest/metrics.py`
- `src/quant_system/backtest/storage.py`
- `src/quant_system/backtest/reporting.py`
- `src/quant_system/backtest/pipeline.py`
- `src/quant_system/cli.py`
- `README.md`

测试文件：

- `tests/test_backtest_broker_portfolio.py`
- `tests/test_backtest_strategy_orders.py`
- `tests/test_backtest_engine_metrics.py`
- `tests/test_backtest_storage_reporting_cli.py`

## 学习文档

见：

- `docs/learning/phase_3_learning.md`

## 执行文档

见：

- `docs/execution/phase_3_execution.md`

## 架构文档

见：

- `docs/architecture/phase_3_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
python -m quant_system.cli backtest run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --top-n 2 --initial-cash 100000 --commission-bps 1 --slippage-bps 5 --output-dir data/phase3_sample
```

通过标准：

- 所有测试通过
- 代码检查通过
- CLI 能生成回测报告
- 输出资金曲线、订单、成交、持仓和指标文件
- 报告明确写出 next bar open 成交假设
- 手续费和滑点进入现金计算
- 策略没有直接生成订单
- 当前阶段没有实盘或 paper trading

## 暂停点

Phase 3 完成后暂停，等待确认后再进入 Phase 4：多因子组合与参数迭代。
