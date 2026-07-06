# Phase 15 维护与迭代路线

> ⚠️ 迭代治理已移交 Hermes-quant-agent（D-18/D-24，2026-07-03）。
> 本文不再是 `ai-quant-platform` 的独立 active roadmap，仅保留素材价值：
> P0 安全边界永久保持；P1/P2/P3/P4/P5 由
> `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md`
> 按需求拉动，其中 P4/P5 由 Hermes 工作台承接。

本文用于回答一个实际问题：当前平台已经有数据、因子、回测、实验、期权、
Polymarket、AI News、模拟账户和策略袖珍仓以后，后续到底该维护什么。

素材结论：不建议追求“接更多交易所 / 开实盘交易”。更有价值的方向是
把本地研究平台做成一个可信、可复现、可解释的研究工作台：

1. 数据可信度与缓存可观测性
2. 实验治理与策略对比
3. Paper account / Strategy Sleeves 风险运营
4. AI 研究助手从“生成候选”升级到“解释、检索、复盘”
5. 全站工作流收敛，而不是继续堆页面

## 外部项目给出的启发

这些项目不能直接照搬，但能帮助判断成熟量化平台真正重视什么：

- QuantConnect LEAN：核心不是漂亮页面，而是把 result processing、datafeed、
  transaction、realtime、setup 等引擎模块拆开，并能在 backtest / live 模式间
  切换。对本项目的启发是：继续强化模块边界和运行记录，不急着打开 live。
- Microsoft Qlib：重点是 AI-oriented quant research，从数据、特征、模型、
  workflow 到生产研究流程。对本项目的启发是：AI 方向应围绕实验、特征、
  复盘和候选审查，而不是让 agent 自动交易。
- Freqtrade：成熟之处在 dry-run、安全警告、回测、参数优化、WebUI/Telegram
  运维入口。对本项目的启发是：paper account 的可观察性、告警和 dry-run 证据
  比“更多按钮”更重要。
- OpenBB：价值在“connect once, consume everywhere”的数据层，把同一批数据
  暴露给 Python、REST、工作区和 AI agents。对本项目的启发是：数据 provider、
  缓存、API schema、前端表格和 agent 工具应该共享同一套 provenance 语义。
- Backtrader / VectorBT：一个偏事件驱动和复用策略组件，一个偏大规模参数矩阵
  和交互可视化。对本项目的启发是：既要保留事件驱动 paper/order lifecycle，
  也要把批量参数扫描和结果比较做得更快、更可解释。

## 推荐优先级

### P0：先守住安全与可验证性

已经形成的边界必须继续保持：

- 测试不打真实外网，不触发 Futu trade context。
- AI News、Polymarket、Futu 行情均保持只读。
- Paper account 和 Strategy Sleeves 仍是本地纸面执行，不等于实盘。
- Agent 候选代码默认只是纯文本；只有显式 CLI 参数才加载人工批准候选，并且
  加载前仍要经过后端安全检查。

### P1：数据可信度工作台

目标：用户一眼知道“这个数据从哪来、是否新鲜、是否缓存、是否 fallback”。

建议做：

- `/data-health` 或嵌入式 provider health 面板：Futu / Tiingo / sample / local
  parquet / DuckDB / PostgreSQL 的可用性、最新时间戳、缓存命中情况。
- 所有研究结果统一展示 `source`、`event_ts`、`knowledge_ts`、`cache_status`、
  fallback warning。
- 给 OHLCV、期权报价、AI News、Polymarket snapshot 做统一 provenance schema。
- 增加“缓存重建 / 只读诊断 / 最近失败原因”的维护入口。

不做：

- 不把 provider failure 静默吞掉。
- 不在测试里依赖真实 Futu/OpenD 或外网。

### P2：实验治理与策略对比

目标：从“能跑实验”升级到“能复盘为什么这个实验值得信”。

建议做：

- Experiment registry：按标签、数据源、时间区间、策略、参数、指标检索运行。
- Run comparison view：多个 backtest / experiment / replication run 横向比较。
- Baseline library：每个策略默认带 SPY/QQQ/现金/等权等基准。
- Model card / strategy card：固定输出假设、数据源、参数、风险、已知限制。
- 一键 clone run：从旧 run 复制配置，改一个变量后重跑。

不做：

- 不做前端自由公式因子编辑器；因子仍应后端代码化、注册化、可测。
- 不把单次最佳 Sharpe 包装成“推荐策略”。

### P3：Paper account 与 Strategy Sleeves 运维

目标：把本地模拟账户变成可信运营面板，而不是隐藏在几个按钮后面。

建议做：

- Order lifecycle 工作台：pending、filled、partial、cancelled、rejected 的时间线。
- Sleeve risk budget：每个 sleeve 的现金、持仓、已冻结额度、风险占用、最近信号。
- Paper ops status：哪些计划待执行、哪些阻塞、哪个价格源失败、是否需要人工处理。
- 本地调度只做 one-shot / LaunchAgent / CLI 显式触发，不做自动真实交易。
- 更细的风险解释：为什么某个 rebalance 被拒绝、哪条规则触发、如何恢复。

不做：

- 不接真实券商下单。
- 不做账户解锁、签名、私钥、真实撤改单。

### P4：AI 研究助手 v2

目标：让 AI 帮人理解和复盘，不让 AI 绕过研究纪律。

建议做：

- Run memory：AI 可检索历史实验、失败原因、参数变更和结果差异。
- Hypothesis assistant：基于已有结果提出“下一组要验证的问题”，生成候选配置，
  但不自动执行。
- Candidate review UX：更清楚地展示候选源码、diff、风险提示、允许导入模块、
  审批/拒绝历史。
- AI News 与实验联动只做“研究上下文”：把热点作为人工观察线索，不接策略执行。

不做：

- 不让 AI 自动批准候选。
- 不让 AI 自动触发 paper rebalance 或任何交易链路。

### P5：全站可用性收敛

目标：减少页面割裂，让普通使用路径更短。

建议做：

- 首页从“入口集合”升级为“今日研究台”：数据健康、最近运行、待处理 paper 计划、
  AI News 摘要、风险阻塞。
- 每个页面统一三段结构：当前状态、可执行动作、结果解释。
- 关键工作流加“下一步”链接：Factor Lab -> Backtest -> Experiment -> Strategy
  Catalog -> Paper sleeve，不跳到无关页面。
- 中文文案继续走“说人话”路线，解释数据源、风险和限制。

## 建议的下一步切片

如果只做一个 1-2 周切片，推荐：

1. 做 `Data Health / Provenance` 后端 schema + 前端面板。
2. 给现有 OHLCV、AI News、Polymarket、options cache 接统一状态显示。
3. 加离线测试，确保 provider 失败不会打真实外网，也不会误导 UI。

如果做一个 4-6 周切片，推荐：

1. P1 数据可信度工作台。
2. P2 Run comparison / Experiment registry。
3. P3 Paper ops status 与 order lifecycle。

这三块完成后，平台会更像“研究工作台”，而不是页面集合；也为后续 AI 研究助手
v2 打好可检索、可解释、可复盘的基础。
