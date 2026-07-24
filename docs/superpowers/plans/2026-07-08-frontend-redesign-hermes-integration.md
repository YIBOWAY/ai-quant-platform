# 前端渐进改造与 Hermes 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-quant-platform 前端从当前 QUANTUM_CORE 冷黑终端风,渐进改造到「B 暗色编辑式 + C Hermes 对话流」混合新视觉,同时新增 Hermes 一等公民页面、每日晨报归档入口、Postgres 业务事实持久化,并安全下线 factor-lab 与 agent-studio 两页,不破坏现有 22 页功能或任何交易安全闸门。

**Architecture:** 2026-07-08 修订版采用「统一 warm near-black shell + sidebar rail token」作为全局底色,`/brief` 暗色晨报与 `/hermes` 对话流在同一主题内 opt-in 编辑式/对话式组件。数据侧采用 expand-contract:先把每日晨报快照、AI HOT daily report、paper account ledger/positions 作为可查询可审计业务事实写入 Postgres,大体量回测 artifact/Parquet/DuckDB/JSONL 继续留在文件或专用缓存。平台数据访问模式(`lib/api.ts`/`lib/apiClient.ts` + TanStack Query)保持同构,Hermes 后端 MVP 只复用现有 agent candidates/detail/review/provenance 读面;不复活平台侧 LLM runner,不前端伪造异步 job。paper account 迁移走 mirror → reconciliation → DB canonical 三步,防止 AAPL 这类文件状态漂移再次发生。

**Tech Stack:** Next.js 15 App Router · React 19 · Tailwind 4(@theme + @tailwindcss/typography)· TanStack Query 5 · recharts + lightweight-charts · motion(^12,已装零启用)· react-hook-form + zod · Vitest · @playwright/test · next/font/google(Source Serif 4 + Noto Serif SC)· FastAPI 后端(:8765)

## 当前执行状态（2026-07-12）

本文件现在是 **Slice 0-8 实现记录与未来前端 backlog**。当前实现已切到
HQA，并已完成 `2026-07-10-phase-1a-4-v2.md` 的 Slice 9A-9G + mini 9H，以及
`2026-07-12-full-9h-automation-notifications.md` 的完整 9H。跨仓产品方向仍由 HQA
roadmap 管理；目前没有选定下一实现切片。

| 事实层 | 状态 |
|---|---|
| Slice 0-8 | 本文件保留已交付实现和未来前端 backlog；Git/进程状态在每次交接时由命令核验，不在计划正文维护易腐 ahead/dirty 快照。 |
| Slice 9A-9G + mini 9H | 已完成。9G 是 HQA ledger + 平台 CLI-only observation seam，没有新增数据库 migration、HTTP route、前端或 `/hermes` 卡片。 |
| 完整 9H | 已完成。调度、对账、周报、freshness 与通知位于 HQA；平台兼容 feed 1.0/1.1 并展示六类只读产物。 |
| 当前选择 | 尚未选定下一实现切片。未来前端 backlog 需要新的产品决定，并按最新源码另立独立 bite-sized plan。 |

复审结果为旧 HQA Phase 1a-4 **ACCEPT-AFTER-REPLAN**；v2 Slice 9A-9G + mini 9H
与完整 9H 后续计划均已交付。当前 handoff 不从本文件直接续写旧 P2/P3，也不预选
新的实现切片。
旧 P0-P4 的逐步代码模板已移入
[归档计划](../../archive/plans/2026-07-08-frontend-redesign-hermes-integration-original-p0-p4.md)，
不能直接照抄执行。

当前 full 9H 审查门禁：平台 Python 全量 `1122 passed, 15 skipped`；前端 Vitest
24 files / 85 tests、type-check 与 ESLint 通过；feed schema 1.0 精确三来源和 1.1
精确六来源的后端/前端合同均通过；throwaway
PostgreSQL 的 13 个 migration / persistence / backfill / reconciliation / advisory-lock tests 通过。
`api.generated.ts` 已从当前 OpenAPI
确定性重生成，并由 focused contract test 覆盖 brief、paper snapshot 与 reconciliation。
2026-07-10 历史验收时，live backend/数据库、brief archive、Hermes 与 paper 页面 smoke 已验收；
`brief-zh.png` / `hermes-desktop.png` 已在禁用 AI HOT 外网的隔离 E2E 环境生成并稳定
复跑；改用按端口复制的临时前端工作区后，E2E 不再干扰当前 3001 服务或改写源码侧
TypeScript 配置。这些 live、截图与运行栈事实是历史快照，不是永久证明。

