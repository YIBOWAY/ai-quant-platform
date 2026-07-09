# 前端渐进改造与 Hermes 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-quant-platform 前端从当前 QUANTUM_CORE 冷黑终端风,渐进改造到「B 暗色编辑式 + C Hermes 对话流」混合新视觉,同时新增 Hermes 一等公民页面、每日晨报归档入口、Postgres 业务事实持久化,并安全下线 factor-lab 与 agent-studio 两页,不破坏现有 22 页功能或任何交易安全闸门。

**Architecture:** 2026-07-08 修订版采用「统一 warm near-black shell + sidebar rail token」作为全局底色,`/brief` 暗色晨报与 `/hermes` 对话流在同一主题内 opt-in 编辑式/对话式组件。数据侧采用 expand-contract:先把每日晨报快照、AI HOT daily report、paper account ledger/positions 作为可查询可审计业务事实写入 Postgres,大体量回测 artifact/Parquet/DuckDB/JSONL 继续留在文件或专用缓存。平台数据访问模式(`lib/api.ts`/`lib/apiClient.ts` + TanStack Query)保持同构,Hermes 后端 MVP 只复用现有 agent candidates/detail/review/provenance 读面;不复活平台侧 LLM runner,不前端伪造异步 job。paper account 迁移走 mirror → reconciliation → DB canonical 三步,防止 AAPL 这类文件状态漂移再次发生。

**Tech Stack:** Next.js 15 App Router · React 19 · Tailwind 4(@theme + @tailwindcss/typography)· TanStack Query 5 · recharts + lightweight-charts · motion(^12,已装零启用)· react-hook-form + zod · Vitest · @playwright/test · next/font/google(Source Serif 4 + Noto Serif SC)· FastAPI 后端(:8765)

## Global Constraints

- **项目路径:** ai-quant-platform 前端在 `/Users/sunyibo/programs/ai-quant-platform/src/frontend`,后端在 `/Users/sunyibo/programs/ai-quant-platform/src/quant_system`。本计划所有前端文件路径相对 `src/frontend/`,后端相对 `src/quant_system/`。
- **不破坏现有功能红线:** 迁移期不改现有业务 getter 语义、不改 `lib/apiClient.ts`、不改各 form 的 `useQuery/useMutation` 调用点。视觉迁移只改 `className` + JSX 结构 + 原语替换。Hermes/brief getter 必须是 read-only additive wrapper;允许读取 `/api/paper/account/snapshot` 与 `/api/paper/account/equity-curve`,但不得触发策略、回测、paper account mutation、真实券商或任何交易链路。
- **token 演进红线:** 不重命名或删除现有 `globals.css` token 与 Material-3 兼容别名。2026-07-08 已拍板把全局底色统一到 warm near-black (`--color-bg-base #12110E`) 并新增 sidebar rail token (`--color-bg-sidebar #1C1B20`, `--color-bg-sidebar-muted #25242A`);后续视觉改动只能通过语义 token 扩展或局部 class opt-in,不能散落硬编码色值。
- **Postgres 持久化边界:** Docker Postgres 只承载可查询、可审计、需要稳定回看的业务事实:brief issues/snapshots/sources、AI HOT daily reports、paper account ledger/current positions/snapshots/root user。大体量 backtest artifact、OHLCV 宽表、DuckDB option cache、Prediction Market JSONL/HTTP cache 暂不迁入 Postgres。
- **paper account 安全迁移:** `PaperAccount.ledger` 是权威事件流。迁移时禁止只迁 cash/positions 当前视图;必须先 backfill ledger + current positions,再 dual-write + reconciliation,最后切 DB canonical。DB canonical 后,Postgres 不可用时 mutation fail closed,只允许读最后快照并显示 stale warning。
- **数据层同构:** 服务端走 `lib/api.ts` 的 `apiGet`(cache:no-store,60s超时,ApiEnvelope fallback),客户端走 `lib/apiClient.ts` 的 `apiRequest`(180s超时,1次重试,AbortController)。Hermes 页必须复用此模式,不新建 fetch 基建。
- **i18n 现状:** middleware.ts 重写做 i18n(非 `[locale]` 段),`localizePath/splitLocalePath` 对任意 pathname 透明。新增 `/hermes` 无需改 `locale.ts`,只需在 Sidebar/TopBar copy 对象加 `nav.hermes` 键(en+zh)。
- **不引入 feature flag:** 通过语义 token 与局部页面 opt-in 让新旧视觉天然同进程并存,无需 next.config flag 或 middleware 切换。中途想看旧版直接 `git revert` 页面文件。
- **contract 测试硬约束:** `tests/test_frontend_topbar_navigation_contract.py` 强制 TopBar 含 `href:'/factor-lab'` 与 `href:'/agent-studio'`;`tests/test_frontend_terminal_surface_contract.py` 强制 `app/agent-studio/page.tsx` 含特定 grid 片段。删导航/删页必须同提交更新这两个测试,否则 CI 红。
- **TDD:** 每个新组件/模块先写失败测试(单测或 E2E 断言)再实现。注意当前 `src/frontend/vitest.config.ts` 只 include `lib/**/*.test.ts`;P0 执行前必须先把新 Vitest 测试放入可见路径,或同提交扩展 include,否则 `npm test`/`vitest run` 会漏测。视觉类用 Playwright `toHaveScreenshot` 做 scoped baseline(见 Q8 裁决);逻辑类用 Vitest。
- **频繁提交:** 按可验证切片提交,commit message 用 `feat(frontend):` / `refactor(frontend):` / `test(frontend):` 前缀。P0 可合并为 1-2 个地基提交,不要为了形式拆成 9 个微提交导致 review 成本过高。
- **单人执行:** 这是一人量化研究者的项目,追求低风险、可回滚、可中途停发布。MVP 切线 3-4 周只覆盖 token/nav/`/brief`/`/hermes` skeleton/一条核心迁移;全量 redesign + 旧页物理删除是 6-8 周级别。

---

## 讨论结论摘要(5 个前端子智能体交叉验证)

完整讨论见 workflow 输出。这里只放落地必须的共识与裁决。

### 8 条共识

1. **token 先行且兼容别名保留** — `globals.css` @theme 已有「规范名 + Material-3 兼容别名指向同一调色板」先例,新增或调整视觉只能走语义 token,不得散落硬编码色值。
2. **页面形态三分类** — 报告型(TerminalSplitShell 左配置右结果:backtest/experiments/strategies)/操作型(表单主导:options-*/paper-trading/settings)/对话工作流型(待新增 Hermes)。改造 effort 按 `components/forms/` 的 form 行数(总计11805行)排期,不按 page.tsx 行数(多仅12-17行薄壳)。
3. **数据层零改动红线** — 16 个 form 用 useQuery/useMutation,QueryClient 单一配置(`Providers.tsx`),迁移只改视觉层。
4. **Hermes 路由位置一致** — `app/hermes/` 一等公民,Sidebar 顶部/独立组,复用 i18n 与 SSR/client 边界(与 backtest 页同构:server 壳取数 + client 主体)。
5. **Hermes 后端复用读面而非新建执行面** — `src/quant_system/api/routes/agent.py` 已有 candidates/detail/review/llm-config 等端点,其中 candidates/detail/review/provenance 可被 Hermes UI 复用。`POST /api/agent/tasks` 是旧 agent-studio 同步 LLM 任务面,且不返回 `poll_url`;MVP 不用它承载 Hermes runner,不在前端单独新增 `propose-strategy`。
6. **图表硬编码色值已与 token 漂移** — `CandlestickChart.tsx` 第24-33行 `CHART_COLORS.background=#111827` 而 @theme `--color-bg-surface=#151515`;`up=#00C896` 而 `--color-accent-success=#089981`。注释写「keep in sync with @theme」但实际已不同步。迁移期必须建 `lib/chartTokens.ts` 作单一真相源。
7. **factor-lab/agent-studio 下线涉及多文件真实引用点** — grep 命中 10 个前端文件 + 2 个后端 contract 测试硬断言。不能一次删净,必须先做 `/hermes` approval parity + factor evidence parity,再软下线导航/重定向,最后物理删除。
8. **逐页迁移靠 primitives token 间接收益** — `ui/primitives.tsx` 9 个原子全消费 token 不硬编码,改 token + primitives 两个文件约 60% 视觉级联到全站 22 页。未迁页面随时可停在中途发布。

### 关键分歧与裁决

| # | 分歧 | 裁决 |
|---|---|---|
| D1 | factor-lab/agent-studio 下线时机 | **三段式**:先建 `/hermes` 与 `/brief`,再做 approval parity + factor evidence parity,最后才删导航/加重定向。物理删除进入 P4 follow-on,不属于 3-4 周 MVP。 |
| D2 | 首页 dashboard 是否变晨报 | **先 `/brief` 试跑再替换首页**:dashboard 是第一印象最高风险,先在隔离路径跑通 B 暗色晨报,用户实屏确认后再替换 `app/page.tsx`(保留全部关键 API 调用不变,仅 JSX 重排)。 |
| D3 | B 暗色色温 | **暖灰近黑 + 象牙暖白**(`--color-paper-ink #14130F` / `--color-ink #EDE7DA`),近黑微暖不偏棕。仅 `/brief`、`/hermes`、报告/叙事块 opt-in,操作型页继续用冷黑/石墨 workbench。 |
| D4 | 总工期 | **MVP 切线 3-4 周**(token/nav/`/brief`/`/hermes` skeleton/一条核心迁移),期权集群/paper-trading/position-map 大件与物理删除延后按周迭代。 |
| D5 | 全局 shell 是否重建独立 layout | **否决独立 layout**:保持 `layout.tsx` 的 Sidebar+TopBar+SafetyStrip+main 共享外壳,晨报在主区内 max-width 1120px 版心,对话流在主区内三栏 grid。route group 物理隔离在硬编码固定布局下不可行。 |
| D6 | 是否引入 Playwright 视觉回归基线 | **启用但 scoped**:先对 6-8 个高风险/新迁移路由建稳定截图基线,必要时 mask 时间戳/动态图表;不一开始强制 22 页 golden wall。 |
| D7 | 是否引入 feature flag | **不引入**:语义 token + 页面级 opt-in 已能让新旧视觉并存,单人项目不需要额外切换层。 |
| D8 | B/C 卡片气质冲突 | **建 `EditorialFigure` 融合容器**:包裹 C 卡片时抑制 hover 上浮与 box-shadow,加暖灰 rule 外框 + 衬线 figcaption,让对话流卡片「印」在版面而非「浮」在版面。两套 up/down 按页面角色分套(操作型用终端色,阅读型用编辑色)。 |

---

## 已拍板的 11 个决策(Q1-Q11)

本节是 2026-07-08 多子智能体评审与后续实屏反馈后的执行裁决。后续 slice0-slice7 必须以本节为准;若与下方旧 P0-P4 任务代码块冲突,以本节为准。

- [x] **Q1【全局色温】** 全局 shell 采用 warm near-black,不是冷黑。当前已执行裁决:`--color-bg-base #12110E`,主内容区渲染 `rgb(18,17,14)`;sidebar rail 采用稍浅同主题色 `--color-bg-sidebar #1C1B20`,hover/active 使用 `--color-bg-sidebar-muted #25242A`。`/brief` 与 `/hermes` 继续使用 paper/editorial 语义 alias,但不得再把 sidebar 做成孤立冷蓝/冷灰。

- [x] **Q2【首页是否变晨报】** 每日晨报是目标方向,但 `/` 不在第一刀替换。先把 `/brief` 做成 direction B 栏目布局的一比一试跑页,标题定为「每日晨报」;实屏满意后再决定 `/` 是否变晨报入口。旧 dashboard 可保留为 `/dashboard` follow-on。

- [x] **Q3【Hermes 是否取代 dashboard 成主入口】** `/hermes` 是一等入口,但不抢先替代 `/`。若 `/brief` 后续升首页,则 `/` 是每日晨报入口,`/hermes` 是操作/对话/调度入口,旧 dashboard 退到 `/dashboard`。

- [x] **Q4【历史 factor run 记录处理】** 不隐藏历史 factor run。目标是 read-only generic run evidence/detail;在该视图完成前,保留旧 deep link。后续如迁到 `/hermes?runId=...`,必须显示 archived/provenance 状态,不能静默 308 到无上下文的 `/hermes`。

- [x] **Q5【Hermes 复用 agent.py 还是新建 hermes.py】** 复用 `agent.py` 的 candidates/detail/review/provenance 读面,但不扩展 `POST /api/agent/tasks` 为 Hermes runner,不前端单独添加 `propose-strategy`。若 UI 需要 Hermes timeline,只新增窄的 read-only `/api/hermes/timeline` 或 artifact 聚合端点。

- [x] **Q6【Hermes 流式传输方式】** MVP 采用 artifact-first + polling。只有当后端返回真实 job state + `poll_url` 时才新增 `lib/hermesJobs.ts`;当前 `/api/agent/tasks` 是同步端点,不能按异步 job 使用。SSE 后置,WebSocket 不做。

- [x] **Q7【总工期/执行节奏】** 当前执行方式从旧 P0-P4 线性阶段修订为 slice0-slice7:先确认现状与契约,再做 brief 持久化,再做 AI daily cache,再做 paper account DB mirror/reconciliation,最后才切 DB canonical 和继续前端全量迁移。3-4 周 MVP 只保证 `/brief` 可归档、`/hermes` 有入口、关键业务事实可回看;全量 redesign、options cluster、position-map、物理删除属于 follow-on。

- [x] **Q8【视觉回归基线】** 引入 Playwright screenshot,但 staged/scoped:先覆盖 `/brief`、shell/sidebar、`/hermes` 与 6-8 个稳定路由,对时间戳、动画、动态图表做 mask 或 reduced-motion。不把 22 页 golden master 作为第一阶段硬门禁;已迁页面才升级为硬 gate。当前已用浏览器确认 `/zh/brief` 主区/侧栏实际色值与 token 一致。

- [x] **Q9【strategies 与 Hermes 产出归一】** Hermes 生成 `.py` 不自动进入 strategies 目录。必须通过显式 Register/Promote/Gate 3 后,才在 strategies 目录中显示为 promoted strategy;目录可展示 `origin=Hermes`。

- [x] **Q10【每日晨报内容来源】** 晨报内容必须来自真实数据或已归档快照。Hermes 手记/一句话总结 MVP 使用确定性模板或已存在 Hermes artifact,不新增文本生成 API,不暗示真实 LLM 撰写。已归档 `/brief/{public_id}` 必须从 Postgres snapshot 读,不能随当天 API 变化漂移。

