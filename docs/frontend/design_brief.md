# Frontend Design Brief — ai-quant-platform

> 这份文档是给设计 agent（Google Stitch / Figma Make / Gemini 3 Pro / v0.dev 等）以及实现 agent（Codex / Gemini 3 Pro）的**单一事实源**。  
> 写作语言为中文，但里面的关键术语会保留英文，方便直接喂给设计工具。

---

## 1. 产品定位（必须出现在每个设计 prompt 的顶部）

`ai-quant-platform` 是一个**本地运行**的量化研究 + 模拟交易 + AI 研究助手平台。零基础友好，**绝不下单**。

它**是**：

- 数据 → 因子 → 回测 → 实验 → 风控 → paper trading 的本地研究流水线
- 一个把 AI Agent 的产出隔离在 candidate pool、必须人工 review 的研究助手
- 一个 prediction market 只读 + dry proposal 的占位扩展

它**不是**：

- 实盘交易系统 / 自动下单机器人
- Robinhood / IBKR / Alpaca / 任何券商的 GUI
- 加密货币交易所 / Polymarket 自动套利机器人

每个页面顶部都必须用某种方式让用户**始终能看到**："paper-only · live trading disabled · kill switch on"。

---

## 2. 品牌与视觉语言

### 2.1 色板（dark mode 主，light mode 次）

| Token | Dark mode | Light mode | 用途 |
| --- | --- | --- | --- |
| `--bg-base` | `#0B1220` | `#F8FAFC` | 整页背景 |
| `--bg-surface` | `#111827` | `#FFFFFF` | 卡片、表格、面板 |
| `--bg-surface-2` | `#1F2937` | `#F1F5F9` | 嵌套面板、hover |
| `--border-subtle` | `#1F2937` | `#E2E8F0` | 分割线、卡片描边 |
| `--text-primary` | `#F1F5F9` | `#0F172A` | 主文本 |
| `--text-secondary` | `#94A3B8` | `#475569` | 次要文本 / label |
| `--text-mono` | `#E5E7EB` | `#1E293B` | 代码、数字、symbol |
| `--accent` | `#00C896` | `#059669` | 主操作（CTA） / 收益正向 |
| `--warning` | `#F59E0B` | `#D97706` | kill switch、待 review |
| `--danger` | `#FF4D4F` | `#DC2626` | 风控突破、回撤、reject |
| `--info` | `#60A5FA` | `#2563EB` | 链接、提示 |

### 2.2 字体

- UI 主字体：**Inter**，weights 400 / 500 / 600 / 700
- 数字 / 代码 / symbol：**JetBrains Mono**，weight 400 / 500
- 中文场景下退回到系统字体（PingFang SC / Microsoft YaHei）

### 2.3 整体调性