当前平台 full 9H 合同仅扩展只读消费：schema 1.0 必须精确三来源，schema 1.1 必须
精确六来源；`/hermes` 展示 risk、prediction、foresight、weekly、opportunity 与
automation，whole-feed freshness budget 为 10800 秒。scheduler、outbound worker
与通知投递留在 HQA；平台没有新增 POST route 或数据库 migration。

Slice 9D 的平台合同是严格只读 `quant-system data prices` JSON seam：显式
Futu/QFQ/1d，最多 25 个标的和 500 个含首尾日历日期，不从 sample、local、Tiingo 或
Longbridge 回退。HQA portfolio-risk v2 使用 previous UTC date 为 `end`、`end-400 days`
为 `start`，
在收益计算前做 global date inner join，至少要求 60 个对齐收益；只计算逐仓相对 SPY
的 beta 和持仓两两 correlation，不计算 aggregate beta、VaR 或阈值 verdict。这里是
2026-07-11 的当前快照，不覆盖上面的历史交付日期。

## Global Constraints

- **项目路径:** ai-quant-platform 前端在 `/Users/sunyibo/programs/ai-quant-platform/src/frontend`,后端在 `/Users/sunyibo/programs/ai-quant-platform/src/quant_system`。本计划所有前端文件路径相对 `src/frontend/`,后端相对 `src/quant_system/`。
- **不破坏现有功能红线:** 迁移期不改现有业务 getter 语义、不改 `lib/apiClient.ts`、不改各 form 的 `useQuery/useMutation` 调用点。视觉迁移只改 `className` + JSX 结构 + 原语替换。Hermes/brief getter 必须是 read-only additive wrapper;允许读取 `/api/paper/account/snapshot` 与 `/api/paper/account/equity-curve`,但不得触发策略、回测、paper account mutation、真实券商或任何交易链路。
- **token 演进红线:** 不重命名或删除现有 `globals.css` token 与 Material-3 兼容别名。2026-07-08 已拍板把全局底色统一到 warm near-black (`--color-bg-base #12110E`) 并新增 sidebar rail token (`--color-bg-sidebar #1C1B20`, `--color-bg-sidebar-muted #25242A`);后续视觉改动只能通过语义 token 扩展或局部 class opt-in,不能散落硬编码色值。
- **Postgres 持久化边界:** Docker Postgres 只承载可查询、可审计、需要稳定回看的业务事实:brief issues/snapshots/sources、AI HOT daily reports、paper account ledger/current positions/snapshots/root user。大体量 backtest artifact、OHLCV 宽表、DuckDB option cache、Prediction Market JSONL/HTTP cache 暂不迁入 Postgres。
- **paper account 安全迁移:** `PaperAccount.ledger` 是权威事件流。迁移时禁止只迁 cash/positions 当前视图；必须先 backfill ledger + current positions，再 dual-write + reconciliation，最后经人工运营门切 DB canonical。canonical 模式下 PostgreSQL authoritative，数据库不可用时 mutation fail closed；不得伪造“最后快照”或静默切回 file。`stale/warnings/reconciliation` 只陈述存储事实，不自动切模式。
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

本节是 2026-07-08 多子智能体评审与后续实屏反馈后的执行裁决。后续
Slice 0-Slice 8 必须以本节为准；若与归档的旧 P0-P4 任务代码块冲突，以本节为准。

- [x] **Q1【全局色温】** 全局 shell 采用 warm near-black,不是冷黑。当前已执行裁决:`--color-bg-base #12110E`,主内容区渲染 `rgb(18,17,14)`;sidebar rail 采用稍浅同主题色 `--color-bg-sidebar #1C1B20`,hover/active 使用 `--color-bg-sidebar-muted #25242A`。`/brief` 与 `/hermes` 继续使用 paper/editorial 语义 alias,但不得再把 sidebar 做成孤立冷蓝/冷灰。

- [x] **Q2【首页是否变晨报】** 每日晨报是目标方向,但 `/` 不在第一刀替换。先把 `/brief` 做成 direction B 栏目布局的一比一试跑页,标题定为「每日晨报」;实屏满意后再决定 `/` 是否变晨报入口。旧 dashboard 可保留为 `/dashboard` follow-on。

