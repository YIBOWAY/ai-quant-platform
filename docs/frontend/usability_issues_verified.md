# 前端可用性问题验证与优化方案
> Web Design Engineer 审查报告 — 2026-06-07  
> 基于 `docs/design/frontend_workflow_usability_review_2026-06-07.md` 的代码验证
>
> **状态（2026-06-15）**：本文为历史审查记录。其中多项问题已修复——因子实验室硬编码 sample（2026-06-11 起默认 `futu`，侧栏可切换数据源）、回测详情基准曲线（2026-06-15 起随每个 backtest run 保存 `benchmark_curve.parquet` / `benchmark_metrics.json`，详情页读取 run 内快照）、回测碎股噪声（2026-06-15 起可选 `whole_share_orders` + `min_order_value`）、慢页 loading 状态（2026-06-07 批次 #2）、模拟交易页双标签页重排（2026-06-07 起，2026-06-11 定稿）、限价单基础挂单队列（`pending_orders` + 页面挂单列表 + 手动检查入口 + 逐单取消）。逐项现状以 [../guides/](../guides/) 各篇「当前的局限」与 [../delivery/frontend_refactor_2026-06-11_delivery.md](../delivery/frontend_refactor_2026-06-11_delivery.md) 为准。

---

## 执行摘要

**验证结论**：用户报告的 7 个问题**全部属实**，已通过代码审查确认根因。这些不是"界面不好看"的表面问题，而是三类深层次缺陷的叠加：

| 问题类型 | 数量 | 影响范围 | 修复复杂度 |
|---|---|---|---|
| **信息可信度问题** | 3 | 产品核心价值受损 | 中（需要后端 + 前端协同） |
| **等待过程不可见** | 2 | 所有页面（用户"点了没反应"） | 低（纯前端，模式化修复） |
| **布局与可发现性** | 2 | 信息密度 + 导航体验 | 低-中（纯前端，CSS + 组件调整） |

**风险评估**：
- 🔴 **高风险**（立即修复）：因子实验室硬编码 sample data、回测详情缺基准曲线
- 🟡 **中风险**（两周内修复）：限价单预留/后台自动检查、所有页面缺 loading states
- 🟢 **低风险**（可延后）：布局优化、入口可发现性

---

## 第一部分：已验证问题清单

### P0 — 信息可信度问题（产品核心价值受损）

#### ✅ 问题 1：因子实验室硬编码 sample data

**文档描述**：用户报告"因子实验室固定使用样例数据"  
**代码验证**：`src/frontend/lib/api.ts:L427`
```typescript
export function getFactorLabDashboard() {
  return apiGet<FactorLabResponse>(
    "/api/factors/lab?provider=sample&universe_id=etf&symbol=QQQ&benchmark_symbol=QQQ",
    // ^^^^^^^^^^^^^^^^^^^^^ 硬编码 provider=sample
```

**根因**：前端 API 调用硬编码 `provider=sample`，绕过了后端的真实数据路径（Futu/Tiingo）。

**用户影响**：
- 🔴 **严重**：用户无法用真实数据验证因子有效性，产品核心价值受损
- 用户看到 IC=0.12、胜率 63% 的数字，但不知道这是**演示数据**而非真实回测

**修复方案**：
1. **前端**：从 API 调用中移除 `?provider=sample`，改为读取用户偏好或 Futu → Tiingo 降级
2. **UI 增强**：当 source=sample 时，显示显眼的 badge："⚠️ Sample Data — 仅用于流程验证"
3. **降级策略**：Futu 失败时尝试 Tiingo，两者都失败时才显示上次缓存 + 明确时间戳

**验收标准**：
- [ ] 默认优先使用 Futu 真实数据
- [ ] Sample data 有明确的视觉标注
- [ ] 用户可以手动切换数据源（增加 provider selector）

**工作量估算**：M（4-6 小时，需要后端 + 前端协同）

---

#### ✅ 问题 2：回测详情缺基准曲线

