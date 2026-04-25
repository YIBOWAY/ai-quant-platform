# Phase 4 交付清单

## 阶段目标说明

本阶段实现多因子组合与实验管理 MVP：

- 多因子标准化
- 因子方向配置
- 因子加权合成
- 多因子 score 生成
- rebalancing
- 参数配置文件
- grid search / simple parameter sweep
- walk-forward validation
- 实验结果保存
- 实验对比报告
- AI Agent-readable experiment summary

为什么重要：

单次回测不能支撑持续研究。Phase 4 让每次实验都有配置、参数、结果、指标和时间戳，后续才能比较、复现和总结。

本阶段不做：

- 不做真实交易
- 不做自动选择策略上线
- 不做复杂机器学习模型
- 不做 Polymarket solver

如何衔接下一阶段：

Phase 5 会在当前研究和回测基础上加入风控、订单生命周期和 paper trading loop。

## 当前目录树

```text
.
|-- README.md
|-- docs/
|   |-- architecture/
|   |   |-- phase_0_architecture.md
|   |   |-- phase_1_architecture.md
|   |   |-- phase_2_architecture.md
|   |   |-- phase_3_architecture.md
|   |   `-- phase_4_architecture.md
|   |-- delivery/
|   |   |-- phase_0_delivery.md
|   |   |-- phase_1_delivery.md
|   |   |-- phase_2_delivery.md
|   |   |-- phase_3_delivery.md
|   |   `-- phase_4_delivery.md
|   |-- execution/
|   |   |-- phase_0_execution.md
|   |   |-- phase_1_execution.md
|   |   |-- phase_2_execution.md
|   |   |-- phase_3_execution.md
|   |   `-- phase_4_execution.md
|   `-- learning/
|       |-- phase_0_learning.md
|       |-- phase_1_learning.md
|       |-- phase_2_learning.md
|       |-- phase_3_learning.md
|       `-- phase_4_learning.md
|-- src/
|   `-- quant_system/
|       |-- experiments/
|       |   |-- __init__.py
|       |   |-- models.py
|       |   |-- config.py
|       |   |-- scoring.py
|       |   |-- sweep.py
|       |   |-- walk_forward.py
|       |   |-- runner.py
|       |   |-- storage.py
|       |   `-- reporting.py
|       |-- backtest/
|       |-- factors/
|       `-- cli.py
`-- tests/
    |-- test_experiment_scoring.py
    |-- test_experiment_config_sweep.py
    |-- test_experiment_walk_forward.py
    `-- test_experiment_runner_cli.py
```

## 完整代码文件

完整代码已经落盘到以下文件：

- `src/quant_system/experiments/__init__.py`
- `src/quant_system/experiments/models.py`
- `src/quant_system/experiments/config.py`
- `src/quant_system/experiments/scoring.py`
- `src/quant_system/experiments/sweep.py`
- `src/quant_system/experiments/walk_forward.py`
- `src/quant_system/experiments/runner.py`
- `src/quant_system/experiments/storage.py`
- `src/quant_system/experiments/reporting.py`
- `src/quant_system/cli.py`
- `README.md`

测试文件：

- `tests/test_experiment_scoring.py`
- `tests/test_experiment_config_sweep.py`
- `tests/test_experiment_walk_forward.py`
- `tests/test_experiment_runner_cli.py`

## 学习文档

见：

- `docs/learning/phase_4_learning.md`

## 执行文档

见：

- `docs/execution/phase_4_execution.md`

## 架构文档

见：

- `docs/architecture/phase_4_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
python -m quant_system.cli experiment run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-03-15 --lookback 3 --lookback 5 --top-n 1 --top-n 2 --output-dir data/phase4_sample
```

通过标准：

- 所有测试通过
- 代码检查通过
- CLI 能生成实验对比报告
- 每个 run 有 run_id、created_at、参数和指标
- JSON 配置能运行
- walk-forward 能生成 train / validation 边界
- agent summary 已生成
- 当前阶段没有真实交易、自动上线、复杂模型或 Polymarket solver

## 暂停点

Phase 4 完成后暂停，等待确认后再进入 Phase 5：风控与 Paper Trading。