- [x] **Q3【Hermes 是否取代 dashboard 成主入口】** `/hermes` 是一等入口,但不抢先替代 `/`。若 `/brief` 后续升首页,则 `/` 是每日晨报入口,`/hermes` 是操作/对话/调度入口,旧 dashboard 退到 `/dashboard`。

- [x] **Q4【历史 factor run 记录处理】** 不隐藏历史 factor run。目标是 read-only generic run evidence/detail;在该视图完成前,保留旧 deep link。后续如迁到 `/hermes?runId=...`,必须显示 archived/provenance 状态,不能静默 308 到无上下文的 `/hermes`。

- [x] **Q5【Hermes 复用 agent.py 还是新建 hermes.py】** 复用 `agent.py` 的 candidates/detail/review/provenance 读面,但不扩展 `POST /api/agent/tasks` 为 Hermes runner,不前端单独添加 `propose-strategy`。若 UI 需要 Hermes timeline,只新增窄的 read-only `/api/hermes/timeline` 或 artifact 聚合端点。

- [x] **Q6【Hermes 流式传输方式】** MVP 采用 artifact-first + polling。只有当后端返回真实 job state + `poll_url` 时才新增 `lib/hermesJobs.ts`;当前 `/api/agent/tasks` 是同步端点,不能按异步 job 使用。SSE 后置,WebSocket 不做。

- [x] **Q7【总工期/执行节奏】** 当前执行方式从旧 P0-P4 线性阶段修订为 Slice 0-Slice 8：先确认现状与契约，再做 brief 持久化、AI daily cache、paper account DB mirror/canonical，随后交付 `/brief` 归档入口与 `/hermes` 只读骨架。全量 redesign、options cluster、position-map、旧页面物理删除属于 follow-on，必须重新展开为后续 slice。

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
- [x] **DP6【失败模式】** DB mirror 阶段数据库不可用时继续文件路径并记录 warning；DB canonical 阶段数据库不可用时 mutation fail closed，读失败显式返回错误，不伪造 file fallback。

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
| `src/quant_system/api/schemas/brief.py` | FastAPI generate/latest/by-id response/request schema |
| `src/quant_system/api/routes/brief.py` | `POST /api/brief/issues/generate`、`GET /api/brief/issues/latest`、`GET /api/brief/issues/{public_id}` |
| `src/quant_system/news/daily_report_repository.py` | `GET /api/news/aihot/daily` 成功后写 `ai_news_daily_reports`,失败时可读缓存并带 warning |
| `src/quant_system/execution/account_repository.py` | repository contract + 结构化 reconciliation result/difference schema |
| `src/quant_system/execution/account_repository_factory.py` | API/CLI/operations 共用 factory；精确选择 `file`/`mirror`/`canonical`，不静默回落 |
| `src/quant_system/execution/account_postgres_repository.py` | Postgres paper account mirror/canonical 实现,按 ledger 写入并物化 current positions |
| `src/quant_system/execution/account_dual_write_repository.py` | mirror 阶段先写文件、再 best-effort 写 DB;DB 失败不改变 response,但记录 warning log |
| `src/quant_system/execution/account_backfill.py` | 显式单文件 backfill：调用方提供一个 account/archive JSON → account/ledger/current positions/snapshots |
| `src/quant_system/execution/account_storage.py` | file repository；集中校验 account ID，并提供只读 `not_applicable` reconciliation |
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
| `src/quant_system/api/schemas/paper.py` | additive 暴露 `storage_mode` / `stale` / `warnings` / `reconciliation` |
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

## 2026-07-08 权威执行节奏（Slice 0-Slice 8）

> 本节是当前执行路线。旧 P0-P4 已移入归档，只保留设计素材；真正开工按
> Slice 0-Slice 8 和后续明确新增的 slice 推进。每个 slice 完成后必须跑本节列出的
> 验证命令；共享文件（`globals.css`、`lib/api.ts`、`paper.py`、`settings.py`）不得并行写。

### Slice 0 — 现状锁定与计划同步

**Goal:** 把已做过的 `/brief`、全局色温、paper account 只读接口、AAPL 排查结论写入契约,避免后续 worker 按旧计划回退。