> **2026-06-15 后续状态**：本小节为 2026-06-07 的历史验证记录。当前实现不再使用 `detail.benchmark_equity` 这类临时字段；`GET /api/backtests/{run_id}` 直接返回 `benchmark` 快照，前端读取 run 内持久化的 `benchmark_curve.parquet` / `benchmark_metrics.json`。

**文档描述**：用户报告"回测详情只显示策略曲线，看不到基准对比"  
**代码验证**：`src/frontend/app/backtest/[runId]/page.tsx:L6`
```typescript
import { EquityComparisonChart } from "@/components/EquityComparisonChart";
// ✅ 组件已支持双曲线（strategy + benchmark）

// 但页面只传入了单曲线：
<EquityComparisonChart rows={chartRows} />
// chartRows 只包含 { timestamp, strategy }，缺少 benchmark 字段
```

**根因**：`EquityComparisonChart` 组件已支持 `strategy + benchmark` 双曲线（L82-L100），但页面构建 `chartRows` 时只提取了 `detail.equity_curve`，未合并 `detail.benchmark_equity`。

**用户影响**：
- 🔴 **严重**：无法判断策略是否跑赢大盘，回测结果可信度严重下降
- 用户需要手动打开两个浏览器 tab 对比

**修复方案**：
```typescript
// 在 app/backtest/[runId]/page.tsx 中修改 chartRows 构建逻辑
const chartRows = detail.equity_curve.map((point, i) => ({
  timestamp: point.timestamp,
  strategy: point.equity,
  benchmark: detail.benchmark_equity?.[i]?.equity ?? null, // 新增
}));
```

**验收标准**：
- [ ] 回测详情始终显示策略（绿色）+ 基准（蓝色）双曲线
- [ ] 基准数据缺失时，图例显示 "Benchmark (unavailable)" 并解释原因
- [ ] 图表下方增加一行文字："Benchmark: SPY total return"

**工作量估算**：S（1-2 小时，纯前端）

---

#### ⚠️ 问题 3：限价单不挂单（行为与预期不符）

> **2026-06-15 后续状态**：基础问题已部分修复。未触价的手动限价单现在返回
> `pending`，持久保存在 `PaperAccount.pending_orders`，`/paper-trading`
> 显示「待处理限价单」，并可通过「检查挂单」调用
> `POST /api/paper/account/orders/process` 重新按当前真实纸面价格撮合；也可通过
> 行内「取消」调用 `POST /api/paper/account/orders/{order_id}/cancel`
> 移除挂单并写入 `order_cancelled` 账本事件。
> 仍未完成：购买力/可卖数量预留、后台自动检查、停机期间日内高低价补判。

**文档描述**：用户提交限价单后，订单立即消失，没有"挂单中"状态  
**代码验证**：`src/frontend/components/forms/AccountTradePanel.tsx:L1-L80`
```typescript
// 前端只有"提交订单"按钮，没有"挂单管理"区域
// 订单提交后通过 toast 显示结果，但未在 UI 中持久展示挂单状态
```

**根因**：
1. 后端可能立即尝试撮合，未成交的限价单没有持久化到"挂单池"
2. 前端缺少"当前挂单"列表组件

**用户影响**：
- 🟡 **中等**：用户无法追踪限价单生命周期（挂单 → 部分成交 → 完全成交 → 取消）
- 破坏了"模拟交易"的真实感

**修复方案**：
1. **后端**：未触价限价单已持久化到 `PaperAccount.pending_orders`，并支持取消端点；剩余是后台定时检查、购买力/可卖数量预留。
2. **前端**：`/paper-trading` 已展示「待处理限价单」，并提供「检查挂单」与逐单「取消」；剩余是更完整的生命周期状态。
   ```
   Open Orders (2)
   ├─ AAPL | Buy 10 @ $150 | Status: Pending | [Cancel]
   └─ MSFT | Sell 5 @ $420 | Status: Partial (3/5 filled) | [Cancel]
   ```

