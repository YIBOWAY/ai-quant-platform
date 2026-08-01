# Hermes UI 重设计 — 测试锚点依赖清单（Task 0）

来源：fe-explorer 只读调研，2026-08-01。影响分级：**keep**=不受影响、**moves**=锚点必须在新 DOM 同名保留、**test-must-change**=断言必须改。

## 1. 右栏六面板（默认可见断言）——重灾区

抽屉化后默认不可见，以下全部 test-must-change。执行策略：新增 helper `openDock(page, 'approvals')` 等，在断言前先点开对应 rail 图标（抽屉内容不常驻 DOM）。

| 测试 file:line | 选择器 / 断言 | 提供组件 |
|---|---|---|
| hermes-lifecycle.spec.ts:213 | `[data-hermes-activity-row]` toHaveCount(3) | ActivityPanel |
| hermes-lifecycle.spec.ts:243-251 | `[data-hermes-approval-row]` count 1 + `-approval-id` + `-approval-status` 文本 | ApprovalsPanel |
| hermes-lifecycle.spec.ts:253-262 | `[data-hermes-gate-row]` + `-gate-id/-kind/-status` | GateSurfacesPanel |
| hermes-lifecycle.spec.ts:302 | typedResultRows.getByText("Fixture terminal backtest") | TypedResultsPanel |
| hermes-lifecycle.spec.ts:305-316 | `[data-hermes-authority-slot]` count 4 + `-authority-count` 文本 `"4 refs · read-only"` | AuthorityPanel |
| hermes-lifecycle.spec.ts:343-351 | `[data-hermes-authority-slot="…"]` / `[data-hermes-authority-empty]` | AuthorityPanel |
| hermes-lifecycle.spec.ts:685-701 | run-stop row→button click→`[data-hermes-run-stop-status="success"]` | RunStopPanel |
| hermes-lifecycle.spec.ts:706-737 | `[data-hermes-approval-decidable]`、`-approval-deny` click、`-approvals-receipt` 文本 | ApprovalsPanel |
| hermes-workbench.spec.ts:272/278/336/369 | `[data-hermes-approval-id="…"]`、`a[aria-current="page"]` | ApprovalsPanel |
| hermes-workbench.spec.ts:286/398/400 | **安全红线**：`[data-hermes-gate2-controls]` count 0、`[data-hermes-approvals] form` count 0 —— 新 DOM 必须继续满足，不可放宽 | Gates/Approvals |

## 2. SafetyStrip → SafetyBadge

- `getByTestId("global-safety-strip")` count 1（workbench:28/192/222、production-prefetch:63）→ testid 必须保留在徽章上。
- workbench:197：`main [data-global-safety-strip]` count 0 —— 徽章进 TopBar 仍在 main 外，天然通过。
- closure-gates.ts:450：`.not.toHaveText("")` —— **徽章必须有可见文本**，纯图标会挂；:429-448 所有可见 role="status" 须有文本。
- 无任何测试断言具体文案。

## 3. 壳 / 布局锚点

| 锚点 | 位置 | 影响 |
|---|---|---|
| `[data-hermes-active-grid]` toBeVisible（lifecycle 5 处） | Boundary | moves：全屏对话容器沿用 |
| `[data-hermes-workbench-a11y]`（closure-gates SHELL_SELECTOR） | Shell+Boundary | moves |
| `main` count 1；`role=navigation` name /Hermes workbench\|Hermes 工作台/；`role=region` name /…主区/ | layout/InternalNav/Shell | moves（nav 改下划线 tab 须保 aria-label） |
| `[data-page-scroll-region]`（visual:47、page-gates 4 处、workbench 3 处） | 滚动容器 | moves：单一页面级滚动容器必须携带 |
| `desktop-sidebar` testid、"Open navigation/打开导航" button | Sidebar:127、TopBar:45/81 | moves |
| `hermes-parity-banner`、`hermes-capability-notice` | 各自 | keep |
| `hermes-today-state` + data-state + 非空文本（closure-quality:62、visual:60/85、gates:451） | HermesTodayView:38 | **最高风险**：授权后 Today 不渲染会挂 visual matrix。决策：授权态保留一个隐藏（sr-only）today-state 节点或改测试；实施 Task 6 时定 |

## 4. Transcript / Composer

