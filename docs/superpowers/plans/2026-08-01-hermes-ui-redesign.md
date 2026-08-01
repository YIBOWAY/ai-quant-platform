# Hermes UI Redesign Implementation Plan（方案 A：呈现层原地重构）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 /hermes 重塑为现代 AI 助手风全屏对话界面（右侧 6 面板收进按需抽屉），并焕新全局壳与设计 token，数据层零改动。

**Architecture:** 只改 JSX/class/token 的呈现层重构。所有面板继续消费同一个 `useWorkspaceFollow()` spine；6 个 Workbench 面板换成共享 `Panel` 壳并搬进右缘 DockRail 抽屉；授权后聊天全屏化、Today 仪表盘仅在未激活态显示；SafetyStrip 横幅收敛为 TopBar 徽章。

**Tech Stack:** Next.js 15 App Router、React 19、Tailwind v4（CSS-first `@theme`）、lucide-react、motion、vitest、Playwright。

**Spec:** `docs/superpowers/specs/2026-08-01-hermes-ui-redesign-design.md`

## Global Constraints

- 前端根：`src/frontend/`；所有路径相对它（除非写明仓库根）。
- **数据层零改动**：`lib/hermes/workspaceClient.ts`、`workspaceFollowSpine.ts`、`lib/api.ts`、所有 hooks/状态机/submit/admission 逻辑不许动。
- **E2E 锚点契约**：`data-hermes-*`、`data-testid`、`data-page-scroll-region`、role/aria 选择器必须保留（可移动位置不可改名/删除）；确因 IA 变化需要改的锚点，同一 commit 内更新 `tests/` 并在 message 注明。
- 每个任务收尾必须绿：`npm run lint && npm run type-check && npm run test`（在 `src/frontend/`）。
- 文案双语：新增用户可见文案一律 en/zh 双份，模式跟随现有 `isZh ? … : …` 或 `lib/hermes/copy.ts`。
- 安全语义不变：SafetyBadge 的 fail-closed 渲染（API 不可用 → 显示 unavailable/blocked）必须保留 SafetyStrip 现行为。
- commit 粒度：每任务一个 commit，message 前缀 `feat(ui):`/`refactor(ui):`。
- 服务重启：改动完成后用 `launchctl kickstart -k gui/$(id -u)/com.aiquant.frontend` 或既有脚本重启前端验证。

---

### Task 0: 测试锚点清单落盘

**Files:**
- Create: `docs/superpowers/plans/2026-08-01-hermes-ui-anchor-inventory.md`

**Interfaces:**
- Produces: 锚点清单文档，后续每个任务动 DOM 前先查它。

- [ ] **Step 1: 生成清单**

在 `src/frontend/` 运行：

```bash
grep -rn "data-hermes\|data-testid\|data-page-scroll-region\|getByRole\|getByLabel\|getByText" tests/e2e tests/support lib/*.test.ts components/**/*.test.tsx 2>/dev/null | sort > /tmp/claude/anchors-raw.txt
wc -l /tmp/claude/anchors-raw.txt
```

- [ ] **Step 2: 整理成表**

把原始结果整理为 markdown 表（列：test file:line / selector / 提供该锚点的组件 / 重构影响：保留原样|随 DOM 移动|需改测试），写入 `docs/superpowers/plans/2026-08-01-hermes-ui-anchor-inventory.md`。重点标出：
- 断言右栏面板默认可见的测试（面板进抽屉后需改为"打开抽屉再断言"）；
- 断言 SafetyStrip 横幅文本的测试（改为断言 SafetyBadge/popover）；
- visual snapshot spec（`hermes-workbench-visual.spec.ts-snapshots` 需重录基线）。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-08-01-hermes-ui-anchor-inventory.md
git commit -m "docs(ui): E2E anchor inventory for hermes redesign"
```

---

### Task 1: 设计 token 重铸（globals.css）

**Files:**
- Modify: `app/globals.css`

**Interfaces:**
- Produces（后续所有任务消费的新 token；名字必须一字不差）：
  - surface 阶梯：`--color-bg-overlay: #26242B`（抽屉/popover 用，现有 base/surface/surface-muted 之上加一层）
  - 圆角：`--radius-card: 12px`、`--radius-bubble: 16px`、`--radius-input: 14px`
  - 阴影：`--shadow-overlay: 0 12px 40px rgba(0,0,0,0.55)`、`--shadow-composer: 0 4px 24px rgba(0,0,0,0.4)`
  - 布局：`--spacing-chat-max: 800px`、`--spacing-dock-rail: 48px`、`--spacing-drawer: 380px`
  - 更新：`--spacing-topbar-height: 56px`；`--spacing-safety-strip-height` 删除（横幅撤除，Task 3 同步改引用）