- [x] **Q11【操作型页面工作台子风格】** options/paper/settings/screener 等操作页保留更亮、更密集的 workbench 子风格。B/C 只覆盖阅读、报告、对话、artifact 体验;语义绿/红继续只用于真实数据状态。

### 新增数据持久化裁决(DP1-DP6)

- [x] **DP1【迁什么】** 迁 Postgres 的是可审计业务事实:root user、brief issues/snapshots/sources、AI HOT daily reports、paper account ledger/current positions/snapshots。研究 artifact、Parquet、DuckDB option cache、Prediction Market JSONL 暂不迁。
- [x] **DP2【root 用户】** 当前只有一个最大权限用户 `root`;新增 `app_users` 表先 seed root,所有新业务表挂 `owner_user_id`,避免以后多用户时全表重构。
- [x] **DP3【日报 URL】** `/brief` 是当天动态预览;`/brief/{public_id}` 是不可变归档,例如 `brf_20260708_7k3f2`。分享 token 只做 bearer secret,数据库只存 `sha256(token)`,支持 rotate/revoke。
- [x] **DP4【快照不可变】** `brief_snapshots` append-only,修订生成 `version + 1`;旧版本保留。前端渲染归档页只读 latest snapshot,不得现场重新聚合 API 替换历史。
- [x] **DP5【paper account】** `PaperAccount.ledger` 是事实源。先从 `account.json` 和 `archive/*.json` backfill,再 dual-write DB + 文件并 reconciliation,最后切 DB canonical。切换前不得删除文件备份。
- [x] **DP6【失败模式】** DB mirror 阶段数据库不可用时继续文件路径并记录 warning;DB canonical 阶段数据库不可用时所有 mutation fail closed,避免再次出现账户状态被局部文件重置污染。

---

## File Structure(本计划涉及的文件)

### 新建文件

| 路径 | 职责 |
|---|---|
| `app/globals.css`(扩展) | @theme 新增 editorial + hermes 两层 token;新增 `.font-editorial-*` 排版类;`@plugin "@tailwindcss/typography"` |
| `lib/navConfig.ts` | 单一导航数据源(Sidebar/TopBar 共享),含 icon 映射 |
| `lib/chartTokens.ts` | 导出 `terminalChartTheme`(兼容现有)与 `editorialChartTheme`(暖灰哑光)两套常量 + `readCssVar` 工具 |
| `lib/hermesJobs.ts`(后置) | 仅当后端提供真实 `poll_url` job contract 后再建。MVP 不用 `/api/agent/tasks` 伪造异步 Hermes job。 |
| `components/editorial/` 目录 | 8 个 B 暗色编辑组件:`Masthead`/`Lede`/`SectionHead`/`EditorialFigure`/`PosTable`/`NewsColumns`/`HermesQuote`/`ErrataLog` |
| `components/hermes/` 目录 | 11 个 C 对话流组件:`HermesOrb`/`UserBubble`/`HermesMessageCard`/`HermesExecCard`/`HermesArtifactCard`/`HermesArtifactBadge`/`HermesCodeCard`/`NewsCard`/`FillReceiptCard`/`SystemCard`/`Daybreak`/`ComposerDock` |
| `app/hermes/page.tsx` + `loading.tsx` | Hermes 页:server 壳 + client 主体(三栏 + ComposerDock) |
| `components/hermes/HermesConversation.tsx` | 静态对话流主体(mock 数据验证 C 视觉) |
| `app/brief/page.tsx` | B 暗色晨报试跑页(初期不替换首页),验证后再决定是否替换 `app/page.tsx` |
| `tests/e2e/visual.spec.ts` | scoped `toHaveScreenshot` 视觉基线:先覆盖 6-8 个稳定/高风险路由,后续逐页迁移逐页收紧。 |
| `tests/e2e/hermes.spec.ts` | Hermes 路由/对话流/dock/回流 E2E |

### 修改文件

| 路径 | 改动 |
|---|---|
| `app/layout.tsx` | 第2行新增 `Source_Serif_4` + `Noto_Serif_SC` via next/font/google 挂 `--font-serif` / `--font-serif-sc`;html className 第29行保留现有变量不动 |
| `components/Sidebar.tsx` | 第105-147行 navSections 改为从 `lib/navConfig.ts` 读;copy 加 `nav.hermes` 键 |
| `components/TopBar.tsx` | 第88-132行 mobileNavSections 改为从 `lib/navConfig.ts` 读;第192行 agent console 图标改指 `/hermes`;copy 加 `nav.hermes` 键 |
| `components/CandlestickChart.tsx` | 第24-33行 `CHART_COLORS` 改为从 props 读 `theme` 默认 `terminalChartTheme`,修复 `#111827`/`#151515` 与 `#00C896`/`#089981` 漂移 |
| `components/EquityComparisonChart.tsx` | 第28-36行 `COLORS` 同样改 theme 注入 |
| `components/FactorRunCharts.tsx` | 同理 theme 注入 |
| `next.config.ts` | parity 完成后再新增 factor-lab/agent-studio→`/hermes` 重定向;MVP 前期不做无上下文早跳转 |
| `app/page.tsx` | quick actions 可新增 `/hermes` 入口;不在 `/brief` 验证前替换首页主体 |
| `lib/dashboardRuns.ts` | factor kind 历史记录不得隐藏;generic run evidence/detail 完成前保留旧 deep link,完成后迁往 read-only evidence 或带 provenance 的 `/hermes?runId=...` |
| `lib/api.ts` | 如需新增 Hermes getter,只能 additive 复用 candidates/detail/review 或只读 artifact timeline;不得新增平台侧 strategy generation runner |
| `app/backtest/page.tsx` + `[runId]/page.tsx` | (P3)编辑式皮肤:EditorialHeader + ColumnRule 重排,保留 form hooks 零改动 |
| `app/data-explorer/page.tsx` | (P3)编辑式控件栏 + EditorialFigure 包裹图表 |
| `app/strategies/page.tsx` | (P2)一拆为二:保留目录(B 报告型),创建动作引导到 `/hermes` |
| `tests/test_frontend_topbar_navigation_contract.py` | (P1)只加 `/hermes` 断言,保留 factor-lab/agent-studio 断言;(P4 parity 后再移除旧断言) |
| `tests/test_frontend_terminal_surface_contract.py` | (P4)移除 agent-studio/page.tsx fragments 断言 |
| `tests/e2e/phase10-smoke.spec.ts` | (P4)routes 数组去 factor-lab/agent-studio,删相关测试 |
| `tests/e2e/run-detail-routes.spec.ts` | (P4)移除 factorRunId fixture 与 factor 断言 |

### 新建文件(2026-07-08 数据持久化增补)

| 路径 | 职责 |
|---|---|
| `scripts/sql/003_app_users_brief_ai_reports.sql` | 建 `quant_system.app_users`、`brief_issues`、`brief_snapshots`、`brief_snapshot_sources`、`ai_news_daily_reports`,并 seed `root` 用户 |
| `scripts/sql/004_paper_account_tables.sql` | 建 `paper_accounts`、`paper_account_ledger`、`paper_pending_orders`、`paper_positions_current`、`paper_position_snapshots`、`paper_position_snapshot_rows` |
| `src/quant_system/brief/models.py` | 定义 `BriefIssue`, `BriefSnapshot`, `BriefSourceRef`, `BriefGenerateRequest` 等 Pydantic/domain model |
| `src/quant_system/brief/repository.py` | Postgres 读写 brief issue/snapshot/sources;DB disabled 时返回 `None` 或明确 unavailable |
| `src/quant_system/brief/service.py` | 聚合当前 live facts 生成 deterministic brief payload;负责 `public_id` 与 token hash 生成 |
| `src/quant_system/api/schemas/brief.py` | FastAPI response/request schema: generate/by-id 已落地;latest/live 留给 Slice 7 |
| `src/quant_system/api/routes/brief.py` | 当前新增 `POST /api/brief/issues/generate` 与 `GET /api/brief/issues/{public_id}`;`/api/brief/live` 和 `/api/brief/issues/latest` 留给 Slice 7 |
| `src/quant_system/news/daily_report_repository.py` | `GET /api/news/aihot/daily` 成功后写 `ai_news_daily_reports`,失败时可读缓存并带 warning |
| `src/quant_system/execution/account_repository.py` | 抽象 paper account repository contract,把 File/Postgres/DualWrite 三种实现的接口固定下来 |
| `src/quant_system/execution/account_repository_factory.py` | API 与 CLI 共用的 paper account repository factory;Slice 5 中 `mirror` 双写,`canonical` 暂回落文件并记录 warning |
| `src/quant_system/execution/account_postgres_repository.py` | Postgres paper account mirror/canonical 实现,按 ledger 写入并物化 current positions |
| `src/quant_system/execution/account_dual_write_repository.py` | mirror 阶段先写文件、再 best-effort 写 DB;DB 失败不改变 response,但记录 warning log |
| `src/quant_system/execution/account_backfill.py` | 一次性 backfill: `account.json` + `archive/*.json` → account/ledger/current positions/snapshots |
| `src/frontend/app/brief/[publicId]/page.tsx` | 渲染已归档每日晨报 `/brief/{public_id}` |
| `src/frontend/lib/briefArchive.ts` | 前端归档 brief getter 类型与 normalize 工具,复用 `lib/api.ts` 的 fetch 模式 |
| `tests/test_api_brief_persistence.py` | 后端 brief 归档/读取/不可变版本测试 |
| `tests/test_news_daily_report_repository.py` | AI HOT daily report cache 写入/读取/fallback 测试 |
| `tests/test_paper_account_postgres_repository.py` | paper account DB mirror/backfill/reconciliation 测试 |
| `src/frontend/lib/briefArchive.test.ts` | 前端归档 payload 类型/URL getter contract 测试 |
| `src/frontend/tests/e2e/brief-archive.spec.ts` | `/brief` → generate/read latest → `/brief/{public_id}` 稳定渲染 E2E |

### 修改文件(2026-07-08 数据持久化增补)

| 路径 | 改动 |
|---|---|
| `src/quant_system/storage/database.py` | 继续按 `scripts/sql/*.sql` 字典序执行 migration;新增 migration 必须幂等 |
| `src/quant_system/api/server.py` | include 新的 `brief.router` |
| `src/quant_system/api/routes/news.py` | `aihot_daily` 成功时写 `ai_news_daily_reports`;upstream 失败时尝试按 date 读缓存 |
| `src/quant_system/api/routes/paper.py` | 已把 account mutation/read helper 接到共用 `PaperAccountRepository` factory;mirror 阶段外部 response 不变 |
| `src/quant_system/cli.py` | paper account rebalance/show 与 strategy operations 调度路径共用 repository factory,避免 CLI 写入绕过 mirror |
| `src/quant_system/api/schemas/paper.py` | 如需暴露 `storage_mode` / `stale` / `reconciliation` warning,只 additive 新增 nullable 字段 |
| `src/frontend/app/brief/page.tsx` | `/brief` 保持当天动态预览,新增归档入口/链接;真实数据缺失时显示 stale/source warning |
| `src/frontend/lib/api.ts` | 新增 read-only brief archive getter: latest/byPublicId/generate;不改现有 getter 语义 |
| `tests/test_api_response_models.py` | 加 brief endpoints schema contract;paper response 字段 additive 更新 |
| `src/frontend/lib/design-tokens.test.ts` | 锁定 `--color-bg-base #12110E`, `--color-bg-sidebar #1C1B20`, `--color-bg-sidebar-muted #25242A` |

### 删除文件(P4)

| 路径 |
|---|
| `app/factor-lab/` 与 `app/factor-lab/[runId]/` 目录 |
| `app/agent-studio/` 目录 |
| `components/forms/FactorLabControls.tsx` / `FactorLabDashboard.tsx` / `FactorRunForm.tsx` / `AgentTaskForm.tsx`(仅在 Hermes/evidence parity 完成后删除或迁移) |
| `components/FactorRunCharts.tsx`(仅在图表能力已迁入 generic evidence view 后删除) |
| `lib/factorLabHandoff.ts` + `lib/factorLabHandoff.test.ts` |

---

## 2026-07-08 权威执行节奏(Slice0-Slice7)

> 本节是当前执行路线。下方旧 P0-P4 保留为前端设计 backlog 与历史细节,但真正开工按 slice0-slice7 推进。每个 slice 完成后必须跑本节列出的验证命令并单独提交;共享文件(`globals.css`, `lib/api.ts`, `paper.py`, `settings.py`)不得并行写。

### Slice 0 — 现状锁定与计划同步

