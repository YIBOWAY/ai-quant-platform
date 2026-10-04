# 平台总览

本仓库是一个**本地优先**的 AI 量化研究与模拟交易平台。它面向研究、测试、报告与只读行情分析而构建，**不是实盘交易平台**。

Phase、Wave 与 Workbench 文档是历史交付证据，不是当前开发或运维路线。Agent v0.2
已有 gated local managed-session write、durable connector 与完整观察面；历史/外部
会话仍只读，继续上下文必须显式 fork。`chat_write_ready` 是本地状态，public standing
继续 OFF。

物理 EV/除息代码的稳定锚点是 `a307b77`；可变 source、deployment mirror HEAD 与
`chat_write_ready` 必须现场重查，public/release/live 仍关闭。当前研发与验收看 HQA
研究重置计划v3.2 §12及09-20实施收据；历史浏览器工作流代码锚点为 Platform `9d0efee`/`b0615fd` 与 HQA
`d51e376`。运行数字只保留在 dated 收据。旧 D-33/D-34 worker、Mandate、soak 与 migration
030–032 的现场描述仅是历史证据。当前进度先看
[INDEX.md](INDEX.md)，运维只看
[Agent v0.2 local-stack runbook](runbooks/agent-v0-2-local-stack.md)，不要从旧
phase 标题或 checkbox 推断。

## 它能做什么

股票研究：

- 读取真实的美股与 ETF 历史数据。
- 在因子实验室查看横截面与择时诊断（2026-06-11 起默认 `futu` 真实数据，数据源/股票池/择时标的/基准可在侧栏调整），并可保存因子研究运行。
- 运行策略、标的池、因子权重与基准回测；长回测可通过 opt-in 本地 async jobs 轮询与取消。
- 从 API 读取已注册的策略目录与股票标的池目录。
- 运行可选数据源（`sample` / `futu` / `tiingo`）的实验扫描并存储结果；结果页会只读展示被扫描的固定因子组合。
- 在持久模拟账户（初始 100 万美元）里手动买卖美股，或让策略一键再平衡，并在持仓地图查看。
- 运行历史回放式模拟交易仿真。

期权研究：

- 读取 Futu 美股期权链与报价快照。
- 运行单标的期权卖方收益筛选器（Options Income Screener），并通过质量过滤、`Avoid` 审计开关和备注列查看评级原因。
- 在 34 个策展标的上运行只读期权推荐扫描；周一至周六 22:00 自动更新，页面也可立即启动同一后台任务并查看进度。
- IV Rank 未满 30 个正式交易日样本时显示积累进度，不阻断由真实报价、事件、正物理 EV 与流动性形成的推荐。
- 从推荐页高级区单独刷新公开财报与 VIX；正式 34 标的策展名单不会被页面替换。
- 周六由 HQA 调度在正式 34 标的之后另写隔离 top-100 宽池；sample 的输入、输出与 IV history 全部隔离。
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

- Hermes 同聊在 note、可执行 formula 与 ordered universe 完整时只创建一个
  research-only job；Platform 负责固定资源双引擎执行、证据校验和 verified candidate
  投影回原会话。缺材料时只追问且零入队。
- 研究成功默认停在 verified。`/library` 是用户选择“启用模拟运行”的唯一产品动作面，
  绑定 candidate digest、固定 `$10,000`，并区分研究验证与实际可启用资格；页面 GET/轮询
  不写账，也没有自动挂仓。
- `/brief` 提供动态晨报和不可变归档；`/hermes` 展示风险、预测、推演、周报、机会与
  自动化状态。
- `/hermes` 合并最近会话列表；`/hermes/sessions/[sessionId]` 通过平台 API/BFF 读取
  official Hermes API Server 上已保存的本机会话。旧 `/hermes/sessions` 是 301 alias；
  session list/detail/messages 均为 server-side GET-only。Hermes Bearer key
  留在 owner-only 文件中，不进入浏览器。health、capabilities 和 session reads 不执行
  prompt、不调用 provider，也不消耗 Hermes 配置的 provider 额度。
- `/hermes` 对当前 managed Session 显示排队、处理、分析、工具、回复和终态；连接
  只在 SSE 收到 `ready` 后标为实时。工具名、参数、输出与推理正文不进入浏览器，
  历史终态或关闭的移动侧栏不轮询活动接口。
- `GET /api/safety/effective` 是 provider-free safety observation：canonical
  PostgreSQL 必须恰好一个 root-owner `default` 账户，materialized/raw
  `account_id` 与 JSON boolean `kill_switch=true` 一致，并绑定 current paper epoch。
  `effective=true` 也不等于 release。
- HQA Keychain 先做非创建式 `probe`；只有操作者可对 exact runtime 单独执行
  `initialize-key`，普通 encrypt/put/bind 与 worker 不得创建 key。旧 private-candidate
  `status|open|revoke` 只保留为资格验证工具，不是本机聊天的日常开关。
- 平台兼容 schema 1.0 的精确三来源合同与 schema 1.1 的精确六来源合同；whole-feed
  freshness budget 是 10800 秒。
- 9G 由 HQA 本地 JSONL opportunity ledger 负责；平台只提供 CLI-only、file-backed 的
  `paper strategies observations` 精确行动事实。9G 没有新增平台数据库表、HTTP route、
  `/hermes` 卡片或调度器。
