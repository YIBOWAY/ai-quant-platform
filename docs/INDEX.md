# 文档索引

这是整个仓库的主地图。先用下面的“当前工作”确定执行入口，再按需查架构、操作
指南和历史交付。不要从旧 phase、audit 或未勾选 checkbox 推断当前进度。

## 当前工作（2026-07-12）

| 层级 | 权威入口 | 状态 |
|---|---|---|
| 跨仓产品路线 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/design/2026-07-01-roadmap-phases-0b-4.md` | Hermes 是 COO/编排层；本仓库是领域后端。 |
| 已交付跨仓计划 | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` | Slice 9A-9G + mini 9H 已完成。 |
| 已交付完整 9H | `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md` | 调度、对账、周报、freshness 与通知已完成；平台只负责只读消费。 |
| 当前实现选择 | 尚未选定 | 若恢复前端 backlog，先做新的产品决定并另立独立 bite-sized plan。 |
| 前序实现记录 | [前端渐进改造与 Hermes 集成](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md) | Slice 0-8 与后续前端 backlog 的事实记录；不是当前可直接续写的 task list。 |
| 被替代计划 | HQA `2026-07-07-phase-1a-4-research-employees.md` | 目标保留，旧 implementation 模板不得原样执行。 |
| 历史路线 | [Phase 15 素材档案](phases/phase_15_iteration_roadmap.md) | 仅作素材，不是独立 roadmap。 |

前序计划已把 `/brief`、PostgreSQL 业务事实、paper account 存储迁移、`/hermes`
只读骨架和渐进前端重设计放在同一条 expand-contract 路线上。2026-07-11 已将 8765
重启到最终 9D 工作树：live `quantplatform` 的四份 migration 共 14 张表全部存在，其中
003/004 是 11 张业务表；health、brief archive、paper API reconciliation 和关键页面
smoke 均通过。paper
mode 仍刻意保持默认 `file`；canonical 只是已验收能力，尚未成为运行事实源。当前
Slice 9A 已把 sleeve list/detail/status 与 crash recovery 分缝：GET/`ops-status` 不写盘，
`paper strategies recover-pending` 才显式恢复。Slice 9B 已让 API、CLI 与 HQA 共用
统一 paper snapshot read-model；live 仍刻意保持 `file` mode。HQA Slice 9C 已只读消费
该 snapshot，产出当前敞口/集中度 artifact。Slice 9D 新增严格只读 `data prices` JSON
seam：仅 Futu/QFQ/1d，限制 25 个标的与 500 个含首尾日历日期，不允许
sample/local/Tiingo/Longbridge fallback。HQA v2 以 previous UTC date 为 `end`、
`end-400 days` 为 `start`，先做全局日期 inner join 再算收益，最少要求 60 个对齐收益；输出逐仓相对
SPY 的 beta 与持仓两两 correlation，不计算 aggregate beta、VaR 或阈值 verdict。
2026-07-11 真实验收使用 274 个对齐收益，AAPL beta 为 `0.8576599678`；平台全量
`1027 passed, 15 skipped`，20 个受观察状态/缓存文件的 bytes、mtime、hash 均未变化。
HQA Slice 9E 已复用该 seam，真实临时 prediction ledger smoke 与到期评分通过。Slice
9F 已发布严格 Futu/QFQ 证据支持、proposal-only 的 market-foresight 候选；mini 9H
通过 `GET /api/hermes/artifacts` 和真实 `/hermes` 卡片展示组合风险、预测状态和推演产物，
Composer 继续禁用。Slice 9G 新增 HQA 本地 opportunity ledger，并通过平台 CLI-only
`paper strategies observations` 读取精确 signal/execution facts；平台没有新增机会账本
数据库、HTTP route 或 UI。真实 59 条 options 信号因无 paper-options route 均为
`not_actionable`，零虚假 missed。完整 9H 随后在 HQA 完成调度、prediction/opportunity
对账、周报聚合、job freshness 与通知投递。平台现在兼容 feed schema 1.0 的精确三来源
合同和 schema 1.1 的精确六来源合同；`/hermes` 展示风险、预测、推演、周报、机会与
自动化状态，whole-feed freshness budget 为 10800 秒。平台没有为完整 9H 新增
scheduler、outbound worker、POST route 或数据库 migration。目前没有选定下一切片。