**Goal:** 把已做过的 `/brief`、全局色温、paper account 只读接口、AAPL 排查结论写入契约,避免后续 worker 按旧计划回退。

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`
- Modify: `src/frontend/lib/design-tokens.test.ts`
- Read-only verify: `data/api_runs/paper_account/default/account.json`, `data/api_runs/paper_account/default/archive/*.json`

- [ ] **Step 1: 锁定当前全局色温测试**

确保 `src/frontend/lib/design-tokens.test.ts` 包含以下断言:

```typescript
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf-8");

describe("editorial design tokens", () => {
  it("defines current warm shell and sidebar rail tokens", () => {
    expect(globalsCss).toContain("--color-bg-base: #12110E;");
    expect(globalsCss).toContain("--color-bg-sidebar: #1C1B20;");
    expect(globalsCss).toContain("--color-bg-sidebar-muted: #25242A;");
    expect(globalsCss).toContain("--color-paper-ink: var(--color-bg-base);");
  });
});
```

- [ ] **Step 2: 运行前端契约**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
npx vitest run lib/design-tokens.test.ts
npm run type-check
npm run lint
```

Expected:
```text
Test Files  1 passed
tsc --noEmit exits 0
eslint exits 0
```

- [ ] **Step 3: 记录 AAPL 现状为迁移输入,不修改账户文件**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
jq '.positions.AAPL, .ledger[-3:]' data/api_runs/paper_account/default/account.json
ls data/api_runs/paper_account/default/archive/account-*.json | tail -5
```

Expected:
```text
current account shows the active mutable file state
archive files still contain historical snapshots used for backfill
```

- [ ] **Step 4: 提交计划同步**

```bash
cd /Users/sunyibo/programs/ai-quant-platform
git add docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md src/frontend/lib/design-tokens.test.ts
git commit -m "docs(frontend): align Hermes redesign plan with persistence slices"
```

### Slice 1 — Brief/AI schema migration + root seed

**Goal:** 建 Postgres 表,让每日晨报和 AI HOT daily report 有稳定、可查询、可回看的存储面。

**Status 2026-07-08:** Slice 1 schema foundation 已完成,但当前 shell 未配置
`QS_TEST_DATABASE_URL`,所以 PostgreSQL integration tests 只做了 opt-in skip,未对用户
当前 Docker DB 执行 live migration。实际 SQL 以
`scripts/sql/003_app_users_brief_ai_reports.sql` 为准;下方保留执行摘要,不再以内联
SQL 草稿作为权威。

**Files:**
- Created: `scripts/sql/003_app_users_brief_ai_reports.sql`
- Created: `tests/test_api_brief_persistence.py`
- Deferred: `tests/test_news_daily_report_repository.py` belongs to the AI daily
  repository/cache wiring slice, not the schema-only foundation.

- [x] **Step 1: 写失败测试 — migration 后应存在 root 与 brief/AI 表**

`tests/test_api_brief_persistence.py` now asserts the presence of
`app_users`, `brief_issues`, `brief_snapshots`, `brief_snapshot_sources`,
`ai_news_daily_reports`, the fixed `root` seed, owner-scoped keys, idempotent
DDL, and the composite latest-snapshot foreign key.

- [x] **Step 2: 创建 migration**

`scripts/sql/003_app_users_brief_ai_reports.sql` now:

- seeds fixed root user `00000000-0000-0000-0000-000000000001`
- guards against an existing `root` username with a different UUID
- creates append-only brief issue/snapshot/source tables
- keeps `brief_issues.latest_snapshot_id` constrained to snapshots belonging to
  the same `issue_id`
- creates owner-scoped `ai_news_daily_reports`
- upgrades the old `(provider, report_date)` daily-report primary key shape
  without dropping legacy rows

- [x] **Step 3: 运行测试确认通过**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
./.venv/bin/pytest tests/test_api_brief_persistence.py tests/test_database.py tests/test_database_connection.py tests/test_runs_repository_postgres.py -q -rs
./.venv/bin/ruff check tests/test_api_brief_persistence.py
git diff --check -- scripts/sql/003_app_users_brief_ai_reports.sql tests/test_api_brief_persistence.py
```

Expected:
```text
4 passed, 3 skipped when QS_TEST_DATABASE_URL is unset
ruff exits 0
diff check exits 0
```

- [ ] **Step 4: 如果 Docker DB 已启用,执行迁移并核对表**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
python - <<'PY'
from quant_system.config.settings import load_settings
from quant_system.storage.database import get_database, run_migrations

settings = load_settings()
database = get_database(settings)
assert database is not None, "QS_DATABASE_ENABLED=true and QS_DATABASE_URL are required"
run_migrations(database)
with database.connect() as conn:
    rows = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='quant_system'
          AND table_name IN ('app_users','brief_issues','brief_snapshots','brief_snapshot_sources','ai_news_daily_reports')
        ORDER BY table_name
    """).fetchall()
print(rows)
PY
```

Expected:
```text
[('ai_news_daily_reports',), ('app_users',), ('brief_issues',), ('brief_snapshot_sources',), ('brief_snapshots',)]
```

- [ ] **Step 5: 提交**

```bash
git add scripts/sql/003_app_users_brief_ai_reports.sql tests/test_api_brief_persistence.py
git commit -m "feat(db): add brief and AI daily report persistence schema"
```

### Slice 2 — Brief repository/API + `/brief/{public_id}`

**Goal:** 让 `/brief` 可以生成当天归档快照,并让 `/brief/{public_id}` 稳定读取已归档内容。

**Status 2026-07-08:** Slice 2 已完成后端 repository/API 与前端归档页最小闭环。默认
测试环境数据库关闭时不会伪造归档;真实归档只从 Postgres snapshot 读取。当前已实现
`POST /api/brief/issues/generate` 与 `GET /api/brief/issues/{public_id}`;`/api/brief/live`、
`/api/brief/issues/latest` 与 `/brief` 上的生成入口仍留给 Slice 7。

**Files:**
- Created: `src/quant_system/brief/models.py`
- Created: `src/quant_system/brief/repository.py`
- Created: `src/quant_system/brief/service.py`
- Created: `src/quant_system/api/schemas/brief.py`
- Created: `src/quant_system/api/routes/brief.py`
- Modified: `src/quant_system/api/server.py`
- Modified: `src/frontend/lib/api.ts`
- Created: `src/frontend/lib/briefArchive.ts`
- Created: `src/frontend/app/brief/[publicId]/page.tsx`
- Updated: `tests/test_api_brief_persistence.py`
- Updated: `tests/test_api_response_models.py`
- Created: `src/frontend/lib/briefArchive.test.ts`

- [x] **Step 1: 写失败测试 — DB unavailable 不伪造归档;PG opt-in 才生成 issue**

在 `tests/test_api_brief_persistence.py` 追加:

```python
def test_generate_brief_issue_requires_database_when_disabled(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/brief/issues/generate",
        json={"issue_date": "2026-07-08", "locale": "zh"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


@pytest.mark.pg
def test_generate_brief_issue_returns_stable_public_id(postgres_client) -> None:
    response = postgres_client.post(
        "/api/brief/issues/generate",
        json={"issue_date": "2026-07-08", "locale": "zh"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["issue"]["public_id"].startswith("brf_20260708_")
    assert body["snapshot"]["version"] == 1
    public_id = body["issue"]["public_id"]

    again = postgres_client.get(f"/api/brief/issues/{public_id}")
    assert again.status_code == 200
    assert again.json()["issue"]["public_id"] == public_id
    assert again.json()["snapshot"]["payload"]["title"] == "每日晨报"
```

实现时不得在 DB disabled 路径用进程内 dict 或文件伪造归档。`/brief/{public_id}` 的
历史快照必须来自 Postgres snapshot;动态 `/brief` 预览可继续聚合 live facts。

- [x] **Step 2: 写前端失败测试 — getter 路径正确**

创建 `src/frontend/lib/briefArchive.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { buildBriefIssuePath } from "@/lib/briefArchive";

describe("brief archive API paths", () => {
  it("builds stable public-id API path", () => {
    expect(buildBriefIssuePath("brf_20260708_7k3f2")).toBe("/api/brief/issues/brf_20260708_7k3f2");
  });
});
```

- [x] **Step 3: 运行测试确认失败**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
pytest tests/test_api_brief_persistence.py::test_generate_brief_issue_returns_stable_public_id -q
cd src/frontend && npx vitest run lib/briefArchive.test.ts
```

Expected:
```text
FastAPI route /api/brief/issues/generate not found
Cannot find module '@/lib/briefArchive'
```

- [x] **Step 4: 实现最小 API contract**

实现 `src/quant_system/api/schemas/brief.py` 的 response shape:

```python
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BriefGenerateRequest(BaseModel):
    issue_date: str | None = None
    locale: str = "zh"


class BriefIssueResponse(BaseModel):
    issue_id: str
    public_id: str
    issue_date: str
    locale: str
    status: str = "published"


class BriefSnapshotResponse(BaseModel):
    snapshot_id: str
    version: int
    payload: dict[str, Any] = Field(default_factory=dict)
    source_watermark: dict[str, Any] = Field(default_factory=dict)


class BriefIssueEnvelope(BaseModel):
    issue: BriefIssueResponse
    snapshot: BriefSnapshotResponse
    warnings: list[str] = Field(default_factory=list)
```

实现 `src/frontend/lib/briefArchive.ts` 的 path helper:

```typescript
export function buildBriefIssuePath(publicId: string): string {
  return `/api/brief/issues/${encodeURIComponent(publicId)}`;
}
```

- [x] **Step 5: 实现 repository/service/route**

`BriefService.generate()` 的最小 payload 必须包含:

```python
payload = {
    "title": "每日晨报" if locale == "zh" else "Daily Brief",
    "issue_date": issue_date.isoformat(),
    "sections": {
        "market": [],
        "ai_news": [],
        "paper_equity": [],
        "hermes_log": [],
    },
}
```

`BriefRepository` 必须在一个 DB transaction 内:
1. upsert/select `(owner_user_id, issue_date, locale)` 的 `brief_issues`
2. 插入 `brief_snapshots(version = max(version)+1)`
3. 更新 `brief_issues.latest_snapshot_id`
4. 返回 issue + snapshot

`src/quant_system/api/server.py` 必须 include:

```python
from quant_system.api.routes import brief

app.include_router(brief.router, prefix="/api", tags=["brief"])
```

- [x] **Step 6: 实现归档页**

`src/frontend/app/brief/[publicId]/page.tsx` 必须使用 server component 读取:

```typescript
import { buildBriefIssuePath } from "@/lib/briefArchive";
import { apiGet } from "@/lib/api";

type Props = { params: Promise<{ publicId: string }> };

export default async function ArchivedBriefPage({ params }: Props) {
  const { publicId } = await params;
  const issue = await apiGet(buildBriefIssuePath(publicId));
  return (
    <main className="min-h-screen bg-paper-ink text-ink">
      <article className="mx-auto max-w-editorial-column px-6 py-10">
        <p className="font-label-caps text-ink-secondary">{issue.issue.issue_date}</p>
        <h1 className="font-editorial-display">{issue.snapshot.payload.title}</h1>
      </article>
    </main>
  );
}
```

- [x] **Step 7: 运行验证**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
./.venv/bin/pytest tests/test_api_brief_persistence.py tests/test_api_response_models.py -q -rs
QS_TEST_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp' ./.venv/bin/pytest tests/test_api_brief_persistence.py -q -m pg -rs
./.venv/bin/ruff check src/quant_system/brief src/quant_system/api/schemas/brief.py src/quant_system/api/routes/brief.py tests/test_api_brief_persistence.py tests/test_api_response_models.py
cd src/frontend
npx vitest run lib/briefArchive.test.ts
npm run type-check
npm run lint
```

Expected:
```text
backend target: 16 passed, 4 skipped when QS_TEST_DATABASE_URL is unset
PostgreSQL opt-in target against quantplatform_codex_tmp: 4 passed
backend ruff exits 0
frontend briefArchive: 6 passed
frontend type-check/lint exit 0
```

- [ ] **Step 8: 提交**

```bash
git add src/quant_system/brief src/quant_system/api/schemas/brief.py src/quant_system/api/routes/brief.py src/quant_system/api/server.py tests/test_api_brief_persistence.py tests/test_api_response_models.py src/frontend/lib/api.ts src/frontend/lib/briefArchive.ts src/frontend/lib/briefArchive.test.ts src/frontend/app/brief/[publicId]/page.tsx
git commit -m "feat(brief): persist and render archived daily briefs"
```

### Slice 3 — AI HOT daily report cache

**Goal:** `GET /api/news/aihot/daily` 成功时写入 `ai_news_daily_reports`,失败时按 date 返回缓存并带 warning,让每日晨报引用的 AI 摘要可回放。

**Status 2026-07-08:** Slice 3 已完成。`/api/news/aihot/daily` live 成功路径会
best-effort 写入 owner-scoped `ai_news_daily_reports`;上游失败时按请求日期或 UTC 当天
读取缓存,命中则返回 200 并带 cache warning、上游错误和 provider beta warning。缓存
写入会把 top-level `window_start/window_end` 合并进 raw,确保当前 schema 无专列时仍可
回放窗口字段。

**Files:**
- Created: `src/quant_system/news/daily_report_repository.py`
- Modified: `src/quant_system/api/routes/news.py`
- Created: `tests/test_news_daily_report_repository.py`
- Updated: `tests/test_api_news_aihot.py`

- [x] **Step 1: 写失败测试**

`tests/test_news_daily_report_repository.py`:

```python
from __future__ import annotations

from quant_system.news.daily_report_repository import daily_report_cache_warning


def test_daily_report_cache_warning_text_is_stable() -> None:
    assert daily_report_cache_warning("2026-07-08") == "Using cached AI HOT daily report for 2026-07-08 from the local database."
```

- [x] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_news_daily_report_repository.py -q
```

Expected:
```text
ModuleNotFoundError: quant_system.news.daily_report_repository
```

- [x] **Step 3: 创建 repository 函数 contract**

`src/quant_system/news/daily_report_repository.py` 必须暴露:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from quant_system.storage.database import SCHEMA, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings


PROVIDER = "aihot"


def daily_report_cache_warning(report_date: str) -> str:
    return f"Using cached AI HOT daily report for {report_date} from the local database."


def cache_aihot_daily_report(payload: dict[str, Any], *, settings: Settings) -> None:
    """Best-effort upsert into quant_system.ai_news_daily_reports."""
    database = get_database(settings)
    if database is None:
        return
    report_date = payload["date"]
    with database.connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.ai_news_daily_reports
                (provider, report_date, fetched_at, generated_at, lead, sections, flashes, warnings, raw, updated_at)
            VALUES ('aihot', %s::date, %s::timestamptz, %s::timestamptz, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (provider, report_date) DO UPDATE
            SET fetched_at = EXCLUDED.fetched_at,
                generated_at = EXCLUDED.generated_at,
                lead = EXCLUDED.lead,
                sections = EXCLUDED.sections,
                flashes = EXCLUDED.flashes,
                warnings = EXCLUDED.warnings,
                raw = EXCLUDED.raw,
                updated_at = now()
            """,
            (
                report_date,
                payload.get("fetched_at"),
                payload.get("generated_at"),
                payload.get("lead", {}),
                payload.get("sections", []),
                payload.get("flashes", []),
                payload.get("warnings", []),
                payload.get("raw", {}),
            ),
        )


def load_cached_aihot_daily_report(*, date: str, settings: Settings) -> dict[str, Any] | None:
    """Return cached daily report payload or None."""
    database = get_database(settings)
    if database is None:
        return None
    with database.connect() as conn:
        row = conn.execute(
            f"""
            SELECT report_date::text, fetched_at::text, generated_at::text, lead, sections, flashes, warnings, raw
            FROM {SCHEMA}.ai_news_daily_reports
            WHERE provider='aihot' AND report_date=%s::date
            """,
            (date,),
        ).fetchone()
    if row is None:
        return None
    report_date, fetched_at, generated_at, lead, sections, flashes, warnings, raw = row
    return {
        "provider": "aihot",
        "date": report_date,
        "fetched_at": fetched_at,
        "generated_at": generated_at,
        "lead": lead,
        "sections": sections,
        "flashes": flashes,
        "warnings": [*warnings, daily_report_cache_warning(report_date)],
        "raw": raw,
    }
```

- [x] **Step 4: 修改 news route**

`src/quant_system/api/routes/news.py` 的 `aihot_daily` 成功路径:

```python
payload = _daily_payload(daily)
cache_aihot_daily_report(payload, settings=settings)
return payload
```

异常路径:

```python
cached = load_cached_aihot_daily_report(date=date or date_today, settings=settings)
if cached is not None:
    return cached
raise
```

- [x] **Step 5: 运行验证**

Run:
```bash
./.venv/bin/pytest tests/test_news_daily_report_repository.py tests/test_api_news_aihot.py -q
./.venv/bin/ruff check src/quant_system/news/daily_report_repository.py src/quant_system/api/routes/news.py tests/test_news_daily_report_repository.py tests/test_api_news_aihot.py
```

Expected:
```text
16 passed
ruff exits 0
```

- [ ] **Step 6: 提交**

```bash
git add src/quant_system/news/daily_report_repository.py src/quant_system/api/routes/news.py tests/test_news_daily_report_repository.py
git commit -m "feat(news): cache AI HOT daily reports for brief archives"
```

### Slice 4 — Paper account Postgres schema + backfill

**Goal:** 把 `account.json`/archive 中的 ledger 与 current positions 导入 DB mirror,但不改变当前 API 读写路径。

**Status 2026-07-09:** Slice 4 已完成 schema + explicit one-file backfill
foundation。当前仍不改变 API read/write/mutation path；`account.json` 仍是事实源。
`backfill_account_file(account_path, settings=..., source="account_json")` 只读取调用方提供的
JSON 文件并写入 Postgres mirror。ledger mirror 采用事务内整表替换,避免 reset/修正 JSON 后
遗留旧 entry 或 seq 冲突；pending/current positions 是 current-state mirror；position
snapshots 是 append-only audit points。Archive 批量扫描/backfill runner 与 API dual-write
留给 Slice 5+。

**Files:**
- Create: `scripts/sql/004_paper_account_tables.sql`
- Create: `src/quant_system/execution/account_backfill.py`
- Test: `tests/test_paper_account_postgres_repository.py`

- [x] **Step 1: 写失败测试 — migration 必须包含 ledger 与 current positions**

```python
from pathlib import Path


def test_paper_account_migration_defines_ledger_tables() -> None:
    sql = Path("scripts/sql/004_paper_account_tables.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS quant_system.paper_accounts" in sql
    assert "CREATE TABLE IF NOT EXISTS quant_system.paper_account_ledger" in sql
    assert "CREATE TABLE IF NOT EXISTS quant_system.paper_positions_current" in sql
    assert "CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshots" in sql
    assert "CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshot_rows" in sql
```

- [x] **Step 2: 创建 migration**

`scripts/sql/004_paper_account_tables.sql`:

```sql
CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.paper_accounts (
    account_id     TEXT PRIMARY KEY,
    owner_user_id  UUID NOT NULL REFERENCES quant_system.app_users(id),
    base_currency  TEXT NOT NULL DEFAULT 'USD',
    initial_cash   DOUBLE PRECISION NOT NULL,
    cash           DOUBLE PRECISION NOT NULL,
    realized_pnl   DOUBLE PRECISION NOT NULL DEFAULT 0,
    kill_switch    BOOLEAN NOT NULL DEFAULT FALSE,
    version        BIGINT NOT NULL DEFAULT 1,
    raw            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS quant_system.paper_account_ledger (
    account_id          TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    entry_id            TEXT NOT NULL,
    seq                 BIGINT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    kind                TEXT NOT NULL,
    source              TEXT NOT NULL,
    symbol              TEXT,
    side                TEXT,
    quantity            DOUBLE PRECISION,
    price               DOUBLE PRECISION,
    gross_value         DOUBLE PRECISION,
    commission          DOUBLE PRECISION NOT NULL DEFAULT 0,
    price_kind          TEXT,
    realized_pnl_delta  DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash_after          DOUBLE PRECISION NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    raw                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (account_id, entry_id),
    UNIQUE (account_id, seq)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_pending_orders (
    account_id   TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    order_id     TEXT NOT NULL,
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, order_id)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_positions_current (
    account_id        TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    symbol            TEXT NOT NULL,
    quantity          DOUBLE PRECISION NOT NULL,
    avg_cost          DOUBLE PRECISION NOT NULL,
    source_quantity   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshots (
    snapshot_id     UUID PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES quant_system.paper_accounts(account_id) ON DELETE CASCADE,
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    equity          DOUBLE PRECISION,
    cash            DOUBLE PRECISION NOT NULL,
    source          TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS quant_system.paper_position_snapshot_rows (
    snapshot_id     UUID NOT NULL REFERENCES quant_system.paper_position_snapshots(snapshot_id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    avg_cost        DOUBLE PRECISION NOT NULL,
    last_price      DOUBLE PRECISION,
    market_value    DOUBLE PRECISION,
    unrealized_pnl  DOUBLE PRECISION,
    source_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_paper_ledger_account_seq
    ON quant_system.paper_account_ledger (account_id, seq);

CREATE INDEX IF NOT EXISTS idx_paper_snapshots_account_time
    ON quant_system.paper_position_snapshots (account_id, snapshot_at DESC);
```

- [x] **Step 3: 实现 backfill 只读导入**

`src/quant_system/execution/account_backfill.py` 必须暴露:

```python
def backfill_account_file(account_path: Path, *, settings: Settings, source: str = "account_json") -> dict[str, int]:
    """Load a PaperAccount JSON file and mirror account, ledger, pending orders, and current positions into Postgres."""
```

返回值 contract:

```python
{"accounts": 1, "ledger_entries": len(account.ledger), "positions": len(account.positions), "pending_orders": len(account.pending_orders)}
```

- [x] **Step 4: 运行验证**

Run:
```bash
pytest tests/test_paper_account_postgres_repository.py::test_paper_account_migration_defines_ledger_tables -q
ruff check src/quant_system/execution/account_backfill.py tests/test_paper_account_postgres_repository.py
```

Expected:
```text
tests pass
ruff exits 0
```

Actual verification:
```bash
./.venv/bin/pytest tests/test_paper_account_postgres_repository.py -q -rs
QS_TEST_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp' ./.venv/bin/pytest tests/test_paper_account_postgres_repository.py -q -m pg -rs
./.venv/bin/ruff check src/quant_system/execution/account_backfill.py tests/test_paper_account_postgres_repository.py
git diff --cached --check
```

Result:
```text
5 passed, 2 skipped
2 passed
All checks passed
diff check passed
```

- [ ] **Step 5: 提交**

```bash
git add scripts/sql/004_paper_account_tables.sql src/quant_system/execution/account_backfill.py tests/test_paper_account_postgres_repository.py
git commit -m "feat(paper): add Postgres schema and backfill path for paper account ledger"
```

### Slice 5 — Paper account dual-write mirror + reconciliation

**Goal:** API mutation 仍以文件为事实源,同时写 DB mirror 并暴露 reconciliation 差异,不改变外部 response contract。

**Status 2026-07-09:** 已完成。实现时根据 code review 将 factory 下沉到
`execution/account_repository_factory.py`,使 API 与 CLI/调度账户写路径共用同一 file/mirror
选择逻辑。Slice 5 中 `canonical` 是保留配置:settings 可解析该字面量,但 factory 暂回落
`PaperAccountStorage` 并记录 warning,避免在 Slice 6 fail-closed contract 落地前把合法配置导向
`PostgresPaperAccountRepository.load/load_or_open/reset` 的 `NotImplementedError`。

**Files:**
- Create: `src/quant_system/execution/account_repository.py`
- Create: `src/quant_system/execution/account_repository_factory.py`
- Create: `src/quant_system/execution/account_postgres_repository.py`
- Create: `src/quant_system/execution/account_dual_write_repository.py`
- Modify: `src/quant_system/config/settings.py`
- Modify: `src/quant_system/api/routes/paper.py`
- Modify: `src/quant_system/cli.py`
- Modify: `src/quant_system/execution/account_backfill.py`
- Test: `tests/test_paper_account_postgres_repository.py`
- Test: `tests/test_api_paper_account.py`
- Test: `tests/test_cli.py`

- [x] **Step 1: 写失败测试 — settings 有 mirror/canonical 模式**

```python
from quant_system.config.settings import PaperAccountSettings


def test_paper_account_settings_expose_db_mode() -> None:
    settings = PaperAccountSettings(db_mode="mirror")
    assert settings.db_mode == "mirror"
```

- [x] **Step 2: 修改 settings**

在 `PaperAccountSettings` 加:

```python
db_mode: Literal["file", "mirror", "canonical"] = "file"
```

并在文件顶部 typing import 加 `Literal`。

- [x] **Step 3: 定义 repository contract**

`account_repository.py`:

```python
from __future__ import annotations

from typing import Protocol

from quant_system.execution.account import PaperAccount


class PaperAccountRepository(Protocol):
    def load(self) -> PaperAccount | None: ...
    def load_or_open(self, *, initial_cash: float) -> PaperAccount: ...
    def save(self, account: PaperAccount, **kwargs) -> object: ...
    def reset(self, *, initial_cash: float) -> PaperAccount: ...
```

- [x] **Step 4: 实现 dual-write wrapper**

`account_dual_write_repository.py` 的 save contract:

```python
class DualWritePaperAccountRepository:
    def save(self, account: PaperAccount, **kwargs) -> object:
        file_result = self.file_repo.save(account, **kwargs)
        try:
            self.postgres_repo.save(account, **kwargs)
        except Exception as exc:
            self.last_warning = f"paper account DB mirror write skipped: {exc}"
        return file_result
```

- [x] **Step 5: paper.py 与 CLI 使用共用 factory,不改 route response**

`_account_storage(api_runs_dir)` 保留;新增 `_account_repository(api_runs_dir, settings)` 并调用
`build_paper_account_repository(...)`:

```python
def build_paper_account_repository(api_runs_dir, *, settings, account_id="default") -> PaperAccountRepository:
    file_repo = PaperAccountStorage(api_runs_dir, account_id=account_id)
    if settings.paper_account.db_mode == "mirror":
        postgres_repo = PostgresPaperAccountRepository(settings=settings, account_id=account_id)
        return DualWritePaperAccountRepository(file_repo=file_repo, postgres_repo=postgres_repo)
    return file_repo
```

Review 后追加约束:
- API 与 CLI/调度写路径必须共用 factory,避免 `quant-system paper rebalance` 或
  `paper strategies execute-pending` 只写文件导致 DB mirror 立刻 stale。
- DB mirror 失败只记录 `last_warning` 与 warning log,不改变外部 response contract。
- 在线 mirror 的 position snapshot 使用 API/runner 当时传入的 quotes;一次性 backfill 继续默认用
  account avg cost。
- `canonical` 的真实 DB read/reset/fail-closed 仍属于 Slice 6。

- [x] **Step 6: 运行验证**

Run:
```bash
./.venv/bin/pytest tests/test_settings.py tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py -q
PYTHONPATH=. ./.venv/bin/pytest tests/test_cli.py tests/test_api_paper_strategy_sleeves.py -q
./.venv/bin/ruff check src/quant_system/config/settings.py src/quant_system/api/routes/paper.py src/quant_system/cli.py src/quant_system/execution/account_repository.py src/quant_system/execution/account_repository_factory.py src/quant_system/execution/account_postgres_repository.py src/quant_system/execution/account_dual_write_repository.py src/quant_system/execution/account_backfill.py tests/test_settings.py tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py tests/test_cli.py
git diff --check
```

Expected:
```text
52 passed, 2 skipped
35 passed
ruff exits 0
diff check exits 0
```

- [ ] **Step 7: 提交**

```bash
git add src/quant_system/config/settings.py src/quant_system/api/routes/paper.py src/quant_system/cli.py src/quant_system/execution/account_repository.py src/quant_system/execution/account_repository_factory.py src/quant_system/execution/account_postgres_repository.py src/quant_system/execution/account_dual_write_repository.py src/quant_system/execution/account_backfill.py tests/test_settings.py tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py tests/test_cli.py
git commit -m "feat(paper): mirror paper account mutations to Postgres"
```

### Slice 6 — Paper account DB canonical + fail-closed mutation

**Goal:** 在 reconciliation 连续通过后,把 paper account 的事实源切到 DB;文件只做 export/backup。

**Slice 6 notes from Slice 5 review:**
- `PostgresPaperAccountRepository.load/load_or_open/reset` 必须成为 DB authoritative,且 DB 不可用时 mutation fail closed。
- response 字段只能 additive (`storage_mode`/`stale`/`warnings`),旧前端必须可忽略。
- 切换前定义 reconciliation criteria:ledger count/seq/current positions/pending orders/snapshot freshness 必须连续通过。
- 决定 CLI `quant-system paper rebalance` 是否也要持久化 rebalance 当次 prices。Slice 5 已覆盖 mirror,
  但该 CLI save 未传 prices,DB snapshot 会退回 avg_cost；API 与 strategy operations runner 的在线保存已传入
  quotes。

**Files:**
- Modify: `src/quant_system/execution/account_postgres_repository.py`
- Modify: `src/quant_system/api/routes/paper.py`
- Modify: `src/quant_system/api/schemas/paper.py`
- Test: `tests/test_paper_account_postgres_repository.py`
- Test: `tests/test_api_paper_account.py`

- [x] **Step 1: 写失败测试 — canonical 模式 DB 不可用时 mutation fail closed**

```python
def test_paper_account_canonical_mode_rejects_mutation_when_db_unavailable(client, monkeypatch) -> None:
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    monkeypatch.setenv("QS_DATABASE_ENABLED", "true")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/invalid")
    response = client.post("/api/paper/account/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 1})
    assert response.status_code in {409, 503}
    assert response.json()["detail"]["code"] == "paper_account_database_unavailable"
```

- [x] **Step 2: 实现 canonical guard**

在 `paper.py` mutation routes 调用 repository 前加:

```python
if settings.paper_account.db_mode == "canonical" and not repository.available_for_mutation():
    raise HTTPException(
        status_code=503,
        detail={
            "code": "paper_account_database_unavailable",
            "message": "Paper account database is unavailable; mutations are disabled in canonical mode.",
        },
    )
```

- [x] **Step 3: response additive 字段**

`PaperAccountResponse` 可新增 nullable:

```python
storage_mode: Literal["file", "mirror", "canonical"] | None = None
stale: bool = False
warnings: list[str] = Field(default_factory=list)
```

旧前端忽略新字段,不破坏 contract。

- [x] **Step 4: 运行验证**

Run:
```bash
pytest tests/test_api_paper_account.py tests/test_api_response_models.py tests/test_paper_account_postgres_repository.py -q
ruff check src/quant_system/api/routes/paper.py src/quant_system/api/schemas/paper.py src/quant_system/execution/account_postgres_repository.py
```

Expected:
```text
tests pass
ruff exits 0
```

- [x] **Step 5: 提交**

```bash
git add src/quant_system/api/routes/paper.py src/quant_system/api/schemas/paper.py src/quant_system/execution/account_postgres_repository.py src/quant_system/execution/account_repository_factory.py src/quant_system/execution/account_repository.py src/quant_system/execution/account_dual_write_repository.py src/quant_system/execution/account_storage.py tests/test_api_paper_account.py tests/test_api_response_models.py tests/test_paper_account_postgres_repository.py
git commit -m "feat(paper): make Postgres canonical mode fail closed"
```

### Slice 7 — Frontend archived brief integration + visual baseline

**Goal:** 让用户从 `/brief` 进入已归档的 `/brief/{public_id}`,并用视觉测试锁定 direction B 日报布局、链接出处、侧栏底色协调。

**Files:**
- Modify: `src/frontend/app/brief/page.tsx`
- Modify: `src/frontend/lib/api.ts`
- Create: `src/frontend/tests/e2e/brief-archive.spec.ts`
- Modify: `src/frontend/tests/e2e/visual.spec.ts`

- [x] **Step 1: 写失败 E2E — 标题链接可点、归档 URL 稳定**

`src/frontend/tests/e2e/brief-archive.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

test("brief page links AI titles to sources and exposes archived issue link", async ({ page }) => {
  await page.goto("/zh/brief");
  await expect(page.getByRole("heading", { name: "每日晨报" })).toBeVisible();
  const firstNewsLink = page.locator('a[href^="http"]').filter({ hasText: /OpenAI|Claude|AI|模型/ });
  await expect(firstNewsLink).toHaveCount(1);
  const archiveLink = page.locator('a[href*="/brief/brf_"]').first();
  await expect(archiveLink).toBeVisible();
});
```

- [x] **Step 2: `/brief` 新增归档入口**

在 `page.tsx` header 附近加:

```tsx
{archivedIssue?.public_id ? (
  <Link href={localizePath(`/brief/${archivedIssue.public_id}`, locale)} className="text-ink-secondary underline decoration-editorial-rule underline-offset-4">
    {locale === "zh" ? "查看归档版" : "Open archived issue"}
  </Link>
) : null}
```

- [x] **Step 3: visual.spec 加 `/brief` 与 `/brief/{public_id}`**

```typescript
test("visual baseline: zh brief", async ({ page }) => {
  await page.goto("/zh/brief");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page).toHaveScreenshot("brief-zh.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.05,
  });
});
```

- [x] **Step 4: 运行验证**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend
npx vitest run lib/design-tokens.test.ts lib/briefArchive.test.ts
npm run type-check
npm run lint
PW_E2E=1 npx playwright test tests/e2e/brief-archive.spec.ts tests/e2e/visual.spec.ts
```

Expected:
```text
vitest/type-check/lint pass
brief archive and visual specs pass
```

- [x] **Step 5: 提交**

```bash
git add src/frontend/app/brief/page.tsx src/frontend/lib/api.ts src/frontend/tests/e2e/brief-archive.spec.ts src/frontend/tests/e2e/visual.spec.ts
git commit -m "feat(frontend): link daily brief to archived snapshots"
```

### Slice Gate Summary

| Slice | 可独立验收结果 | 必跑命令 |
|---|---|---|
| 0 | 计划与当前 UI/token/API 状态同步,AAPL 迁移输入确认 | `npx vitest run lib/design-tokens.test.ts`, `npm run type-check`, `npm run lint` |
| 1 | brief/AI daily/root schema 入库 | `pytest tests/test_api_brief_persistence.py -q` |
| 2 | `/api/brief/*` + `/brief/{public_id}` 可用 | `pytest tests/test_api_brief_persistence.py tests/test_api_response_models.py -q`, `npx vitest run lib/briefArchive.test.ts` |
| 3 | AI HOT daily report cache 可回放 | `pytest tests/test_news_daily_report_repository.py tests/test_api_news_aihot.py -q` |
| 4 | paper account ledger/positions 可 backfill 到 DB mirror | `pytest tests/test_paper_account_postgres_repository.py -q`, opt-in `QS_TEST_DATABASE_URL=... pytest tests/test_paper_account_postgres_repository.py -q -m pg` |
| 5 | paper account API/CLI mutation 双写 DB mirror 且 response 不变 | `pytest tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py -q`, `PYTHONPATH=. pytest tests/test_cli.py tests/test_api_paper_strategy_sleeves.py -q` |
| 6 | DB canonical mutation fail closed | `pytest tests/test_api_paper_account.py tests/test_api_response_models.py tests/test_paper_account_postgres_repository.py -q` |
| 7 | `/brief` 可跳归档,视觉基线覆盖日报 | `PW_E2E=1 npx playwright test tests/e2e/brief-archive.spec.ts tests/e2e/visual.spec.ts` |

---

## 分阶段计划

> 历史说明:下方 P0-P4 是原前端渐进 redesign 计划的详细 backlog。2026-07-08 之后的实际开工顺序以 slice0-slice7 为准;P0-P4 中与当前 token/brief/persistence 裁决冲突的代码块只作为历史参考,不得照抄执行。

### Phase P0 · Week 1 — 设计地基(token + 字体 + chartTheme + navConfig + 视觉基线)

**目标:** 兼容式扩展 token 层、字体、图表主题、导航配置,不触碰任何业务 getter 或 form hook,建立新旧视觉并存的物理基础 + 锁定当前视觉基线。

> **P0 执行前修正:** 当前 `src/frontend/vitest.config.ts` 的 `include` 仅有 `lib/**/*.test.ts`。P0 新增 Vitest 测试统一放在 `lib/*.test.ts`,确保 `npx vitest run` 默认会执行到。

**Scope:**
- `globals.css` @theme 新增 editorial + hermes 语义层,并保留现有 token 名称与兼容别名
- `layout.tsx` 加 Source Serif 4 + Noto Serif SC 字体
- 建 `lib/navConfig.ts` 单一导航数据源(不删 factor-lab/agent-studio 项,仅加 Hermes)
- 建 `lib/chartTokens.ts` 两套图表主题
- 3 个图表组件 refactor(签名不变,theme 参数 optional)
- 建 `components/editorial/` + `components/hermes/` 空目录占位
- 建 `tests/e2e/visual.spec.ts` scoped 截图基线(先 6-8 个稳定/高风险路由,不做 22 页硬门禁)
- contract 测试只加不删(P0 只新增「新原语目录存在」断言;`/hermes` TopBar/Sidebar 导航断言等 P1 接入 navConfig 后再加)

**Deliverables:**
- `globals.css` 扩展后的 @theme(editorial + hermes 语义层,现有 token 0 改动)
- `lib/navConfig.ts` 单一导航数据源
- `lib/chartTokens.ts` 两套图表主题常量
- 3 个图表组件 refactor 签名不变
- `tests/e2e/visual.spec.ts` scoped 截图基线
- contract 测试新增目录断言不删旧

**Dependencies:** 无(P0 是一切起点)

**Validation:**
- `npm run type-check` + `lint` + `vitest run` 全绿
- `npm run build` 全绿
- `PW_E2E=1 npm run test:e2e` 全绿(含 scoped visual.spec 首次 capture)
- `pytest tests/test_frontend_terminal_surface_contract.py tests/test_frontend_topbar_navigation_contract.py` 全绿(旧断言未改,仅新增)
- 手动目检 22 个现有页面确认未出现布局、对比度、可读性回归;注意 2026-07-08 已统一 warm base/sidebar,不再要求冷黑色值不变
- 浏览器 DevTools `:root` 确认新 token 可见
- 访问临时 `/dev/preview`(若有)确认 editorial/hermes 组件渲染

#### Task P0-1: globals.css 扩展 editorial + hermes token 层

**Files:**
- Modify: `app/globals.css`(在现有 @theme 块末尾、compat aliases 之前插入新 token)

**Interfaces:**
- Produces: `--color-paper-ink #14130F`、`--color-paper-surface #1A1916`、`--color-paper-surface-muted #222019`、`--color-ink #EDE7DA`、`--color-ink-secondary #A39E92`、`--color-editorial-rule #3A3733`、`--color-editorial-accent #7B8FD0`、`--color-editorial-up #2E9E6A`、`--color-editorial-down #C84A52`、`--color-hermes #9085E9`、`--color-hermes-glow rgba(144,133,233,.4)`、`--color-stream-bg #17171C`、`--color-stream-surface #1F1F27`、`--color-stream-surface-2 #262631`、`--font-editorial-serif`、`--spacing-rail-width 208px`、`--spacing-right-panel 340px`、`--spacing-stream-max 720px`、`--spacing-editorial-column 1120px`、`--radius-editorial 2px`

- [ ] **Step 1: 写失败测试 — 验证新 token 存在于 :root**

新建 `lib/design-tokens.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

// P0-1: 验证 editorial + hermes token 层已加入 globals.css @theme
// 这些 token 必须出现在编译后的 CSS :root 里(Tailwind 4 @theme 会输出到 :root)
describe('editorial + hermes design tokens', () => {
  const expectedTokens = [
    '--color-paper-ink',
    '--color-paper-surface',
    '--color-paper-surface-muted',
    '--color-ink',
    '--color-ink-secondary',
    '--color-editorial-rule',
    '--color-editorial-accent',
    '--color-editorial-up',
    '--color-editorial-down',
    '--color-hermes',
    '--color-hermes-glow',
    '--color-stream-bg',
    '--color-stream-surface',
    '--color-stream-surface-2',
    '--font-editorial-serif',
    '--spacing-rail-width',
    '--spacing-right-panel',
    '--spacing-stream-max',
    '--spacing-editorial-column',
    '--radius-editorial',
  ];

  it.each(expectedTokens)('%s is defined in globals.css @theme', async (token) => {
    const css = await import('fs').then(fs =>
      fs.readFileSync('app/globals.css', 'utf-8')
    );
    expect(css).toContain(`--${token.replace('--', '')}:`);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/design-tokens.test.ts`
Expected: FAIL — 所有 token 未找到(globals.css 尚未新增)

- [ ] **Step 3: 在 globals.css @theme 块插入 editorial + hermes token**

在 `app/globals.css` 的 `@theme { ... }` 块内,在现有 `--color-data-mono: #D1D4DC;` 行之后、`/* ---- Compat aliases ----` 注释之前,插入:

```css
  /* ---- Editorial layer (B 暗色编辑式: 暖灰近黑 + 象牙暖白) ----
     仅在 B/C 页面(dashboard 晨报/Hermes/docs/ai-news)opt-in 引用。
     操作型页面继续用上面的 QUANTUM_CORE 冷黑 token。两套 up/down 按页面角色分套不复用。 */
  --color-paper-ink: #14130F;            /* 暖灰近黑底,近黑微暖不偏棕 */
  --color-paper-surface: #1A1916;        /* 编辑卡片/印刷图版底 */
  --color-paper-surface-muted: #222019;  /* figure 底/嵌套 */
  --color-ink: #EDE7DA;                  /* 象牙暖白文字,替代冷白 #E0E3EB */
  --color-ink-secondary: #A39E92;        /* 暖灰次要文字 */
  --color-editorial-rule: #3A3733;       /* 暖灰规则线,替代冷灰 #2A2A2A */
  --color-editorial-accent: #7B8FD0;     /* 编辑蓝紫(section rule/figure 边框/数据线) */
  --color-editorial-up: #2E9E6A;         /* 编辑哑光涨 */
  --color-editorial-down: #C84A52;       /* 编辑哑光跌 */

  /* ---- Hermes layer (C 对话流: 冷紫品牌色) ----
     hermes 紫专用于 Hermes 主体(球/头像/run 态/send/链接)。 */
  --color-hermes: #9085E9;
  --color-hermes-glow: rgba(144, 133, 233, 0.4);
  --color-stream-bg: #17171C;
  --color-stream-surface: #1F1F27;
  --color-stream-surface-2: #262631;

  /* ---- Editorial + Hermes layout tokens ---- */
  --spacing-rail-width: 208px;        /* C 对话流左轨宽度 */
  --spacing-right-panel: 340px;       /* C 对话流右栏宽度 */
  --spacing-stream-max: 720px;        /* C 主流 max-width */
  --spacing-editorial-column: 1120px; /* B 晨报版心 max-width */
  --radius-editorial: 2px;            /* 印刷直角感,区别于 primitives 的 rounded-lg 8px */