**Files:**
- Modify: `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`
- Modify: `src/frontend/lib/design-tokens.test.ts`
- Read-only verify: `data/api_runs/paper_account/default/account.json`, `data/api_runs/paper_account/default/archive/*.json`

- [x] **Step 1: 锁定当前全局色温测试**

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

- [x] **Step 2: 运行前端契约**

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

- [x] **Step 3: 记录 AAPL 现状为迁移输入,不修改账户文件**

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

- [x] **Step 4: 提交计划同步** — 由 2026-07-08 的 plan/foundation commits 覆盖。

```bash
cd /Users/sunyibo/programs/ai-quant-platform
git add docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md src/frontend/lib/design-tokens.test.ts
git commit -m "docs(frontend): align Hermes redesign plan with persistence slices"
```

### Slice 1 — Brief/AI schema migration + root seed

**Goal:** 建 Postgres 表,让每日晨报和 AI HOT daily report 有稳定、可查询、可回看的存储面。

**Status 2026-07-10:** Slice 1 schema foundation 已完成。Migrations 003/004 已在
throwaway `quantplatform_codex_tmp` 通过当前 13 个 PostgreSQL tests，并确认 11 张业务表
存在；live 8765 也已重启并把两份 migration 应用到 `quantplatform`。实际 SQL 以
`scripts/sql/003_app_users_brief_ai_reports.sql` 为准；下方保留执行摘要，不再以内联
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

- [x] **Step 4: 重启 live backend，执行 auto-migrate 并核对 live 表**

2026-07-10 已备份 live DB 后重启 8765；health 显示 database reachable，live
`quantplatform` 已确认 003/004 的 11 张目标表真实存在。该证据与 throwaway DB 测试
分开记录。

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

- [x] **Step 5: 提交** — 已由 `e9b7389` 合并交付 Slice 1-Slice 3。

```bash
git add scripts/sql/003_app_users_brief_ai_reports.sql tests/test_api_brief_persistence.py
git commit -m "feat(db): add brief and AI daily report persistence schema"
```

### Slice 2 — Brief repository/API + `/brief/{public_id}`

**Goal:** 让 `/brief` 可以生成当天归档快照,并让 `/brief/{public_id}` 稳定读取已归档内容。

**Status 2026-07-08:** Slice 2 已完成后端 repository/API 与前端归档页最小闭环。默认
测试环境数据库关闭时不会伪造归档;真实归档只从 Postgres snapshot 读取。当前已实现
`POST /api/brief/issues/generate` 与 `GET /api/brief/issues/{public_id}`;`/api/brief/live`、
`/api/brief/issues/latest` 与 `/brief` 上的归档入口当时留给 Slice 7，现已交付。

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

- [x] **Step 8: 提交** — 已由 `e9b7389` 合并交付 Slice 1-Slice 3。

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

- [x] **Step 6: 提交** — 已由 `e9b7389` 合并交付 Slice 1-Slice 3。

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

2026-07-10 补充：migration 004 已在 throwaway DB 与 003 一起实测，也已由重启后的
8765 应用到 live 库；现有一个 account 已显式 backfill，mirror/canonical 对账均为
`in_sync`。paper mode 仍刻意保持 `file`，没有自动切换事实源。

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

-- UNIQUE (account_id, seq) 已提供同列 B-tree；当前 migration 会删除旧重复索引。
DROP INDEX IF EXISTS quant_system.idx_paper_ledger_account_seq;

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

- [x] **Step 5: 提交** — commit `f56dbf4`。

```bash
git add scripts/sql/004_paper_account_tables.sql src/quant_system/execution/account_backfill.py tests/test_paper_account_postgres_repository.py
git commit -m "feat(paper): add Postgres schema and backfill path for paper account ledger"
```

### Slice 5 — Paper account dual-write mirror + reconciliation

**Goal:** API mutation 仍以文件为事实源,同时写 DB mirror 并暴露 reconciliation 差异,不改变外部 response contract。

**Status 2026-07-10:** commit `322879b` 已交付 file-authoritative dual-write mirror。
当前 code-review 工作树补齐结构化 reconciliation：mirror 用 file account 对比
PostgreSQL raw/materialized state，file 返回 `not_applicable`，差异以 summary hash、typed
differences 和 snapshot freshness 表达。API additive 返回
`storage_mode/stale/warnings/reconciliation`。这些 review 修复尚未提交。

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
- `canonical` 的真实 DB read/reset/fail-closed 由 Slice 6 交付；不要把本段 Slice 5
  的中间态代码块当作当前 factory 实现。

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