- [ ] **Step 1: 在 `@theme` 的 canonical palette 段追加新 token**（按 Produces 列表逐条加，放在 `--color-border-subtle` 之后）；把 `--spacing-topbar-height` 从 64px 改 56px；删 `--spacing-safety-strip-height` 前先 `grep -rn "safety-strip-height" app components lib` 确认引用点（预期只有 SafetyStrip/layout，Task 3 处理，若本任务删除会break则保留到 Task 3 一起删）。

- [ ] **Step 2: 验证** `npm run lint && npm run type-check && npm run test`，然后 `npm run dev` 起本地（或直接看 3001 端口热更）目测无断色。

- [ ] **Step 3: Commit** `git commit -m "feat(ui): recast design tokens — overlay surface, radii, shadows, chat layout vars"`

---

### Task 2: 共享 Panel 壳组件

**Files:**
- Create: `components/ui/Panel.tsx`
- Test: `components/ui/Panel.test.tsx`（vitest + @testing-library/react，仓库已有同类测试可参考 `lib/hermesTodayPage.test.ts` 的运行方式；若无 RTL 依赖则用现有测试栈能力做纯渲染断言，实在没有 DOM 测试设施就以 type-check + 后续面板迁移的既有测试为准并在 commit message 说明）

**Interfaces:**
- Produces:
  ```tsx
  export type PanelProps = {
    title: string;
    count?: number | null;        // header 右侧计数徽标
    error?: string | null;        // 顶部错误行（role="alert"）
    empty?: string | null;        // items 为空时的占位文案
    isEmpty?: boolean;
    headerExtra?: ReactNode;      // header 尾部自定义（如 receipt 链接）
    children: ReactNode;
    /** 透传测试锚点，如 data-hermes-approvals-panel */
    [dataAttr: `data-${string}`]: unknown;
  };
  export function Panel(props: PanelProps): JSX.Element;
  ```
  视觉：`rounded-[var(--radius-card)] border border-border-subtle bg-bg-surface`，header `font-label-caps text-text-secondary`，count 为 `rounded-full bg-bg-surface-muted px-2 text-[11px]`。**不含折叠开关**（抽屉里不需要，折叠语义由抽屉承担）。

- [ ] **Step 1: 写 Panel.tsx**（按上面接口与视觉实现，error 行 `role="alert" className="text-danger font-body-sm"`，empty 行 `text-text-secondary font-body-sm`）。
- [ ] **Step 2: 写渲染测试**（title/count/error/empty/children 五个断言）并跑 `npm run test`。
- [ ] **Step 3: Commit** `git commit -m "feat(ui): shared Panel chrome component"`

---

### Task 3: 全局壳 — SafetyStrip→SafetyBadge、TopBar、Sidebar、root layout

**Files:**
- Create: `components/SafetyBadge.tsx`
- Modify: `components/TopBar.tsx`、`components/Sidebar.tsx`、`app/layout.tsx`、`app/globals.css`（删 safety-strip-height）
- Delete-usage（文件保留可后删）：`components/SafetyStrip.tsx` 从 layout 移除
- Test: 按 Task 0 清单更新断言 SafetyStrip 文本的测试

**Interfaces:**
- Consumes: Task 1 token。
- Produces: `SafetyBadge`（server component，数据获取照抄 SafetyStrip 的 `getCachedSettings`/`getCachedEffectivePaperSafety`），渲染：TopBar 内 `PAPER-ONLY` pill（ShieldAlert 图标 + 状态点：全部安全=success 点，任一异常=warning/danger 点），HTML `<details>`+absolute popover 列出完整安全清单（liveDisabled/kill/frozen/authority epoch/api，行文案沿用 SafetyStrip 的 copy 对象）。保留原 SafetyStrip 的可见文本关键词（如 `PAPER-ONLY`、`LIVE TRADING DISABLED`）在 popover 内，尽量让文本断言类测试改动最小。