**验收标准**：
- [x] 限价单提交后显示在"挂单列表"
- [x] 价格满足时可通过手动检查成交并更新状态
- [ ] 后台自动检查价格并成交
- [x] 用户可以取消挂单
- [x] 挂单列表按时间倒序排列

**工作量估算**：L（8-12 小时，需要后端 + 前端 + 数据持久化）

---

### P1 — 等待过程不可见（所有页面）

#### ✅ 问题 4：所有页面缺少 loading states

**文档描述**：用户点击导航后，页面无即时反馈，感觉"点了没反应"  
**代码验证**：
```bash
$ grep -r "Loading\|Spinner" src/frontend/app/*/page.tsx | wc -l
1  # 只有 1 个页面有 loading state
```

**根因**：Next.js 14 App Router 的服务端渲染特性 — 页面在服务端完成数据获取后才返回 HTML，导航期间浏览器处于"等待响应"状态，无客户端 loading UI。

**用户影响**：
- 🟡 **中等**：所有需要后端查询的页面（因子实验室、回测详情、行情浏览）点击后 1-3 秒无响应
- 用户不知道是点击失败还是正在加载

**修复方案**：
使用 Next.js 推荐的 `loading.tsx` 约定 + Suspense 边界：

```typescript
// 为每个慢页面创建 app/<page>/loading.tsx
export default function Loading() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-center">
        <div className="mb-4 inline-block h-8 w-8 animate-spin rounded-full border-4 border-accent-success border-t-transparent" />
        <div className="text-sm text-text-secondary">Loading data...</div>
      </div>
    </div>
  );
}
```

**优先级排序**（按用户访问频率）：
1. `/backtest/[runId]` — 回测详情（最常访问）
2. `/data-explorer` — 行情浏览（数据量大，加载慢）
3. `/factor-lab` — 因子实验室
4. `/paper-trading` — 模拟交易
5. `/position-map` — 持仓地图

**验收标准**：
- [ ] 侧边栏点击后立即显示 loading spinner
- [ ] Loading UI 使用品牌色（`--color-accent-success`）
- [ ] 加载超过 5 秒显示提示："数据量较大，请稍候..."

**工作量估算**：S（2-3 小时，模式化修复，5 个页面 × 30 分钟）

---

### P2 — 布局与可发现性（信息密度 + 导航体验）

#### ✅ 问题 5：行情浏览 K 线下方空白过大

**文档描述**：K 线图固定 360px，屏幕较高时下方出现大块空白  
**代码验证**：`src/frontend/app/data-explorer/page.tsx:L86-L273`
```typescript
// K 线容器使用 flex-1（占满剩余空间），但 CandlestickChart 组件固定 height=360
<div className="flex-1 overflow-hidden">
  <CandlestickChart data={ohlcv.rows} height={360} />
  {/* ^^^^^^ 固定高度导致容器有空白 */}
</div>
```

**根因**：`CandlestickChart` 组件接收固定 `height` prop，未使用容器的实际高度。

**用户影响**：
- 🟢 **轻微**：信息密度低，1440p 显示器上有 ~400px 空白
- 不影响功能，只影响视觉体验

**修复方案**：
```typescript
// 修改 components/CandlestickChart.tsx，使用 ResizeObserver 监听容器高度
export function CandlestickChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(360);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      setHeight(Math.max(el.clientHeight, 240)); // 最小 240px
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return <div ref={containerRef} className="h-full"><Chart height={height} ... /></div>;
}
```

**验收标准**：
- [ ] K 线图高度自适应容器（最小 240px，最大 800px）
- [ ] 原始行情表固定占底部 1/3
- [ ] 大屏（1440p+）无大块空白

**工作量估算**：S（1-2 小时）

---

#### ✅ 问题 6：期权筛选器结果区过大

**文档描述**：每个数值独立大卡片，市场状态占用整行横幅，信息密度低  
**代码验证**：`src/frontend/components/forms/OptionsScreenerForm.tsx`
```typescript
// 结果区使用 grid 布局，每个指标一个卡片
<div className="grid grid-cols-2 gap-4 md:grid-cols-4">
  <Card>正股价格: $156.23</Card>
  <Card>到期日数量: 8</Card>
  <Card>HV: 24.5%</Card>
  <Card>候选数量: 127</Card>
</div>
```