- [x] **Step 7: 提交** — commit `322879b`。

```bash
git add src/quant_system/config/settings.py src/quant_system/api/routes/paper.py src/quant_system/cli.py src/quant_system/execution/account_repository.py src/quant_system/execution/account_repository_factory.py src/quant_system/execution/account_postgres_repository.py src/quant_system/execution/account_dual_write_repository.py src/quant_system/execution/account_backfill.py tests/test_settings.py tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py tests/test_cli.py
git commit -m "feat(paper): mirror paper account mutations to Postgres"
```

### Slice 6 — Paper account DB canonical + fail-closed mutation

**Goal:** 实现 DB-authoritative canonical 能力与 fail-closed contract。真正把运行环境
切到 canonical 是独立运营动作，必须在 live migration/backfill/reconciliation 连续通过后执行。

**Status 2026-07-10:** canonical repository 能力已由本地 commit `c78140b` 实现；
`@Code Reviewer` 后续补齐 account ID 校验、缺账户 bootstrap fail-closed、锁内业务异常
原样传播、纯读取不修复文件，以及覆盖 account/ledger/positions/pending/latest snapshot
的结构化 reconciliation。live 账户 backfill 和 mirror/canonical smoke 已通过，但配置
仍是默认 `file`；因此只能宣称能力已验收，不能宣称运行事实源已切到 canonical。

**Slice 6 notes from Slice 5 review:**
- `PostgresPaperAccountRepository.load/load_or_open/reset` 必须成为 DB authoritative,且 DB 不可用时 mutation fail closed。
- response 字段只能 additive（`storage_mode`/`stale`/`warnings`/`reconciliation`），旧前端必须可忽略。
- 切换前定义 reconciliation criteria：raw account、账户物化列、完整 ledger 物化
  字段/row raw/seq、current positions、pending orders、latest snapshot state/integrity/
  provenance/freshness 必须连续通过；canonical 缺账户只能显式 backfill，普通 GET
  不得 bootstrap。
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
reconciliation: PaperAccountReconciliationResponse | None = None
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

**Status 2026-07-10:** 归档入口代码已由 `fc85598` 提交；重启后的 current backend
已生成并读取 `brf_20260710_3yz4rm`，浏览器完成 `/zh/brief` → archive、`/zh/hermes`
和 `/zh/paper-trading` smoke，未见 console warning/error。`brief-zh.png` 已在
`QS_AIHOT_ENABLED=false` 的隔离 Playwright 环境生成并复跑通过。

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

- [x] **Step 4: 完成 Playwright/runtime 验收**