- [ ] **Step 1: 写 SafetyBadge.tsx**（copy 对象整体从 SafetyStrip 复制，fail-closed 分支照抄）。
- [ ] **Step 2: TopBar 改造**：高度 `h-[var(--spacing-topbar-height)]`，右侧插入 `<SafetyBadge />`（TopBar 是 server 或 client？先读文件；若 client 则 SafetyBadge 由 layout 作为 sibling 放 TopBar 同一行的 flex 容器）。搜索框收窄 `max-w-[320px]`。
- [ ] **Step 3: app/layout.tsx**：移除 `<SafetyStrip />`；main `pt-[100px]` → `pt-[var(--spacing-topbar-height)]`；`lg:ml-[240px]` → `lg:ml-[220px]`。
- [ ] **Step 4: Sidebar 改造**：宽度 240→220（含内部 `w-[240px]` 与 token `--spacing-sidebar-width: 220px`）；激活项样式改为 `border-l-2 border-[var(--color-hermes)] bg-transparent text-text-primary`，分组标题 `font-label-caps opacity-60`。
- [ ] **Step 5: globals.css** 删除 `--spacing-safety-strip-height`；`grep -rn "safety-strip-height\|pt-\[100px\]" app components` 确认无残留。
- [ ] **Step 6: 按锚点清单更新受影响测试**；跑 `npm run lint && npm run type-check && npm run test`。
- [ ] **Step 7: Commit** `git commit -m "feat(ui): global shell refresh — SafetyBadge replaces banner, slim TopBar/Sidebar"`

---

### Task 4: DockRail + DockDrawer

**Files:**
- Create: `components/hermes/dock/DockRail.tsx`、`components/hermes/dock/DockDrawer.tsx`、`components/hermes/dock/dockPanels.ts`
- Test: `components/hermes/dock/dockPanels.test.ts`

**Interfaces:**
- Consumes: `useWorkspaceFollow()`（`lib/hermes/workspaceFollowContext`，只读 `approvals`、`transport`、`snapshotCursor`）。
- Produces:
  ```tsx
  // dockPanels.ts
  export type DockPanelId = "approvals" | "activity" | "runs" | "results" | "gates" | "authority";
  export const DOCK_PANELS: ReadonlyArray<{ id: DockPanelId; icon: LucideIcon; labelEn: string; labelZh: string }>;
  export function pendingApprovalCount(approvals: unknown[]): number; // 过滤 pending 状态

  // DockRail.tsx ('use client')
  export function DockRail({ locale, open, onToggle }: {
    locale: Locale;
    open: DockPanelId | null;
    onToggle: (id: DockPanelId) => void;   // 再点同一图标 = 关闭
  }): JSX.Element;

  // DockDrawer.tsx ('use client')
  export function DockDrawer({ locale, open, onClose, children, title }: {
    locale: Locale; open: boolean; onClose: () => void; title: string; children: ReactNode;
  }): JSX.Element;
  ```
  视觉/行为：Rail 固定右缘 `w-[var(--spacing-dock-rail)]`，图标 44px touch target，`aria-pressed`，Approvals 图标叠 `pendingApprovalCount>0` 时的琥珀 badge。Drawer `fixed right-[var(--spacing-dock-rail)] w-[var(--spacing-drawer)] bg-[var(--color-bg-overlay)] shadow-[var(--shadow-overlay)] rounded-l-[var(--radius-card)]`，`motion` 滑入（`motion-reduce` 降级），头部一行 title + transport/cursor 状态（`data-hermes-follow-transport` 锚点放这里，全局唯一）+ 关闭钮，Esc 与点击遮罩关闭，body 不滚动穿透。开面板 id 存 `localStorage("hermes-dock-open")`，挂载时恢复。图标映射：approvals=BadgeCheck、activity=ListTree、runs=CirclePlay、results=FileChartColumn、gates=ShieldCheck、authority=Database。

- [ ] **Step 1: 写 dockPanels.ts + 测试**（DOCK_PANELS 顺序/数量、pendingApprovalCount 过滤逻辑），跑测试红→绿。
- [ ] **Step 2: 写 DockRail、DockDrawer**。
- [ ] **Step 3: `npm run lint && npm run type-check && npm run test`。**
- [ ] **Step 4: Commit** `git commit -m "feat(ui): dock rail + slide-over drawer for hermes side panels"`

---

### Task 5: 六面板迁 Panel 壳 + 去重调试角标

**Files:**
- Modify: `components/hermes/approvals/WorkbenchCommandApprovalsPanel.tsx`、`activity/WorkbenchCommandActivityPanel.tsx`、`run-control/WorkbenchRunStopPanel.tsx`、`results/WorkbenchTypedResultsPanel.tsx`、`gates/WorkbenchGateSurfacesPanel.tsx`、`authority/WorkbenchAuthorityProjectionPanel.tsx`
- Test: 各面板对应的既有测试按锚点清单同步

