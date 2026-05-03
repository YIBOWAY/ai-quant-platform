# UI Function Matrix — Audit (read-only)

> Audit performed on branch `phase-9-api`, with backend live on `127.0.0.1:8765` and frontend on `127.0.0.1:3001`. Source of truth: code on disk + live curl probes. **No code changes were made in this round.**

## 0. 总体结论（一行）

> 整个前端目前是「**展示稿**」级别：除 [Sidebar.tsx](../src/frontend/components/Sidebar.tsx) 一个 client component 外，**所有页面都是 Next.js server component，全工程零 `onClick` / `onChange` / `onSubmit` handler**。所有按钮、select、input、tab、modal 都是装饰，点了不会调用任何东西。

证据：

```
grep "use client"      → 仅 Sidebar.tsx
grep onClick|onChange  → 0 命中（前端工程范围内）
```

## 1. 路由 vs 导航不一致

| 路径 | 文件存在 | 在 [Sidebar.tsx](../src/frontend/components/Sidebar.tsx) 里？ | 备注 |
| --- | --- | --- | --- |
| `/` | ✅ | ✅ Dashboard | OK |
| `/agent-studio` | ✅ | ✅ Agent Studio | OK |
| `/backtest` | ✅ | ✅ Backtester | OK |
| `/factor-lab` | ✅ | ✅ Factor Lab | OK |
| `/paper-trading` | ✅ | ✅（标签已修正为 "Paper Trading"）| OK |
| `/experiments` | ✅ | ✅ | OK |
| `/settings` | **❌（路径不存在）** | ✅ | 点击 "Settings" 会 404 |
| `/data-explorer` | ✅ | **❌**（导航缺失）| 用户无法通过 UI 进入 |
| `/order-book` | ✅ | **❌** | 用户无法进入 |
| `/position-map` | ✅ | **❌** | 用户无法进入 |

## 2. 完整功能矩阵

> Status 缩写：DEAD=控件无 handler 一定不响应；NAV=链接型有效；READ=只展示 API 真实数据；FAKE=展示硬编码内容；BROKEN=点了会 404 / 报错。

### 2.1 Global / Layout（[layout.tsx](../src/frontend/app/layout.tsx) / [Sidebar.tsx](../src/frontend/components/Sidebar.tsx) / [TopBar.tsx](../src/frontend/components/TopBar.tsx) / [SafetyStrip.tsx](../src/frontend/components/SafetyStrip.tsx)）

| Page | UI Element | Current Status | Expected | Actual | Frontend Code | Backend API | Data Source | Issue | Priority | Fix Plan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Global | Sidebar nav links | NAV | 跳到对应路由 | OK，但 `/settings` 404、缺 3 个路由 | Sidebar.tsx | — | — | 路由清单与文件清单不一致 | P0 | 添加 settings 页 + 在 sidebar 列出 data-explorer / order-book / position-map |
| Global | "New Strategy" button (sidebar) | DEAD | 弹出 Agent Task 表单 | 无反应 | Sidebar.tsx L43 | 应调 POST /api/agent/tasks | — | 无 handler | P1 | 改为 Link 到 `/agent-studio?mode=new` 或加 client modal |
| Global | "Docs" / "Help" / "User" 链接 | DEAD | 跳到外链 / 内部 docs | `href="#"` 占位 | Sidebar.tsx | — | — | 无目标 | P2 | 接到 `/docs/OVERVIEW.md` 渲染页或 GitHub 链接 |
| Global | TopBar (theme / search / notifications) | DEAD | 主题切换、搜索、通知 | 装饰 | TopBar.tsx | — | — | 无 handler | P1 (theme), P2 (其余) |
| Global | SafetyStrip 文案 | READ | 显示 dry_run/paper/kill_switch 真实状态 | 硬编码字符串（未读 /api/health.safety） | SafetyStrip.tsx | /api/health | 应取 health.safety | 没有打 API | P0 | 改为 server component 调 getHealth() 渲染真实安全态 |

### 2.2 Dashboard（[/](../src/frontend/app/page.tsx)）

