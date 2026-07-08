# 前端渐进改造与 Hermes 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ai-quant-platform 前端从当前 QUANTUM_CORE 冷黑终端风,渐进改造到「B 暗色编辑式 + C Hermes 对话流」混合新视觉,同时新增 Hermes 一等公民页面、安全下线 factor-lab 与 agent-studio 两页,不破坏现有 22 页功能。

**Architecture:** 纯加法 token 演进(不重命名现有 token)→ `/brief` 暗色晨报试跑 + `/hermes` 一等公民入口 → B/C 组件库 + artifact-first Hermes 骨架 → approval parity + factor evidence parity → 用户确认后再替换首页/软下线旧入口 → 后续物理删除收口。平台数据访问模式(`lib/api.ts`/`lib/apiClient.ts` + TanStack Query)保持同构,不触碰交易/执行链路。Hermes 后端 MVP 只复用现有 agent candidates/detail/review/provenance 读面;不复活平台侧 LLM runner,不前端伪造异步 job。若需要 Hermes timeline,只新增窄的 read-only artifact 聚合端点。

**Tech Stack:** Next.js 15 App Router · React 19 · Tailwind 4(@theme + @tailwindcss/typography)· TanStack Query 5 · recharts + lightweight-charts · motion(^12,已装零启用)· react-hook-form + zod · Vitest · @playwright/test · next/font/google(Source Serif 4 + Noto Serif SC)· FastAPI 后端(:8765)

## Global Constraints

- **项目路径:** ai-quant-platform 前端在 `/Users/sunyibo/programs/ai-quant-platform/src/frontend`,后端在 `/Users/sunyibo/programs/ai-quant-platform/src/quant_system`。本计划所有前端文件路径相对 `src/frontend/`,后端相对 `src/quant_system/`。
- **不破坏现有功能红线:** 迁移期不改现有业务 getter 语义、不改 `lib/apiClient.ts`、不改各 form 的 `useQuery/useMutation` 调用点。视觉迁移只改 `className` + JSX 结构 + 原语替换。若新增 Hermes/brief getter,必须是 read-only additive wrapper,且不得接入策略、回测、paper account 或交易链路。
- **token 纯加法:** 绝不重命名或删除现有 `globals.css` 第13-25行 QUANTUM_CORE 冷黑 token 与第27-52行 Material-3 兼容别名。新增 editorial + hermes 两层语义 token,旧 22 页继续用旧 token(值不变)。
- **数据层同构:** 服务端走 `lib/api.ts` 的 `apiGet`(cache:no-store,60s超时,ApiEnvelope fallback),客户端走 `lib/apiClient.ts` 的 `apiRequest`(180s超时,1次重试,AbortController)。Hermes 页必须复用此模式,不新建 fetch 基建。
- **i18n 现状:** middleware.ts 重写做 i18n(非 `[locale]` 段),`localizePath/splitLocalePath` 对任意 pathname 透明。新增 `/hermes` 无需改 `locale.ts`,只需在 Sidebar/TopBar copy 对象加 `nav.hermes` 键(en+zh)。
- **不引入 feature flag:** token 纯加法让新旧视觉天然同进程并存,无需 next.config flag 或 middleware 切换。中途想看旧版直接 `git revert` 页面文件。
- **contract 测试硬约束:** `tests/test_frontend_topbar_navigation_contract.py` 强制 TopBar 含 `href:'/factor-lab'` 与 `href:'/agent-studio'`;`tests/test_frontend_terminal_surface_contract.py` 强制 `app/agent-studio/page.tsx` 含特定 grid 片段。删导航/删页必须同提交更新这两个测试,否则 CI 红。
- **TDD:** 每个新组件/模块先写失败测试(单测或 E2E 断言)再实现。注意当前 `src/frontend/vitest.config.ts` 只 include `lib/**/*.test.ts`;P0 执行前必须先把新 Vitest 测试放入可见路径,或同提交扩展 include,否则 `npm test`/`vitest run` 会漏测。视觉类用 Playwright `toHaveScreenshot` 做 scoped baseline(见 Q8 裁决);逻辑类用 Vitest。
- **频繁提交:** 按可验证切片提交,commit message 用 `feat(frontend):` / `refactor(frontend):` / `test(frontend):` 前缀。P0 可合并为 1-2 个地基提交,不要为了形式拆成 9 个微提交导致 review 成本过高。
- **单人执行:** 这是一人量化研究者的项目,追求低风险、可回滚、可中途停发布。MVP 切线 3-4 周只覆盖 token/nav/`/brief`/`/hermes` skeleton/一条核心迁移;全量 redesign + 旧页物理删除是 6-8 周级别。