- `[data-hermes-transcript-loading]`：moves。
- `[data-hermes-transcript-scroll]`（lifecycle:387/415/442/820，:821-828 直接读写 scrollTop/scrollHeight）：**test-must-change 或属性上移** —— 把该属性与 `[data-page-scroll-region]` 合并挂到新的页面级滚动容器（fe-explorer 建议，采纳）。
- `getByRole("textbox", {name:"和 Hermes 对话"/"Talk with Hermes"})`（12+ 处）：**composer aria-label 文案不可改**。

## 5. 视觉快照

- hermes-workbench-visual：20 张 zh（5 fixture × 4 viewport 1440/1280/768/390）+ 4 张 en，`maxDiffPixelRatio 0.02`，全部重录。
- visual.spec.ts 路由级快照 + brief-zh.png：壳/token 变会漂移，重录。
- 每 case 附 loopback-only guard + console error/warning 必须为空 —— 新组件不得产生 React warning。

## 6. Vitest 源码文本契约（readFileSync 逐字断言，改写法即挂）

- workbenchA11y.test.ts:63-95：Boundary/Shell 源码必须含 `data-hermes-workbench-a11y={WORKBENCH_A11Y_MARKER}`、`WORKBENCH_CONTENT_PAD_CLASS`、`data-hermes-workbench-main`、`role="region"`、`aria-label={isZh ? "Hermes 工作台主区"`；不得出现 `<main`。
- :97-142：activity/approvals/authority 面板源码必须含 `COLLAPSE_TOGGLE_CLASS`、`LONG_ID_CLASS`、`displayId`；approvals 必须含 `data-hermes-approval-decide="v7a-m1"`；禁 `shortId`/`stop_command`/`allow_permanently`/`allow_always`。→ **Task 5 换 Panel 壳时这三个常量引用不能删**。
- :144-166：ComposerDock 源码 14 项字面量（`app-touch-target`、`aria-label={label}`、`MessageSquarePlus`、`newSessionButtonRef.current?.focus()`、`rounded-md bg-bg-base`、`data-testid="hermes-composer-byte-count"`、`draftResetToken` 等）→ Task 7 改造需逐项保留或改该测试。
- :167-184：ComposerSubmitController 8 处字面量。
- :185-195：TranscriptCanvas 必须含 `COLLAPSE_TOGGLE_CLASS`、`displayId`、`break-all`。
- :41-61 + design-tokens.test.ts:50-56：globals.css 必须含 `.app-touch-target` 44px、focus-visible、reduced-motion 两条 `0.01ms !important`。
- design-tokens.test.ts:20-38：globals.css **逐字**含约 15 个 token 行（`--color-hermes: #9085E9;`、`--spacing-hermes-composer-min: 64px;`、`--spacing-hermes-content-max: 1180px;`、`--spacing-rail-width: 208px;`、`--spacing-right-panel: 340px;`、`--spacing-stream-max: 720px;`、`--radius-editorial: 2px;`、`--color-stream-*`）→ **globals.css 只增不删**。
- editorial-typography/editorial-font tests：`@plugin "@tailwindcss/typography"`、`.font-editorial-*`、layout.tsx 的 next/font/local 四变量结构不可动。
- commandApprovalDecide.test.ts:163-181、runStopControl.test.ts:286-300：两面板源码字面量清单（见原始调研）。

## 硬约束总结（约束后续 Task 3-9 的 dispatch）

1. 六面板抽屉化 → lifecycle/workbench 约 10 组断言改为先 `openDock()`。
2. `[data-hermes-transcript-scroll]` 属性上移到页面级滚动容器（与 `data-page-scroll-region` 同节点）。
3. globals.css 只增不删（含已废弃 token）。
4. Composer textbox aria-label（"和 Hermes 对话"/"Talk with Hermes"）逐字不变。
5. SafetyBadge 保留 `global-safety-strip` testid + 可见非空文本 + 在 main 外。
6. 源码文本契约：换壳不删 `COLLAPSE_TOGGLE_CLASS`/`LONG_ID_CLASS`/`displayId` 引用；改 ComposerDock/TranscriptCanvas 前先读 workbenchA11y.test.ts 对应段。
7. Today：授权态需保留 `hermes-today-state` 节点（可视觉隐藏）或改 visual/closure 测试。