```

在 `@theme` 块内 `--font-code-sm: ...` 行之后,加字体 token(实际字体变量在 P0-2 由 next/font 注入,这里先声明语义名):

```css
  --font-editorial-serif: var(--font-serif), var(--font-serif-sc), Georgia, 'Songti SC', serif;
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/design-tokens.test.ts`
Expected: PASS — 20 个 token 全部找到

- [ ] **Step 5: 手动确认 22 个现有页面无布局/可读性回归**

Run: `cd src/frontend && npm run build && npm run dev`,浏览器打开 `localhost:3001` 目检 dashboard/backtest/options-screener 等 3-5 页,确认 warm base/sidebar 改动没有造成布局、对比度、可读性回归。

- [ ] **Step 6: 提交**

```bash
cd src/frontend
git add app/globals.css lib/design-tokens.test.ts
git commit -m "feat(frontend): add editorial + hermes design token layers (pure additive)

新增 B 暗色编辑式(暖灰近黑)与 C Hermes 对话流(冷紫)两层语义 token,
现有 QUANTUM_CORE token 名称与兼容别名保留。22 个旧页无布局/可读性回归。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-2: layout.tsx 加 Source Serif 4 + Noto Serif SC 字体

**Files:**
- Modify: `app/layout.tsx`(第2行 next/font/google import 区;第29行 html className)