---

## 讨论结论摘要(5 个前端子智能体交叉验证)

完整讨论见 workflow 输出。这里只放落地必须的共识与裁决。

### 8 条共识

1. **token 先行且纯加法** — `globals.css` @theme 已有「规范名 + Material-3 兼容别名指向同一调色板」先例(第27-52行),新增 editorial/hermes 语义层零破坏。
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
| D7 | 是否引入 feature flag | **不引入**:token 纯加法天然新旧并存,单人项目过度工程。 |
| D8 | B/C 卡片气质冲突 | **建 `EditorialFigure` 融合容器**:包裹 C 卡片时抑制 hover 上浮与 box-shadow,加暖灰 rule 外框 + 衬线 figcaption,让对话流卡片「印」在版面而非「浮」在版面。两套 up/down 按页面角色分套(操作型用终端色,阅读型用编辑色)。 |

---

## 已拍板的 11 个决策(Q1-Q11)

本节是 2026-07-08 多子智能体评审后的执行裁决。后续 P1-P4 任务必须以这些决策为准;若与下方旧任务代码块冲突,以本节为准。

- [x] **Q1【色温】** 采用暖灰近黑 `#14130F` + 象牙暖白 `#EDE7DA`,但仅用于 `/brief`、`/hermes`、报告/叙事块。操作型页面继续保留冷黑/石墨 terminal workbench,避免全站一刀切。

- [x] **Q2【首页是否变晨报】** 首页晨报是目标方向,但不在 MVP 第一步替换 `/`。先建 `/brief` 作为隔离试跑页,用真实数据和实屏截图确认后,再决定是否把 `/` 升级为 Morning Brief / Workbench。旧 dashboard 可保留为 `/dashboard` follow-on。

- [x] **Q3【Hermes 是否取代 dashboard 成主入口】** P1/P2 阶段 `/` 仍是 Dashboard/安全状态锚点,`/hermes` 放第二位并视觉强化。若 `/brief` 后续升首页,则 `/` 是晨报入口,`/hermes` 是操作/对话入口。

- [x] **Q4【历史 factor run 记录处理】** 不隐藏历史 factor run。目标是 read-only generic run evidence/detail;在该视图完成前,保留旧 deep link。后续如迁到 `/hermes?runId=...`,必须显示 archived/provenance 状态,不能静默 308 到无上下文的 `/hermes`。

- [x] **Q5【Hermes 复用 agent.py 还是新建 hermes.py】** 复用 `agent.py` 的 candidates/detail/review/provenance 读面,但不扩展 `POST /api/agent/tasks` 为 Hermes runner,不前端单独添加 `propose-strategy`。若 UI 需要 Hermes timeline,只新增窄的 read-only `/api/hermes/timeline` 或 artifact 聚合端点。

- [x] **Q6【Hermes 流式传输方式】** MVP 采用 artifact-first + polling。只有当后端返回真实 job state + `poll_url` 时才新增 `lib/hermesJobs.ts`;当前 `/api/agent/tasks` 是同步端点,不能按异步 job 使用。SSE 后置,WebSocket 不做。

- [x] **Q7【总工期期望】** 选择 3-4 周 MVP,硬切范围:token/nav foundation、`/brief` trial、`/hermes` shell、read-only artifact/candidate integration、一条核心页面迁移。全量 redesign、options cluster、paper-trading、position-map、物理删除属于 6-8 周 follow-on。

- [x] **Q8【视觉回归基线】** 引入 Playwright screenshot,但 staged/scoped:先覆盖 6-8 个稳定路由和移动端 shell,对时间戳、动画、动态图表做 mask 或 reduced-motion。不一开始把 22 页 golden master 作为硬门禁;已迁页面才升级为硬 gate。

