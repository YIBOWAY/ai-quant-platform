# 文档索引

这是整个仓库的主地图。用它来查找架构文档、执行手册、学习笔记、交付记录与安全边界。

当前状态：Phase 14 已交付，后续还补充了本地期权工具、雷达下钻、运行详情页、实验回顾、本地 Futu 期权报价缓存、PostgreSQL 运行索引加固、研报复现运行持久化、实验数据源选择，以及语言连续性修复，均记录在下文。最近一次大型变更为 2026-06-11 的前端全面重构（设计系统统一 + 全页面布局/可解释性整治 + E2E 38/38），见 [delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md)。

## 0. 界面操作指南（新，建议先读）

如果你看着研究流水线的界面"理解不了它在干什么"，先读这些基于真实代码编写的中文操作与说明文档：

| 文档 | 界面 |
|---|---|
| [guides/factor-lab.md](guides/factor-lab.md) | 因子实验室 `/factor-lab` |
| [guides/backtester.md](guides/backtester.md) | 回测器 `/backtest` |
| [guides/strategy-catalog.md](guides/strategy-catalog.md) | 策略目录 `/replications` |
| [guides/experiments.md](guides/experiments.md) | 实验管理 `/experiments` |
| [guides/paper-trading.md](guides/paper-trading.md) | 模拟交易 `/paper-trading` |
| [guides/position-map.md](guides/position-map.md) | 持仓地图 `/position-map` |
| [design/paper_trading_position_map_redesign.md](design/paper_trading_position_map_redesign.md) | 模拟交易 + 持仓地图**重设计**（设计文档 + 分阶段实现计划） |

## 1. 从这里开始

| 文档 | 用途 |
|---|---|
| [../README.md](../README.md) | 快速项目入口与运行命令。 |
| [audits/project_assessment_2026-06-11.html](audits/project_assessment_2026-06-11.html) | **2026-06-11 全项目评估报告（HTML）**：8 维度多智能体审核 + 对抗复核、"不顺手"根因分析、16 项快赢、分阶段治理路线图、渐进 vs 重构结论。 |
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

## 3. 关键代码入口

| 区域 | 入口 |
|---|---|
| 股票数据提供方工厂 | `src/quant_system/data/provider_factory.py` |
| Futu 股票数据提供方 | `src/quant_system/data/providers/futu.py` |
| 因子流水线 | `src/quant_system/factors/pipeline.py` |
| 因子实验室仪表盘引擎 | `src/quant_system/factors/lab.py` |
| 回测流水线 | `src/quant_system/backtest/pipeline.py` |
| 策略注册表 | `src/quant_system/strategies/registry.py` |
| Universe 注册表 | `src/quant_system/universe/registry.py` |
| 反转/动量论文复现 | `src/quant_system/replication/reversal_momentum.py` |
| 模拟交易历史回放流水线 | `src/quant_system/execution/pipeline.py` |
| 持久模拟账户模型 + 账本 | `src/quant_system/execution/account.py` |
| 模拟账户持久化 | `src/quant_system/execution/account_storage.py` |
| 模拟账户取价（Futu 快照→最近收盘） | `src/quant_system/execution/price_source.py` |
| 模拟账户下单/再平衡服务 | `src/quant_system/execution/account_service.py` |
| 期权卖方筛选器 | `src/quant_system/options/screener.py` |
| 期权雷达 | `src/quant_system/options/radar.py` |
| 期权雷达刷新辅助 | `src/quant_system/options/data_refresh.py` |
| 本地 AlphaGBM 风格期权工具 | `src/quant_system/options/local_tools.py` |
| 本地期权研究辅助 | `src/quant_system/options/local_research.py` |
| Futu 期权 DuckDB 缓存 | `src/quant_system/storage/options_cache.py` |
| PostgreSQL 运行索引（可选） | `src/quant_system/storage/runs_repository.py` |
| 数据库连接 + 迁移 | `src/quant_system/storage/database.py` |
| 买方指标 | `src/quant_system/options/buy_side_metrics.py` |
| 买方策略生成 | `src/quant_system/options/buy_side_strategy.py` |
| 买方场景实验室 | `src/quant_system/options/buy_side_scenarios.py` |
| 买方决策 API 逻辑 | `src/quant_system/options/buy_side_decision.py` |
| Futu 股票/期权提供方 | `src/quant_system/data/providers/futu.py` |
| 预测市场提供方工厂 | `src/quant_system/prediction_market/provider_factory.py` |
| 预测市场采集器 | `src/quant_system/prediction_market/collector.py` |
| 预测市场回放回测 | `src/quant_system/prediction_market/timeseries_backtest.py` |
| API 路由 | `src/quant_system/api/routes/` |
| 前端路由 | `src/frontend/app/` |

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
| `/factor-lab` | 只读因子健康度与单标的择时仪表盘。 |
| `/factor-lab/[runId]` | 因子运行详情。 |
| `/backtest` | 策略、universe 与因子权重回测运行。 |
| `/backtest/[runId]` | 回测运行详情。 |
| `/replications` | 由策略注册表支撑的策略目录。 |
| `/replications/[runId]` | 已落盘的反转/动量研报复现运行详情。 |
| `/docs/reversal-momentum` | 前端可读的复现文档。 |
| `/experiments` | 实验扫描、可选滚动验证折、对比、数据源标注与最佳运行回顾。 |
| `/paper-trading` | 持久模拟账户（手动下单 + 策略一键再平衡）＋历史回放（研究）。 |
| `/paper-trading/[runId]` | 历史回放运行详情。 |
| `/position-map` | 模拟账户实时持仓地图（净值/现金/暴露/来源归因），另含回测暴露对比块。 |
| `/options-screener` | 单标的卖方期权筛选。 |
| `/options-radar` | 每日卖方期权雷达快照。 |
| `/options-radar/[symbol]` | 已保存的雷达候选，以及可选的实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/order-book` | 只读预测市场研究。 |
| `/agent-studio` | AI 研究助手工作流。 |
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
.\scripts\verify.ps1
# 可选：dev server 停止时再运行 .\scripts\verify.ps1 -Build
```

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

已实现两个本地存储层：

- DuckDB 缓存本地 Futu 期权报价窗口
  （`storage/options_cache.py`）。
- 一个可选的 PostgreSQL **运行索引**（`storage/database.py`、
  `storage/runs_repository.py`、`scripts/sql/001_runs_index.sql`）镜像
  基于文件的 backtest/factor/paper 运行以便快速列出。它默认关闭
  （`QS_DATABASE_ENABLED`），在启动时于后台与文件系统对账，当数据库
  关闭、缓慢或不可达时，API 回退到扫描文件。

延伸阅读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

当前与下一步方向：

- DuckDB 现用于本地 Futu 期权报价窗口。
- PostgreSQL 现（可选）用于 backtest/factor/paper 运行索引。
- 剩余的 PostgreSQL 目标：雷达运行、请求日志，以及更丰富的
  API 可见快照。
- 对大型 OHLCV 与分析型时间序列数据集采用 Parquet / DuckDB。
- 若 PostgreSQL 后续成为主要时间序列存储，可选引入 TimescaleDB。
