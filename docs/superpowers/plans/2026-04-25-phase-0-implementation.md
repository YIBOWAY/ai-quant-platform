# Phase 0 实施计划

> **致自动化执行的智能体：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实施本计划。各步骤使用复选框（`- [ ]`）语法进行追踪。

**目标：** 为 AI 量化研究与模拟交易平台搭建可运行的 Phase 0 项目基础。

**架构：** 保持 Phase 0 小巧而明确：settings、logging、风控默认值、CLI、跨层插件接口、测试与文档。不包含数据下载、不连接券商、不涉及交易策略、不集成 Polymarket。

**技术栈：** Python 3.11+、conda + pip 可编辑安装（editable install）、pandas、numpy、pydantic、pydantic-settings、typer、duckdb、pyarrow、pytest、ruff。

---

## 文件结构

- 创建 `pyproject.toml`：包元数据、依赖项、CLI 入口、pytest 与 ruff 配置。
- 创建 `environment.yml`：conda 环境封装，用于安装 `.[dev]`。
- 创建 `.env.example`：安全的默认值与注释。
- 创建 `README.md`：Phase 0 概览、安装、运行、验证、安全边界。
- 创建 `src/quant_system/__init__.py`：包元数据。
- 创建 `src/quant_system/cli.py`：Typer CLI，包含 `config show`、`doctor` 以及版本行为。
- 创建 `src/quant_system/config/settings.py`：基于 pydantic 的 settings，含默认安全控制与实盘交易防护。
- 创建 `src/quant_system/logging/setup.py`：结构化 JSON 日志配置。
- 创建 `src/quant_system/risk/defaults.py`：可复用的风险限额默认值。
- 创建 `src/quant_system/core/interfaces.py`：Phase 0 的插件契约，涵盖 Factor、Strategy 与 PortfolioOptimizer。
- 创建各个包的 `__init__.py` 文件。
- 在 `tests/` 下创建测试：CLI、settings、logging、风控默认值以及接口契约测试。
- 创建文档：`docs/learning/phase_0_learning.md`、`docs/execution/phase_0_execution.md`、`docs/architecture/phase_0_architecture.md`。
- 初始化 git 仓库，因为 Phase 0 包含建立该仓库这一步。

## 任务

### 任务 1：测试与配置

- [ ] 先编写测试：覆盖 settings 默认值、实盘防护、风控默认值、日志输出、CLI 输出以及接口定义。
- [ ] 创建 `pyproject.toml` 与 `environment.yml`，以便测试能在可编辑安装模式下运行。
- [ ] 运行 pytest 并确认测试失败，因为生产模块尚不存在。

### 任务 2：最小化实现

- [ ] 实现 settings、风控默认值、日志配置、CLI 与核心接口。
- [ ] 运行针对性测试直至通过。
- [ ] 默认禁用实盘交易，若启用则要求显式的确认短语。

### 任务 3：文档

- [ ] 编写 README。
- [ ] 编写 Phase 0 的 learning、execution 与 architecture 文档。
- [ ] 包含目录树、命令、成功标志、常见错误、Mermaid 图以及向 Phase 1 的交接说明。

### 任务 4：验证

- [ ] 运行 `python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"`。
- [ ] 运行 `python -m pytest`。
- [ ] 运行 `ruff check .`。
- [ ] 运行 `python -m quant_system.cli --help`。
- [ ] 运行 `quant-system config show`。
- [ ] 确认 git 仓库存在，并在不还原用户文件的前提下检查其状态。
