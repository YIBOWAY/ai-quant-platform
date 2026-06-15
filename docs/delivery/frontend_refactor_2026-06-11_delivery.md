# 前端全面重构交付记录（2026-06-11）

本次工作对前端进行了一次**全页面**的审查、修复与优化，覆盖 19 条路由（含中英文与动态路由）。出发点是几处明确的体验问题（持仓地图布局、策略目录与持仓地图的联动、因子实验室难以理解、K 线页布局、页面缺少自我解释），按要求扩展为对所有页面的系统性整治。

## 一、设计系统统一

全部页面收敛到同一套深色密集型设计语言：

- **背景令牌归一**：统一使用 `bg-bg-base` / `bg-bg-surface` / `bg-bg-surface-muted` 三级背景。清除了散落的 `bg-base`、`bg-surface-muted` 等不规范写法。`bg-surface-dim`、`bg-surface-container`、`bg-primary/10`、`text-on-primary`、`text-bg-base` 属于合法令牌，保持不动。
- **圆角统一**：所有卡片、输入框、按钮、徽章统一 `rounded-lg`；仅细进度条保留 `rounded-full`。
- **表单控件统一**：用模块级 `inputClass` / `selectClass` / `fieldClass` 常量取代了内联 `optionStyle = { background: "#0E1511", ... }` 的 hack，该写法已在全部组件中清除。
- **修复失效令牌**：`accent-danger` 并不存在于主题中（错误提示框因此完全没有样式），统一替换为 `border-danger/40 bg-danger/10 text-danger`，共修复 3 个文件。

## 二、布局骨架（全局）

- `app/layout.tsx`：应用外壳改为**固定视口高度**（`h-screen overflow-hidden pt-[100px] lg:ml-[240px]`），顶栏与侧栏固定，**页面在内部滚动**（每页根元素 `h-full overflow-y-auto`）。长表格、期权链等区域有独立滚动区，避免整页跳动。
- 2026-06-15 更新：桌面端主导航以侧栏为唯一权威；TopBar 不再重复展示主导航链接、Run Backtest CTA 或“铃铛=期权雷达”入口，只保留搜索、语言切换和少量全局工具。
- 移动端：侧栏收起为汉堡菜单（TopBar「Open navigation」），页面占满全宽。

## 三、分页面改动摘要

### 研究流水线群
- **Dashboard**：信息密度与入口指引优化。
- **Data Explorer（K 线页）**：布局重排，蜡烛图 + 成交量为主体，参数表单收敛到侧栏。
- **Backtester**：默认值改为「真实数据优先」——provider 默认 `futu`，时间窗为**截至今天的滚动 180 天**；权益对比图、Trade Blotter 保留。2026-06-15 更新：每个 backtest run 会持久化 `benchmark_curve.parquet` / `benchmark_metrics.json`，详情页和最新运行面板读取 run 内 `benchmark` 快照，不再打开页面时重拉 `/api/benchmark`；回测表单/API 也新增可选 `min_order_value` 与 `whole_share_orders`，用于减少小额碎股噪声订单。
- **Factor Lab**：页面重构为可理解的两个视图，使用共享 `Tabs` 组件（`role="tab"`）切换「横截面体检 / 单标的择时」，列头悬停有指标定义；因子研究表单挂在侧栏。
- **Experiments**：Sweep 热图 / Walk-forward 折 / 运行对比 / Agent 摘要四个 tab（共享 `Tabs` 组件），「Send to Backtest」可把最优参数带入回测表单。
- **Strategy Catalog（Replications）**：与持仓地图的关系在页面上说明清楚；运行后展示权益图、月度收益与组合持仓。

### 模拟交易与持仓
- **Paper Trading**：「实时账户 / 历史回放（研究）」两 tab 分离;手动下单、策略再平衡在实时账户侧;回放研究不再与账户混淆。
- **Position Map**：以**模拟账户为唯一事实来源**重做——账户指标行（总值/现金/持仓市值/未实现盈亏）、按标的的敞口条、账户活动流、空仓时给出「Open Paper Trading」引导;最近回测敞口仅作为研究对比保留在页尾并明确标注。

### 期权研究群
- **Options Screener / Buy-Side Assistant / Options Tools / Options Radar**:令牌全面收敛,`optionStyle` hack 清除,错误框样式修复;雷达页把手动 Futu 刷新（标的池/财报/VIX）收进默认折叠的「Advanced data sources」,避免日常误触发慢扫描。
- **`options-radar/[symbol]`、`paper-trading/[runId]`**（两个此前被遗漏的动态路由页）:整页重写为带 `copy = {en, zh}` 的服务端组件,补全中文文案、返回链接本地化、安全横幅 `rounded-lg`。
- 移除了 OptionsRadarView 与 BuySideOptionsAssistant 页内多余的语言切换链接（TopBar 已有全局 LocaleToggle）。

