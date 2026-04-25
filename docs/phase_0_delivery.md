# Phase 0 交付清单

## 阶段目标说明

本阶段解决“系统从哪里开始”的问题：项目结构、依赖、配置、日志、测试、文档和基础命令都已经落地。

它在完整量化系统中重要，是因为后续数据、因子、回测、风控、执行和 AI Agent 都要复用这些基础设施。

本阶段不做：

- 不下载真实行情
- 不计算因子
- 不写策略
- 不做回测
- 不接券商
- 不接 Polymarket
- 不允许真实下单

本阶段完成后，下一阶段可以在同一项目结构下开始建设数据层。

## 当前目录树

```text
.
├── .env.example
├── .gitignore
├── AI-assisted_quant_research_and_paper-trading_platform.code-workspace
├── environment.yml
├── pyproject.toml
├── README.md
├── Roan-on-X-the-Math-Needed-for-Trading-on-Polymarket-Complete-Roadmap(1).pdf
├── docs/
│   ├── SYSTEM_DESIGN_RESEARCH.md
│   ├── phase_0_architecture.md
│   ├── phase_0_delivery.md
│   ├── phase_0_execution.md
│   ├── phase_0_learning.md
│   └── superpowers/
│       └── plans/
│           └── 2026-04-25-phase-0-implementation.md
├── src/
│   └── quant_system/
│       ├── __init__.py
│       ├── cli.py
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── interfaces.py
│       ├── logging/
│       │   ├── __init__.py
│       │   └── setup.py
│       └── risk/
│           ├── __init__.py
│           └── defaults.py
└── tests/
    ├── test_cli.py
    ├── test_interfaces.py
    ├── test_logging_setup.py
    ├── test_risk_defaults.py
    └── test_settings.py
```

## 完整代码文件

完整代码已经按文件落盘在项目目录中，不是片段。

主要代码文件：

- `src/quant_system/__init__.py`
- `src/quant_system/cli.py`
- `src/quant_system/config/__init__.py`
- `src/quant_system/config/settings.py`
- `src/quant_system/core/__init__.py`
- `src/quant_system/core/interfaces.py`
- `src/quant_system/logging/__init__.py`
- `src/quant_system/logging/setup.py`
- `src/quant_system/risk/__init__.py`
- `src/quant_system/risk/defaults.py`

主要测试文件：

- `tests/test_cli.py`
- `tests/test_interfaces.py`
- `tests/test_logging_setup.py`
- `tests/test_risk_defaults.py`
- `tests/test_settings.py`

## 学习文档

见：

- `docs/phase_0_learning.md`

## 执行文档

见：

- `docs/phase_0_execution.md`

## 架构文档

见：

- `docs/phase_0_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
quant-system --help
quant-system config show
quant-system doctor
```

通过标准：

- 所有测试通过
- 代码检查无错误
- CLI 可运行
- 配置显示真实交易默认关闭
- 健康检查显示 Phase 0 基础可用

## 暂停点

Phase 0 完成后暂停，等待用户确认后再进入 Phase 1。