- 完整 9H 的 scheduler 与 outbound delivery 位于 HQA；平台没有为此新增 scheduler、
  outbound worker、POST route 或数据库 migration。
- Hermes session-read 增量同样没有新增数据库 migration，也没有把上游会话复制到
  PostgreSQL。旧 TUI gateway contract 已漂移并 fail closed；official API Server 是当前
  主读取链路。
- 平台不复活 LLM runner；普通 chat prompt 只经 HQA encrypted Intent Payload
  authority，不进入 PostgreSQL 或 `/act`。
- 当前自然语言产品链只有 HQA same-chat；平台内部 `d34` namespace 只是固定资源
  双引擎 worker/Registry 的实现名，不是第二套产品。新研究按需入队并停 verified；
  已启用模拟运行的策略才每天跑。`paper_only` 进不了 live registry。
- 新 managed Session 的 composer 只有在 local mutation flags、owner/CSRF、正式 034
  schema/effective paper safety、Keychain、connector liveness 与一个有效 admission 全通过
  时打开。当前 admission 是 owner-only `local_trust`；它在 local-trust/release 交叉状态中
  优先，但绝不投影 public/release 授权。External/history session 不原地写入。
- `public_chat_write_ready`、`public_write_authorized`、
  `release_authorized` 继续 OFF；旧研究页、Mandate/canary 控件与 owner API 已退役删除。
- 手工 Scene-B 和任何 live 资格仍必须人工评审。研究账和模拟账都只能进 paper，没有
  live 升级接口。常驻路径从不加载未绑定 candidate 文件。

AI 行业资讯：

- 浏览 AI HOT 精选或全部新闻流。
- 按分类、关键词和时间窗筛选，查看日报和近期日报归档。
- 打开原文链接核对来源。
- 当可选 PostgreSQL 启用且已有缓存时，上游暂时失败可显示本地缓存并标注 warning。
- 资讯页面只用于研究阅读，不生成交易信号，不触发策略、回测或模拟账户。

跨市场观察：

- `/watch?pane=radar` 用 12 只美国上市国家 ETF 做只读跨市场热力图、排名与动态 K 型分化；旧 `/asia-radar` 为 301 alias。
- `/watch?pane=cross` 用预设标的篮子（AI/半导体关注、美股板块 ETF 或显式 symbol 白名单）做只读 YTD 热力图与排序表；旧 `/market-cross-section` 为 301 alias。它与亚洲雷达共享数据通路，不共享标的池。
- 数据严格来自 Futu 1d QFQ 日线，专用 API 失败即报 400/503，不回退 sample。
- Phase 1 不提供 PE/PB、ERP、行业拥挤度或个股风险名单。

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

正常本机启动只使用 deployment mirror 的常驻栈脚本：

```bash
cd $HOME/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

服务由 LaunchAgent 持续运行，不依赖当前终端。开发态后端/前端命令见根 README；不要
用开发命令替代 live stack。打开：

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
- [Hermes 会话、本地写路径与读取边界](guides/hermes-sessions.md)
- [期权推荐：立即更新、六态和模型边界](guides/options-recommendations.md)
- [D-34 内部历史架构](architecture/d34-autonomous-paper.md)

随旧 Mandate/canary 工作台、owner API 一同退役的操作指南已物理删除；不得从历史架构
记录重建旧产品入口（口径见 [INDEX.md](INDEX.md)）。

模拟交易与持仓地图的历史设计/实现记录（其中固定初始金额与阶段编号只代表当时设计，
当前账户以 canonical PostgreSQL 事实为准）：

- [模拟交易 + 持仓地图 重设计](design/paper_trading_position_map_redesign.md)

2026-06-11 前端重构的 dated 验收记录见
[delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md)；
它不是当前路由、测试数量或运行态证明。

## 新贡献者阅读顺序

1. [INDEX.md](INDEX.md) — 当前主线和文档分类。
2. [README.md](../README.md) — 启动、稳定能力和安全边界。
3. [Agent v0.2 local-stack 运维权威](runbooks/agent-v0-2-local-stack.md)。
4. HQA `docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md` 与
   `docs/superpowers/plans/2026-07-12-full-9h-automation-notifications.md`（已交付记录）。
5. [前序 Slice 0-8 记录](superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)。
6. [数据库/存储架构](architecture/database_cache_plan.md)。
7. 改到具体功能时再读对应 `guides/`、`execution/` 和测试。

`SYSTEM_DESIGN_RESEARCH.md`、Phase 0-15、delivery 和 audit 文档是设计/交付历史，
需要追溯决策时再读，不作为“下一步”入口。

期权方向，另读：

- [guides/options-recommendations.md](guides/options-recommendations.md)
- [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md)
- [options/options_screener_learning.md](options/options_screener_learning.md)
- [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md)

当前数据库/缓存实现，请读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)

## 当前交接

当前入口是 [INDEX.md](INDEX.md) 与HQA研究重置计划v3.2 §12，主人已授权完整Phase2；
实现、真实计算与部署状态看[实施收据](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/receipts/2026-09-20-phase2-implementation.md)。可变HEAD
和运行态必须现场重查，不沿用旧OP的接班点或完成标签。Public/release/live继续关闭；安全开关以现场API为准。收据中的
dated 快照只在收据中解释。d489 历史分配台账缺口已按 HQA 计划 §13.38
在备份后追加唯一 correction，经济状态与现金未改；
今后其他正式修账仍需另行授权。
