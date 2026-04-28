# Phase 2 交付清单

## 阶段目标说明

本阶段解决因子研究层 MVP：

- 定义因子基类
- 建立因子注册表
- 实现动量、波动率、流动性三个示例因子
- 实现因子计算流程
- 实现 IC / Rank IC
- 实现分组收益分析
- 保存因子结果
- 生成因子报告
- 为 Phase 3 输出统一信号表

为什么重要：

后续回测不能直接从零散研究脚本开始。因子必须有统一格式、统一时间戳和统一保存方式，否则无法稳定复现和比较实验。

本阶段不做：

- 不做完整回测
- 不做多因子组合优化
- 不做实盘交易
- 不做 AI 自动生成因子上线
- 不做 Polymarket 套利模块

如何衔接下一阶段：

Phase 3 会读取 `factor_signals.parquet` 或等价 DataFrame，把 `score` 转成目标仓位，再交给回测引擎模拟交易。

## 当前目录树

```text
.
|-- .env.example
|-- environment.yml
|-- pyproject.toml
|-- README.md
|-- docs/
|   |-- SYSTEM_DESIGN_RESEARCH.md
|   |-- architecture/
|   |   |-- phase_0_architecture.md
|   |   |-- phase_1_architecture.md
|   |   `-- phase_2_architecture.md
|   |-- delivery/
|   |   |-- phase_0_delivery.md
|   |   |-- phase_1_delivery.md
|   |   `-- phase_2_delivery.md
|   |-- execution/
|   |   |-- phase_0_execution.md
|   |   |-- phase_1_execution.md
|   |   `-- phase_2_execution.md
|   `-- learning/
|       |-- phase_0_learning.md
|       |-- phase_1_learning.md
|       `-- phase_2_learning.md
|-- src/
|   `-- quant_system/
|       |-- cli.py
|       |-- config/
|       |-- core/
|       |-- data/
|       |-- factors/
|       |   |-- __init__.py
|       |   |-- base.py
|       |   |-- examples.py
|       |   |-- registry.py
|       |   |-- pipeline.py
|       |   |-- evaluation.py
|       |   |-- storage.py
|       |   `-- reporting.py
|       |-- logging/
|       `-- risk/
`-- tests/
    |-- test_factor_evaluation.py
    |-- test_factor_storage_reporting_cli.py
    |-- test_factors_examples.py
    |-- test_factors_pipeline.py
    `-- test_factors_registry.py
```

## 完整代码文件

完整代码已经落盘到以下文件：

- `src/quant_system/factors/__init__.py`
- `src/quant_system/factors/base.py`
- `src/quant_system/factors/examples.py`
- `src/quant_system/factors/registry.py`
- `src/quant_system/factors/pipeline.py`
- `src/quant_system/factors/evaluation.py`
- `src/quant_system/factors/storage.py`
- `src/quant_system/factors/reporting.py`
- `src/quant_system/cli.py`
- `README.md`

测试文件：

- `tests/test_factors_examples.py`
- `tests/test_factors_registry.py`
- `tests/test_factors_pipeline.py`
- `tests/test_factor_evaluation.py`
- `tests/test_factor_storage_reporting_cli.py`

## 学习文档

见：

- `docs/learning/phase_2_learning.md`

## 执行文档

见：

- `docs/execution/phase_2_execution.md`

## 架构文档

见：

- `docs/architecture/phase_2_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
python -m quant_system.cli factor list
python -m quant_system.cli factor run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --output-dir data/phase2_sample
```

通过标准：

- 测试全部通过
- 代码检查通过
- `factor list` 显示三个示例因子
- `factor run-sample` 生成完整结果文件
- 报告文件能打开并包含 IC、Rank IC、分组收益说明
- 因子结果里有 `signal_ts` 和 `tradeable_ts`
- 最后一根 K 线不会被当成可交易信号

## yfinance 判断

已在当前环境临时测试 yfinance，能成功获取 `SPY` 的小段历史数据。

本阶段不把 yfinance 加入正式依赖，原因：

- Phase 1 主线 Tiingo 已经跑通，字段更适合当前项目。
- yfinance 适合作零额度兜底，但稳定性和数据许可边界不适合作主源。
- 后续可以在 Phase 1.x 或 Phase 2.x 加一个可选 provider。

参考：yfinance 项目主页 https://github.com/ranaroussi/yfinance

## 暂停点

Phase 2 完成后暂停，等待确认后再进入 Phase 3：回测引擎 MVP。

## 扩展因子库交付补充

本阶段后续补充了可选 Alpha101 因子库，用于验证“读论文 -> 实现因子 -> 注册 -> 测试 -> 文档”的可复制流程。

新增文件：

- `src/quant_system/factors/library/__init__.py`
- `src/quant_system/factors/library/alpha101.py`
- `tests/test_factors_alpha101.py`

新增命令：

```powershell
python -m quant_system.cli factor register-library --name alpha101
```

验收标准：

- 默认 `factor list` 仍只显示核心示例因子，不自动混入 Alpha101。
- `factor register-library --name alpha101` 输出 `alpha101_001` 到 `alpha101_010`。
- Alpha101 的 `rank()` 按同一 `signal_ts` 横截面计算。
- Alpha101 的时间序列算子按同一 `symbol` 滚动计算。
- 每条 Alpha101 因子都有确定性输入的测试。