Vitest/type-check/lint 已通过；brief archive、Hermes baseline 与 brief baseline 已在
隔离 backend/frontend 上通过（3 passed）。Playwright 后端显式禁用 AI HOT，避免
browser test 触发真实外网。

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
| 5 | paper account API/CLI mutation 双写 DB mirror，结构化 reconciliation 可发现漂移 | `pytest tests/test_api_paper_account.py tests/test_paper_account_postgres_repository.py -q`, opt-in PG tests |
| 6 | DB canonical authoritative + mutation fail closed；运行环境仍需单独切换 | `pytest tests/test_api_paper_account.py tests/test_api_response_models.py tests/test_paper_account_postgres_repository.py -q` |
| 7 | `/brief` 可跳归档,视觉基线覆盖日报 | `PW_E2E=1 npx playwright test tests/e2e/brief-archive.spec.ts tests/e2e/visual.spec.ts` |
| 8 | `/hermes` 只读骨架 + Sidebar/TopBar 完全由 `navConfig` 驱动 | `pytest tests/test_frontend_topbar_navigation_contract.py tests/test_frontend_terminal_surface_contract.py -q`, `npx vitest run lib/navConfig.test.ts`, `npm run type-check`, `npm run lint` |
| 9A | strategy GET/status 严格只读；crash recovery 显式分缝 | 见 HQA `2026-07-10-phase-1a-4-v2.md`；`pytest tests/test_paper_strategy_operations.py tests/test_api_paper_strategy_sleeves.py tests/test_cli.py -q` |
| 9B | API/CLI/HQA 共用统一 paper snapshot read-model | 见 HQA `2026-07-10-phase-1a-4-v2.md`；`pytest tests/test_paper_account_snapshot.py tests/test_cli.py -q` |
| 9C | HQA 只读当前 snapshot 的敞口/集中度 artifact | 见 HQA `2026-07-10-phase-1a-4-v2.md` 与 HQA `tests/test_portfolio_risk.py` |
| 9D | 严格 Futu/QFQ/1d 历史价格 seam + portfolio-risk v2 | `pytest tests/test_price_history.py tests/test_cli_price_history.py -q`；HQA `tests/test_historical_risk.py tests/test_portfolio_risk.py` |
| 9E | HQA 并发安全 prediction ledger；平台代码/schema/前端无改动 | 见 HQA active v2 plan；HQA `tests/test_predictions.py tests/test_prediction_cli.py tests/test_install.py` |
| 9F | HQA proposal-only market-foresight；严格 Futu/QFQ evidence、原子/幂等发布 | 见 HQA `2026-07-12-slice-9f-mini-9h.md` 与 `tests/test_market_foresight.py` |
| mini 9H | HQA versioned feed → `GET /api/hermes/artifacts` → `/hermes` 真实只读卡片 | `pytest tests/test_api_hermes_artifacts.py tests/test_api_response_models.py -q`；前端 Vitest/type-check/lint；live browser smoke |
| 9G | HQA stable signal/decision/action/coverage ledger + 平台 bounded observation CLI；无 DB/API/UI | 见 HQA `2026-07-12-slice-9g-opportunity-ledger.md`；平台 `pytest tests/test_paper_strategy_observations.py tests/test_cli.py -q` |
| 完整 9H | HQA 调度/对账/周报/freshness/通知 + feed 1.1；平台双版本只读消费与六类卡片，无 scheduler/outbound worker/POST/DB migration | 见 HQA `2026-07-12-full-9h-automation-notifications.md`；平台 Python 全量、前端 Vitest/type-check/lint、13 个 PostgreSQL tests |

### Slice 8 — Hermes first-class shell + navConfig chrome

**Goal:** 把 Hermes 做成一等公民只读工作台骨架,并把 Sidebar/TopBar 完全接到 `lib/navConfig.ts` SSOT。保留 factor-lab/agent-studio 入口;不启用 `POST /api/agent/tasks`、不复活平台侧 LLM runner、不提交 paper/live 交易动作。

**Status 2026-07-10 historical:** 代码当时已落地并本地验证通过，但尚未 commit；
当前发布状态不由这一历史 checkbox 维护。

**Files:**
- Create: `src/frontend/app/hermes/page.tsx`
- Create: `src/frontend/app/hermes/loading.tsx`
- Create: `src/frontend/components/hermes/ComposerDock.tsx`
- Modify: `src/frontend/components/hermes/index.ts`
- Modify: `src/frontend/components/Sidebar.tsx`
- Modify: `src/frontend/components/TopBar.tsx`
- Modify: `src/frontend/app/page.tsx` (dashboard quick action → `/hermes`)
- Modify: `tests/test_frontend_topbar_navigation_contract.py`
- Modify: `tests/test_frontend_terminal_surface_contract.py`
- Modify: `src/frontend/tests/e2e/navigation-layout.spec.ts`
- Modify: `src/frontend/tests/e2e/visual.spec.ts` (`hermes-desktop.png` 已生成并稳定复跑)

- [x] **Step 1: Sidebar/TopBar 改为 `navConfig` 驱动**
  - `Sidebar` / `TopBar` 从 `navSections` + `isVisibleOnSurface(..., "sidebar"|"mobile")` 映射
  - labels 仍用本地 en/zh copy;routes/icons 不硬编码列表
  - TopBar Terminal 图标 → `/hermes`, `aria-label={text.openHermes}`
  - Sidebar/mobile 链接保留 `aria-current="page"`

- [x] **Step 2: `/hermes` 只读 RSC 骨架**
  - server component 调 `getAgentCandidates()` 读面
  - safety banner(paper-only)
  - candidates rail + empty stream placeholders + stream tokens
  - `ComposerDock` 默认 `disabled` + `allowSubmit={false}`;`preventDefault`;无 `fetch`/`apiPost`/`AgentTaskForm`/`/api/agent/tasks`