### 安全文案（逐字保留）
所有"仅模拟、只读、不可下单"的安全声明逐字保留,包括:买方助手「No orders, no account unlock, no live trading.」、雷达「This area never places orders.」、回放表单「No real fills, no real trading, no signing, no account custody.」、订单簿「Live integration intentionally disabled」、模拟运行明细「Paper-only simulation. Live trading is disabled and this page cannot submit orders.」等。Polymarket 所有 POST 维持 `polymarket_api_key: null`。

## 四、E2E 基础设施修复（重要根因）

首轮全量 E2E 为 20 通过 / 18 失败。排查发现 **14 个失败的共同根因不是前端 bug**:

- `src/frontend/.env.local` 把 `NEXT_PUBLIC_QUANT_API_BASE_URL` 指到 `http://127.0.0.1:8800` —— 一个无服务监听的死端口。Playwright 自启的 `npm run dev` 没有显式环境变量,Next.js 读取 `.env.local`,导致整个测试期间前端请求 8800,而测试种子数据全部写入 8765。
- **修复**:`playwright.config.ts` 的前端 webServer 显式注入 `NEXT_PUBLIC_QUANT_API_BASE_URL=http://127.0.0.1:8765`（shell 环境变量优先于 `.env.local`）,E2E 从此自包含。
- 日常手动起前端时 shell 里显式传 8700,所以平时不受影响;`.env.local` 中的 8800 疑似历史遗留,建议自行确认后修正。

其余 7 个失败均为**测试断言落后于本次有意的改版**,已更新测试:

| 测试 | 原因 | 修复 |
| --- | --- | --- |
| navigation-layout「app shell 允许整页滚动」 | 新外壳有意固定视口、内部滚动 | 改为断言外壳内存在实际可滚动区域 |
| navigation-layout「移动端导航」 | 持仓地图新增「Open Paper Trading」CTA 与侧栏链接撞名 | 链接定位加 `exact: true` |
| navigation-layout「回测默认值」 | 默认值有意改为 futu + 今天 | 断言 `futu` 与 `new Date().toISOString().slice(0,10)` |
| phase10「workflow 按钮」/「中文标签」 | Factor Lab 改用 `role="tab"` 的共享 Tabs | `getByRole("button")` → `getByRole("tab")` / `openTab()` |
| experiments-workbench | 同上 + run ID 截断显示（带 title）导致文本出现两处 | role 改 tab;断言加 `.first()` |
| phase13「雷达刷新」 | 刷新控件有意收进折叠的 Advanced 披露区 | 测试先展开披露区（带 hydration 重试） |

## 五、验证结果

| 检查 | 结果 |
| --- | --- |
| `tsc --noEmit` | 0 错误 |
| `eslint` | 0 错误（1 条与本次无关的既有 warning） |
| `next build` | 成功,19 条路由 |
| Playwright E2E 全量 | **38 / 38 通过**（1.9 分钟） |
| 渲染 HTML 令牌审计 | EN+ZH 关键页 `grep` 零残留（裸 `rounded`、`bg-base` 等） |

E2E 复跑命令（Windows / Git Bash,需 conda env `ai-quant`）:

```bash
cd src/frontend
QUANT_API_COMMAND="D:/anaconda3/envs/ai-quant/python.exe -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765" \
PW_E2E=1 npx playwright test
```

## 六、截图

- **改版后**（1440×900 全部页面 + 390×844 移动端抽查,共 20 张）:`output/ui-audit/after-2026-06-11/`
- **改版前**留档:`output/ui-audit/shots/`、`output/playwright/audit-*.png`
- 采集脚本:`src/frontend/scripts/capture-after-screenshots.mjs`（前后端起好后 `node scripts/capture-after-screenshots.mjs` 即可重采）

## 七、遗留与建议

1. `.env.local` 的 `8800` 建议确认来源后改为实际后端端口（日常为 8700）;E2E 已不受其影响。
2. eslint 既有 1 条 warning（与本次改动无关）,可择机清理。
3. 持仓地图与策略目录的联动已在页面文案中说明;若后续希望"目录一键再平衡到账户",可在 AccountTradePanel 基础上扩展。