- [x] **Q9【strategies 与 Hermes 产出归一】** Hermes 生成 `.py` 不自动进入 strategies 目录。必须通过显式 Register/Promote/Gate 3 后,才在 strategies 目录中显示为 promoted strategy;目录可展示 `origin=Hermes`。

- [x] **Q10【晨报 Hermes 导语生成方式】** MVP 使用确定性模板拼接,不新增文本生成 API,不暗示真实 LLM 撰写。文案使用 “Compiled from platform facts” 这一类可信表述。后续若 Hermes 生成 artifact,晨报可读取该 artifact。

- [x] **Q11【操作型页面工作台子风格】** options/paper/settings/screener 等操作页保留更亮、更密集的 workbench 子风格。B/C 只覆盖阅读、报告、对话、artifact 体验;语义绿/红继续只用于真实数据状态。

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

### 删除文件(P4)

| 路径 |
|---|
| `app/factor-lab/` 与 `app/factor-lab/[runId]/` 目录 |
| `app/agent-studio/` 目录 |
| `components/forms/FactorLabControls.tsx` / `FactorLabDashboard.tsx` / `FactorRunForm.tsx` / `AgentTaskForm.tsx`(仅在 Hermes/evidence parity 完成后删除或迁移) |
| `components/FactorRunCharts.tsx`(仅在图表能力已迁入 generic evidence view 后删除) |
| `lib/factorLabHandoff.ts` + `lib/factorLabHandoff.test.ts` |

---

## 分阶段计划

### Phase P0 · Week 1 — 设计地基(token + 字体 + chartTheme + navConfig + 视觉基线)

**目标:** 纯加法扩展 token 层、字体、图表主题、导航配置,不触碰任何现有页面内部样式与原语签名,建立新旧视觉并存的物理基础 + 锁定当前视觉基线。

> **P0 执行前修正:** 当前 `src/frontend/vitest.config.ts` 的 `include` 仅有 `lib/**/*.test.ts`。P0 新增 Vitest 测试统一放在 `lib/*.test.ts`,确保 `npx vitest run` 默认会执行到。

**Scope:**
- `globals.css` @theme 新增 editorial + hermes 语义层(现有 token 零改动)
- `layout.tsx` 加 Source Serif 4 + Noto Serif SC 字体
- 建 `lib/navConfig.ts` 单一导航数据源(不删 factor-lab/agent-studio 项,仅加 Hermes)
- 建 `lib/chartTokens.ts` 两套图表主题
- 3 个图表组件 refactor(签名不变,theme 参数 optional)
- 建 `components/editorial/` + `components/hermes/` 空目录占位
- 建 `tests/e2e/visual.spec.ts` scoped 截图基线(先 6-8 个稳定/高风险路由,不做 22 页硬门禁)
- contract 测试只加不删(新增「新原语存在」「`/hermes` 导航存在」断言)

**Deliverables:**
- `globals.css` 扩展后的 @theme(editorial + hermes 语义层,现有 token 0 改动)
- `lib/navConfig.ts` 单一导航数据源
- `lib/chartTokens.ts` 两套图表主题常量
- 3 个图表组件 refactor 签名不变
- `tests/e2e/visual.spec.ts` scoped 截图基线
- contract 测试新增断言不删旧

**Dependencies:** 无(P0 是一切起点)

**Validation:**
- `npm run type-check` + `lint` + `vitest run` 全绿
- `npm run build` 全绿
- `PW_E2E=1 npm run test:e2e` 全绿(含 scoped visual.spec 首次 capture)
- `pytest tests/test_frontend_terminal_surface_contract.py tests/test_frontend_topbar_navigation_contract.py` 全绿(旧断言未改,仅新增)
- 手动目检 22 个现有页面确认 QUANTUM_CORE 冷黑终端风完全不变(新 token 未被任何现有类引用)
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

- [ ] **Step 5: 手动确认 22 个现有页面视觉不变**

Run: `cd src/frontend && npm run build && npm run dev`,浏览器打开 `localhost:3001` 目检 dashboard/backtest/options-screener 等 3-5 页,确认 QUANTUM_CORE 冷黑终端风完全不变(新 token 未被任何现有类引用)。