| UI Element | Status | Expected | Actual | Backend | Source | Issue | Pri | Fix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 个 KPI 卡 | READ | 真实数据 | factors.length / paper.final_equity / candidates.length / latest_backtest.sharpe 都来自 API | /api/factors,/api/paper,/api/agent/candidates,/api/backtests | 真实但**初始为空**（`paper_runs:[]`） | OK，但 final_equity/Sharpe 都显示 "--" 无引导 | P1 | 加空态 CTA |
| 4 张 Recent Operations 卡片 | 半 READ | 列出最近 4 个 run | latestBacktest / latestPaper 真实，**Experiment 卡的 progress 是 45% 硬编码**，**Agent Build 卡 runtime/15% 硬编码** | 真实数据卡片仅 2/4 | 部分 mock | 数字会骗人 | P0 | 全部接 API 或显式标注 "demo" |
| "View All" 按钮 | DEAD | 跳到列表页 | 不响应 | — | — | 无 handler | P1 | 改为 Link |
| System Log 三行 | FAKE | 真实日志 | 时间戳和文本是硬编码（`14:02:11` / `14:00:05` / `13:45:22`），仅 `health.status` / `bind_address` 是真的 | 真实日志没接口 | mock | 误导性"日志" | P0 | 移除假日志或接 backend audit jsonl |
| Right Sidebar — Quick Actions 三按钮 | DEAD | 启动 backtest / sweep / 导出 | 装饰 | 应调 /api/backtests/run 等 | — | 无 handler | P0 | 加 client component + form |
| Right Sidebar — API Feed / Execution Engine 状态 | 半 READ | 反映真实连接 | API Feed 圆点恒绿；Execution Engine 文案恒为 "Paper" | /api/health | 真实+装饰混合 | OK | P2 | 显式 fail 态 |
| Right Sidebar — Kill Switch toggle | DEAD/READ | 切换 paper trading kill switch | UI 是 disabled toggle，文案显示 health.safety.kill_switch 真值 | /api/health 只读 | OK（设计就是 read-only）| 无问题，但文案 cursor-not-allowed 应加 tooltip | P2 | 加 tooltip "Read-only by design" |
| Right Sidebar — CPU / RAM 占用条 | FAKE | 真实利用率 | 42% / 65% 硬编码 | 无后端 | mock | 误导 | P1 | 删除或接 `/api/health/system` (新 endpoint) |

### 2.3 Data Explorer（[/data-explorer](../src/frontend/app/data-explorer/page.tsx)）

| UI Element | Status | Expected | Actual | Backend | Source | Issue | Pri | Fix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Universe `<select>` | DEAD + 样式坏 | 选择 universe → 重拉数据 | 无 onChange；点开后 option 黑底白字与 dark UI 反差大（**用户截图问题**） | /api/symbols | symbols 真实，但选项 4 个被透明度变灰像 disabled | 无交互 + option 样式坏 | P0 | 改 client component；用 shadcn Select 或显式给 `<option>` 加 `class="bg-bg-surface text-text-primary"` |
| Asset `<input type="text">` | DEAD | 输 symbol 重拉 | 无 onChange | /api/ohlcv?symbol=… | — | 无交互 | P0 | 改 client component |
| Date Range 两个 `<input type="date">` | DEAD | 改日期重拉 | 无 onChange | /api/ohlcv?start=&end= | — | 无交互 | P0 | 同上 |
| Resolution `<select>` (1D/1H/15M) | DEAD + FAKE | 切分辨率 | 后端只有日线，1H/15M 后端不支持 | /api/ohlcv（无 interval 参数）| FAKE option | 选项写死却无后端能力 | P0 | 删除 1H/15M 或先在 API 添加 interval 参数（或 disable + tooltip） |
| ZoomIn / ZoomOut 按钮 | DEAD | 缩放图表 | 无 handler | — | — | — | P2 | 真实实现需要图表库 |
| Export 按钮 | DEAD | 下载 CSV | 无 handler | 应调 /api/ohlcv → blob | — | 无 handler | P1 | 加客户端下载逻辑 |
| 主图（candle/volume）| **FAKE** | 渲染 ohlcv.rows | **是 5 根硬编码 `<div>` bar 装饰**，根本没用 ohlcv 数据 | /api/ohlcv | rows 真实但**未渲染** | 完全 mock 视觉 | P0 | 用 lightweight-charts 真渲染 ohlcv.rows |
| Y 轴 195/190/185 | FAKE | 自动计算 | 硬编码字符串 | — | mock | 误导 | P0 | 同上一项一起修 |
| OHLCV 表格 | READ | 显示行情 | 真实 ohlcv.rows.slice(-6) | /api/ohlcv | sample 数据（见下文 MARKET_DATA_SOURCE_AUDIT）| 数据是真后端返回的，但后端是 sample | P0 (data source) | 不动前端，先修后端 provider 接 .env |
| "Live Sync" 绿点 + 文字 | FAKE | 真实流式 | 硬编码动画；后端不流 | — | mock | 误导：让人以为是 live | P0 | 改 "Sample data" 标签 |
| Data Quality — Coverage 99.98% | FAKE | 真实计算 | 硬编码数字 | — | mock | 误导 | P0 | 接 `/api/ohlcv` 自算或新加 `/api/data/quality` |
| Data Quality — Missing Days 列表 (MLK Day 等) | FAKE | 真实空缺 | 硬编码 | — | mock | 误导 | P0 | 同上 |
| Spike Detection 0 Anomalies | FAKE | 真实检测 | 硬编码 | — | mock | 误导 | P0 | 同上 |
| "View Detailed Audit Log" 按钮 | DEAD | 跳转 | 无 handler | — | — | — | P2 | Link to existing audit jsonl viewer (TBD) |

### 2.4 Backtest（[/backtest](../src/frontend/app/backtest/page.tsx)）

