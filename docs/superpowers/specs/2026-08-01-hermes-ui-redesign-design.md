# /hermes UI 重设计（方案 A：呈现层原地重构）— 设计文档

日期：2026-08-01
范围仓库：`ai-quant-platform` `src/frontend/`（Next.js 15 App Router + React 19 + Tailwind v4）
状态：待用户评审

## 1. 目标与非目标

**目标**
- 把 /hermes 从"聊天 + 6 面板堆叠 + 仪表盘叠加"改造成现代 AI 助手风的全屏对话界面（参照 Claude/ChatGPT 的信息密度与质感）。
- 右侧 6 个常驻面板收敛为"状态条 + 按需抽屉"：默认隐藏，右缘图标条一键滑出。
- 全局壳（Sidebar / TopBar / SafetyStrip）同步焕新：安全横幅收敛为可展开徽章，导航精简视觉。
- 重铸 `globals.css` 设计 token：统一圆角/间距/阴影/字体层级，清理 Material-3 遗留别名的使用面。

**非目标（本轮不做）**
- 不改任何数据层：follow spine、admission/bootstrap 流程、submit 通道、API client 全部原样。
- 不拆巨型逻辑组件（`workspaceClient.ts` 2523 行、`ComposerSubmitController` 571 行内部状态机等）——只包新皮。
- 不动 /hermes 之外页面的内部布局（它们自动继承新壳与新 token，逐页深化留到后续轮次）。
- 不删 Playwright 依赖的 `data-*` 锚点；确需移动的锚点同步改测试。

## 2. 信息架构

### 2.1 /hermes 激活态（授权后）
```
┌ TopBar（搜索 + 安全徽章 + 语言/设置）
├─────────────────────────────────────────────┬──┐
│                                             │图│
│        居中对话流（max-w 800px）              │标│
│   气泡消息：用户右侧浅色卡、Hermes 左侧        │条│
│   无边框排版化正文；时间戳/run id 弱化为        │  │
│   hover 显示的 meta 行                       │≡ │
│                                             │✓ │
│                                             │⚡│
│  ┌───────────────────────────────────┐      │▶ │
│  │  悬浮 Composer 卡（圆角、阴影、     │      │⛩ │
│  │  自动增高、发送按钮内嵌）           │      │… │
│  └───────────────────────────────────┘      │  │
└─────────────────────────────────────────────┴──┘
```
- **对话流**：`WorkbenchTranscriptPanel` 去掉 `max-h-[min(48vh,28rem)]` 内滚动，改为页面级单一滚动区，消灭三层嵌套滚动；消息渲染为气泡/排版式（用户消息浅色圆角卡靠右，Hermes 消息无框全宽排版靠左，带小型 Hermes 标识）。
- **Composer**：`ComposerDock` 重绘为悬浮圆角输入卡（内嵌发送按钮、字节计数弱化进右下角、"新建空白对话"移为输入卡上方小按钮）。
- **右缘图标条（Dock Rail）**：固定右缘约 48px 竖条，6 个图标 = Approvals（含未决数 badge）、Activity、Run 控制、Results、Gates、Authority。点击滑出约 380px 抽屉（overlay，不挤压对话流）；同一时间只开一个；Esc/点外部关闭；开关状态存 `localStorage`。
- **状态徽标**：spine 的 transport/cursor 只在抽屉头部渲染一次（替代现在 6 处重复）；Approvals 有 pending 时图标出现琥珀色 badge 数字。
- **Today 内容与聊天分离**：授权后的聊天视图不再渲染 Today 仪表盘四条 lane；Today 内容仅在"无激活会话/未授权"状态下作为落地页显示（`{children}` 由 `authorizedChatOpen` 条件化）。

### 2.2 /hermes 未激活态（落地页）
- OwnerSessionBootstrapPanel 重绘为居中欢迎卡（标题 + 一句话说明 + 授权按钮），下方保留 Today 摘要 lane（问候/状态/结果/Automation，视觉按新 token 更新）。

