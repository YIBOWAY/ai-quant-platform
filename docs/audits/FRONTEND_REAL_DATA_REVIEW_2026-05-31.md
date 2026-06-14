# 前端真实数据审查 — 2026-05-31

本次审查用于检查前端展示的是后端衍生数据，还是未加标注的样本/演示输出。审查针对本地后端
`127.0.0.1:8765` 与前端 `127.0.0.1:3001` 运行。

## 完成标准

- 后端与前端均可访问。
- 主要页面渲染时不出现前端运行时错误。
- 行情数据页面标明其数据来源。
- 样本或示例输入不会被悄无声息地当作实时数据呈现。
- 面向初学者的页面解释只读 / 仅研究的边界。

## 当前数据真相图

| 页面 | 当前来源行为 | 审查结果 |
|---|---|---|
| `/` Dashboard | 调用 `/api/health`、`/api/symbols`、`/api/factors`、`/api/backtests`、`/api/paper` 以及 `/api/agent/candidates`。最近一次保存运行的来源现已显示在卡片上。 | 后端衍生。已保存的样本运行被标注为 sample / not real。 |
| `/data-explorer` | 除非显式选择 `provider=sample`，否则默认使用富途 (Futu)。图表与表格使用 `/api/market-data/history`。 | 后端衍生。富途运行已通过真实 OHLCV 行验证。 |
| `/factor-lab` | 运行 `/api/factors` 与 `/api/factors/run`；默认 provider 为富途。 | 后端衍生。 |
| `/backtest` | 运行 `/api/backtests`、`/api/backtests/{id}`、`/api/benchmark` 以及 `/api/backtests/run`；默认 provider 为富途。 | 后端衍生。最近保存的样本运行与基准来源均已标注。 |
| `/replications` | 调用 `/api/replications/reversal-momentum/run`；默认 provider 为富途。 | 后端衍生。样本 provider 仅保留用于冒烟测试。 |
| `/paper-trading` | 运行 `/api/paper`、`/api/paper/{id}`、`/api/health` 以及 `/api/paper/run`；默认 provider 为富途。 | 仅后端衍生的本地模拟。 |
| `/position-map` | 读取最近保存的回测持仓以及纸面交易安全状态。 | 后端衍生的本地产物。来源已显示。 |
| `/options-screener` | 通过后端调用富途的只读实时期权链。 | 后端衍生。浏览器运行返回了真实的 SPY 期权候选。 |
| `/options-radar` | 读取已保存的雷达快照，并可运行后端扫描。 | 后端衍生快照。样本扫描选项仍保持显式。 |
| `/options-radar/[symbol]` | 读取已保存的候选，并可选择加载实时期权链数据。 | 后端衍生。 |
| `/options-buyside` | 提交至 `/api/options/buy-side/assistant`。后端获取富途现货与期权链行，然后在 `buy_side_decision.py` 中对策略进行排序。 | 后端衍生。评分过程为真实的后端逻辑，而非前端模拟。 |
| `/options-tools` | 对市场敏感的工具会先获取所输入标的的富途快照与期权链，然后以这些输入调用本地后端计算器。模板/自选列表等非市场操作仍为本地后端调用。 | 期权链计算为后端衍生；仅本地调用被标注为后端研究操作，而非实时行情数据。 |
| `/order-book` | 默认使用 Polymarket 只读公开数据。样本仍可选，但带有警告标注。 | 默认后端衍生。 |
| `/agent-studio` | 读取候选文件与 agent API 数据。 | 后端衍生的本地产物。 |
| `/settings` | 读取经掩码处理的 `/api/settings` 与 `/api/health`。 | 后端衍生。 |

## 买方期权评分

`/options-buyside` 中显示的买方评分并非前端的装饰性数字。前端调用
`POST /api/options/buy-side/assistant`；后端构建一个富途行情数据 provider，获取标的快照与期权链，
然后在 `src/quant_system/options/buy_side_decision.py` 中对 Long Call、Bull Call Spread、LEAPS Call
以及 LEAPS Call Spread 候选进行排序。

该页面现在会在现货与时间戳字段旁，将数据来源显示为后端富途期权链数据。

## 本次审查所做的更改

- 语言切换现在会在保存 cookie 后执行一次硬性页面刷新，使可见的外壳立即切换。
- Dashboard 的 KPI/详情现在包含最近保存运行的来源标签。
- `DataSourceBadge` 将任何样本来源标记为 `sample / not real`。
- 回测基准来源现显示在基准卡片旁。
- Options Tools 现在会在希腊值、策略排序、合约评分、模拟与信号计算之前加载实时富途期权链上下文。
  仅本地的研究操作单独标注。
- Buy-Side Options Assistant 现在声明其推荐来自后端富途期权链数据。
- 预测市场订单簿 (Prediction Market Order Book) 默认使用 `polymarket` 而非 `sample`。
  样本模式仍可用于冒烟测试，但不再是默认路径。

## 保留的护栏

- `sample` provider 仍然存在，用于确定性冒烟测试与离线开发。它们必须保持显式标注，
  且不应作为面向用户的研究页面的默认值。
- 已保存的历史运行可能是由样本数据产生的。这些是真实保存的后端产物，但其来源必须保持可见，
  以免用户将其误认为实时行情结果。
- Options Tools 仍包含无需行情数据的本地研究操作，例如模板与自选列表操作。它们必须保持标注为
  本地后端调用，而非实时行情计算。

## 验证记录

- `/api/health` 返回 `status=ok`、`configured_default=futu`、
  `live_trading_enabled=false` 以及 `kill_switch=true`。
- `/api/symbols` 返回富途默认篮子。
- `/api/market-data/history?provider=futu&ticker=SPY&start=2026-05-01&end=2026-05-31`
  返回 20 行带 `source=futu` 的真实 OHLCV 数据。
- `/api/options/snapshot/AAPL` 返回 `source=futu`、当前现货、最近到期日、IV、HV 以及 IV-rank 字段。
- `/api/prediction-market/markets?provider=polymarket&limit=2` 返回实时
  Polymarket 公开市场与订单簿。
- 浏览器检查覆盖了 Dashboard、Data Explorer、Factor Lab、Backtest、
  Replications、Paper Trading、Position Map、Options Screener、Options Radar、
  Options Tools、Buy-Side Options Assistant、Order Book、Agent Studio、Settings
  以及反转/动量文档页面。
