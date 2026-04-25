# AI-Assisted Quant Research and Paper-Trading Platform

这是一个从研究开始、逐步走向回测和模拟交易的量化交易工程项目。当前系统仍然只做研究和本地验证，不会真实下单。

> 📘 **第一次接触本项目？** 先读 [docs/OVERVIEW.md](docs/OVERVIEW.md)：零基础导读 + 5 分钟跑通教程 + 术语表 + 安全边界，看完就能上手。

## 当前状态

已完成：

- Phase 0：项目骨架、配置、日志、CLI、安全默认值、最小测试
- Phase 1：数据层 MVP，支持样例数据、本地 CSV、Tiingo 日线数据、本地 Parquet / DuckDB 保存、数据质量报告
- Phase 2：因子研究层 MVP，支持基础因子、因子注册、因子计算、IC / Rank IC、分组收益、因子报告和命令行生成
- Phase 3：回测引擎 MVP，支持信号输入、订单生成、模拟成交、交易成本、滑点、资金持仓跟踪、交易记录、资金曲线和基础绩效报告
- Phase 4：实验管理 MVP，支持多因子标准化、方向配置、加权合成、参数 sweep、walk-forward、实验对比报告和 AI 可读摘要

当前没有实现：

- 生产级完整回测引擎
- 实盘交易
- 券商接口
- AI 自动上线策略
- 复杂机器学习模型
- Polymarket 套利执行

## 安全边界

默认配置保持保守：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `no_live_trade_without_manual_approval = true`
- `kill_switch = true`

当前系统不会真实下单，也不会绕过风控层。

## 安装

推荐使用已经创建的独立环境 `ai-quant`。

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

如果需要从头创建环境：

```powershell
conda env create -f environment.yml
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 常用命令

基础检查：

```powershell
python -m quant_system.cli --help
python -m quant_system.cli config show
python -m quant_system.cli doctor
```

生成样例数据：

```powershell
python -m quant_system.cli data ingest-sample --symbol SPY --symbol AAPL --start 2024-01-02 --end 2024-01-31 --output-dir data/phase1_sample
```

查看因子：

```powershell
python -m quant_system.cli factor list
```

生成 Phase 2 因子报告：

```powershell
python -m quant_system.cli factor run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --output-dir data/phase2_sample
```

运行 Phase 3 样例回测：

```powershell
python -m quant_system.cli backtest run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --top-n 2 --initial-cash 100000 --commission-bps 1 --slippage-bps 5 --output-dir data/phase3_sample
```

运行 Phase 4 样例实验：

```powershell
python -m quant_system.cli experiment run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-03-15 --lookback 3 --lookback 5 --top-n 1 --top-n 2 --output-dir data/phase4_sample
```

运行测试：

```powershell
python -m pytest
ruff check .
```

## 文档

- `docs/SYSTEM_DESIGN_RESEARCH.md`：系统设计调研
- `docs/learning/phase_0_learning.md`：Phase 0 学习文档
- `docs/execution/phase_0_execution.md`：Phase 0 执行文档
- `docs/architecture/phase_0_architecture.md`：Phase 0 架构文档
- `docs/delivery/phase_0_delivery.md`：Phase 0 交付清单
- `docs/learning/phase_1_learning.md`：Phase 1 学习文档
- `docs/execution/phase_1_execution.md`：Phase 1 执行文档
- `docs/architecture/phase_1_architecture.md`：Phase 1 架构文档
- `docs/delivery/phase_1_delivery.md`：Phase 1 交付清单
- `docs/learning/phase_2_learning.md`：Phase 2 学习文档
- `docs/execution/phase_2_execution.md`：Phase 2 执行文档
- `docs/architecture/phase_2_architecture.md`：Phase 2 架构文档
- `docs/delivery/phase_2_delivery.md`：Phase 2 交付清单
- `docs/learning/phase_3_learning.md`：Phase 3 学习文档
- `docs/execution/phase_3_execution.md`：Phase 3 执行文档
- `docs/architecture/phase_3_architecture.md`：Phase 3 架构文档
- `docs/delivery/phase_3_delivery.md`：Phase 3 交付清单
- `docs/learning/phase_4_learning.md`：Phase 4 学习文档
- `docs/execution/phase_4_execution.md`：Phase 4 执行文档
- `docs/architecture/phase_4_architecture.md`：Phase 4 架构文档
- `docs/delivery/phase_4_delivery.md`：Phase 4 交付清单

## 下一步

Phase 4 完成后暂停。确认后进入 Phase 5：风控与 Paper Trading。