## 0. 界面操作指南（新，建议先读）

如果你看着研究流水线的界面"理解不了它在干什么"，先读这些基于真实代码编写的中文操作与说明文档：

| 文档 | 界面 |
|---|---|
| [guides/factor-lab.md](guides/factor-lab.md) | 因子实验室 `/factor-lab` |
| [guides/backtester.md](guides/backtester.md) | 回测器 `/backtest` |
| [guides/strategy-catalog.md](guides/strategy-catalog.md) | 策略目录 `/strategies` |
| [guides/experiments.md](guides/experiments.md) | 实验管理 `/experiments` |
| [guides/paper-trading.md](guides/paper-trading.md) | 模拟交易 `/paper-trading` |
| [guides/position-map.md](guides/position-map.md) | 持仓地图 `/position-map` |
| [guides/ai-news.md](guides/ai-news.md) | AI 新闻研究流 `/ai-news` |
| [design/paper_trading_position_map_redesign.md](design/paper_trading_position_map_redesign.md) | 模拟交易 + 持仓地图**重设计**（设计文档 + 分阶段实现计划） |
| [design/paper_strategy_sleeves_plan.md](design/paper_strategy_sleeves_plan.md) | Paper Strategy Sleeves **MVP-1**（策略资金段/信号观察/allocated 分账设计，非历史 Phase 1） |
| [design/paper_strategy_sleeves_mvp2_plan.md](design/paper_strategy_sleeves_mvp2_plan.md) | Paper Strategy Sleeves **MVP-2**（pending execution / next-open 纸面执行计划） |
| [execution/paper_strategy_sleeves.md](execution/paper_strategy_sleeves.md) | Paper Strategy Sleeves 执行说明（后端基础、API contract、daily signal、手动 signal CLI、pending execution、backend next-open processor、手动处理 API/CLI、UI 执行状态控件与 opt-in 真实 Futu 验证已实现；自动调度尚未实现） |
| [design/ai_news_integration_plan.md](design/ai_news_integration_plan.md) | AI News Integration **MVP-1 / MVP-2**（AI HOT 只读新闻接入、可选 Postgres 缓存兜底，Horizon 二期自托管雷达方向） |

## 1. 从这里开始

| 文档 | 用途 |
|---|---|
| [../README.md](../README.md) | 快速项目入口与运行命令。 |
| `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` | **已交付记录**：Slice 9A-9G + mini 9H。 |
| `/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md` | **已交付记录**：完整 9H 自动化与通知。 |
| [superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md) | Slice 0-8 实现记录与未来前端 backlog。 |
| [architecture/database_cache_plan.md](architecture/database_cache_plan.md) | 当前本地存储与 PostgreSQL 业务事实架构。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | **2026-06-11 历史评估快照（HTML）**。 |
| [audits/remediation_ledger_2026-06-23.md](audits/remediation_ledger_2026-06-23.md) | **2026-06-23 整改快照**，不承担当前进度维护。 |
| [audits/remediation_goal_protocol.md](audits/remediation_goal_protocol.md) | `/goal` 长程整改执行协议：用“整改包”替代开放式优化，定义分层目标、机器验收、边界、降级、继续门禁与提交规则。 |
| [phases/phase_15_iteration_roadmap.md](phases/phase_15_iteration_roadmap.md) | **Phase 15 素材档案**：已被 HQA D-18/D-24 接管，不再是独立 active roadmap；仅保留 P0-P5 的素材价值。 |
| [OVERVIEW.md](OVERVIEW.md) | 简短的平台总览与安全摘要。 |
| [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md) | 最初的系统设计与长期架构。 |
| [AGENTS.md](../AGENTS.md) | 本仓库中 AI 代理工作的规则。 |

## 2. 阶段地图