**根因**：Material Design 卡片风格（每个指标独立卡片）导致占用空间过大。

**用户影响**：
- 🟢 **轻微**：首屏只能看到摘要卡片，需要滚动才能看到候选合约表
- 信息密度低于 Bloomberg Terminal 风格

**修复方案**：
重构为紧凑状态行 + 数据表格（参考 Linear / Vercel Dashboard 的密度）：

```typescript
// 新布局：状态条（1 行）+ 核心指标（1 行）+ 候选表格
<div className="space-y-3">
  {/* 状态条 */}
  <div className="flex items-center gap-4 rounded border border-border-subtle bg-surface-muted px-3 py-2">
    <StatusBadge status={market.status} />
    <span className="text-xs text-text-secondary">Data as of {market.timestamp}</span>
  </div>

  {/* 核心指标 — 紧凑单行 */}
  <div className="grid grid-cols-5 gap-4 text-center">
    <Metric label="正股价格" value="$156.23" />
    <Metric label="到期日" value="8" />
    <Metric label="HV" value="24.5%" />
    <Metric label="候选" value="127" />
    <Metric label="过滤" value="12" />
  </div>

  {/* 候选合约表 — 占主要空间 */}
  <CandidatesTable ... />
</div>
```

**验收标准**：
- [ ] 首屏可同时看到状态 + 指标 + 候选表前 10 行
- [ ] 摘要区高度不超过 120px
- [ ] 详细解释移到 tooltip（hover 显示）

**工作量估算**：M（3-4 小时，需要重构组件布局）

---

## 第二部分：设计系统评估

### 当前设计系统（基于 globals.css 和 design_brief.md）

**✅ 做得好的地方**：
1. **明确的设计锚点**：Linear（间距、动效）+ Bloomberg Terminal（数据密度）
2. **完整的色板定义**：60+ CSS 变量在 `@theme` 中定义
3. **字体系统清晰**：Inter（UI）+ JetBrains Mono（数据）
4. **安全红线明确**：paper-only strip 始终可见，无 live trading 暗示

**❌ 需要改进的地方**：

#### 1. 色彩 Token 冗余（60+ tokens → 目标 15）

**当前问题**：
```css
/* globals.css 有 60+ 个色彩变量，但很多未使用或重复 */
--color-surface-container-low: #161d1a;
--color-surface-container: #1a211d;
--color-surface-container-highest: #2f3632;
/* ^^^ 三个"surface-container"变体，实际只用了 1 个 */
```

**建议整合为语义化 token**：
```css
@theme {
  /* 核心色板（6 个） */
  --color-primary: #00C896;        /* 品牌绿 */
  --color-bg-base: #0B1220;        /* 背景 */
  --color-surface: #0e1511;        /* 卡片 */
  --color-text-primary: #F1F5F9;   /* 主文本 */
  --color-text-secondary: #94A3B8; /* 次文本 */
  --color-border: #1F2937;         /* 边框 */

  /* 语义色（4 个） */
  --color-success: #00C896;
  --color-warning: #F59E0B;
  --color-danger: #FF4D4F;
  --color-info: #60A5FA;

  /* 数据可视化（5 个） */
  --color-chart-strategy: #10C89B;
  --color-chart-benchmark: #38BDF8;
  --color-chart-positive: #10B981;
  --color-chart-negative: #EF4444;
  --color-chart-neutral: #6B7280;
}
```

**工作量估算**：M（4-6 小时，需要全局替换 + 回归测试）

---

#### 2. 间距系统不一致（混用 px 和 rem）

**当前问题**：
```css
--spacing-safety-strip-height: 36px;  /* px */
--spacing-stack-gap: 0.5rem;          /* rem */
--spacing-gutter: 1rem;               /* rem */
```