- [ ] **Step 6: 提交**

```bash
cd src/frontend
git add app/globals.css lib/design-tokens.test.ts
git commit -m "feat(frontend): add editorial + hermes design token layers (pure additive)

新增 B 暗色编辑式(暖灰近黑)与 C Hermes 对话流(冷紫)两层语义 token,
现有 QUANTUM_CORE 冷黑 token 零改动。22 个旧页视觉不变。
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
- Produces: `terminalChartTheme`(兼容现有 `#00C896`/`#60A5FA`/`#111827` 系)、`editorialChartTheme`(暖灰哑光 + 直角 tooltip)、`readCssVar(name, fallback)` 工具、`ChartTheme` 类型
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
    expect(terminalChartTheme.down).toBe('#F23645');
  });

  it('editorialChartTheme uses warm-grey palette', () => {
    expect(editorialChartTheme.background).toBe('#1A1916');
    expect(editorialChartTheme.up).toBe('#2E9E6A');
    expect(editorialChartTheme.down).toBe('#C84A52');
    expect(editorialChartTheme.tooltipBorderRadius).toBe(2);
  });

  it('both themes have required ChartTheme keys', () => {
    const keys: (keyof ChartTheme)[] = [
      'background', 'up', 'down', 'grid', 'axisLabel', 'tooltipBg', 'tooltipBorderRadius',
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
  up: string;
  down: string;
  grid: string;
  axisLabel: string;
  tooltipBg: string;
  tooltipBorderRadius: number;
};

export const terminalChartTheme: ChartTheme = {
  background: '#111827',
  up: '#00C896',
  down: '#F23645',
  grid: '#2A2A2A',
  axisLabel: '#8A8D95',
  tooltipBg: '#151515',
  tooltipBorderRadius: 8,
};

export const editorialChartTheme: ChartTheme = {
  background: '#1A1916',
  up: '#2E9E6A',
  down: '#C84A52',
  grid: '#3A3733',
  axisLabel: '#A39E92',
  tooltipBg: '#222019',
  tooltipBorderRadius: 2,
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
5. 把所有 `CHART_COLORS.xxx` 替换为 `t.xxx`(background/up/down/grid/axisLabel/tooltipBg)

> **注意:** 不改 lightweight-charts 的 API 调用方式,只替换色值来源。component 签名向后兼容(theme optional 默认 terminal)。

- [ ] **Step 4: refactor EquityComparisonChart.tsx 与 FactorRunCharts.tsx**

同理:删旧 `COLORS` 常量,import `terminalChartTheme` + `ChartTheme`,加 optional `theme` prop,替换色值引用。

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

#### Task P0-9: contract 测试新增「新原语 + /hermes 导航」断言(不删旧)

**Files:**
- Modify: `tests/test_frontend_terminal_surface_contract.py`(新增断言)
- Modify: `tests/test_frontend_topbar_navigation_contract.py`(新增 `/hermes` 断言,不删 factor-lab/agent-studio 断言)

**Interfaces:**
- Produces: contract 测试只加不删,P1 才删旧断言

- [ ] **Step 1: 读现有 contract 测试结构**

读 `tests/test_frontend_topbar_navigation_contract.py` 第30-31行与第42行的 `expected_routes` 断言结构,确认新增 `/hermes` 的位置。

- [ ] **Step 2: 在 topbar navigation contract 加 /hermes 断言**

在 `expected_routes` 列表中新增 `'/hermes'`(不删 `'/factor-lab'` 与 `'/agent-studio'` 两行,P1 才删)。

- [ ] **Step 3: 在 terminal surface contract 加「新原语目录存在」断言**

在 `test_frontend_terminal_surface_contract.py` 末尾新增测试函数:

```python
def test_editorial_and_hermes_component_dirs_exist():
    """P0: editorial + hermes 组件目录已建(P2 填充组件)。"""
    from pathlib import Path
    frontend = Path(__file__).parent.parent / "src" / "frontend" / "components"
    assert (frontend / "editorial" / "index.ts").exists()
    assert (frontend / "hermes" / "index.ts").exists()
```

- [ ] **Step 4: 运行两个 contract 测试确认通过**

Run:
```bash
cd /Users/sunyibo/programs/ai-quant-platform
pytest tests/test_frontend_topbar_navigation_contract.py tests/test_frontend_terminal_surface_contract.py -v
```
Expected: PASS(旧断言 + 新断言全过)

- [ ] **Step 5: 提交**

```bash
cd /Users/sunyibo/programs/ai-quant-platform
git add tests/test_frontend_topbar_navigation_contract.py tests/test_frontend_terminal_surface_contract.py
git commit -m "test(frontend): add /hermes nav + editorial/hermes dir contract assertions

只加不删 — factor-lab/agent-studio 旧断言保留,parity 完成后的 P4 再删。
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
- [ ] **V7:** 手动目检 22 个现有页面 QUANTUM_CORE 冷黑终端风完全不变
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

- [x] token 纯加法(共识1)→ P0-1
- [x] 字体(衬线)→ P0-2
- [x] editorial 排版类 + typography 插件 → P0-3
- [x] navConfig 单一数据源(共识)→ P0-4
- [x] chartTokens 修漂移(共识6)→ P0-5/P0-6
- [x] editorial + hermes 目录占位 → P0-7
- [x] scoped 视觉基线(分歧D6,Q8裁决)→ P0-8
- [x] contract 测试只加不删 → P0-9
- [x] `/brief` 试跑 + Hermes 一等入口(分歧D1/D2/Q2/Q3裁决)→ P1
- [x] B 编辑组件库 → P2
- [x] C 对话流组件库 → P2
- [x] EditorialFigure 融合(分歧D8)→ P2
- [x] Hermes 页骨架 + 静态流 → P2
- [x] Hermes read-only 数据层复用 agent.py candidates/detail/review/provenance(共识5,Q5裁决)→ P2
- [x] Hermes job/polling 后置,不伪造 `/api/agent/tasks` 异步(Q6裁决)→ P2
- [x] strategies 一拆为二 → P2
- [x] approval parity + factor evidence parity → P3
- [x] 一条核心页面迁移 → P3
- [x] Hermes 回流徽章 → P3
- [x] 首页替换裁决 + factor-lab/agent-studio 软下线/物理删除 follow-on → P4
- [x] 大件迁移作为 weekly follow-on(Q7裁决)→ P4

**未覆盖项:** P1/P2/P3/P4 的 bite-sized 步骤仍是概要,这是有意的执行门控。11 个问题已裁决;后续每个阶段开始前按最新 repo 状态展开该阶段的具体 TDD 步骤,避免一次性写死大范围 UI 改造。

### 2. Placeholder scan

- P1/P2/P3/P4 的 Task 概要会在阶段开始前展开为 bite-sized TDD 步骤——这是**有意的阶段门控**,非占位符。
- P0-4 的 navConfig icon 映射标注「需对照 Sidebar.tsx 实际值核对」——执行 agent 读真实代码即可,非占位符。
- 无 "TBD"/"TODO"/"implement later"/"add error handling" 等占位符。

### 3. Type consistency

- `ChartTheme` 类型在 P0-5 定义,P0-6 引用一致
- `NavSection`/`NavItem` 在 P0-4 定义,P1 将引用
- token 名(`--color-paper-ink` 等)在 P0-1 定义,P2 组件将引用
- `terminalChartTheme`/`editorialChartTheme` 在 P0-5 定义,P0-6/P3 引用一致

---

## Execution Handoff

Plan updated and saved to `docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`.

**下一步执行节奏:**

1. 执行 P0 foundation,先修正 Vitest include/test path,再做 token/font/navConfig/chartTokens/scoped visual baseline。
2. 每个切片用 subagent-driven 节奏:一个 writer 执行,随后 spec review + code quality review;共享文件不并行写。
3. P0 结束后用截图和测试结果评审,再展开 P1 的 bite-sized 步骤。
4. P1 先交付 `/brief` 与 `/hermes` 入口,不替换首页、不重定向旧页。
5. P2/P3 继续 artifact-first + parity-first,确认旧页能力已承接后才进入 P4 下线/删除。