| 阶段 | 范围 | 架构 | 执行 | 学习 | 交付 |
|---|---|---|---|---|---|
| 0 | 项目骨架 | [架构](architecture/phase_0_architecture.md) | [执行](execution/phase_0_execution.md) | [学习](learning/phase_0_learning.md) | [交付](delivery/phase_0_delivery.md) |
| 1 | 数据层 MVP | [架构](architecture/phase_1_architecture.md) | [执行](execution/phase_1_execution.md) | [学习](learning/phase_1_learning.md) | [交付](delivery/phase_1_delivery.md) |
| 2 | 因子研究 MVP | [架构](architecture/phase_2_architecture.md) | [执行](execution/phase_2_execution.md) | [学习](learning/phase_2_learning.md) | [交付](delivery/phase_2_delivery.md) |
| 3 | 回测 MVP | [架构](architecture/phase_3_architecture.md) | [执行](execution/phase_3_execution.md) | [学习](learning/phase_3_learning.md) | [交付](delivery/phase_3_delivery.md) |
| 4 | 多因子实验 | [架构](architecture/phase_4_architecture.md) | [执行](execution/phase_4_execution.md) | [学习](learning/phase_4_learning.md) | [交付](delivery/phase_4_delivery.md) |
| 5 | 风险与模拟交易 | [架构](architecture/phase_5_architecture.md) | [执行](execution/phase_5_execution.md) | [学习](learning/phase_5_learning.md) | [交付](delivery/phase_5_delivery.md) |
| 7 | AI 研究助手 | [架构](architecture/phase_7_architecture.md) | [执行](execution/phase_7_execution.md) | [学习](learning/phase_7_learning.md) | [交付](delivery/phase_7_delivery.md) |
| 8 | 预测市场接口 | [架构](architecture/phase_8_architecture.md) | [执行](execution/phase_8_execution.md) | [学习](learning/phase_8_learning.md) | [交付](delivery/phase_8_delivery.md) |
| 9 | 本地 HTTP API | [架构](architecture/phase_9_api_architecture.md) | [执行](execution/phase_9_api_execution.md) | [学习](learning/phase_9_api_learning.md) | [交付](delivery/phase_9_api_delivery.md) |
| 10 | 前端/后端修复 | - | [执行](execution/phase_10_execution.md) | [学习](learning/phase_10_learning.md) | [交付](delivery/phase_10_fix_delivery.md) |
| 11 | 只读 Polymarket 数据 | [架构](architecture/phase_11_architecture.md) | [执行](execution/phase_11_execution.md) | [学习](learning/phase_11_learning.md) | [交付](delivery/phase_11_delivery.md) |
| 12 | Polymarket 历史回放 | [架构](architecture/phase_12_architecture.md) | [执行](execution/phase_12_execution.md) | [学习](learning/phase_12_learning.md) | [交付](delivery/phase_12_delivery.md) |
| 13 | 期权雷达 | [架构](architecture/phase_13_architecture.md) | [执行](execution/phase_13_execution.md) | [学习](learning/phase_13_learning.md) | [交付](delivery/phase_13_delivery.md) |
| 14 | 买方期权助手 | - | [执行](execution/phase_14_execution.md) | [学习](options/buyside_strategy_learning.md) | [交付](delivery/phase_14_delivery.md) |
| 15 | 历史维护素材（非活跃路线） | [素材](phases/phase_15_iteration_roadmap.md) | - | - | - |

## 3. 关键代码入口