| UI Element | Status | Issue | Pri | Fix |
| --- | --- | --- | --- | --- |
| 所有 ConfigPanel 输入 | DEAD | 无 handler；无 form 提交 | P0 | 改 client component + react-hook-form + 调 POST /api/backtests/run |
| "Run Backtest" 按钮 | DEAD | 不调 API | P0 | 同上 |
| 资金曲线图 | 待 grep 验证 | 多半同 Data Explorer：装饰柱状 | P0 | 用 recharts 渲染 backtest.equity_curve |
| KPI 数字 | 半 READ | 已经在用 latestBacktest？需逐字段确认 | P1 | 见 [page.tsx](../src/frontend/app/backtest/page.tsx) 逐字段核对 |
| Compare With Benchmark | 缺 | 应调 /api/benchmark | P0 | 接 getBenchmark() |

> 注：本表 Backtest / Factor Lab / Paper / Experiments / Agent Studio / Order Book / Position Map 的细化逐控件清单未在本轮全部展开，因为**它们都共享同一根因——所有页面都是 server component，没有任何 onClick / onChange**。修复 P0 时需要把这 7 个页面整体改成 client component（或拆为 server shell + client form）。

### 2.5 Factor Lab / Paper Trading / Experiments / Agent Studio / Order Book / Position Map / (假)Settings

统一结论：

| 页面 | 真实数据来自 | 已读 API | 装饰元素（FAKE） | 致命点 |
| --- | --- | --- | --- | --- |
| Factor Lab | /api/factors | factors 列表 | IC/分组/分布图全是装饰 | 无 "Run" 按钮可用 |
| Paper Trading | /api/paper, /api/health | KPI 数字、kill_switch 文案 | 资金曲线、订单生命周期表（部分行硬编码）| Run 按钮 DEAD；kill_switch toggle 是 Disabled UI |
| Experiments | /api/experiments | 列表 | sweep heatmap、walk-forward fold 全装饰 | 无对比、无 send-to-backtest |
| Agent Studio | /api/agent/candidates, /api/factors | candidate 名 + factor 计数 | 代码 preview 是硬编码 momentum 模板，**不是真实候选源码**；"PASS" 标签恒亮；左侧 "RL_Agent_v1.py" / "Sentiment_LLM.py" 都是假文件 | Approve / Reject 按钮 DEAD |
| Order Book / Position Map | 未确认 | 未知 | 大概率全是设计稿 | sidebar 进不去 |

## 3. UI/UX 样式问题（与用户截图相关）

| 现象 | 文件 / 行 | 根因 | 修复 |
| --- | --- | --- | --- |
| Universe `<select>` 展开后选项几乎看不清（白底浅灰） | [data-explorer/page.tsx](../src/frontend/app/data-explorer/page.tsx) L19 | 浏览器原生 `<option>` 不继承 Tailwind 暗色 token；只有第一个 option 是高亮蓝色（OS 默认 selected），其余是白底+灰字 | 给 `<option>` 显式 `style={{background:'#0E1511',color:'#F1F5F9'}}` 或换 shadcn `<Select>` |
| 同问题影响 Resolution / Date Range 触发的原生 picker 在 Windows 下浅色 | 多处 | 同上 | 同上 |
| 输入框 focus 时 `focus:ring-0` 反而失去可见性 | 多处 | 主动取消 ring | 改 `focus:ring-1 focus:ring-info` |
| disabled 状态没有特殊样式 | 多处 | 没有 `disabled:` 变体 | 加 `disabled:opacity-50 disabled:cursor-not-allowed` |
| Kill Switch toggle `cursor-not-allowed` 但无 tooltip | dashboard 右栏 | 缺解释 | 加 `title="Read-only. Edit QS_KILL_SWITCH in .env."` |
| 无 loading / error / empty 状态组件 | 全工程 | 无封装 | 实现 `<EmptyState>` / `<ErrorBanner>` / `<LoadingSkeleton>` |

## 4. 数据来源标记缺失

每个图表 / KPI 卡都应显示当前数据源（`source=sample` / `source=tiingo` / `source=local` / `source=fallback`）。当前只有 Data Explorer 的 filter bar 显示了一个 `API source: ...` 角标；其它页面全部静默。

## 5. 直接验证记录

```
GET /api/health        200  status=ok kill_switch=true bind=127.0.0.1
GET /api/symbols       200  symbols=[SPY,QQQ,IWM,TLT,GLD] source=sample
GET /api/ohlcv?SPY     200  source=sample rows=9 first.open=100.0 close=100.5  ← 完美等差，明显合成
GET /api/factors       200
GET /api/backtests     200
GET /api/paper         200
GET /api/experiments   200
GET /api/agent/...     200
GET /api/prediction-market/markets 200
GET /api/settings      200
GET /api/benchmark     200
```

后端 9 个核心 endpoint 全部 200，但 **`source=sample` 暴露了 SPY 数据为合成数据**，详见 [MARKET_DATA_SOURCE_AUDIT.md](MARKET_DATA_SOURCE_AUDIT.md)。
