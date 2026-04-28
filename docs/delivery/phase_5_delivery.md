# Phase 5 交付清单

## 阶段目标说明

本阶段实现风控与 Paper Trading MVP：

- risk engine
- risk rules
- max position size
- max order value
- max daily loss
- max drawdown
- allowed symbols / blocked symbols
- kill switch
- order manager
- order lifecycle
- paper broker
- simulated execution loop
- trade logs
- risk breach logs
- paper trading report

为什么重要：

从 Phase 5 开始，系统不再只是研究和回测。它开始具备交易系统的基本安全边界：订单必须过风控，状态必须可审计，broker 必须可替换。

本阶段不做：

- 不做真实 broker API
- 不做真实资金交易
- 不做自动 live trading
- 不做高频低延迟执行

如何衔接下一阶段：

Phase 6 会基于 `BrokerAdapter` 接口增加实盘适配层 stub，但默认仍然 dry-run / sandbox / paper，不允许直接真实交易。

## 当前目录树

```text
.
|-- README.md
|-- docs/
|   |-- architecture/
|   |   `-- phase_5_architecture.md
|   |-- delivery/
|   |   `-- phase_5_delivery.md
|   |-- execution/
|   |   `-- phase_5_execution.md
|   `-- learning/
|       `-- phase_5_learning.md
|-- src/
|   `-- quant_system/
|       |-- execution/
|       |   |-- __init__.py
|       |   |-- models.py
|       |   |-- broker.py
|       |   |-- paper_broker.py
|       |   |-- portfolio.py
|       |   |-- order_manager.py
|       |   |-- pipeline.py
|       |   |-- storage.py
|       |   `-- reporting.py
|       |-- risk/
|       |   |-- __init__.py
|       |   |-- defaults.py
|       |   |-- models.py
|       |   `-- engine.py
|       `-- cli.py
`-- tests/
    |-- test_risk_engine_phase5.py
    |-- test_order_manager_paper_broker.py
    `-- test_paper_trading_pipeline_cli.py
```

## 完整代码文件

完整代码已经落盘到以下文件：

- `src/quant_system/risk/models.py`
- `src/quant_system/risk/engine.py`
- `src/quant_system/risk/__init__.py`
- `src/quant_system/execution/__init__.py`
- `src/quant_system/execution/models.py`
- `src/quant_system/execution/broker.py`
- `src/quant_system/execution/paper_broker.py`
- `src/quant_system/execution/portfolio.py`
- `src/quant_system/execution/order_manager.py`
- `src/quant_system/execution/pipeline.py`
- `src/quant_system/execution/storage.py`
- `src/quant_system/execution/reporting.py`
- `src/quant_system/cli.py`
- `README.md`

测试文件：

- `tests/test_risk_engine_phase5.py`
- `tests/test_order_manager_paper_broker.py`
- `tests/test_paper_trading_pipeline_cli.py`

## 学习文档

见：

- `docs/learning/phase_5_learning.md`

## 执行文档

见：

- `docs/execution/phase_5_execution.md`

## 架构文档

见：

- `docs/architecture/phase_5_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
python -m quant_system.cli paper run-sample --symbol SPY --symbol AAPL --start 2024-01-02 --end 2024-01-12 --initial-cash 100000 --max-order-value 20000 --max-position-size 0.60 --no-kill-switch --output-dir data/phase5_sample
python -m quant_system.cli paper run-sample --symbol SPY --start 2024-01-02 --end 2024-01-08 --kill-switch --output-dir data/phase5_kill_switch
```

通过标准：

- 测试全部通过
- 代码检查通过
- 正常模式生成成交记录
- kill switch 模式拒绝订单且没有成交
- 所有订单状态变化可查
- 风控违规日志可查
- paper trading report 可打开
- 当前阶段没有真实 broker API、真实资金交易或自动 live trading

## 暂停点

Phase 5 完成后暂停，等待确认后再进入 Phase 6：实盘接口适配层。