| 区域 | 入口 |
|---|---|
| 股票数据提供方工厂 | `src/quant_system/data/provider_factory.py` |
| Futu 股票数据提供方 | `src/quant_system/data/providers/futu.py` |
| 因子流水线 | `src/quant_system/factors/pipeline.py` |
| 因子实验室仪表盘引擎 | `src/quant_system/factors/lab.py` |
| 回测流水线 | `src/quant_system/backtest/pipeline.py` |
| 回测 API job runner | `src/quant_system/api/jobs/backtest_jobs.py` |
| 策略注册表（含账户再平衡能力位） | `src/quant_system/strategies/registry.py` |
| Universe 注册表 | `src/quant_system/universe/registry.py` |
| 反转/动量论文复现 | `src/quant_system/replication/reversal_momentum.py` |
| 模拟交易历史回放流水线 | `src/quant_system/execution/pipeline.py` |
| 持久模拟账户模型 + 账本 | `src/quant_system/execution/account.py` |
| 模拟账户持久化 | `src/quant_system/execution/account_storage.py` |
| 模拟账户统一观察快照 | `src/quant_system/execution/account_snapshot.py` |
| 模拟账户取价（Futu 快照→最近收盘） | `src/quant_system/execution/price_source.py` |
| 模拟账户下单/再平衡服务 | `src/quant_system/execution/account_service.py` |
| Paper Strategy Sleeves 领域模型 / 分账基础 | `src/quant_system/execution/paper_strategy_sleeves.py` |
| Paper Strategy Sleeves 本地存储 | `src/quant_system/execution/paper_strategy_sleeve_storage.py` |
| Paper Strategy Sleeves 信号生成 | `src/quant_system/execution/paper_strategy_signal_service.py` |
| Paper Strategy Sleeves next-open 执行处理器 | `src/quant_system/execution/paper_strategy_execution_service.py` |
| Paper Strategy Sleeves 9G bounded observations | `src/quant_system/execution/paper_strategy_observations.py` |
| Paper Strategy Sleeves MVP-2 计划 | `docs/design/paper_strategy_sleeves_mvp2_plan.md` |
| 期权卖方筛选器 | `src/quant_system/options/screener.py` |
| 期权雷达 | `src/quant_system/options/radar.py` |
| 期权雷达刷新辅助 | `src/quant_system/options/data_refresh.py` |
| 本地 AlphaGBM 风格期权工具 | `src/quant_system/options/local_tools.py` |
| 本地期权研究辅助 | `src/quant_system/options/local_research.py` |
| Futu 期权 DuckDB 缓存 | `src/quant_system/storage/options_cache.py` |
| PostgreSQL 运行索引（可选） | `src/quant_system/storage/runs_repository.py` |
| 数据库连接 + 迁移 | `src/quant_system/storage/database.py` |
| Brief 业务事实 | `src/quant_system/brief/` / `src/quant_system/api/routes/brief.py` |
| AI HOT 只读新闻缓存（可选） | `src/quant_system/news/repository.py` / `scripts/sql/002_ai_news_cache.sql` |
| Paper repository factory | `src/quant_system/execution/account_repository_factory.py` |
| Paper PostgreSQL / mirror repository | `src/quant_system/execution/account_postgres_repository.py` / `account_dual_write_repository.py` |
| 买方指标 | `src/quant_system/options/buy_side_metrics.py` |
| 买方策略生成 | `src/quant_system/options/buy_side_strategy.py` |
| 买方场景实验室 | `src/quant_system/options/buy_side_scenarios.py` |
| 买方决策 API 逻辑 | `src/quant_system/options/buy_side_decision.py` |
| Futu 股票/期权提供方 | `src/quant_system/data/providers/futu.py` |
| AI HOT 只读新闻 client | `src/quant_system/news/aihot_client.py` |
| AI News API route/schema | `src/quant_system/api/routes/news.py` / `src/quant_system/api/schemas/news.py` |
| 预测市场提供方工厂 | `src/quant_system/prediction_market/provider_factory.py` |
| 预测市场采集器 | `src/quant_system/prediction_market/collector.py` |
| 预测市场回放回测 | `src/quant_system/prediction_market/timeseries_backtest.py` |
| API 路由 | `src/quant_system/api/routes/` |
| 前端路由 | `src/frontend/app/` |
| Factor Lab 到 Backtester 的预填链接 | `src/frontend/lib/factorLabHandoff.ts` |

## 4. 期权与 Futu 文档

| 文档 | 用途 |
|---|---|
| [futu/futu_integration_design.md](futu/futu_integration_design.md) | Futu 集成设计。 |
| [futu/futu_environment_setup.md](futu/futu_environment_setup.md) | OpenD 与 SDK 设置。 |
| [futu/futu_market_data_provider.md](futu/futu_market_data_provider.md) | Futu 股票数据提供方。 |
| [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md) | Futu 期权提供方、字段、速率限制与安全失败。 |
| [futu/futu_troubleshooting.md](futu/futu_troubleshooting.md) | Futu 故障排查。 |
| [options/options_screener_api.md](options/options_screener_api.md) | 期权筛选器 API 参考。 |
| [options/options_screener_learning.md](options/options_screener_learning.md) | 卖方期权筛选器指南。 |
| [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md) | 买方助手指南、场景实验室与风险披露。 |
| [options/local_alphagbm_tools.md](options/local_alphagbm_tools.md) | 本地 AlphaGBM 风格期权工具与端点。 |
| [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md) | Phase 14 交付与验证记录。 |
| [audits/README.md](audits/README.md) | 历史审计笔记与现行状态指引。 |
| [audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](audits/FRONTEND_REAL_DATA_REVIEW_2026-05-31.md) | 现行前端真实数据与 sample 标注审查。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | 2026-06-11 全项目多智能体评估报告（现行权威，HTML）。 |