**Interfaces:**
- Produces: `--font-serif` / `--font-serif-sc` CSS 变量(由 next/font 注入到 html className),供 `--font-editorial-serif` 引用
- Consumes: P0-1 的 `--font-editorial-serif` token,其字体栈必须包含 `var(--font-serif)` 与 `var(--font-serif-sc)`

- [ ] **Step 1: 写失败测试 — 验证 Source Serif 4 + Noto Serif SC 已加载**

新建 `lib/editorial-font.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import * as fs from 'fs';

describe('editorial serif font loading', () => {
  it('layout.tsx imports Source_Serif_4 and Noto_Serif_SC via next/font/google', () => {
    const src = fs.readFileSync('app/layout.tsx', 'utf-8');
    expect(src).toMatch(/Source_Serif_4/);
    expect(src).toMatch(/Noto_Serif_SC/);
  });

  it('layout.tsx assigns serif font to --font-serif variable on html', () => {
    const src = fs.readFileSync('app/layout.tsx', 'utf-8');
    // next/font 的 variable 选项定义 CSS 变量,html className 引用它
    expect(src).toMatch(/variable:\s*['"]--font-serif['"]/);
  });

  it('html className preserves existing inter + jetbrains variables', () => {
    const src = fs.readFileSync('app/layout.tsx', 'utf-8');
    // 现有第29行 html className 含 inter.variable + jetbrains.variable,不能删
    expect(src).toMatch(/inter\.variable/);
    expect(src).toMatch(/jetbrains\.variable/);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/editorial-font.test.ts`