### 2.3 全局壳
- **SafetyStrip → SafetyBadge**：撤掉 100px 高的橙色全宽横幅；TopBar 内放一枚 `PAPER-ONLY` 徽章（盾牌图标 + 绿色/琥珀点），点击展开 popover 显示完整安全清单（live off / kill switch / 冻结 / epoch / api）。数据源与 fail-closed 逻辑不变。root layout 的 `pt-[100px]` 相应改小。
- **Sidebar**：宽度 240→220px，分组标题更弱化，激活项左侧 2px 强调线 + 品牌色文字（替代整块高亮），图标统一 lucide 16px。
- **TopBar**：搜索框收窄居左，右侧依次 SafetyBadge / 语言切换 / 设置。
- **HermesInternalNav**：5 个 pill tab 改为下划线式二级 tab，贴 TopBar 下沿。

## 3. 设计 token（globals.css 重铸）

- 保留暖黑色系基调，但整理为明确的 4 级 surface 阶梯：`bg-base #101010 系 → surface → surface-raised → surface-overlay`，配套 `border-subtle/border-strong`。
- 品牌主色继续 `--color-hermes #9085E9`（对话/AI 相关强调），交易语义色不变（success/danger/warning/info）。
- 新增组件级 token：`--radius-card 12px`、`--radius-bubble 16px`、`--radius-input 14px`、`--shadow-overlay`、`--shadow-composer`。
- M3 compat alias 保留定义（避免旧页面断色），但 hermes 目录及壳组件内的引用全部迁到 canonical 名。
- 字体体系不变（Inter/JetBrains Mono/Source Serif 4/Noto Serif SC 自托管）；聊天正文用 sans（当前部分 mono 观感过"终端"），代码/id/时间戳保持 mono。

## 4. 组件方案

新增（`components/hermes/dock/` 与 `components/ui/`）：
- `DockRail.tsx` — 右缘图标条（client，含 badge 计数，从 `useWorkspaceFollow()` 读 approvals 数）。
- `DockDrawer.tsx` — 滑出抽屉容器（标题、关闭钮、统一的 transport/cursor 状态行、`motion` 进出动画）。
- `Panel.tsx`（components/ui）— 统一的 header/count/toggle/error/empty 面板 chrome，6 个 Workbench 面板迁移到它，删除各自手写的重复结构（仅换壳，面板内部 hooks/逻辑不动）。
- `ChatMessage.tsx` — 气泡/排版式消息呈现（从 TranscriptCanvas 抽出渲染部分）。
- `SafetyBadge.tsx` — 替代 SafetyStrip 的徽章 + popover。

改动（仅呈现层）：`HermesLocalChatBoundary`（网格→全屏对话 + DockRail；Today children 条件化）、`HermesWorkbenchShell`、`TranscriptCanvas`、`ComposerDock`/`ComposerSubmitController`（只动 JSX/class）、`OwnerSessionBootstrapPanel`、`Sidebar`、`TopBar`、`app/layout.tsx`、`HermesInternalNav`、6 个 Workbench 面板（换 Panel 壳）、`globals.css`。

## 5. 测试与验收

- **E2E 锚点契约**：动手前先 grep `tests/e2e/` 生成 `data-*`/aria 锚点依赖清单；被移动的锚点跟随新 DOM 保留同名；确因 IA 变化失效的（如 rail 常驻可见性断言）同步改测试并在 commit message 注明。
- **单元**：`npm run test`（vitest）、`npm run lint`、`npm run type-check` 全绿。
- **E2E**：`npm run test:e2e` 中 hermes 相关 spec 全绿（visual snapshot 需重录基线）。
- **人工验收**：Chrome DevTools MCP 截图对比 before/after（已存 `artifacts/hermes-ui-before-full.png`）；验证 1440/1100/768 三档宽度；抽屉开合、审批操作、发消息、SSE 更新全链路可用。
- **最终验收**：重跑"论文→因子→回测→沉淀策略"终极 prompt，全程在新 UI 上完成。

## 6. 风险与回退

- 呈现层重构不触碰状态机，最大风险是 E2E 锚点漂移——用锚点清单前置管控。
- 所有改动在 git 上分小 commit（token → 壳 → 聊天区 → 抽屉 → 面板迁移），任一步可独立 revert。
- SafetyStrip 收敛为徽章后安全信息仍一屏可达（popover），fail-closed 渲染路径保留。