## 5. 研究复现文档

| 文档 | 用途 |
|---|---|
| [replications/reversal_momentum_replication.md](replications/reversal_momentum_replication.md) | 短期反转与长期动量论文的本地复现指南。 |
| [learning/research_registry_pipeline_2026_06_02.md](learning/research_registry_pipeline_2026_06_02.md) | 策略、universe、回测与只读因子实验室注册表工作流。 |

## 6. Polymarket / 预测市场文档

| 文档 | 用途 |
|---|---|
| [polymarket/polymarket_read_only_integration.md](polymarket/polymarket_read_only_integration.md) | 只读集成指南。 |
| [polymarket/polymarket_history_collection.md](polymarket/polymarket_history_collection.md) | 历史快照采集器指南。 |
| [polymarket/polymarket_timeseries_backtest_learning.md](polymarket/polymarket_timeseries_backtest_learning.md) | 时间序列回放学习指南。 |
| [polymarket/polymarket_charts_and_metrics.md](polymarket/polymarket_charts_and_metrics.md) | 图表与指标说明。 |
| [polymarket/polymarket_troubleshooting.md](polymarket/polymarket_troubleshooting.md) | 故障排查指南。 |
| [polymarket/polymarket_safety_boundaries.md](polymarket/polymarket_safety_boundaries.md) | 安全边界与非目标。 |

## 7. 当前前端页面

| 页面 | 用途 |
|---|---|
| `/data-explorer` | 股票数据查看器。 |
| `/brief` | 当日动态晨报预览；归档入口读取 PostgreSQL 中不可变 brief snapshot。 |
| `/brief/[publicId]` | 已归档晨报的只读快照页。 |
| `/hermes` | 只读产物架：展示风险、预测、推演、周报、机会与自动化状态；不提交 agent task 或交易动作。 |
| `/factor-lab` | 现有只读因子健康度与单标的择时仪表盘；HQA 工作台落地后应从一级入口降级为 run/detail 分析面。 |
| `/factor-lab/[runId]` | 因子运行详情。 |
| `/backtest` | 策略、universe 与因子权重回测运行。 |
| `/backtest/[runId]` | 回测运行详情。 |
| `/strategies` | 由策略注册表支撑的策略目录。 |
| `/strategies/[runId]` | 已落盘的反转/动量研报复现运行详情。 |
| `/docs/reversal-momentum` | 前端可读的复现文档。 |
| `/experiments` | 实验扫描、可选滚动验证折、固定因子组合摘要、数据源标注与最佳运行回顾。 |
| `/paper-trading` | 持久模拟账户（手动下单 + 策略一键再平衡）＋历史回放（研究）。 |
| `/paper-trading/[runId]` | 历史回放运行详情。 |
| `/position-map` | 模拟账户实时持仓地图（净值/现金/暴露/来源归因），另含回测暴露对比块。 |
| `/options-screener` | 单标的卖方期权筛选，含质量过滤、`Avoid` 审计开关与备注列。 |
| `/options-radar` | 每日卖方期权雷达快照。 |
| `/options-radar/[symbol]` | 已保存的雷达候选，以及可选的实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/ai-news` | AI HOT 只读新闻研究流，含精选动态、关键词/分类/时间窗筛选、日报和原文链接。 |
| `/polymarket` | 只读预测市场研究。 |
| `/agent-studio` | 现有候选池与人工审批 UI；HQA 工作台落地后保留审批能力，移除平台侧 LLM/task-running 表象。 |
| `/settings` | 脱敏后的本地设置。 |

前端文档：

| 文档 | 用途 |
|---|---|
| [frontend/frontend_chinese_version.md](frontend/frontend_chinese_version.md) | 站点级 English / 中文 语言路径、切换与 cookie 回退。 |
| [frontend/design_brief.md](frontend/design_brief.md) | 前端设计简报与组件规划。 |
| [delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md) | 2026-06-11 前端全面重构交付记录（设计系统、布局、E2E 根因与验证、截图）。 |

## 8. 常用命令

后端：

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

前端：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

测试与代码检查：

```powershell
conda activate ai-quant
quant-system doctor
.\scripts\verify.ps1
# 可选：dev server 停止时再运行 .\scripts\verify.ps1 -Build
```

`quant-system doctor` 是离线本地健康摘要：不连接行情源或数据库，只读取 settings
并输出安全开关、默认数据源、Futu/OpenD 端点、数据库索引配置和
`data/_runtime/logs/backend.jsonl` 路径。

期权雷达 sample 规模的真实运行：

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

期权雷达调度任务（刷新标的池、财报、VIX 后再扫描）：

```powershell
conda activate ai-quant
quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
```

买方助手调试运行：

```powershell
conda activate ai-quant
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

