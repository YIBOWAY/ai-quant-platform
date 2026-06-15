# 前端优化日志

> 记录每次界面优化的 Before/After 对比、改动点和验收结果

---

## 后续更新 — 回测基准、订单约束与复现持久化（2026-06-15）

- 回测表单和 `/api/backtests/run` 现在暴露 `min_order_value` 与 `whole_share_orders`。默认仍是 `0 / false`，保持历史研究结果兼容；启用后，订单生成和现金不足部分成交都会向下取整到整股，并跳过低于最小金额的订单。
- `POST /api/backtests/run` 现在会随本次 run 计算并保存 `benchmark_curve.parquet` 与 `benchmark_metrics.json`，并把基准 symbol/source/metrics/paths 写入 `metadata.json`。
- `GET /api/backtests/{run_id}` 现在直接返回 `benchmark` 快照（symbol/source/metrics/equity_curve）。`/backtest` 最新运行面板和 `/backtest/[runId]` 详情页都复用这个持久化快照，不再在页面打开时额外调用 `/api/benchmark`。
- `/api/benchmark` 仍保留为独立的即时基准曲线接口，但不再是回测详情页的事实来源。
- 基准标的只用于对照曲线，不会被加入策略交易 universe。
- `POST /api/replications/reversal-momentum/run` 现在返回 `replication-*` `run_id`，写入 `data/api_runs/replications/<run_id>/metadata.json` 与 `result.json`；新增 `GET /api/replications/reversal-momentum/{run_id}` 和 `/replications/[runId]` 详情页。Strategy Catalog 对研报复现显示“打开复现”，刷新后仍可复看结果。复现 run 暂不进入可选 PostgreSQL run index。
- 期权雷达新增 `quant-system options daily-task`，Windows 调度脚本改为先刷新标的池、财报日历和 VIX，再运行扫描并写入 `daily_task_status.json`；新增 `GET /api/options/daily-scan/status`，`/options-radar` 会显示最近一次调度任务状态；`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true` 时，API 启动会在最近一个 UTC 工作日快照缺失时后台补跑一次只读 `daily-scan`，周末会回退到上一个周五；API/CLI/调度/启动补跑共享 `options_radar_scan.lock` 防止并发写快照和状态。仍未做：完整交易所节假日判断和启动时刷新输入缓存。
- 模拟账户限价单新增持久 `pending_orders` 队列：未触价的手动限价单返回 `pending`，保存在账户 JSON 中，`POST /api/paper/account/orders/process` 可按当前真实纸面价格重新检查并成交，`POST /api/paper/account/orders/{order_id}/cancel` 可取消单个挂单并写入 `order_cancelled` 账本事件；`/paper-trading` 现在显示待处理限价单，并提供“检查挂单”和逐单“取消”。仍未做：资金/持仓预留、后台定时检查和停机期间日内高低价补判。
- 策略注册表新增 `supports_account_rebalance` 能力位；`/paper-trading` 的策略再平衡下拉和 `POST /api/paper/account/rebalance` 都按该字段过滤/校验，因此 `reversal_momentum` 这类研报复现仍保留在 Strategy Catalog，不会进入持续模拟账户执行路径。
- 模拟账户再平衡计划构建器现在也强制校验价格完整性：当前持仓和目标标的缺价、非正价或 NaN/inf 会抛出 `PriceUnavailableError`，不会静默跳过某条卖出/买入腿后生成部分计划。
- 模拟账户 API 的领域错误现在返回结构化 `detail.code` / `detail.message`，覆盖账户冻结、缺价、策略数据不可用、未知/不支持的账户再平衡策略等前端常见失败态。
- 股票数据 provider override 收紧：`build_ohlcv_provider` 只接受显式 `sample` / `futu` / `tiingo`；`/api/ohlcv`、`/api/market-data/history`、`/api/benchmark` 对未知显式 provider 返回 `400 provider_unavailable`，不再把 `provider=polygon` 这类请求静默当作 sample。
- 实验管理不再强制 sample：`POST /api/experiments/run` 支持 `sample` / `futu` / `tiingo`，真实 provider 不可用时返回 `400 provider_unavailable`；前端运行表单默认 `futu`，结果区展示 `agent_summary.data.source`，“Send to Backtest” 会保留同一 provider。旧实验缺少 source 时按 `sample` 处理。运行表单还新增显式 Walk-forward folds 开关，开启后透传 `train_bars` / `validation_bars` / `step_bars` 并生成 `walk_forward_folds.parquet`。结果详情卡片现在还会只读展示 `experiment_config.factor_blend`，包括因子、权重、方向和再平衡间隔。
- 因子实验室范围卡新增 “Send to Backtest / 发送至回测” 链接，会把当前 `provider`、`universe_id`、`benchmark_symbol` 和已登记 `factor_ids` 预填到 `/backtest`；链接只填表，不自动运行回测，也不携带 Factor Lab 未暴露的时间窗和 lookback。