Expected: FAIL — Source_Serif_4 / Noto_Serif_SC / --font-serif 未找到

- [ ] **Step 3: 在 layout.tsx 加字体 import 与配置**

在 `app/layout.tsx` 顶部 next/font import 区(第2行附近,现有 Inter + JetBrains_Mono import 之后)加:

```typescript
import { Source_Serif_4, Noto_Serif_SC } from "next/font/google";
```

在现有 `const inter = Inter({...})` 与 `const jetbrains = JetBrains_Mono({...})` 之后加:

```typescript
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-serif",
  display: "swap",
  weight: ["400", "600", "700"],
  style: ["normal", "italic"],
  fallback: ["Georgia", "serif"],
});

const notoSerifSC = Noto_Serif_SC({
  subsets: ["latin"],
  variable: "--font-serif-sc",
  display: "swap",
  weight: ["400", "700"],
  fallback: ["Songti SC", "serif"],
});
```

修改 `<html>` 标签的 className(第29行附近),在现有 `inter.variable` + `jetbrains.variable` 之后追加 `sourceSerif.variable` + `notoSerifSC.variable`:

```typescript
<html lang="..." className={`${inter.variable} ${jetbrains.variable} ${sourceSerif.variable} ${notoSerifSC.variable}`}>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/editorial-font.test.ts`
Expected: PASS

- [ ] **Step 5: 手动确认字体加载不破坏首屏**

Run: `cd src/frontend && npm run build && npm run dev`,打开 `localhost:3001`,DevTools Network 确认 Source Serif 4 + Noto Serif SC 字体文件加载(200),首屏 LCP 无明显回退(衬线只用于后续 B/C 页面,现有页面不引用 `--font-editorial-serif`)。

- [ ] **Step 6: 提交**

```bash
cd src/frontend
git add app/layout.tsx lib/editorial-font.test.ts
git commit -m "feat(frontend): load Source Serif 4 + Noto Serif SC for editorial layer

挂 --font-serif / --font-serif-sc 变量,供 --font-editorial-serif 引用。
现有 inter/jetbrains 变量保留不动。display:swap 避免 FOIT。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-3: globals.css 新增 editorial 排版类 + 启用 typography 插件

**Files:**
- Modify: `app/globals.css`(在现有 `.font-*` 排版类之后新增;顶部 `@import` 之后加 `@plugin`)

**Interfaces:**
- Produces: `.font-editorial-display`(衬线46px)、`.font-editorial-body`(衬线21px)、`.font-editorial-caps`(衬线斜体小字)排版类;`prose` 基础(由 @tailwindcss/typography 提供)

- [ ] **Step 1: 写失败测试 — 验证 editorial 排版类存在**

新建 `lib/editorial-typography.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import * as fs from 'fs';