**建议统一为 4px 基础单位**：
```css
@theme {
  --spacing-1: 0.25rem; /* 4px */
  --spacing-2: 0.5rem;  /* 8px */
  --spacing-3: 0.75rem; /* 12px */
  --spacing-4: 1rem;    /* 16px */
  --spacing-6: 1.5rem;  /* 24px */
  --spacing-8: 2rem;    /* 32px */
  --spacing-12: 3rem;   /* 48px */
}
```

**工作量估算**：S（2-3 小时）

---

#### 3. 字体比例不足（headline/body < 2.5×）

**当前问题**：
```css
.font-headline-xl { font-size: 24px; } /* 1.71× body (14px) */
.font-headline-lg { font-size: 20px; } /* 1.43× body */
```

**建议增强对比**：
```css
.font-headline-xl { font-size: 32px; } /* 2.29× body (14px) */
.font-headline-lg { font-size: 24px; } /* 1.71× body */
.font-headline-md { font-size: 20px; } /* 新增 */
```

**工作量估算**：S（1-2 小时，逐页测试）

---

## 第三部分：优先修复清单

### Quick Wins（高影响 × 低工作量）

| 优先级 | 问题 | 影响 | 工作量 | ROI |
|---|---|---|---|---|
| 🥇 | 回测详情缺基准曲线 | 🔴 高 | S (1-2h) | ⭐⭐⭐⭐⭐ |
| 🥈 | 所有页面缺 loading states | 🟡 中 | S (2-3h) | ⭐⭐⭐⭐ |
| 🥉 | 行情浏览 K 线空白过大 | 🟢 低 | S (1-2h) | ⭐⭐⭐ |
| 4 | 因子实验室硬编码 sample | 🔴 高 | M (4-6h) | ⭐⭐⭐⭐ |
| 5 | 期权筛选器结果区过大 | 🟢 低 | M (3-4h) | ⭐⭐⭐ |

### 本周应完成（P0）

1. ✅ **回测详情缺基准曲线** — 1-2 小时，立即修复
2. ✅ **所有页面缺 loading states** — 2-3 小时，模式化修复
3. ⚠️ **因子实验室硬编码 sample** — 4-6 小时，需要后端协同

### 两周内完成（P1）

4. ⚠️ **限价单预留/后台自动检查** — 剩余工作，需要后端 + 前端
5. ✅ **行情浏览 K 线空白** — 1-2 小时
6. ✅ **期权筛选器结果区** — 3-4 小时

### 可延后（P2 — 设计系统重构）

7. 色彩 Token 整合 — 4-6 小时
8. 间距系统统一 — 2-3 小时
9. 字体比例增强 — 1-2 小时

---

## 第四部分：我不同意的建议

### ❌ 建议 1：历史回放移到独立页面

**你的理由**：降低模拟交易页复杂度  
**我的判断**：这会**破坏用户心智模型**

**原因**：
- 用户需要在同一页面对比"持续账户 vs 历史回放"
- 拆分页面会增加认知负担（"我在哪？两者有什么区别？"）
- Paper Trading 页面的复杂度来自两个功能**混在一起**展示，而非功能本身

**替代方案**：用 Tab 切换 + 视觉区分
```typescript
<Tabs defaultValue="live">
  <TabsList>
    <TabsTrigger value="live">
      <span className="flex items-center gap-2">
        Live Account
        <Badge variant="success">Active</Badge>
      </span>
    </TabsTrigger>
    <TabsTrigger value="replay">
      <span className="flex items-center gap-2">
        Historical Replay
        <Badge variant="secondary">Research Only</Badge>
      </span>
    </TabsTrigger>
  </TabsList>

  <TabsContent value="live" className="border-l-4 border-l-success">
    <AccountTradePanel ... />
  </TabsContent>

  <TabsContent value="replay" className="border-l-4 border-l-secondary">
    <PaperRunForm ... />
  </TabsContent>
</Tabs>
```

**工作量**：S（2-3 小时，比拆分页面更快）