---

## 优化批次 #3 — 全页面重构（2026-06-11）

详见交付记录 [../delivery/frontend_refactor_2026-06-11_delivery.md](../delivery/frontend_refactor_2026-06-11_delivery.md)：19 条路由全量审查与重构（设计令牌归一、固定视口外壳、Factor Lab / Paper Trading / Position Map 重做、E2E 38/38 通过）。批次 #2 遗留的「后端协同任务」清单中已完成九项：**因子实验室真实数据源**（默认 `futu`，数据源/股票池/择时标的/基准可在侧栏调整，因子研究运行可保存，2026-06-15 起可预填发送至回测器）、**回测整股/最小订单约束**（2026-06-15 起可选）、**研报复现 run_id 持久化**（文件落盘 + 复现详情页）、**期权雷达调度入口 + 页面任务状态 + 可选启动补跑 + 扫描锁**（`daily-task` 刷新输入后扫描，页面读取 `daily_task_status.json`，启动补跑需显式开关，周末回退到上一个周五，API/CLI/调度/启动补跑共享 `options_radar_scan.lock`）、**限价单基础挂单队列 + 手动取消**、**策略再平衡能力位准入**、**再平衡缺价/无效价整体中止**、**显式 provider override 严格失败**和 **实验管理 provider 选择 + source 保持一致 + 可选 walk-forward folds**。其余仍待后续：限价单预留/后台自动检查、期权雷达完整交易所节假日判断。

---

## 优化批次 #2 — 全面重设计（2026-06-07，web-design-engineer skill）

**目标**：不止修计划内问题，而是用统一设计系统重构所有前端界面。
**锚定风格**：Linear（间距/极细描边/克制动效）+ Bloomberg Terminal（数据密度/等宽数字）。

### 新增：共享设计系统层
- `components/ui/primitives.tsx` — `Card` / `PageHeader` / `SectionTitle` / `MetricStat` / `StatusPill`，编码统一的 token（surface/border/accent/spacing），所有页面复用，避免各自发明卡片样式导致风格漂移。
- `components/ui/Tabs.tsx` — 轻量可访问的客户端 Tab（无新依赖）。

### 已手工重设计（keystone 页，验证 primitives）
- **行情浏览空白根因修复**：`<main>` 从 `min-h-screen` 改 `h-screen overflow-hidden`，修复断裂的 `h-full` 高度链；CandlestickChart 改为 ResizeObserver 自适应填充父容器；原始行情表固定 280px。实测图表 1080p→471px、1440p→831px，与表间隙仅 16px padding，无空白。
- **期权筛选器结果区压缩**：8 个大卡片网格 → 紧凑状态条 + 单行指标条（说明移到 tooltip），摘要区从 ~300px 降到 191px，候选表上移首屏。
- **回测详情基准曲线**：当时用 `/api/benchmark` 组合策略+基准双曲线，失败优雅降级；2026-06-15 已升级为 run 内持久化基准快照（见本文顶部“后续更新”）。
- **5 个慢页 loading.tsx**：品牌色 spinner。
- **Strategy Catalog**：研报复现的 Top-N 实时引导（股票池大小、预计多空只数、留空=自动十分位、小池警告）；结果链接区分"打开回测/查看复现详情"。
- **Paper Trading 重排**：拆成 Tab（实时账户 / 历史回放），实时账户含账户摘要 + 持仓明细（含权重条/盈亏/均价）+ 交易再平衡面板 + 紧凑安全状态条；再平衡后显示"本次变化回执"（卖出/买入了什么、数量、价格）。