**Interfaces:**
- Consumes: Task 2 `Panel`。
- Produces: 六面板外层统一为 `<Panel title=… count=… error=… data-hermes-…>`；**内部 hooks、动作按钮、列表渲染逻辑逐行保留**；各自渲染的 transport/snapshotCursor 状态行删除（已移到 DockDrawer 头部，锚点若被测试引用则按清单改测试指向抽屉头）；各自的 `useState(true)` 折叠开关与折叠按钮删除（抽屉即折叠语义）——若锚点清单显示折叠钮被 E2E 依赖，保留按钮但仅控制面板内列表显隐。

- [ ] **Step 1-6: 每个面板一步**：换壳→删重复 chrome→跑该面板相关 vitest→下一个。顺序：Activity（最简单）→ RunStop → TypedResults → Authority → Approvals → Gates（最大，729 行，只动外壳与重复 chrome，内部 source/sha256 逻辑不碰）。
- [ ] **Step 7: 全量 `npm run lint && npm run type-check && npm run test`。**
- [ ] **Step 8: Commit** `git commit -m "refactor(ui): migrate six workbench panels onto shared Panel chrome"`

---

### Task 6: 聊天全屏化 — HermesLocalChatBoundary 重排 + Today 分离

**Files:**
- Modify: `components/hermes/shell/HermesLocalChatBoundary.tsx`、`components/hermes/transcript/WorkbenchTranscriptPanel.tsx`
- Test: 按锚点清单更新（`data-hermes-active-grid/rail` 相关断言）

**Interfaces:**
- Consumes: Task 4 DockRail/DockDrawer、Task 5 面板。
- Produces: 授权后布局 =
  ```tsx
  <div className="relative flex min-h-0 flex-1">
    <div className="min-h-0 flex-1 overflow-y-auto" data-page-scroll-region>
      <div className="mx-auto w-full max-w-[var(--spacing-chat-max)] px-4 py-6" data-hermes-active-main>
        <WorkbenchTranscriptPanel locale={locale} />
      </div>
    </div>
    <DockRail locale={locale} open={openPanel} onToggle={togglePanel} />
    <DockDrawer …>{renderPanel(openPanel)}</DockDrawer>
  </div>
  ```
  `openPanel: DockPanelId | null` state 放本组件（含 localStorage 恢复）。`data-hermes-active-grid`/`data-hermes-active-rail` 锚点：grid 属性保留在外层容器（值不变），rail 属性移到 DockRail 根元素。**Today children**：`{authorizedChatOpen ? null : children}` —— 未授权/无会话时照旧显示 Today 落地内容。`WorkbenchTranscriptPanel` 内删除 `max-h-[min(48vh,28rem)]` 与自身滚动容器（滚动交给页面级 scroll region），保留其余状态机与锚点。

- [ ] **Step 1: 改 HermesLocalChatBoundary**（按 Produces 结构；六面板从常驻 aside 改为 `renderPanel(id)` switch 按需渲染进抽屉）。
- [ ] **Step 2: 改 WorkbenchTranscriptPanel 滚动**（删内滚 max-h；确认自动滚到底逻辑如有则改为对页面 scroll region 生效，读原文件后照改）。
- [ ] **Step 3: 按锚点清单更新 E2E 断言**（右栏可见性断言→先点 rail 图标再断言抽屉内容）。
- [ ] **Step 4: `npm run lint && npm run type-check && npm run test`；Commit** `git commit -m "feat(ui): fullscreen chat layout — panels move to on-demand drawers, Today separates from active chat"`

---

### Task 7: 消息气泡与 Composer 焕新

**Files:**
- Modify: `components/hermes/transcript/TranscriptCanvas.tsx`、`components/hermes/ComposerDock.tsx`
- Test: 既有 vitest（transcriptHelpers 等）不受影响；锚点全保留