- **dense + professional**，不要拟物化、不要大插画
- 参考目标：[Linear](https://linear.app)（间距）/ [Vercel Dashboard](https://vercel.com)（卡片密度）/ [QuantConnect Terminal](https://www.quantconnect.com/terminal/)（图表密度）
- **避免**：金融科技产品里的"绿涨红跌大屏"那种炫技感、不要 lottie 动画、不要大字标语
- 圆角统一 `rounded-lg`（8px）；按钮、卡片、输入框统一描边而非阴影
- 状态色不要单独靠颜色区分（考虑色盲），文字 / icon 必须同时变化

---

## 3. 信息架构

### 3.1 整体布局

```
┌──────────────────────────────────────────────────────────────────┐
│  [LOGO]                                       [theme] [help] [⚙] │  ← 64px topbar
├────────┬─────────────────────────────────────────────────────────┤
│        │  🟢 paper-only · live trading disabled · kill switch on │  ← 36px safety strip（永远显示）
│        ├─────────────────────────────────────────────────────────┤
│ side   │                                                         │
│ nav    │                page content                             │
│ 240px  │                                                         │
│        │                                                         │
└────────┴─────────────────────────────────────────────────────────┘
```

### 3.2 左侧导航（按 phase 顺序排列）

| Icon | Label | 路由 | Phase |
| --- | --- | --- | --- |
| `LayoutDashboard` | Dashboard | `/` | 全局 |
| `Database` | Data Explorer | `/data` | Phase 1 |
| `FlaskConical` | Factor Lab | `/factors` | Phase 2 |
| `LineChart` | Backtest & Compare | `/backtest` | Phase 3 |
| `Beaker` | Experiments | `/experiments` | Phase 4 |
| `Wallet` | Paper Trading | `/paper` | Phase 5 |
| `Bot` | Agent Studio | `/agent` | Phase 7 |
| `Globe2` | Prediction Market | `/prediction-market` | Phase 8 |
| `Settings` | Settings | `/settings` | 全局 |

底部加一个折叠的 "Safety & Limits" 面板，永远展示：

```
dry_run: true
paper_trading: true
live_trading_enabled: false
kill_switch: ON
max_position_size: 5%
max_daily_loss: 2%
max_drawdown: 10%
```

不可编辑。点击跳到 Settings。

---

## 4. 页面规格

> 每个页面用 **页面目的 / 必须展示的数据 / 主要操作 / 不能做的事 / 空状态 / 错误状态** 6 段式描述。  
> 设计 agent 必须**严格遵守"不能做的事"**——这是产品的安全承诺。

### 4.1 Dashboard（首页）

**目的**：30 秒内让用户看到"项目正在干什么 / 最近一次跑了什么"。

**必须展示**：

1. 顶部 4 个 KPI 卡：`total runs`、`pending agent reviews`、`risk breaches (last 7d)`、`last paper-trading equity`（若无显示 `—`）
2. 4 列卡片流（按 `created_at` 倒序，最多 12 张）：
   - 卡片头：类型标签（backtest / experiment / paper / agent）+ 时间
   - 卡片体：策略名 / output_dir 路径
   - 卡片尾：核心指标（return / Sharpe / fills / candidates）
3. 右侧栏：Quick Actions（4 个按钮：New Backtest / New Experiment / New Agent Task / Open Settings）

**主要操作**：点击卡片 → 跳到对应详情页。

**不能做的事**：

- ❌ 不展示"账户余额 / 实时盈亏"（后端没有 live 概念）
- ❌ 不展示与外部 broker 的连接状态

**空状态**：插画 + "Run `quant-system data ingest-sample` to bootstrap your first dataset" + 一个 "Open docs" 按钮链到 [OVERVIEW.md](../OVERVIEW.md)。

**错误状态**：API 不通时显示一个置顶的 banner："Backend unreachable at `http://127.0.0.1:8765`. Did you run `quant-system serve`?"

---

### 4.2 Data Explorer

**目的**：浏览本地数据集质量，K 线可视化。

**必须展示**：

1. 顶部 filter bar：universe 多选（chip）、start/end date picker、source 选择（sample / tiingo / local）
2. 主区：candlestick + volume chart（推荐 lightweight-charts 或 ECharts）
3. 右侧栏 — 数据质量小卡片：rows、coverage %、missing days、duplicate rows、price anomalies count
4. 底部表格：可分页查看 raw OHLCV，每页 50 行

**主要操作**：

- 选 symbol + 日期 → 自动重新拉数据
- 点 "Re-ingest from Tiingo" 按钮 → 调 `POST /api/data/ingest`（仅 dev mode 可用）

**不能做的事**：

- ❌ 不展示实时报价 / 分钟级以下数据
- ❌ 不允许编辑 OHLCV 数值

**空状态**：引导按钮 "Run sample ingestion (no API key needed)"。

---

### 4.3 Factor Lab

**目的**：跑因子，看 IC、分组收益、值分布。

**必须展示**：

1. 顶部 Factor 选择器（5 个内置 + alpha101 库可展开）
2. 右侧 ConfigPanel：universe 多选、start/end、lookback 滑块（1-252）、direction（only display）
3. 主区四象限：
   - **左上**：因子值时间序列折线图（每个 symbol 一条线）
   - **右上**：IC / Rank IC 时间序列 + 期间均值卡片
   - **左下**：分组收益柱状图（quintile，5 根柱子）
   - **右下**：因子值分布直方图 + 偏度 / 峰度数字
4. 顶部右上角："Draft new factor with AI" 按钮 → 跳到 Agent Studio 的 propose-factor 页面

**主要操作**：

- 跑因子 → 进度条
- 把当前 IC 报告"另存为研究笔记"

**不能做的事**：

- ❌ 不允许在前端编辑因子代码（前端永远不 import / exec 因子）
- ❌ 不展示 sample data 的 IC 当作真实结论（必须有 banner 警告 "sample data: results are illustrative only"）

**空状态**：引导 "Pick a factor and a date range to start."

---

### 4.4 Backtest & Compare（核心页）

**目的**：跑回测，与大盘 / buy-and-hold 对比。

**必须展示**：

1. 左侧 ConfigPanel：strategy 类型（top-N / approved candidate）、universe、start/end、initial cash、commission_bps、slippage_bps、top_n
2. 主区从上到下：
   - **巨型对比图**：3 条曲线（strategy / benchmark = SPY / equal-weight buy-and-hold）+ 切换控件（normalized to 1.0 / absolute equity / drawdown）
   - **指标卡 6 个**：total return、annualized、Sharpe、Sortino、max drawdown、turnover ratio。每个卡片附"vs benchmark"差值，绿/红显示
   - **持仓热力图**：x = 日期，y = symbol，色块深浅 = weight 绝对值。tooltip 显示具体权重
   - **订单 / 成交表**：可筛选（all / fills only / rejected only / SPY only），分页 50 行
3. 顶部右上角 "Save snapshot" → 把整套 config + result 落到 `backtests/<id>/`

**主要操作**：

- 跑回测 → 进度条 + 实时 log（仅展示 stderr 摘要，不展示完整 stack）
- 切换 benchmark 标的（SPY / QQQ / Custom symbol）

**不能做的事**：

- ❌ "Save snapshot" 不会推到任何外部位置；只本地落盘
- ❌ 不展示"如果上线能赚多少"之类的预测

**空状态**："Run your first backtest. Sample data needs no API key."

---

### 4.5 Experiments

**目的**：浏览历史实验、对比 walk-forward 折叠。

**必须展示**：

1. 左侧实验列表（按时间倒序），每条显示 experiment_id 和 best_run_id
2. 主区四个 tab：
   - **Sweep heatmap**：lookback × top_n 的 Sharpe 矩阵（颜色 = Sharpe）
   - **Walk-forward folds**：每个 fold 一行，展示 train / validation Sharpe + total return
   - **Run comparison**：所有 run 的柱状图 + 排序按钮
   - **Agent summary**：直接渲染该实验的 `agent_summary.json` 内容（折叠树形 + 复制 JSON 按钮）
3. 顶部"Compare with another experiment"下拉，可叠加另一组 experiment

**主要操作**：选 best run → 一键 "Send to Backtest page" 复用配置。

**不能做的事**：

- ❌ 不允许在前端修改 experiment_config.json；必须重新跑
- ❌ 不展示"上线建议"

**空状态**：链到 `quant-system experiment run-sample` 文档。

---

### 4.6 Paper Trading

**目的**：基于已有 score frame 跑 paper trading，可视化订单生命周期 + 风控。

**必须展示**：

1. 左侧 ConfigPanel：score frame 选择（来自某次 experiment）、universe、initial cash、commission/slippage、`kill_switch` 开关（默认 on，warning 色高亮）
2. 主区从上到下：
   - **资金曲线 + benchmark 对比图**（同 backtest 页）
   - **订单生命周期表格**：状态色块（NEW=蓝 / SENT=info / PARTIALLY_FILLED=warning / FILLED=accent / REJECTED=danger / EXPIRED=gray）+ 状态机示意（mini stepper）
   - **风控突破日志**：红底卡片，每条显示 reason / breached_limit / order_id / timestamp
   - **持仓 + 现金时间轴**
3. 顶部 prominent 提示："This is a one-shot batch run. There is no live order book."

**主要操作**：

- "Run paper trading" 按钮：confirm dialog 强制确认 kill switch 状态
- 切换 kill switch：写到下次 run 的 config，**不影响当前正在跑的进程**（要 explicit 解释）

**不能做的事**：

- ❌ 不实现"实时下单"动画（后端是离线 batch，假装实时是欺骗）
- ❌ 不允许在前端"取消订单 / 改单"
- ❌ 不展示与外部 broker 连接状态

**空状态**："Run an experiment first to generate a score frame, then bring it here."

---

### 4.7 Agent Studio（核心页）

**目的**：让人用 AI 起草因子 / 实验配置 / 报告，并通过人工 review 隔离风险。

**布局**：三栏。

**左栏 — 任务发起表单**：

- Task type：propose-factor / propose-experiment / summarize / audit-leakage（radio）
- Goal（textarea，required）
- Universe（多选 chip）
- Output dir（默认 `data/agent_run`）
- LLM：stub（默认）/ openai（hover tooltip 解释 "stub is offline & deterministic"）
- 提交按钮 "Run task"

**中栏 — Candidate Pool**：

- 三个 tab：Pending / Approved / Rejected
- 每个 candidate 卡片：candidate_id、type、created_at、metadata 摘要（含 `safety.auto_promotion: false` 高亮）
- 卡片 click → 选中并加载到右栏

**右栏 — Candidate Detail**：

- Tab 1：Source preview。代码块只读、语法高亮、**不允许 run**。顶部红 banner："This platform never imports or executes candidate code. To use this factor, you must manually rename, code-review, add tests, and register it in `factors/registry.py`."
- Tab 2：Metadata JSON viewer
- Tab 3：Audit Log timeline（每个 event：task / tool_call / candidate_written / review_recorded）
- Tab 4：Reviews（list of reviews.jsonl）
- 底部：人工 review 表单 (Approve / Reject) + Note textarea + 提交按钮  
  ⚠️ Approve 按钮必须有 confirm dialog，dialog 文案明确写 "Approving creates an `approved.lock` file only. It does NOT register the factor automatically."

**独立 Tab — Research Reports**：

- 渲染 `reports/agent/*.md`（用 react-markdown + KaTeX + syntax highlight）

**不能做的事**：

- ❌ 不能从前端注册因子到 FactorRegistry（这是产品最重要的 invariant）
- ❌ 不能在前端 exec 候选源码
- ❌ Approve 不能链式触发任何后续动作

---

### 4.8 Prediction Market（占位页）

**目的**：展示 sample 数据下的 mispricing scanner + dry proposal。

**必须展示**：

1. 顶部红色横幅（不可关闭）："Polymarket live integration is intentionally disabled. Sample data is illustrative only."
2. Events 列表 → 选一个 event → 显示其 markets / outcomes
3. Order book snapshot（best bid / best ask）
4. Mispricing candidates 表格（显示 edge_bps，按 edge 排序）
5. Dry proposals 表格（每条显示 dry_run=true 标签，capital, expected_profit）
6. 左下角"Why is live disabled?"链接，跳到 [phase_8_architecture.md §8.4](../architecture/phase_8_architecture.md)

**主要操作**：

- "Run scanner on sample data" → 调 `POST /api/prediction-market/scan`
- "Generate dry arbitrage" → 调 `POST /api/prediction-market/dry-arbitrage`

**不能做的事**：

- ❌ 不展示真实 Polymarket 数据
- ❌ 不显示任何"submit / sign / redeem"按钮
- ❌ 不允许调整 fee / gas 参数后"模拟上链"

---

### 4.9 Settings

**目的**：只读展示当前 settings；少量"切换主题 / 切换语言"。

**必须展示**：

- 当前 `.env` 解析结果（API key 永远脱敏为 `**********`）
- 默认风控参数表
- 数据目录配置
- 主题切换（dark / light / system）
- 语言切换（中文 / English；前端文案至少要做 i18n 占位）

**不能做的事**：

- ❌ 不能在前端修改 `.env` 或 risk limits

---

## 5. 全局组件清单

> 设计稿和实现都用同一套命名，方便对应到 shadcn/ui。

| 组件 | shadcn/ui | 用法 |
| --- | --- | --- |
| `SafetyStrip` | `Banner` | 顶部永远显示的 paper-only 提示 |
| `KpiCard` | `Card` | Dashboard 顶部 KPI |
| `RunCard` | `Card` | Dashboard 卡片流 |
| `ConfigPanel` | `Card` + `Form` | 各页左侧 / 右侧的参数面板 |
| `EquityChart` | recharts `LineChart` | 资金曲线 + benchmark 对比 |
| `CandlestickChart` | lightweight-charts | OHLCV 蜡烛 |
| `HeatmapMatrix` | recharts custom | sweep heatmap / 持仓热力图 |
| `OrderTable` | `Table` + `Badge` | 订单生命周期 |
| `RiskBreachList` | `Alert` | 风控突破日志 |
| `CandidateCard` | `Card` | Agent Studio 候选 |
| `AuditTimeline` | custom | 审计日志 |
| `MarkdownReport` | `react-markdown` | 研究报告渲染 |
| `ConfirmDialog` | `AlertDialog` | 所有需要确认的高风险操作 |
| `KillSwitchToggle` | `Switch` + `AlertDialog` | paper trading 页 |
| `LiveDisabledBanner` | `Banner` | Prediction Market 顶部 |

---

## 6. 后端 API 形态（前端依赖项）

> 详见 [src/quant_system/api/](../../src/quant_system/api/)（Phase 9 实现，见 Codex prompt）。

预期 endpoint 集（前端可凭这个 mock 数据先做静态稿）：

```
GET    /api/health                         → safety state snapshot
GET    /api/settings                       → masked settings
GET    /api/symbols                        → list of symbols available locally
GET    /api/ohlcv?symbol=&start=&end=      → time series

GET    /api/factors                        → registry list
POST   /api/factors/run                    → kick a factor run
GET    /api/factors/{run_id}               → factor result

POST   /api/backtests/run                  → kick backtest
GET    /api/backtests                      → list
GET    /api/backtests/{id}                 → detail (equity, orders, fills, metrics)
GET    /api/benchmark?symbol=&start=&end=  → benchmark equity curve

GET    /api/experiments                    → list
GET    /api/experiments/{id}               → detail (runs, folds, agent_summary)

POST   /api/paper/run                      → kick paper trading
GET    /api/paper                          → list paper-trading runs
GET    /api/paper/{id}                     → detail (orders, fills, breaches, equity)

GET    /api/agent/candidates               → list (filter by status)
GET    /api/agent/candidates/{id}          → detail (metadata, source, audit)
POST   /api/agent/tasks                    → propose-factor / propose-experiment / ...
POST   /api/agent/candidates/{id}/review   → write approved.lock / rejected.lock

GET    /api/prediction-market/markets      → sample events / markets
POST   /api/prediction-market/scan         → run scanners
POST   /api/prediction-market/dry-arbitrage→ run dry optimizer
```

所有 POST 同步执行（小数据足够），不开后台 worker。

---

## 7. 安全与诚实性约束（设计 agent 必读）

这一节直接复制到给 Stitch / v0.dev / Codex 的 prompt 末尾：

1. **paper-only 标识必须始终可见**。任何隐藏它的设计稿都要被退回。
2. **禁止任何"submit order / send to broker / connect wallet / redeem token"按钮**。即使是占位也不允许。
3. **禁止把 sample data 的 Sharpe / IC / edge 当作真实策略效果**。所有 sample 来源的图表必须有 "Sample data — illustrative only" 角标。
4. **Approve 候选必须二次确认**，文案必须包含 "approving does not register the factor"。
5. **禁止编辑因子源码 / risk limits / .env 内容**。前端永远只读这些。
6. **禁止"实时下单动画"**。paper trading 是离线 batch，UI 应展示出 batch 性质（进度条 + 完成态）。
7. **禁止 mock 假登录界面**。本平台是单机工具，没有用户系统。
8. **配色必须保持非情绪化**。不要全屏绿色 / 红色，不要"涨势火焰"动画。

---

## 8. 国际化与可访问性

- 所有文案先用英文写一份，中文 i18n 文件用 key-value 存到 `frontend/locales/zh-CN.json`。
- 颜色对比度全部满足 WCAG AA。
- 所有交互可键盘完成；图表给 alt 描述。
- 不依赖鼠标 hover 才能看到的数据：tooltip 内容必须有备用展现方式。

---

## 9. 实现技术栈（implementation 必须使用）

- **框架**：Next.js 14+（app router）+ TypeScript（strict）
- **样式**：Tailwind CSS + shadcn/ui
- **图表**：recharts（线 / 柱 / 散点）+ lightweight-charts（K 线）
- **数据**：TanStack Query v5（fetch + cache）+ zod（response 校验）
- **表格**：TanStack Table v8
- **Markdown**：react-markdown + remark-gfm + remark-math + rehype-katex + rehype-highlight
- **测试**：Vitest（unit）+ Playwright（e2e smoke）
- **包管理**：pnpm

---

## 10. 给设计 agent 的提示模板

```
You are designing a 9-page web app for a local quant research platform. Read the brief
in docs/frontend/design_brief.md verbatim. Output dark-mode-first, dense, professional
designs in the style of Linear and Vercel Dashboard. Use the color tokens, typography,
and component names from the brief exactly.

Constraints (must follow strictly):
- The "paper-only · live trading disabled · kill switch on" strip must appear on every page.
- Do NOT design any "submit order", "connect wallet", "redeem token" buttons.
- Sample-data charts must include a "Sample data — illustrative only" tag.
- The Agent Studio approve action must be a two-step confirm with the text
  "Approving creates an approved.lock file only. It does NOT register the factor automatically."

Generate, in order:
1. The 240px sidebar with 9 nav entries.
2. Dashboard.
3. Backtest & Compare (this is the most important page).
4. Agent Studio (three-column layout).
5. Paper Trading.
6. The remaining pages (Data Explorer, Factor Lab, Experiments, Prediction Market, Settings).

After each page, list the components by shadcn/ui name and the API endpoints they bind to.
```