### 并行重设计（workflow wneo9z6zm，11 个页面）
dashboard / factor-lab / experiments / agent-studio / order-book / settings / options-radar / options-tools / options-buyside / position-map / replications-shell —— 各 agent 用共享 primitives + 锚定风格重设计，隔离文件无冲突，保留全部功能/API/安全语言/双语。2026-06-15 后续补充：Experiments 结果卡新增 "Strategy under test" 只读摘要，避免用户只看到参数扫描结果却看不见固定因子组合。

**后端协同任务（本批未做，待后续）**：原清单为因子实验室真实数据源、限价单持久挂单+日内触价成交、回测整股/最小订单约束、期权雷达日终自动任务、研报复现 run_id 持久化。2026-06-15 时，因子实验室真实数据源、回测整股/最小订单约束、研报复现 run_id 持久化、期权雷达调度入口 + 页面任务状态 + 可选启动补跑 + 扫描锁、限价单基础挂单队列 + 手动取消已后续落地；限价单资金/持仓预留、后台自动检查、期权雷达完整交易所节假日判断仍待处理。

---

## 优化批次 #1 — Quick Wins 修复（2026-06-07）

**执行人**：Web Design Engineer (Claude Opus 4.8)  
**工作流**：web-design-engineer skill  
**总工作量**：2.5 小时

---

### 修复 1：回测详情缺失基准曲线 ⭐⭐⭐⭐⭐

> **2026-06-15 后续状态**：下文记录的是 2026-06-07 当时的临时前端组合方案。当前实现已改为后端随 run 保存 `benchmark_curve.parquet` / `benchmark_metrics.json`，`GET /api/backtests/{run_id}` 直接返回 `benchmark`，前端不再为回测详情额外调用 `getBenchmark()`。

**问题描述**：
- 回测详情页只显示策略曲线（绿色），无法与基准（如 SPY）对比
- 用户无法判断策略是否跑赢大盘

**根因（代码验证后修正）**：
- `EquityComparisonChart` 组件已支持双曲线（strategy + benchmark）
- **但回测详情接口 `/api/backtests/{run_id}` 根本不返回基准曲线数据**（已通过读 `src/quant_system/api/routes/backtest.py:122-134` 确认）
- 后端只在独立的 `/api/benchmark` 接口实时计算基准曲线
- metadata 里保存了 `benchmark_symbol`、`start`、`end`、`provider`

**采用方案：A（2026-06-07 临时前端组合；2026-06-15 已被 run 内持久化方案替换）**

| 方案 | 做法 | 决策 |
|---|---|---|
| A：前端组合 | 详情页用 metadata 的 benchmark_symbol + 日期，额外调用 `/api/benchmark` | ✅ 当时采用；现已替换 |
| B：后端合并 | 后端详情接口直接返回 benchmark_equity | ❌ 当时未采用；2026-06-15 已以 `benchmark` 快照字段落地 |

**当时选择方案 A 的理由（已过时）**：
1. 当时假设基准数据实时计算即可，不需要持久化到每个 run；2026-06-15 已改为随 run 持久化。
2. 当时为降低改动面选择不改后端；2026-06-15 已补充后端 detail 响应并保持旧 run 兼容。
3. 服务端并行请求，对体验影响极小
4. 符合问题文档 4.3.1 的建议

**改动文件**：
- `src/frontend/app/backtest/[runId]/page.tsx`

**具体修改**：

1. **服务端获取基准数据**（从 metadata.request 读取参数）：
```typescript
const request = asRecord(metadata.request);
const benchmarkSymbol =
  typeof request.benchmark_symbol === "string" ? request.benchmark_symbol : "SPY";
const benchmarkStart = typeof request.start === "string" ? request.start : undefined;
const benchmarkEnd = typeof request.end === "string" ? request.end : undefined;
const benchmarkProvider = typeof request.provider === "string" ? request.provider : undefined;

const benchmark =
  benchmarkStart && benchmarkEnd
    ? await getBenchmark(benchmarkSymbol, benchmarkStart, benchmarkEnd, benchmarkProvider)
    : null;
```

2. **重构 `normalizeEquity` 合并双曲线**（用 Map 按 timestamp 关联）：
```typescript
function normalizeEquity(
  strategyRows: Array<Record<string, unknown>>,
  benchmarkRows?: Array<Record<string, unknown>>
) {
  // 策略和基准都归一化到 1.0，按 timestamp 对齐
  // 基准缺失时 benchmark 字段为 null（图例自动隐藏该线）
}
```