- [x] **Step 3: contract / unit / lint 门禁**
  - `pytest tests/test_frontend_topbar_navigation_contract.py tests/test_frontend_terminal_surface_contract.py` → 11 passed
  - `npx vitest run lib/navConfig.test.ts` → 8 passed
  - `npm run lint` → clean(已去掉 form 上非法 `aria-disabled`)
  - `npm run type-check` → type check OK(沙箱下 `tsconfig.tsbuildinfo` 写失败可忽略)

- [ ] **Step 4: 提交（历史验收时尚未执行；当前状态查 git）**
  ```bash
  git add \
    src/frontend/app/hermes/ \
    src/frontend/components/hermes/ \
    src/frontend/components/Sidebar.tsx \
    src/frontend/components/TopBar.tsx \
    src/frontend/app/page.tsx \
    src/frontend/tests/e2e/navigation-layout.spec.ts \
    src/frontend/tests/e2e/visual.spec.ts \
    tests/test_frontend_topbar_navigation_contract.py \
    tests/test_frontend_terminal_surface_contract.py \
    docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md
  git commit -m "feat(frontend): add Hermes workbench shell driven by navConfig"
  ```

**Out of scope / residuals:**
- 不 POST agent tasks;不启用 composer submit
- 不删除/重定向 factor-lab/agent-studio(parity 后才做)
- Playwright E2E 需本地前端服务；本地隔离端口复跑已通过

---

### Slice 9A — Paper strategy read-model safety seam

权威范围与后续顺序见
`/Users/sunyibo/programs/Hermes-quant-agent/docs/superpowers/plans/2026-07-10-phase-1a-4-v2.md`。
本仓实现结果：

- sleeve list/detail/status GET 与 CLI `ops-status` 走同一个
  `PaperStrategyOpsObserver`，不读 account repository、不拿 mutation lock、不 reconcile。
- status 分开报告 finalized/pending sleeve、pending/corrupt journal；corrupt artifact 在
  显式恢复后仍持续告警。
- `paper strategies recover-pending` 是独立显式 mutation，只恢复 crash journal，不生成
  signal、不创建/处理 execution plan；canonical account 缺失时 fail closed。
- API schema、OpenAPI generated types、手写 TypeScript 与 PaperStrategyOpsPanel 已同步；
  file/mirror/canonical、CLI text/json、missing storage 与 bytes/mtime 目录指纹均有回归测试。
- `ops-status --window` 只接受 `next_open` / 规范化的 `next-open`，拼写错误非零退出。
- Playwright 使用按端口复制的 `.tmp/e2e-frontend-*` 临时工作区，不再清理正在运行
  前端的 `.next`，也不改写源码侧 `next-env.d.ts`/`tsconfig.json`；关键三页在隔离
  E2E 前后均保持 HTTP 200。

本 slice 在当时验收点尚未 commit/push；这是历史事实，当前发布状态以 git 为准。

---

### Mini 9H historical follow-on — real read-only artifact shelf

**Status 2026-07-12 historical:** 本地代码与真实运行验收完成；当时尚未
commit/push，当前发布状态以 git 为准。

- HQA 把 portfolio-risk、folded prediction states、market-foresight candidates 投影到
  `artifacts/hermes-feed/manifest.v1.json`；该 feed 可删除重建，不是新事实源。
- 平台新增窄的 `GET /api/hermes/artifacts?limit=20`，对 manifest 做大小、schema、
  freshness 与语义校验；缺失/损坏/陈旧/部分来源失败均返回稳定状态，不泄漏路径或异常。
- `/hermes` RSC 并发读取候选池和 artifact feed；`ArtifactShelf` 展示三类真实卡片及
  empty/degraded/unavailable 状态。Composer 的 textarea 和按钮继续 disabled，页面没有
  mutation fetch，也不调用 `/api/agent/tasks`。
- live `/zh/hermes` 已显示 AAPL market-foresight、组合风险和三来源状态；prediction
  ledger 当前无正式事件，因此 `empty` 是诚实状态而非未接通。

以上是 mini 9H 当时的历史边界；其中“完整 9H 尚未运行”的陈述不再代表当前状态。
完整 9H 后续已由 HQA `2026-07-12-full-9h-automation-notifications.md` 交付，平台仍只做
schema 1.0/1.1 的确定性只读消费。

---


## 历史前端 backlog

