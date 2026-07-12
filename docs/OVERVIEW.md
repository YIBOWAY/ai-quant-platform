# 平台总览

本仓库是一个**本地优先**的 AI 量化研究与模拟交易平台。它面向研究、测试、报告与只读行情分析而构建，**不是实盘交易平台**。

Phase 0-14 是已交付的历史能力层，不是当前开发路线。HQA Slice 9A-9G、只读
mini 9H 与完整 9H 自动化/通知均已完成；目前没有选定下一实现切片。
[前端渐进改造与 Hermes 集成计划](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)
保留 Slice 0-8 记录与未来 UI backlog；恢复该 backlog 前必须先做新的产品决定并另立
独立 bite-sized plan。9E 位于 HQA；它复用 9D 的 `data prices`
严格只读 Futu/QFQ/1d JSON seam（25 个标的、500 个
含首尾日历日期上限，无其他 provider 或 local fallback）；HQA v2 以 previous UTC date
为 `end`、`end-400 days` 为 `start`，经全局日期 inner join 和至少 60 个对齐收益，输出逐仓 beta 与持仓两两
correlation，不输出 aggregate beta、VaR 或阈值 verdict。当前进度先看
[INDEX.md](INDEX.md)，
不要从旧 phase 文档的标题或 checkbox 推断。

## 它能做什么

股票研究：

- 读取真实的美股与 ETF 历史数据。
- 在因子实验室查看横截面与择时诊断（2026-06-11 起默认 `futu` 真实数据，数据源/股票池/择时标的/基准可在侧栏调整），并可保存因子研究运行。
- 运行策略、universe、因子权重与基准回测；长回测可通过 opt-in 本地 async jobs 轮询与取消。
- 从 API 读取已注册的策略目录与股票 universe 目录。
- 运行可选数据源（`sample` / `futu` / `tiingo`）的实验扫描并存储结果；结果页会只读展示被扫描的固定因子组合。
- 在持久模拟账户（初始 100 万美元）里手动买卖美股，或让策略一键再平衡，并在持仓地图查看。
- 运行历史回放式模拟交易仿真。

期权研究：

- 读取 Futu 美股期权链与报价快照。
- 运行单标的期权卖方收益筛选器（Options Income Screener），并通过质量过滤、`Avoid` 审计开关和备注列查看评级原因。
- 在本地 universe 上运行每日期权雷达（Options Radar）扫描。
- 从雷达 UI 刷新本地的雷达 universe、财报与 VIX 缓存；默认使用公开数据源，sample 数据仅作为明确的测试源。
- 查看单标的雷达候选，并可选地加载实时期权链。
- 使用 VIX/VIX3M 历史对市场状态（regime）进行分类。
- 运行买方期权助手（Buy-Side Options Assistant），用于看涨的多头权利金结构。
- 使用本地 AlphaGBM 风格的期权工具，进行希腊字母、波动率微笑、曲面、打分、策略排序与仅研究用途的提醒/自选清单。

预测市场研究：

- 读取公开市场数据。
- 采集历史快照。
- 运行回放式时间序列回测。
- 生成报告与图表。

Hermes 与 AI 研究工作流：

- Hermes 会话负责生成研究源码/产物；平台负责确定性摄入、候选池、人工审批、
  一次性研究回测和 promote diff。
- `/brief` 提供动态晨报和不可变归档；`/hermes` 通过只读
  `GET /api/hermes/artifacts` 展示风险、预测、推演、周报、机会与自动化状态。
- 平台兼容 schema 1.0 的精确三来源合同与 schema 1.1 的精确六来源合同；whole-feed
  freshness budget 是 10800 秒。
- 9G 由 HQA 本地 JSONL opportunity ledger 负责；平台只提供 CLI-only、file-backed 的
  `paper strategies observations` 精确行动事实。9G 没有新增平台数据库表、HTTP route、
  `/hermes` 卡片或调度器。
- 完整 9H 的 scheduler 与 outbound delivery 位于 HQA；平台没有为此新增 scheduler、
  outbound worker、POST route 或数据库 migration。
- 平台不复活 LLM runner，不把 disabled composer 伪装成可执行任务面。
- 任何候选晋级前都必须经过人工评审；常驻 paper/live 路径不加载 candidate 文件。

AI 行业资讯：

- 浏览 AI HOT 精选或全部新闻流。
- 按分类、关键词和时间窗筛选，查看日报和近期日报归档。
- 打开原文链接核对来源。
- 当可选 PostgreSQL 启用且已有缓存时，上游暂时失败可显示本地缓存并标注 warning。
- 资讯页面只用于研究阅读，不生成交易信号，不触发策略、回测或模拟账户。

## 它不能做什么

- 不做实盘交易。
- 不做真实券商下单。
- 不连接钱包。
- 不做签名。
- 不解锁 Futu 账户。
- 不创建 Futu 交易上下文。
- 不把策略自动晋级到实盘执行。
- 不提供投资建议。

## 安全边界

默认的安全姿态必须保持保守：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`
- `no_live_trade_without_manual_approval = true`

每一个新功能都必须维持这些边界。

## 如何启动

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

打开：

```text
http://127.0.0.1:3001
```

## 界面操作指南（新）

如果你看着界面"理解不了它在干什么"，先读这些基于真实代码写的中文操作与说明文档：

- [因子实验室 Factor Lab](guides/factor-lab.md)
- [回测器 Backtester](guides/backtester.md)
- [策略目录 Strategy Catalog](guides/strategy-catalog.md)
- [实验管理 Experiments](guides/experiments.md)
- [模拟交易 Paper Trading](guides/paper-trading.md)
- [持仓地图 Position Map](guides/position-map.md)
- [AI 新闻研究流 AI News](guides/ai-news.md)

模拟交易与持仓地图的设计与实现记录（单一 100 万模拟账户、策略一键再平衡 + 手动美股下单、统一持仓地图，**阶段 1-5 已实现**）：

- [模拟交易 + 持仓地图 重设计](design/paper_trading_position_map_redesign.md)

前端于 2026-06-11 完成全页面重构（统一设计令牌、固定视口外壳、模拟交易双标签页、账户驱动持仓地图、E2E 38/38），详见 [delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md)。

## 新贡献者阅读顺序

1. [INDEX.md](INDEX.md) — 当前主线和文档分类。
2. [README.md](../README.md) — 启动、稳定能力和安全边界。
3. HQA `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` 与
   `docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md`（已交付记录）。
4. [前序 Slice 0-8 记录](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)。
5. [数据库/存储架构](architecture/database_cache_plan.md)。
6. 改到具体功能时再读对应 `guides/`、`execution/` 和测试。

`SYSTEM_DESIGN_RESEARCH.md`、Phase 0-15、delivery 和 audit 文档是设计/交付历史，
需要追溯决策时再读，不作为“下一步”入口。

期权方向，另读：

- [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md)
- [options/options_screener_learning.md](options/options_screener_learning.md)
- [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md)

当前数据库/缓存实现，请读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

## 当前交接

HQA 9A-9G、mini 9H 与完整 9H 已完成，目前没有选定下一实现切片。未来前端 backlog
需要新的产品决定，并按最新源码另立独立 bite-sized plan；平台继续只读消费 HQA
产物，不承担调度或外发投递。