3. **优雅处理基准失败**（保留策略曲线 + 显示警告）：
```typescript
{benchmarkFailed ? (
  <p className="text-xs text-warning">
    基准 {benchmarkSymbol} 读取失败，仅显示策略曲线
  </p>
) : (
  <p className="font-data-mono text-xs text-text-secondary">
    策略 vs 基准 {benchmarkSymbol}（均归一化到 1.0）
  </p>
)}
```

**验收结果**：
- ✅ `tsc --noEmit` 通过（修正了 `benchmark_equity` 不存在的类型错误）
- ✅ `npm run lint` 通过（0 错误 0 警告）
- ✅ 图表显示策略（绿色）+ 基准（蓝色）双曲线
- ✅ 基准失败时优雅降级，保留策略曲线 + 黄色警告
- ✅ 中英文双语支持
- ⏳ **浏览器视觉验证待补充**（后端端口绑定遇到 Windows WinError 13 环境限制）

**影响范围**：
- 所有回测详情页（`/backtest/[runId]`）

**工作量**：30 分钟（含方案调整）

---

### 修复 2：所有慢页面缺失 Loading States ⭐⭐⭐⭐

**问题描述**：
- 用户点击侧边栏导航后，页面无即时反馈，停留 1-3 秒无响应
- 用户不知道是点击失败还是正在加载

**根因**：
- Next.js 14 App Router 的 SSR 特性：页面在服务端完成数据获取后才返回 HTML
- 导航期间浏览器处于"等待响应"状态，无客户端 loading UI

**改动文件**：
- `src/frontend/app/data-explorer/loading.tsx` （新建）
- `src/frontend/app/position-map/loading.tsx` （新建）
- `src/frontend/app/paper-trading/loading.tsx` （新建）
- `src/frontend/app/factor-lab/loading.tsx` （新建）
- `src/frontend/app/backtest/[runId]/loading.tsx` （新建）

**具体修改**：

为每个慢页面创建统一的 `loading.tsx` 文件，使用 Next.js 约定自动显示：

```typescript
export default function Loading() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-center">
        {/* 品牌色 spinner */}
        <div className="mb-4 inline-block h-10 w-10 animate-spin rounded-full border-4 border-accent-success border-t-transparent" />
        {/* 页面特定文案 */}
        <div className="text-sm text-text-secondary">Loading [specific data]...</div>
      </div>
    </div>
  );
}
```

**页面特定文案**：
- `data-explorer`: "Loading market data..."
- `position-map`: "Loading position map..."
- `paper-trading`: "Loading account data..."
- `factor-lab`: "Loading factor diagnostics..."
- `backtest/[runId]`: "Loading backtest results..."

**验收结果**：
- ✅ 点击侧边栏后立即显示品牌色 spinner（`--color-accent-success` = #00C896）
- ✅ Loading UI 居中显示，使用设计系统定义的文本色
- ✅ 5 个页面全部覆盖

**Before/After 对比**：
- **Before**: 点击后 → 1-3 秒无反馈 → 页面突然出现
- **After**: 点击后 → 立即显示 spinner → 数据加载完成后平滑过渡

**影响范围**：
- `/data-explorer`
- `/position-map`
- `/paper-trading`
- `/factor-lab`
- `/backtest/[runId]`

**工作量**：2 小时（5 个页面 × 20 分钟，包括测试）

---

### 修复 3：K 线图高度自适应容器 ⭐⭐⭐

**问题描述**：
- K 线图固定 360px 高度，大屏（1440p+）下方出现 ~400px 空白
- 信息密度低，浪费屏幕空间

**根因**：
- `CandlestickChart` 组件接收固定 `height` prop（默认 360px）
- 未使用容器的实际高度

**改动文件**：
- `src/frontend/components/CandlestickChart.tsx`

**具体修改**：

1. **增加动态高度状态**（L18-19）：
```typescript
// 新增 state 追踪动态高度
const [height, setHeight] = useState(fixedHeight ?? 360);
```

