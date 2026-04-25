# Phase 0 学习文档

## 当前阶段核心概念

Phase 0 解决的是“项目能不能稳定开始”的问题。它不研究策略，也不下载数据，而是先把项目骨架、环境、配置、日志、命令行入口、测试和安全默认值建起来。

完整量化系统后面会越来越复杂：数据、因子、回测、风控、执行、模拟交易、AI Agent、Polymarket 扩展都会加入。如果一开始没有清楚的项目边界，后面很容易变成一堆脚本。

Phase 0 的核心目标是让后续每个阶段都有固定落点：

- 配置从 `settings` 读取
- 日志从统一入口输出
- 命令从 CLI 进入
- 默认不开真实交易
- 风控默认值可被复用
- 因子、策略、组合优化器通过接口扩展
- 每次改动都有测试验证

## 从零解释知识点

### 1. 项目骨架

项目骨架就是代码、测试、文档和配置文件的摆放规则。它让人一眼知道：

- 代码放在哪里
- 测试放在哪里
- 文档放在哪里
- 怎么安装
- 怎么启动
- 怎么检查是否正常

本阶段使用 `src/quant_system/` 作为主代码目录，`tests/` 作为测试目录，`docs/` 作为文档目录。

### 2. 配置

配置就是系统运行时会变化的参数，例如：

- 是否 dry-run
- 是否 paper trading
- 是否允许 live trading
- 最大单票仓位
- 最大单日亏损
- 最大订单金额

这些值不能散落在代码里，否则后续很难审计。本阶段用 `pydantic-settings` 管理配置，并从 `.env` 或环境变量读取。

### 3. 安全默认值

交易系统必须默认安全。Phase 0 的默认状态是：

- 只允许研究和模拟
- 不允许真实交易
- kill switch 默认开启
- live trading 即使被打开，也必须输入固定确认短语

这不是为了麻烦，而是为了避免后续任何模块绕过安全边界。

### 4. 结构化日志

普通日志只是一段文字。结构化日志是 JSON 格式，后续可以被程序读取、过滤、统计和审计。

Phase 0 先用本地标准输出，不引入复杂日志平台。以后可以扩展到文件、数据库、Prometheus、Grafana 或 OpenTelemetry。

### 5. CLI

CLI 是命令行入口。Phase 0 提供：

- `quant-system --help`
- `quant-system config show`
- `quant-system doctor`

后续数据下载、因子计算、回测、实验运行都可以继续加到这个入口下。

### 6. 插件接口

Phase 0 预留了三类接口：

- `Factor`：因子只负责计算因子值
- `Strategy`：策略只负责输出目标仓位
- `PortfolioOptimizer`：组合优化器只负责生成目标权重

这保证后续新论文、新因子、新策略可以通过插件接入，而不是修改核心系统。

## 代码和概念如何对应

| 概念 | 文件 |
|---|---|
| 项目依赖和命令入口 | `pyproject.toml` |
| conda 环境 | `environment.yml` |
| 本地配置示例 | `.env.example` |
| CLI | `src/quant_system/cli.py` |
| 配置模型 | `src/quant_system/config/settings.py` |
| 结构化日志 | `src/quant_system/logging/setup.py` |
| 风控默认值 | `src/quant_system/risk/defaults.py` |
| 插件接口 | `src/quant_system/core/interfaces.py` |
| 测试 | `tests/` |

## 常见错误

1. **一开始就写策略**

   这会跳过数据质量、风控、回测假设和执行边界，后面很难修。

2. **把配置写死在代码里**

   后续无法复现实验，也无法审计风险参数。

3. **默认允许实盘**

   这是交易系统最危险的设计之一。真实交易必须显式开启，并通过清单验收。

4. **策略直接下单**

   策略必须只输出目标仓位。下单要经过执行层和风控层。

5. **没有测试就继续扩展**

   系统层数越多，没有测试越容易出现隐藏错误。

6. **把 AI Agent 放到风控之外**

   AI Agent 只能做研究助手，不能直接交易。

## 自检清单

- `quant-system --help` 能显示命令
- `quant-system config show` 能显示默认安全配置
- `quant-system doctor` 能说明当前处于安全状态
- `python -m pytest` 全部通过
- `ruff check .` 没有报错
- 默认不开 live trading
- 测试覆盖配置、CLI、日志、风控默认值和接口

## 下一阶段如何复用

Phase 1 会建设数据层。它会复用：

- CLI：增加数据相关命令
- settings：增加数据目录、缓存目录、数据源配置
- logging：记录数据下载和校验结果
- tests：继续用 pytest 验证数据校验
- docs：沿用阶段文档格式