## 9. 安全检查清单

1. `/api/health` 显示 `live_trading_enabled=false`。
2. `/api/orders/submit` 返回 404。
3. `/api/settings` 对密钥脱敏。
4. `/api/agent/llm-config` 不返回 API 密钥。
5. 携带 `polymarket_api_key` 的预测市场请求返回 400。
6. 不存在任何钱包、签名、券商或**实盘**下单路由（`/api/paper/account/orders` 等仅为本地模拟账户，不触达真实券商）。
7. Futu 代码只使用行情/数据上下文。
8. 前端页面清晰标注仅研究 / 只读输出。

## 10. 缓存层状态

已实现五类本地存储能力：

- DuckDB 缓存本地 Futu 期权报价窗口
  （`storage/options_cache.py`）。
- 一个可选的 PostgreSQL **运行索引**（`storage/database.py`、
  `storage/runs_repository.py`、`scripts/sql/001_runs_index.sql`）镜像
  基于文件的 backtest/factor/paper/replication 运行以便快速列出。它默认关闭
  （`QS_DATABASE_ENABLED`），在启动时于后台与文件系统对账，当数据库
  关闭、缓慢或不可达时，API 回退到扫描文件。
- 一个可选的 PostgreSQL **AI HOT 新闻缓存**（`news/repository.py`、
  `scripts/sql/002_ai_news_cache.sql`）镜像只读 AI 新闻条目；实时请求成功后写入，
  上游失败时可作为 `/ai-news` 的 stale fallback，并通过 warning 告知用户。
- PostgreSQL **brief / AI daily 业务事实**（migration 003）：root owner、不可变
  brief issue/snapshot/source 和 owner-scoped AI 日报。
- PostgreSQL **paper account repository**（migration 004）：`file` 默认、
  file-authoritative `mirror`、DB-authoritative `canonical` 三种模式；API additive
  返回 `storage_mode/stale/warnings/reconciliation`。reconciliation 对账 raw、账户
  物化列、完整 ledger、positions、pending orders 和 snapshot state/integrity/freshness，
  不自动切换模式；canonical 缺账户时要求显式 backfill，不由普通 GET 创建。

延伸阅读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

当前状态与后续决策：

- DuckDB 现用于本地 Futu 期权报价窗口。
- PostgreSQL 现（可选）用于 backtest/factor/paper/replication 运行索引。
- PostgreSQL 现（可选）也用于 AI HOT 只读新闻条目缓存。
- 四份 migration 的 14 张表（其中 003/004 为 11 张业务表）、brief archive 与 paper repository 已在代码、
  throwaway DB 和重启后的 live 库验证。
- paper account 当前默认仍是 `file`，不能把 canonical 能力误写成已切换状态。
- `quant-system data prices` 现为只读 Futu/QFQ/1d JSON seam；不读取 local cache，也不
  回退到 sample、Tiingo 或 Longbridge。
- HQA 9A-9G、mini 9H 与完整 9H 均已完成；目前没有选定下一实现切片。
- 未来前端 backlog 需要新的产品决定，并按最新源码另立独立 bite-sized plan。
- 剩余的 PostgreSQL 目标：雷达运行、请求日志，以及更丰富的
  API 可见快照。
- 对大型 OHLCV 与分析型时间序列数据集采用 Parquet / DuckDB。
- 若 PostgreSQL 后续成为主要时间序列存储，可选引入 TimescaleDB。