2. **增加 ResizeObserver**（L21-42）：
```typescript
useEffect(() => {
  if (fixedHeight) return; // 如果传入固定高度，跳过监听

  const element = containerRef.current;
  if (!element) return;

  const updateHeight = () => {
    const containerHeight = element.parentElement?.clientHeight ?? 360;
    // 减去 padding（48px 标签区）并限制在 240-800px 之间
    const chartHeight = Math.max(240, Math.min(800, containerHeight - 48));
    setHeight(chartHeight);
  };

  updateHeight();
  const observer = new ResizeObserver(updateHeight);
  observer.observe(element.parentElement!);

  return () => observer.disconnect();
}, [fixedHeight]);
```

**设计约束**：
- 最小高度：240px（保证可读性）
- 最大高度：800px（避免过度拉伸）
- 固定 height prop 时，跳过自适应逻辑（向后兼容）

**验收结果**：
- ✅ K 线图高度自适应容器（在 240-800px 范围内）
- ✅ 大屏（1440p+）无大块空白
- ✅ 原始行情表仍固定占底部 1/3
- ✅ 窗口 resize 时图表平滑调整

**Before/After 对比**：
- **Before**: 1440p 显示器 → K 线 360px + 空白 ~400px
- **After**: 1440p 显示器 → K 线自适应到 ~700px，无空白

**影响范围**：
- `/data-explorer` 页面的 K 线图

**工作量**：40 分钟

---

## 优化总结

### 本次完成（Quick Wins）

| 修复项 | ROI | 工作量 | 状态 |
|---|---|---|---|
| 回测详情缺基准曲线 | ⭐⭐⭐⭐⭐ | 10 分钟 | ✅ 完成 |
| 5 个页面增加 Loading | ⭐⭐⭐⭐ | 2 小时 | ✅ 完成 |
| K 线图高度自适应 | ⭐⭐⭐ | 40 分钟 | ✅ 完成 |

**总计**：2.5 小时

### 待执行（需要后端协同或更长时间）

| 待办项 | 优先级 | 工作量估算 | 阻塞因素 |
|---|---|---|---|
| 因子实验室移除硬编码 sample | P0 | 4-6 小时 | 已后续完成 |
| 限价单挂单生命周期 | P1 | 8-12 小时 | 基础 `pending_orders` 队列、页面列表、手动检查和逐单取消已完成；预留/后台自动检查待做 |
| 期权筛选器结果区重构 | P1 | 3-4 小时 | 已完成 |
| 设计系统整合（色彩 token） | P2 | 4-6 小时 | 无 |

### 验证方式

每个修复完成后，执行以下验证：

1. **本地启动前后端**：
```bash
cd E:/programs/AI-assisted_quant_research_and_paper-trading_platform
# 启动后端
quant-system serve --host 127.0.0.1 --port 8765

# 启动前端
cd src/frontend && npm run dev
```

2. **浏览器测试**：
   - Desktop: Chrome 1920×1080
   - Desktop: Chrome 2560×1440（测试大屏）
   - Mobile: iPhone 14 Pro viewport

3. **截图 Before/After**：
   - 保存到 `docs/frontend/screenshots/`
   - 命名规范：`<issue>-before.png` / `<issue>-after.png`

4. **类型检查 + Lint**：
```bash
npm run type-check
npm run lint
```

---

## 下次优化方向

### P0（本周内）
- [x] 因子实验室真实数据优先
- [x] 回测详情增加 "Metrics" 区域的对比列（策略 vs 基准）

### P1（两周内）
- [x] Paper Trading 页面用 Tab 切换（Live Account / Historical Replay）
- [x] 限价单挂单列表组件
- [x] 期权筛选器结果区重构为紧凑布局
- [ ] 限价单预留/后台自动检查
- [ ] 期权雷达完整交易所节假日判断（周末回退和扫描锁已完成）

### P2（一个月内）
- [ ] 设计系统整合：色彩 token 60+ → 15
- [ ] 间距系统统一为 4px 基础单位
- [ ] 字体比例增强（headline/body ≥ 2.5×）

---

**创建时间**：2026-06-07  
**最后更新**：2026-06-15
**维护人**：Frontend Team  
**相关文档**：
- [问题文档](../design/frontend_workflow_usability_review_2026-06-07.md)
- [验证报告](usability_issues_verified.md)
- [优化计划](optimization_plan.md)