---

### ⚠️ 建议 2：期权雷达移除手动按钮

**你的理由**：自动化后，手动按钮成为噪声  
**我的保留意见**：完全移除会让高级用户失去控制感

**折中方案**：保留手动入口，但用 UI 明确标注其用途
```typescript
<Collapsible>
  <CollapsibleTrigger>
    <span className="text-xs text-text-secondary">
      Advanced Options
      <Badge variant="outline" className="ml-2">For debugging</Badge>
    </span>
  </CollapsibleTrigger>
  <CollapsibleContent>
    <div className="space-y-2 rounded border border-border-subtle bg-surface-muted p-3">
      <p className="text-xs text-text-secondary">
        自动刷新已启用。以下按钮仅用于高级维护或强制重跑。
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm">Force Refresh</Button>
        <Button variant="outline" size="sm">Rebuild Cache</Button>
      </div>
    </div>
  </CollapsibleContent>
</Collapsible>
```

---

## 第五部分：下一步行动

### 立即执行（本次会话）

1. **修复回测详情缺基准曲线** — 1-2 小时（我现在就做）
2. **为 5 个慢页面增加 loading.tsx** — 2-3 小时（模式化修复）

### 本周内执行

3. **因子实验室移除硬编码 sample** — 需要与后端确认降级策略
4. **行情浏览 K 线自适应高度** — 1-2 小时

### 需要用户确认的产品决策

在实施以下功能前，需要确认：

1. **限价单挂单机制**：
   - 2026-06-15 已落地：基础 `pending_orders` 队列、页面挂单列表、手动检查触价成交和逐单取消。
   - 方案 A：启动后读取停机期间日内高低价，回溯判断是否曾触价（更真实）
   - 方案 B：只在系统观察到价格时成交（更简单）
   - **推荐**：方案 A

2. **碎股订单**：
   - 2026-06-15 已落地：Backtester 暴露 `whole_share_orders` 与 `min_order_value`，默认保留兼容，用户可显式启用整股与最小订单金额。
   - 方案 A：完全禁用碎股，默认整股 + 最小 $500
   - 方案 B：增加 Trading Mode 选择器（Realistic / Academic）
   - **推荐**：方案 B

3. **历史回放位置**：
   - 方案 A：移到独立页面（你的建议）
   - 方案 B：保留在 Paper Trading，用 Tab 切换 + 视觉区分（我的建议）
   - **推荐**：方案 B

---

## 附录：文件修改清单

### 立即修复（Quick Wins）

| 文件 | 修改内容 | 工作量 |
|---|---|---|
| `app/backtest/[runId]/page.tsx` | chartRows 增加 benchmark 字段 | 10 分钟 |
| `app/backtest/loading.tsx` | 新建 loading UI | 20 分钟 |
| `app/data-explorer/loading.tsx` | 新建 loading UI | 20 分钟 |
| `app/factor-lab/loading.tsx` | 新建 loading UI | 20 分钟 |
| `app/paper-trading/loading.tsx` | 新建 loading UI | 20 分钟 |
| `app/position-map/loading.tsx` | 新建 loading UI | 20 分钟 |
| `components/CandlestickChart.tsx` | 高度自适应 ResizeObserver | 40 分钟 |

**总计**：~2.5 小时

### 后续修复（需要协同）

| 文件 | 修改内容 | 依赖 |
|---|---|---|
| `lib/api.ts` | 移除 `getFactorLabDashboard` 的硬编码 sample | 后端确认降级策略 |
| `components/forms/AccountTradePanel.tsx` | 增加 Open Orders 列表 | 后端持久化 pending orders |
| `components/forms/OptionsScreenerForm.tsx` | 重构结果区布局 | 无 |

---

**验证方式**：每个修复完成后，在对应页面截图 Before/After，记录到 `docs/frontend/optimization_log.md`。

**创建时间**：2026-06-07  
**审查人**：Web Design Engineer (Claude Opus 4.8)  
**状态**：✅ 验证完成，待执行修复