旧 P0-P4 任务已移至 [归档计划](../../archive/plans/2026-07-08-frontend-redesign-hermes-integration-original-p0-p4.md)。它们只保留未来前端 backlog 设计素材，不占用 HQA v2 的 9A+ slice 编号，也不是当前可直接执行的步骤；恢复任一项前必须另立新计划并核对现有代码。

## Self-Review

### 1. Spec coverage(对照讨论结论)

- [x] Q1 色温改为当前实屏确认的 warm shell + sidebar rail → Q1 + Slice 0
- [x] Q2 首页晨报路径保持 `/brief` 试跑,标题「每日晨报」→ Q2 + Slice 7
- [x] Q3 Hermes 一等入口但不抢替 `/` → Q3 + Slice 8
- [x] Q4 factor run history 不隐藏、不无上下文跳转 → Q4 + 旧 P3/P4 backlog
- [x] Q5/Q6 Hermes 后端复用读面,artifact-first + polling → Q5/Q6 + 旧 P2 backlog
- [x] Q7 执行节奏从 P0-P4 修订为 Slice 0-Slice 8 → Q7 + Slice Gate Summary
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
- [x] 旧前端 P0-P4 详细设计已移入 archive，并标记为 backlog/历史参考

**未覆盖项:** 旧 P1-P4 中尚未展开的 follow-on 不是当前执行步骤。需要继续前端改造时，
先做新的产品决定，再从归档 backlog 选择一件并按最新代码另立 bite-sized 计划；不得
借用 HQA 9A+ 编号。

### 2. Placeholder scan

- 当前权威 slice0-slice8 均已有实现记录；Slice 8 在最初验收时尚未提交，该历史状态
  不再承担当前 git 跟踪。后续 redesign 必须从旧 P2/P3 backlog 另立前端计划，不得与
  HQA v2 slice 编号混用。
- 旧 P0-P4 内保留的“阶段概要”已被文档明确标记为历史 backlog,不得作为当前执行路线照抄。
- 旧 P0 中关于“冷黑 token 值不变”的措辞已改成“无布局/可读性回归”,与 Q1 当前裁决一致。

### 3. Type consistency

- `BriefGenerateRequest`, `BriefIssueResponse`, `BriefSnapshotResponse`, `BriefIssueEnvelope` 在 Slice 2 schema 中定义,API route 和前端 getter 使用同一字段名。
- `buildBriefIssuePath(publicId)` 在 Slice 2 定义,Slice 7 E2E 只检查 `/brief/brf_*` 前端 route 与 `/api/brief/issues/{public_id}` API route。
- `app_users.id` 使用固定 root UUID `00000000-0000-0000-0000-000000000001`,`brief_issues.owner_user_id` 与 `paper_accounts.owner_user_id` 均引用该表。
- `PaperAccountSettings.db_mode` 只允许 `"file" | "mirror" | "canonical"`。factory 精确选择 file、file-first dual-write mirror 或 DB-authoritative canonical；不静默回落。当前 live 仍配置为默认 `file`。
- `PaperAccount.ledger` 字段名与 `paper_account_ledger` columns 一一对应: `entry_id`, `timestamp`, `kind`, `source`, `symbol`, `side`, `quantity`, `price`, `gross_value`, `commission`, `price_kind`, `realized_pnl_delta`, `cash_after`, `note`。
- 旧前端 `ChartTheme`、`NavSection`、editorial/hermes token 名仍保留在 P0-P4 backlog,但当前先执行 persistence slices。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`.

**Historical Slice 0-8 execution options:**

**1. Subagent-Driven (recommended)** - 每个 slice 派 fresh subagent 执行,主线程做 review 与集成。共享文件禁止并行写;Slice 1/2/3 可由后端 agent 顺序推进,Slice 7 可在 Slice 2 之后由前端 agent 接手。

**2. Inline Execution** - 按当前 slice 顺序执行，每个 slice 完成后暂停做测试结果与 diff review。

**Current handoff:** Slice 9A-9G、mini 9H 与完整 9H 均已实现，目前没有选定下一
实现切片。平台现兼容 schema 1.0 exact-three 与 schema 1.1 exact-six feed，并在
`/hermes` 展示六类只读产物；HQA 负责调度与外发投递。若恢复旧前端 P2/P3 backlog，
必须先有新的产品决定，再按最新源码另立独立 bite-sized plan。Git 与运行状态在每次
交接时现场核验，不在本计划写易腐的 ahead/dirty/尚未推送描述。