**Interfaces:**
- Consumes: Task 1 token。
- Produces（纯 class/结构调整，props 与全部 `data-hermes-*` 锚点不变）：
  - 用户消息：`max-w-[72%] rounded-[var(--radius-bubble)] rounded-br-md bg-info/12 border-none px-4 py-3`，右对齐；"You" label 删除（靠对齐+配色区分），pending 态改透明度+右下角小 spinner 字符。
  - Hermes 消息：无边框无底色，全宽（chat-max 内），左侧 24px 品牌色小圆标（`bg-[var(--color-hermes)]/15 text-[var(--color-hermes)]`，内放 sparkle 字形或 lucide Sparkles 14px），正文 `font-body-md`（14px，从 13px 提一档）。
  - 时间戳/fork 按钮：默认 `opacity-0 group-hover:opacity-100 transition-opacity`（li 加 `group`），`motion-reduce` 与触屏（`@media (hover:none)`）常显。
  - SessionChip：移到列表顶部一条居中弱化 meta 行。
  - ComposerDock：外层去 `border-t`，改 `px-4 pb-4 pt-2 bg-transparent`；form 容器 `max-w-[var(--spacing-chat-max)] rounded-[var(--radius-input)] border border-border-subtle bg-bg-surface shadow-[var(--shadow-composer)] focus-within:border-[var(--color-hermes)]/50 p-2`；textarea 去自身边框底色（`bg-transparent border-none focus-visible:outline-none`）；发送钮圆形 36px 内嵌右下（enabled 时 `bg-[var(--color-hermes)] text-white`）；byte-count 移到卡内右下角 `text-[11px] opacity-60`（`data-testid` 保留）；"新建空白对话"钮移到卡上方右侧小字按钮。status/retry 行保持卡下方。

- [ ] **Step 1: TranscriptCanvas 改造**（锚点逐个 diff 核对不丢）。
- [ ] **Step 2: ComposerDock 改造**（`hermes-composer-draft` id、aria、data-testid 全保留）。
- [ ] **Step 3: `npm run lint && npm run type-check && npm run test`；Commit** `git commit -m "feat(ui): chat bubbles + floating composer card"`

---

### Task 8: 未激活态落地页 + 二级导航 + Today lane 视觉

**Files:**
- Modify: `components/hermes/OwnerSessionBootstrapPanel.tsx`、`components/hermes/shell/HermesInternalNav.tsx`、`components/hermes/today/*.tsx`（仅 class）
- Test: 锚点清单同步

**Interfaces:**
- Consumes: Task 1 token、Task 2 Panel（Today lane 可选用）。
- Produces: Bootstrap 面板改居中欢迎卡（`max-w-[480px] mx-auto mt-16 rounded-[var(--radius-card)] bg-bg-surface p-8 text-center`，标题 `font-headline-lg`，授权按钮主色填充）；HermesInternalNav pill → 下划线 tab（激活项 `border-b-2 border-[var(--color-hermes)] text-text-primary`，非激活 `text-text-secondary`，容器 `border-b border-border-subtle`）；Today 四 lane 统一卡片 token（`rounded-[var(--radius-card)]`、间距 `gap-6`），只动 class。

- [ ] **Step 1: OwnerSessionBootstrapPanel**（授权流程逻辑与锚点不动）。
- [ ] **Step 2: HermesInternalNav。**
- [ ] **Step 3: Today lanes class 扫一遍统一。**
- [ ] **Step 4: 验证 + Commit** `git commit -m "feat(ui): welcome card bootstrap, underline nav tabs, unified Today cards"`

---

### Task 9: 全量回归 + 视觉验收 + 快照重录

**Files:**
- Modify: `tests/e2e/hermes-workbench-visual.spec.ts-snapshots/*`（重录）、锚点清单遗漏项

- [ ] **Step 1: 单元/静态全绿** `npm run lint && npm run type-check && npm run test`。
- [ ] **Step 2: E2E**：`npm run test:e2e -- tests/e2e/hermes-workbench.spec.ts tests/e2e/hermes-artifacts.spec.ts tests/e2e/hermes-closure-matrix.spec.ts`（其余 hermes spec 也跑）；visual spec 用 `--update-snapshots` 重录并人工比对新基线合理。
- [ ] **Step 3: 重启前端** LaunchAgent，Chrome DevTools MCP 打开 `http://127.0.0.1:3001/en/hermes`：截图存 `artifacts/hermes-ui-after-full.png`，与 before 对比；核对 1440/1100/768 三档宽度、抽屉开合、审批 badge、发消息、SSE 转圈到回复全链路。
- [ ] **Step 4: Commit + 收尾** `git commit -m "test(ui): regression + visual baselines for hermes redesign"`；更新记忆文件。

---

## Self-Review 结论

- Spec 覆盖：token(T1)、壳(T3)、聊天全屏+Today 分离(T6)、气泡/Composer(T7)、抽屉(T4/5/6)、落地页/二级导航(T8)、测试验收(T0/T9)——全覆盖。
- 类型一致：`DockPanelId`、`PanelProps`、`open/onToggle` 签名在 T4/T5/T6 间已核对一致。
- 无 TBD/占位符；改既有大文件的步骤均注明"先读原文件再照改"，因为方案 A 明确不重写其内部逻辑。