describe('editorial typography classes', () => {
  it('globals.css defines .font-editorial-display/.font-editorial-body/.font-editorial-caps', () => {
    const css = fs.readFileSync('app/globals.css', 'utf-8');
    expect(css).toMatch(/\.font-editorial-display\s*\{/);
    expect(css).toMatch(/\.font-editorial-body\s*\{/);
    expect(css).toMatch(/\.font-editorial-caps\s*\{/);
  });

  it('globals.css enables @tailwindcss/typography plugin via @plugin', () => {
    const css = fs.readFileSync('app/globals.css', 'utf-8');
    expect(css).toMatch(/@plugin\s+["']@tailwindcss\/typography["']/);
  });

  it('editorial classes use var(--font-editorial-serif)', () => {
    const css = fs.readFileSync('app/globals.css', 'utf-8');
    expect(css).toMatch(/font-family:\s*var\(--font-editorial-serif\)/);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/editorial-typography.test.ts`
Expected: FAIL

- [ ] **Step 3: 在 globals.css 启用 typography 插件**

在 `app/globals.css` 顶部 `@import "tailwindcss";` 行之后加:

```css
@plugin "@tailwindcss/typography";
```

- [ ] **Step 4: 在 globals.css 现有 `.font-*` 排版类区块末尾加 editorial 排版类**

在现有 `.font-code-sm { ... }` 块之后加:

```css
/* ---- Editorial typography (B 暗色编辑式: 衬线) ---- */
.font-editorial-display {
  font-family: var(--font-editorial-serif);
  font-size: 46px;
  line-height: 54px;
  letter-spacing: 0;
  font-weight: 700;
}
.font-editorial-body {
  font-family: var(--font-editorial-serif);
  font-size: 21px;
  line-height: 32px;
  font-weight: 400;
}
.font-editorial-caps {
  font-family: var(--font-editorial-serif);
  font-size: 13px;
  line-height: 18px;
  font-style: italic;
  font-weight: 400;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/editorial-typography.test.ts`
Expected: PASS

- [ ] **Step 6: 手动确认现有页面不引用新类(无副作用)**

Run: `cd src/frontend && grep -r 'font-editorial-' app components --include='*.tsx' || echo "无引用,符合预期(新类仅供后续 B/C 页面用)"`

- [ ] **Step 7: 提交**

```bash
cd src/frontend
git add app/globals.css lib/editorial-typography.test.ts
git commit -m "feat(frontend): add editorial typography classes + enable typography plugin

.font-editorial-display/body/caps 衬线排版类 + @plugin @tailwindcss/typography
为 B 编辑正文提供 prose 基础。现有页面不引用新类,零副作用。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-4: 建 lib/navConfig.ts 单一导航数据源

**Files:**
- Create: `lib/navConfig.ts`
- Test: `lib/navConfig.test.ts`

**Interfaces:**
- Produces: `navSections` 数组(含 icon 映射)、`NavSection` / `NavItem` 类型。Sidebar.tsx 与 TopBar.tsx 将在 P1 改为从此 import。
- Consumes: 现有 `Sidebar.tsx` 第105-147行 navSections 结构(逐项迁移,含 factor-lab/agent-studio 项暂保留)

- [ ] **Step 1: 写失败测试 — 验证 navConfig 导出结构与 Sidebar 现有导航一致**

新建 `lib/navConfig.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { navSections, type NavSection } from '@/lib/navConfig';

describe('navConfig single source of truth', () => {
  it('exports navSections array with 5 groups', () => {
    expect(Array.isArray(navSections)).toBe(true);
    expect(navSections).toHaveLength(5);
  });

  it('groups match existing Sidebar groups', () => {
    const groupIds = navSections.map((s: NavSection) => s.id);
    expect(groupIds).toEqual([
      'research',
      'paper',
      'options',
      'markets',
      'system',
    ]);
  });

  it('includes hermes nav item in research group top', () => {
    const research = navSections.find((s: NavSection) => s.id === 'research');
    expect(research).toBeDefined();
    expect(research!.items[0].href).toBe('/hermes');
    expect(research!.items[0].id).toBe('hermes');
  });

  it('still includes factorLab and agentStudio items until parity is complete', () => {
    const allItems = navSections.flatMap((s: NavSection) => s.items);
    expect(allItems.some(i => i.id === 'factorLab')).toBe(true);
    expect(allItems.some(i => i.id === 'agentStudio')).toBe(true);
  });

  it('each item has id/href/icon keys', () => {
    for (const section of navSections) {
      for (const item of section.items) {
        expect(item).toHaveProperty('id');
        expect(item).toHaveProperty('href');
        expect(item).toHaveProperty('icon');
      }
    }
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/navConfig.test.ts`
Expected: FAIL — `@/lib/navConfig` 未找到

- [ ] **Step 3: 创建 lib/navConfig.ts**

先读 `components/Sidebar.tsx` 第105-147行拿现有 navSections 的 id/href/icon 映射,然后创建 `lib/navConfig.ts`:

```typescript
import {
  BadgeDollarSign, BriefcaseBusiness, LayoutDashboard, Zap, LineChart,
  FlaskConical, Settings, Database, BookOpen, Map, Newspaper, FileText,
  HelpCircle, Plus, ListFilter, Radar, ShieldCheck, Wrench, ScrollText,
  Beaker, Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavItem = {
  id: string;
  href: string;
  icon: LucideIcon;
};

export type NavSection = {
  id: "research" | "paper" | "options" | "markets" | "system";
  items: NavItem[];
};

// 单一导航数据源 — Sidebar.tsx 与 TopBar.tsx 共享。
// P0: 从 Sidebar.tsx 第105-147行迁移,保留 factorLab/agentStudio 项(避免 TS 报错),
//     新增 hermes 项置 research 顶部。
// P4: approval parity + factor evidence parity 完成后再移除 factorLab/agentStudio 项。
export const navSections: NavSection[] = [
  {
    id: "research",
    items: [
      { id: "hermes", href: "/hermes", icon: Sparkles },
      { id: "dashboard", href: "/", icon: LayoutDashboard },
      { id: "dataExplorer", href: "/data-explorer", icon: Database },
      { id: "factorLab", href: "/factor-lab", icon: FlaskConical },
      { id: "backtester", href: "/backtest", icon: LineChart },
      { id: "replications", href: "/strategies", icon: ScrollText },
      { id: "experiments", href: "/experiments", icon: Beaker },
    ],
  },
  {
    id: "paper",
    items: [
      { id: "paperTrading", href: "/paper-trading", icon: BadgeDollarSign },
      { id: "agentStudio", href: "/agent-studio", icon: Zap },
    ],
  },
  {
    id: "options",
    items: [
      { id: "optionsScreener", href: "/options-screener", icon: ListFilter },
      { id: "optionsRadar", href: "/options-radar", icon: Radar },
      { id: "optionsTools", href: "/options-tools", icon: Wrench },
      { id: "buySide", href: "/options-buyside", icon: ShieldCheck },
    ],
  },
  {
    id: "markets",
    items: [
      { id: "aiNews", href: "/ai-news", icon: Newspaper },
      { id: "orderBook", href: "/polymarket", icon: BriefcaseBusiness },
      { id: "positionMap", href: "/position-map", icon: Map },
    ],
  },
  {
    id: "system",
    items: [
      { id: "docs", href: "/docs", icon: BookOpen },
      { id: "settings", href: "/settings", icon: Settings },
      { id: "support", href: "/docs", icon: HelpCircle },
    ],
  },
];
```

> **注意:** 上面的 icon 映射与 item 顺序需对照 `Sidebar.tsx` 第105-147行实际值核对修正——P0 实施时由执行 agent 读真实代码确认,此处给出结构与 hermes 顶置的契约。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/navConfig.test.ts`
Expected: PASS

- [ ] **Step 5: 确认 Sidebar/TopBar 尚未引用(P0 只建数据源,不改组件)**

Run: `cd src/frontend && grep -l 'navConfig' components/Sidebar.tsx components/TopBar.tsx 2>/dev/null || echo "未引用,符合预期(P1 才接入)"`

- [ ] **Step 6: 提交**

```bash
cd src/frontend
git add lib/navConfig.ts lib/navConfig.test.ts
git commit -m "feat(frontend): add lib/navConfig.ts single nav data source

从 Sidebar.tsx 第105-147行抽出 navSections 单一数据源,新增 hermes 项置 research 顶部。
factorLab/agentStudio 项暂保留到 parity 完成。Sidebar/TopBar P1 才接入 navConfig。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-5: 建 lib/chartTokens.ts 两套图表主题

**Files:**
- Create: `lib/chartTokens.ts`
- Test: `lib/chartTokens.test.ts`

**Interfaces:**
- Produces: `terminalChartTheme`(兼容现有 Candlestick/Recharts 全部字面色值)、`editorialChartTheme`(暖灰哑光 + 直角 tooltip)、`readCssVar(name, fallback)` 工具、`ChartTheme` 类型
- `ChartTheme` 必须覆盖 3 个现有图表的真实字段,不能只含 `background/up/down/grid`:Candlestick 需要 `text/border/volumeUp/volumeDown`;EquityComparison 需要 `strategy/benchmark/axis/tick/rechartsGrid/tooltipBorder/legendText`;FactorRunCharts 需要 `ic/rankIc/positive/negative`。
- Consumes: 无(自包含常量)

- [ ] **Step 1: 写失败测试 — 验证两套 theme 与 readCssVar**

新建 `lib/chartTokens.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import {
  terminalChartTheme,
  editorialChartTheme,
  readCssVar,
  type ChartTheme,
} from '@/lib/chartTokens';

describe('chartTokens', () => {
  it('terminalChartTheme keeps existing colors for compat', () => {
    expect(terminalChartTheme.background).toBe('#111827');
    expect(terminalChartTheme.up).toBe('#00C896');
    expect(terminalChartTheme.down).toBe('#FF4D4F');
    expect(terminalChartTheme.strategy).toBe('#00C896');
    expect(terminalChartTheme.benchmark).toBe('#60A5FA');
    expect(terminalChartTheme.rankIc).toBe('#00C896');
  });

  it('editorialChartTheme uses warm-grey palette', () => {
    expect(editorialChartTheme.background).toBe('#1A1916');
    expect(editorialChartTheme.up).toBe('#2E9E6A');
    expect(editorialChartTheme.down).toBe('#C84A52');
    expect(editorialChartTheme.tooltipBorderRadius).toBe(2);
  });

  it('both themes have required ChartTheme keys', () => {
    const keys: (keyof ChartTheme)[] = [
      'background', 'text', 'grid', 'rechartsGrid', 'border',
      'up', 'down', 'volumeUp', 'volumeDown',
      'strategy', 'benchmark', 'ic', 'rankIc', 'positive', 'negative',
      'axis', 'tick', 'tooltipBg', 'tooltipBorder', 'tooltipText', 'tooltipBorderRadius', 'legendText',
    ];
    for (const k of keys) {
      expect(terminalChartTheme[k]).toBeDefined();
      expect(editorialChartTheme[k]).toBeDefined();
    }
  });

  it('readCssVar returns fallback when window undefined (SSR safe)', () => {
    expect(readCssVar('--color-paper-ink', '#14130F')).toBe('#14130F');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/chartTokens.test.ts`
Expected: FAIL — 模块未找到

- [ ] **Step 3: 创建 lib/chartTokens.ts**

```typescript
// 单一图表色真相源 — lightweight-charts 与 recharts 都需字面色值(不读 CSS 变量),
// 故集中在此替代散落的 CHART_COLORS 常量。两套 theme 按页面角色选用:
//   terminalChartTheme: 操作型页面(backtest/options/paper-trading),兼容现有色
//   editorialChartTheme: 阅读型页面(晨报/Hermes 报告),暖灰哑光

export type ChartTheme = {
  background: string;
  text: string;
  grid: string;
  rechartsGrid: string;
  border: string;
  up: string;
  down: string;
  volumeUp: string;
  volumeDown: string;
  strategy: string;
  benchmark: string;
  ic: string;
  rankIc: string;
  positive: string;
  negative: string;
  axis: string;
  tick: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipBorderRadius: number;
  legendText: string;
};

export const terminalChartTheme: ChartTheme = {
  background: '#111827',
  text: '#94A3B8',
  grid: 'rgba(148, 163, 184, 0.10)',
  rechartsGrid: 'rgba(148, 163, 184, 0.12)',
  border: 'rgba(148, 163, 184, 0.22)',
  up: '#00C896',
  down: '#FF4D4F',
  volumeUp: 'rgba(0, 200, 150, 0.32)',
  volumeDown: 'rgba(255, 77, 79, 0.32)',
  strategy: '#00C896',
  benchmark: '#60A5FA',
  ic: '#60A5FA',
  rankIc: '#00C896',
  positive: '#00C896',
  negative: '#FF4D4F',
  axis: '#64748B',
  tick: '#94A3B8',
  tooltipBg: '#111827',
  tooltipBorder: 'rgba(148, 163, 184, 0.24)',
  tooltipText: '#E2E8F0',
  tooltipBorderRadius: 8,
  legendText: '#CBD5E1',
};

export const editorialChartTheme: ChartTheme = {
  background: '#1A1916',
  text: '#A39E92',
  grid: '#3A3733',
  rechartsGrid: '#3A3733',
  border: '#3A3733',
  up: '#2E9E6A',
  down: '#C84A52',
  volumeUp: 'rgba(46, 158, 106, 0.28)',
  volumeDown: 'rgba(200, 74, 82, 0.28)',
  strategy: '#2E9E6A',
  benchmark: '#7B8FD0',
  ic: '#7B8FD0',
  rankIc: '#2E9E6A',
  positive: '#2E9E6A',
  negative: '#C84A52',
  axis: '#A39E92',
  tick: '#A39E92',
  tooltipBg: '#222019',
  tooltipBorder: '#3A3733',
  tooltipText: '#EDE7DA',
  tooltipBorderRadius: 2,
  legendText: '#EDE7DA',
};

// SSR-safe CSS 变量读取(图表组件若需在 client 侧读 token 可用)
export function readCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/chartTokens.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd src/frontend
git add lib/chartTokens.ts lib/chartTokens.test.ts
git commit -m "feat(frontend): add lib/chartTokens.ts single chart-color source

terminalChartTheme(兼容现有) + editorialChartTheme(暖灰哑光)两套常量,
消除 CandlestickChart/EquityComparisonChart 硬编码色与 token 漂移隐患。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-6: 3 个图表组件 refactor 为 theme 注入(签名不变)

**Files:**
- Modify: `components/CandlestickChart.tsx`(第24-33行 CHART_COLORS)
- Modify: `components/EquityComparisonChart.tsx`(第28-36行 COLORS)
- Modify: `components/FactorRunCharts.tsx`(同理)
- Test: `lib/chart-theme-injection.test.ts`

**Interfaces:**
- Consumes: P0-5 的 `terminalChartTheme` + `ChartTheme` 类型
- Produces: 3 个图表组件新增 optional `theme?: ChartTheme` prop(默认 `terminalChartTheme`,签名向后兼容)

- [ ] **Step 1: 写失败测试 — 验证图表组件接受 theme prop 且默认 terminal**

新建 `lib/chart-theme-injection.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import * as fs from 'fs';

describe('chart components accept optional theme prop', () => {
  it('CandlestickChart imports terminalChartTheme as default', () => {
    const src = fs.readFileSync('components/CandlestickChart.tsx', 'utf-8');
    expect(src).toMatch(/import.*terminalChartTheme.*from.*['"]@\/lib\/chartTokens['"]/);
    expect(src).not.toMatch(/const CHART_COLORS\s*=\s*\{/); // 旧常量已删
  });

  it('CandlestickChart has optional theme prop defaulting to terminalChartTheme', () => {
    const src = fs.readFileSync('components/CandlestickChart.tsx', 'utf-8');
    expect(src).toMatch(/theme\??\s*[:=]/);
  });

  it('EquityComparisonChart imports from chartTokens', () => {
    const src = fs.readFileSync('components/EquityComparisonChart.tsx', 'utf-8');
    expect(src).toMatch(/import.*from.*['"]@\/lib\/chartTokens['"]/);
    expect(src).not.toMatch(/const COLORS\s*=\s*\{[^}]*#00C896/);
  });

  it('FactorRunCharts imports from chartTokens', () => {
    const src = fs.readFileSync('components/FactorRunCharts.tsx', 'utf-8');
    expect(src).toMatch(/import.*from.*['"]@\/lib\/chartTokens['"]/);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd src/frontend && npx vitest run lib/chart-theme-injection.test.ts`
Expected: FAIL — 仍用旧 CHART_COLORS 常量

- [ ] **Step 3: refactor CandlestickChart.tsx**

读 `components/CandlestickChart.tsx` 第1-40行,然后:

1. 删除第24-33行 `const CHART_COLORS = { ... }`
2. 顶部加 `import { terminalChartTheme, type ChartTheme } from "@/lib/chartTokens";`
3. 在组件 props 类型加 `theme?: ChartTheme`(optional)
4. 组件内 `const t = theme ?? terminalChartTheme;`
5. 把所有 `CHART_COLORS.xxx` 替换为 `t.xxx`(background/text/grid/border/up/down/volumeUp/volumeDown)

> **注意:** 不改 lightweight-charts 的 API 调用方式,只替换色值来源。component 签名向后兼容(theme optional 默认 terminal)。

- [ ] **Step 4: refactor EquityComparisonChart.tsx 与 FactorRunCharts.tsx**

同理:删旧 `COLORS` 常量,import `terminalChartTheme` + `ChartTheme`,加 optional `theme` prop,替换色值引用。EquityComparisonChart 使用 `strategy/benchmark/axis/tick/rechartsGrid/tooltipBg/tooltipBorder/tooltipText/tooltipBorderRadius/legendText`;FactorRunCharts 使用 `ic/rankIc/positive/negative/axis/tick/rechartsGrid/tooltip*`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd src/frontend && npx vitest run lib/chart-theme-injection.test.ts`
Expected: PASS

- [ ] **Step 6: 运行 type-check + 现有图表相关 E2E 确认无回归**

Run:
```bash
cd src/frontend
npx tsc --noEmit
PW_E2E=1 npx playwright test tests/e2e/ --grep "backtest|data-explorer|factor"
```
Expected: 全绿(图表渲染不变,因为默认 theme = terminalChartTheme = 旧色)

- [ ] **Step 7: 提交**

```bash
cd src/frontend
git add components/CandlestickChart.tsx components/EquityComparisonChart.tsx components/FactorRunCharts.tsx lib/chart-theme-injection.test.ts
git commit -m "refactor(frontend): inject chart theme via props, fix color drift

3 个图表组件改为从 props 读 theme(默认 terminalChartTheme),签名向后兼容。
修复 CHART_COLORS.background=#111827 与 token #151515 漂移隐患。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-7: 建 components/editorial/ + components/hermes/ 空目录占位

**Files:**
- Create: `components/editorial/index.ts`(空导出占位)
- Create: `components/hermes/index.ts`(空导出占位)

**Interfaces:**
- Produces: 两个目录存在,P2 填充组件时无 import 报错

- [ ] **Step 1: 创建占位 index.ts**

`components/editorial/index.ts`:
```typescript
// B 暗色编辑式组件库 — P2 填充。
// 预期组件: Masthead / Lede / SectionHead / EditorialFigure / PosTable / NewsColumns / HermesQuote / ErrataLog
export {};
```

`components/hermes/index.ts`:
```typescript
// C Hermes 对话流组件库 — P2 填充。
// 预期组件: HermesOrb / UserBubble / HermesMessageCard / HermesExecCard / HermesArtifactCard / HermesArtifactBadge / HermesCodeCard / NewsCard / FillReceiptCard / SystemCard / Daybreak / ComposerDock
export {};
```

- [ ] **Step 2: 确认目录可被 import**

Run: `cd src/frontend && npx tsc --noEmit`
Expected: 无错误(空导出不破坏类型)

- [ ] **Step 3: 提交**

```bash
cd src/frontend
git add components/editorial/index.ts components/hermes/index.ts
git commit -m "feat(frontend): scaffold editorial + hermes component dirs

P2 填充前的空目录占位,避免后续 import 报错。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-8: 建 tests/e2e/visual.spec.ts scoped 视觉基线

> **Q8 裁决:** 启用视觉回归,但 staged/scoped。先覆盖 6-8 个稳定/高风险路由与移动端 shell,不把 22 页 golden master 作为第一阶段硬门禁。已迁移页面后续逐页升级为硬 gate。

**Files:**
- Create: `tests/e2e/visual.spec.ts`

**Interfaces:**
- Produces: 6-8 个 scoped `toHaveScreenshot` baseline(maxDiffPixelRatio 0.05),优先覆盖 `/`, `/backtest`, `/data-explorer`, `/strategies`, `/options-screener`, `/paper-trading` 或 `/position-map`,以及一个 mobile shell viewport。`/brief` 与 `/hermes` 创建后再加入。

- [ ] **Step 1: 写 visual.spec.ts 对 scoped routes 截基线**

```typescript
import { test, expect } from '@playwright/test';

const pages = [
  '/',
  '/backtest',
  '/data-explorer',
  '/strategies',
  '/options-screener',
  '/paper-trading',
  '/position-map',
];

for (const path of pages) {
  test(`visual baseline: ${path}`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(page).toHaveScreenshot(`baseline-${path.replace('/', '_')}.png`, {
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
    });
  });
}
```

> **注意:** 需用 PW_E2E 已注入的 `e2e-data` 固定 sample 数据源避免动态数据噪音。执行 agent 需确认 `playwright.config.ts` 的 baseURL 与数据注入方式;对时间戳、闪烁动画、动态图表可加 mask 或专用等待。

- [ ] **Step 2: 首次 capture 基线**

Run: `cd src/frontend && PW_E2E=1 npx playwright test tests/e2e/visual.spec.ts --update-snapshots`
Expected: 生成 scoped baseline PNG

- [ ] **Step 3: 重新运行确认基线稳定**

Run: `cd src/frontend && PW_E2E=1 npx playwright test tests/e2e/visual.spec.ts`
Expected: PASS(与刚 capture 的基线一致)

- [ ] **Step 4: 提交**

```bash
cd src/frontend
git add tests/e2e/visual.spec.ts tests/e2e/visual.spec.ts-snapshots/
git commit -m "test(frontend): add scoped Playwright visual baselines

先锁定 6-8 个稳定/高风险路由与 mobile shell,避免 22 页字体/时间戳噪音。
后续逐页迁移时用「有意更新该页基线 + 未迁页不变」检测跨页回归。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### Task P0-9: contract 测试新增「新原语目录存在」断言(不删旧)

**Files:**
- Modify: `tests/test_frontend_terminal_surface_contract.py`(新增断言)

**Interfaces:**
- Produces: contract 测试只加不删。P0 不要求 TopBar/Sidebar 已经暴露 `/hermes`;P1 接入 navConfig 后再新增 `/hermes` 导航断言。

- [ ] **Step 1: 在 terminal surface contract 加「新原语目录存在」断言**

在 `test_frontend_terminal_surface_contract.py` 末尾新增测试函数:

```python
def test_editorial_and_hermes_component_dirs_exist():
    """P0: editorial + hermes 组件目录已建(P2 填充组件)。"""
    from pathlib import Path
    frontend = Path(__file__).parent.parent / "src" / "frontend" / "components"
    assert (frontend / "editorial" / "index.ts").exists()
    assert (frontend / "hermes" / "index.ts").exists()
```

- [ ] **Step 2: 运行 contract 测试确认通过**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
pytest tests/test_frontend_terminal_surface_contract.py -v
```
Expected: PASS(旧断言 + 新目录断言全过)

- [ ] **Step 3: 提交**

```bash
cd /Users/sunyibo/programs/ai-quant-platform
git add tests/test_frontend_terminal_surface_contract.py
git commit -m "test(frontend): add editorial/hermes dir contract assertion

P0 只锁定 editorial/hermes 组件目录存在。/hermes 导航 contract 等 P1 navConfig 接入后再加。
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

#### P0 阶段验证(Exit Criteria)

执行完 P0-1 ~ P0-9 后:

- [ ] **V1:** `cd src/frontend && npx tsc --noEmit` 全绿
- [ ] **V2:** `cd src/frontend && npm run lint` 全绿
- [ ] **V3:** `cd src/frontend && npx vitest run` 全绿(含新 design-tokens/editorial-font/editorial-typography/navConfig/chartTokens/chart-theme-injection 6 个测试文件)
- [ ] **V4:** `cd src/frontend && npm run build` 全绿
- [ ] **V5:** `cd src/frontend && PW_E2E=1 npx playwright test` 全绿(现有 10 个 E2E 零回归)
- [ ] **V6:** `cd /Users/sunyibo/programs/ai-quant-platform && pytest tests/test_frontend_topbar_navigation_contract.py tests/test_frontend_terminal_surface_contract.py` 全绿
- [ ] **V7:** 手动目检 22 个现有页面确认 warm base/sidebar 改动后无布局、对比度、可读性回归
- [ ] **V8:** 浏览器 DevTools `:root` 确认 editorial + hermes token 可见

---

### Phase P1 · Week 2 — `/brief` 试跑 + Hermes 一等入口 + navConfig 接入

**目标:** 用 navConfig 单一数据源重构 Sidebar/TopBar,新增 `/hermes` 一等入口,同时创建 `/brief` 暗色晨报试跑页。P1 不删除 factor-lab/agent-studio 导航、不加无上下文重定向;旧入口要等 approval parity + factor evidence parity 完成后再下线。

**Scope:**
- Sidebar.tsx + TopBar.tsx 改为从 `lib/navConfig.ts` 读 navSections
- navConfig + Sidebar/TopBar copy 新增 `nav.hermes`(factorLab/agentStudio 暂保留)
- app/page.tsx quick actions 新增 `/hermes` 入口;不替换首页主体
- app/brief/page.tsx 试跑晨报(暖灰暗色,模板 lede,只读现有 dashboard facts)
- contract 测试只加 `/hermes` 断言,不删 factor-lab/agent-studio 断言
- visual.spec 加入 `/brief` 与 `/hermes`(若 `/hermes` 已有 placeholder)

**Deliverables:**
- `/brief` 暗色晨报 trial 页面
- Sidebar/TopBar/page.tsx 接入 Hermes 入口
- contract 测试只加不删
- visual baseline 包含 `/brief`

**Dependencies:** P0(navConfig 已建)

**Validation:**
- type-check + lint + vitest + E2E 全绿
- 手动访问 `/brief` 确认暖灰暗色晨报可读,不替换 `/`
- 手动访问 `/` 确认 dashboard 仍是安全/状态锚点,仅新增 Hermes 入口且布局未错位
- 手动访问 `/factor-lab` `/agent-studio` 确认旧入口仍可用(未完成 parity 前不做早跳转)
- 中英双语 shell 目检

> **P1 bite-sized Task 需在 P0 完成后按本节裁决展开。**

#### P1 Task 概要(P0 后展开为 bite-sized 步骤)

- P1-1: Sidebar.tsx + TopBar.tsx 改为从 `lib/navConfig.ts` 读(消除双份维护)
- P1-2: navConfig + Sidebar/TopBar copy 新增 hermes 项,factorLab/agentStudio 暂保留
- P1-3: app/page.tsx quick actions 新增 `/hermes`,不替换首页主体
- P1-4: 建 app/brief/page.tsx 试跑晨报(模板 lede,只读 dashboard facts)
- P1-5: contract 测试同步更新(只加 /hermes)
- P1-6: visual.spec 加入 `/brief` baseline
- P1-7: P1 阶段验证与截图评审

---

### Phase P2 · Week 3-4 — B/C 组件 + Hermes artifact-first 骨架 + read-only 数据层

**目标:** 建 B 暗色编辑式基础组件库 + C Hermes 对话/任务流组件 + EditorialFigure 融合容器;搭 Hermes 页骨架与静态对话流(mock 数据验证 C 视觉);接 candidates/detail/review/provenance 与只读 artifact timeline。P2 不接平台侧 LLM runner,不使用 `/api/agent/tasks` 伪造 Hermes 长任务。

**Scope:**
- components/editorial/ 实现 8 个组件:Masthead / Lede / SectionHead / EditorialFigure / PosTable / NewsColumns / HermesQuote / ErrataLog
- components/hermes/ 实现 11 个组件:HermesOrb / UserBubble / HermesMessageCard / HermesExecCard / HermesArtifactCard / HermesArtifactBadge / HermesCodeCard / NewsCard / FillReceiptCard / SystemCard / Daybreak / ComposerDock
- EditorialFigure 融合机制(包裹 C 卡片时抑制 hover/box-shadow,加暖灰 rule + 衬线 figcaption)
- app/hermes/page.tsx + loading.tsx(server 壳 + client 主体三栏 + ComposerDock)
- components/hermes/HermesConversation.tsx 静态对话流(mock 数据)
- lib/api.ts 新增只读 Hermes getters(复用 /api/agent/candidates、candidate detail/review/provenance;或读取 read-only artifact timeline)
- ComposerDock MVP 只做 disabled/queued/local draft 状态或跳转到 HQA 指令,不 POST `/api/agent/tasks`
- `lib/hermesJobs.ts` 后置:只有后端提供真实 job state + `poll_url` 后再实现
- HermesArtifactCard/Badge 跨页组件 + 回流深链
- strategies 页一拆为二(目录 + CTA)
- tests/e2e/hermes.spec.ts

**Deliverables:**
- app/hermes/page.tsx + loading.tsx 骨架
- components/hermes/ 11 个对话流组件(mock 数据)
- components/editorial/ 8 个 B 编辑基础组件
- EditorialFigure 融合容器
- HermesArtifactCard/Badge 跨页组件
- Hermes read-only 数据层(candidate/artifact timeline)
- strategies 页拆分
- hermes.spec E2E + 回流用例

**Dependencies:** P0(token + navConfig + chartTokens),P1(Hermes 在 Sidebar 有入口)

**Validation:**
- type-check + lint + vitest 全绿(含新 Hermes 数据层单测)
- PW_E2E=1 E2E 全绿 + 新增 hermes.spec
- /hermes 页渲染完整 artifact-first 对话流,呼吸动画在 run 态可见且尊重 reduced-motion
- 现有 22 页 E2E 零回归
- Lighthouse 衬线对比度 ≥ 4.5:1

> **P2 的 bite-sized Task 在 P1 完成后展开。色温已裁决:暖灰近黑只用于 `/brief`、`/hermes`、报告/叙事块。**

#### P2 Task 概要(P1 后展开为 bite-sized 步骤)

- P2-1 ~ P2-8: 逐个实现 editorial 组件(每个一个 Task:TDD,先写 vitest + 可选 screenshot,再实现)
- P2-9 ~ P2-19: 逐个实现 hermes 组件(每个一个 Task)
- P2-20: EditorialFigure 融合容器(包裹 C 卡片印刷化)
- P2-21: app/hermes/page.tsx + loading.tsx 骨架
- P2-22: HermesConversation.tsx 静态对话流(mock)
- P2-23: lib/api.ts Hermes read-only getter(candidate/detail/review/provenance 或 artifact timeline)
- P2-24: ComposerDock MVP disabled/queued/local draft 状态,不接 `/api/agent/tasks`
- P2-25: HermesArtifactCard/Badge 跨页 + 回流深链
- P2-26: strategies 页拆分
- P2-27: tests/e2e/hermes.spec.ts
- P2-28: P2 阶段验证

---

### Phase P3 · Week 5-6 — approval/factor evidence parity + 一条核心迁移

**目标:** 先把 agent-studio 与 factor-lab 的有用能力吸收到 Hermes:候选列表、源码预览、审计/review、approve affordance、历史 factor run evidence/charts/provenance。完成 parity 后,再迁移一条核心研究页面(backtest 或 data-explorer)验证 B/C 回流模式。首页替换仍以后续 `/brief` 实屏确认作为门槛。

**Scope:**
- Hermes approval parity: candidate list/source preview/audit/reviews/approve 状态搬入 `/hermes`
- Hermes factor evidence parity: historical factor run detail/charts/provenance 搬入 read-only evidence panel 或 generic run detail
- app/backtest 或 app/data-explorer 选择一条核心页面做编辑式迁移,保留 form hooks 零改动
- Hermes 回流徽章集成(由 Hermes 产出的 artifact/run 显示 HermesArtifactBadge)
- visual.spec 相关页基线更新

**Deliverables:**
- approval queue/detail parity
- factor run evidence/detail parity
- 1 条核心页面编辑式皮肤
- Hermes 回流徽章集成
- visual.spec 基线更新

**Dependencies:** P2(B/C 组件库 + Hermes 数据层)

**Validation:**
- 每迁一页 type-check + lint + vitest + 该页 E2E 全绿
- 视觉 diff 手动截图确认只皮肤变布局数据不变
- 全量 E2E 里程碑跑一次确认无跨页回归
- 手动跑一次被迁移页面的 sample flow 确认原 API 行为不变

---

### Phase P4 · Week 7+ — homepage decision + 软下线/物理删除 follow-on

**目标:** 在 `/brief` 与 `/hermes` 经实屏确认、approval parity/factor evidence parity 通过后,再决定是否把 `/` 替换为 Morning Brief / Workbench,并分阶段下线 factor-lab/agent-studio。物理删除与大件迁移不属于 3-4 周 MVP。

**Scope:**
- 首页决策:若 `/brief` 明显优于 dashboard,替换 `/`;旧 dashboard 可保留 `/dashboard`
- 软下线:从 nav/quick actions 移除 factor-lab/agent-studio,加带上下文的 redirect/archived 状态
- 物理删 app/factor-lab/ 与 app/agent-studio/ 目录(仅 parity 完成后)
- 删或迁移孤儿组件(FactorLabControls/FactorLabDashboard/FactorRunForm/AgentTaskForm/FactorRunCharts)
- 删或迁移 lib/factorLabHandoff.ts + test
- lib/api.ts 移除已无引用的 factor-lab 专用 getter(保留 getFactors/getUniverses)
- E2E(phase10-smoke/run-detail-routes)更新
- contract 测试移除 agent-studio fragments 断言
- 后端 agent.py 保留(供 candidates/detail/review/provenance 读面)
- weekly follow-on:迁移 options cluster / paper-trading / position-map 大件

**Deliverables:**
- 首页替换或保留的明确裁决
- 两旧入口软下线 + 可回滚重定向
- 两目录物理删除(可拆 follow-on)
- 孤儿组件删除或迁移
- lib/api factor-lab getter 移除
- E2E + contract 测试更新
- 大件迁移计划或 follow-on 列表

**Dependencies:** P3(approval parity + factor evidence parity 已完成,Hermes 已承接旧入口能力)

**Validation:**
- type-check + lint + vitest + E2E + contract 全绿
- `grep -r 'factor-lab|agent-studio|FactorLab|AgentStudio' app components lib` 确认零残留(除 next.config 重定向规则与历史注释)
- 访问 `/factor-lab` `/agent-studio` 确认 308→`/hermes`
- build 产物体积对比确认未因孤儿残留膨胀

---

## Self-Review

### 1. Spec coverage(对照讨论结论)

- [x] Q1 色温改为当前实屏确认的 warm shell + sidebar rail → Q1 + Slice 0
- [x] Q2 首页晨报路径保持 `/brief` 试跑,标题「每日晨报」→ Q2 + Slice 7
- [x] Q3 Hermes 一等入口但不抢替 `/` → Q3 + 旧 P1/P2 backlog
- [x] Q4 factor run history 不隐藏、不无上下文跳转 → Q4 + 旧 P3/P4 backlog
- [x] Q5/Q6 Hermes 后端复用读面,artifact-first + polling → Q5/Q6 + 旧 P2 backlog
- [x] Q7 执行节奏从 P0-P4 修订为 slice0-slice7 → Q7 + Slice Gate Summary
- [x] Q8 scoped 视觉基线 → Q8 + Slice 7 + 旧 P0-8 backlog
- [x] Q9 strategies/Hermes promote 关系 → Q9 + 旧 P2/P3 backlog
- [x] Q10 晨报内容必须来自真实数据或归档快照 → Q10 + Slice 1/2/3/7
- [x] Q11 操作型页面保持 workbench 子风格 → Q11 + 旧 P3/P4 backlog
- [x] DP1-DP6 数据持久化裁决 → 新增数据持久化裁决 + Slice 1-6
- [x] root 用户与 brief/AI schema → File Structure + Slice 1
- [x] `/brief/{public_id}` 不可变归档 → Slice 2 + Slice 7
- [x] AI HOT daily report cache → Slice 3
- [x] paper account ledger/positions backfill → Slice 4
- [x] paper account dual-write mirror + reconciliation → Slice 5
- [x] paper account DB canonical fail closed → Slice 6
- [x] 旧前端 P0-P4 详细设计仍保留,并标记为 backlog/历史参考 → 分阶段计划前说明

**未覆盖项:** 无。旧 P1/P2/P3/P4 仍有概要任务,但当前可执行路线已经由 slice0-slice7 给出 bite-sized TDD 步骤和命令;旧概要仅作为前端 redesign backlog。

### 2. Placeholder scan

- 当前权威 slice0-slice7 已交付到 Slice 7;Slice 6/7 代码已提交。后续前端 redesign 以旧 P1/P2 backlog 展开为 Slice 8+。
- 旧 P0-P4 内保留的“阶段概要”已被文档明确标记为历史 backlog,不得作为当前执行路线照抄。
- 旧 P0 中关于“冷黑 token 值不变”的措辞已改成“无布局/可读性回归”,与 Q1 当前裁决一致。

### 3. Type consistency

- `BriefGenerateRequest`, `BriefIssueResponse`, `BriefSnapshotResponse`, `BriefIssueEnvelope` 在 Slice 2 schema 中定义,API route 和前端 getter 使用同一字段名。
- `buildBriefIssuePath(publicId)` 在 Slice 2 定义,Slice 7 E2E 只检查 `/brief/brf_*` 前端 route 与 `/api/brief/issues/{public_id}` API route。
- `app_users.id` 使用固定 root UUID `00000000-0000-0000-0000-000000000001`,`brief_issues.owner_user_id` 与 `paper_accounts.owner_user_id` 均引用该表。
- `PaperAccountSettings.db_mode` 只允许 `"file" | "mirror" | "canonical"`。Slice 5 中 factory 对 `"mirror"` 启用 file-first dual-write;`"canonical"` 暂回落文件并 warning,避免提前进入未实现 DB authoritative methods。Slice 6 再改为 DB canonical + fail-closed。
- `PaperAccount.ledger` 字段名与 `paper_account_ledger` columns 一一对应: `entry_id`, `timestamp`, `kind`, `source`, `symbol`, `side`, `quantity`, `price`, `gross_value`, `commission`, `price_kind`, `realized_pnl_delta`, `cash_after`, `note`。
- 旧前端 `ChartTheme`、`NavSection`、editorial/hermes token 名仍保留在 P0-P4 backlog,但当前先执行 persistence slices。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - 每个 slice 派 fresh subagent 执行,主线程做 review 与集成。共享文件禁止并行写;Slice 1/2/3 可由后端 agent 顺序推进,Slice 7 可在 Slice 2 之后由前端 agent 接手。

**2. Inline Execution** - 当前会话按 slice0 → slice7 顺序执行,每个 slice 完成后暂停做测试结果与 diff review。

**Recommended next slice:** Slice 0-Slice 7 已完成。下一步 Slice 8: Hermes 一等公民页骨架 + Sidebar/TopBar 完全接入 `navConfig`(保留 factor-lab/agent-studio,不 POST `/api/agent/tasks`)。
