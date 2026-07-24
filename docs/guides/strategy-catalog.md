# 策略目录 Strategy Catalog（界面路由：/strategies）

> 适用范围声明：本平台为**纯本地、仅研究 / 仅模拟**的量化研究工具。策略目录只是一个"启动器"——它把后端登记好的研究策略列出来，让你填参数、点运行、看结果，**绝不接触真实下单、钱包、签名或任何券商接口**。

## 一句话定位

由后端**策略注册表（StrategyRegistry）驱动的"策略启动器"**：后端是唯一事实源，列表里有几个策略、每个策略有哪些参数，全部来自后端；前端读到 `GET /api/strategies` 后，**按每个策略自带的 `parameter_schema` 自动生成参数表单**。"后端加一个策略，这个界面就自动多一项"，前端不需要改代码。

## 它解决什么问题 / 为什么存在

平台里"能跑出东西"的入口有好几个（回测器、因子实验室、研报复现……），它们各自有一套手写的表单。策略目录想解决的是另一个问题：**让"新增一个研究策略"这件事不再需要前端跟着写一遍表单**。

它的核心思想是"配置即界面"。一个策略在后端注册时，会连同它的元数据一起声明：叫什么名字、出自哪篇论文、运行时打哪个接口、结果是哪一类、需要哪些参数（每个参数的类型 / 默认值）。前端拿到这份声明后，用一个通用的 `FieldRenderer` 把每种参数类型渲染成对应控件（下拉、勾选、文本框……）。于是新策略一旦在后端登记，界面就"白来"一项，无需前端介入。

这是个**优雅的设计意图**。前端路由已经正名为 `/strategies`，但目录里仍同时承载 backtest 与 replication 两类结果；两类结果都具备可复看的运行入口。

## 它实际能做什么（基于真实代码）

后端 `GET /api/strategies`（`api/routes/strategies.py`）直接返回 `build_default_strategy_registry()`（`strategies/registry.py`）里登记的全部策略元数据。**目前注册表里有 3 个策略**：

| 策略 id | 名称 | `result_type` | `supports_account_rebalance` | 运行接口 `run_endpoint` |
| --- | --- | --- | --- | --- |
| `cross_sectional_top_n` | Cross-Sectional Top-N | `backtest` | `true` | `/api/backtests/run` |
| `reversal_momentum` | Short-Term Reversal / Longer-Term Momentum | `replication` | `false` | `/api/replications/reversal-momentum/run` |
| `mean_reversion_top_n` | Mean-Reversion Top-N | `backtest` | `true` | `/api/backtests/run` |

关键点：**目录里同时混着两类性质完全不同的策略**，区别就在 `result_type`：

1. **`result_type === "backtest"`（2 个：`cross_sectional_top_n`、`mean_reversion_top_n`）**
   - 点"运行"后 `POST /api/backtests/run`，走的是完整的回测流水线（`backtest/pipeline.py` 的 `run_backtest`）。
   - **结果会落盘并建立索引**：后端生成一个 `run_id`、一个独立的运行目录、六个 parquet + `metrics.json` + 文本报告，并调用 `index_run` 写入运行索引。
   - 返回的 `metadata` 里带 `run_id`，于是界面右上角出现"**打开回测 Open backtest**"链接，跳到 `/backtest/{run_id}` 看完整结果。**这条结果是持久的，刷新页面后还能在回测器里找回来。**
   - 这两个策略**在独立的"回测器 /backtest"里也能跑**（徽章会写"同时可在独立的回测器中运行"）。

2. **`result_type === "replication"`（1 个：`reversal_momentum`）**
   - 点"运行"后 `POST /api/replications/reversal-momentum/run`（`api/routes/replications.py`），调用 `build_reversal_momentum_replication`（`replication/reversal_momentum.py`）。
   - 这是对论文《Short-Term Reversals and Longer-Term Momentum》（DOI 10.1093/rfs/hhaf057）的本地复现：取日线 OHLCV → **月末重采样** → 剔除上月末收盘价 < $1 的观测 → 算"过去 1 个月收益"做反转打分、算"t-12 到 t-2 收益"做动量打分 → 每个月做**横截面 z-score** 后相加得到 composite 复合分 → 按分数高低做**多空分组**（默认十分位，longs 减 shorts）→ **月度复利**成权益曲线，并算反转 / 动量 / 复合三条腿的月均收益、相关性、噪声分组诊断。
   - 返回一个**信息很丰富的字典**：`run_id` / `paper` / `methodology` / `metrics` / `diagnostics` / `equity_curve` / `monthly_returns` / `positions` / `legs` / `warnings`，外加接口补的 `source` / `request` / `paths`。
   - **结果会落盘到文件系统**：`data/api_runs/replications/<run_id>/metadata.json` 与 `result.json`。界面右上角出现"**打开复现 Open replication**"链接，跳到 `/strategies/{run_id}` 复看这次运行。
   - 注意：复现运行的文件目录和详情接口仍是事实来源；启用可选 PostgreSQL 本地镜像时，会 best-effort 写入 run index / recent mirror，数据库不可用时不影响复看。

> 安全边界：两条路径取行情都走 `build_ohlcv_provider`（sample / futu / tiingo），全是只读拉数据；"订单 / 成交 / 多空持仓"全部是内存里的模拟计算，没有任何真实交易动作。

## 操作步骤（一步一步，结合真实的输入项与默认值）

界面左侧是 `StrategyCatalogWorkbench`（`src/frontend/components/forms/StrategyCatalogWorkbench.tsx`）的参数侧栏，右侧是结果区。
参数控件仍由该组件渲染；提交前的 schema-driven payload 转换集中在
`src/frontend/lib/strategyPayload.ts`，对应单测是
`src/frontend/lib/strategyPayload.test.ts`。

1. **选策略 Strategy**：顶部下拉，默认选中列表第一项（即 `cross_sectional_top_n`）。下拉列出注册表全部 3 个策略。换策略时，表单会**自动重置为该策略的 `default_payload`**，并清空上一次的结果与报错。
2. **看出处与徽章**：选中后，侧栏会显示该策略的"论文出处"（`paper_source`，没有就退回显示 `description`），下面一个徽章标明它的性质：
   - 绿色"同时可在独立的回测器中运行" → 这是 `backtest` 类策略；
   - 蓝色"研报复现 · 仅在本目录运行" → 这是 `replication` 类策略。
3. **填参数 Parameters**：参数控件由 `parameter_schema.fields` 自动生成，**填什么取决于你选了哪个策略**（默认值见下）。
4. **点"运行策略 Run Strategy"**：
   - 若是 `backtest` 策略，前端会**额外把 `strategy_id` 注入到请求体**（schema 里没有这个字段，但回测接口靠它来分发到对应策略），然后 `POST /api/backtests/run`。
   - 若是 `replication` 策略，直接 `POST /api/replications/reversal-momentum/run`（接口忽略 `strategy_id`）。
   - 运行中按钮显示"运行中..."并禁用；完成后弹一条 toast。
5. **看结果**（2026-06-11 重构后按 `result_type` 分流渲染）：
   - **backtest 路径**：返回含 `run_id`，结果区给出"**打开回测**"链接（跳 `/backtest/{run_id}` 看完整可视化），本页只以 key/value 表列出返回摘要（`flattenResult`，最多 20 行）。
   - **replication 路径**：返回含 `run_id`，结果区给出"**打开复现**"链接（跳 `/strategies/{run_id}`）。本页和详情页都使用富渲染：告警横幅（如有 warnings）→ 4 张指标卡（总收益 / 年化收益 / Sharpe / 观测月数）→ 权益曲线图（`ReplicationEquityChart`）→ 方法学卡（formation / 反转信号 / 动量信号 / 持有期 / 价格过滤）→ 诊断卡（反转-动量相关性、高/低噪声环境反转收益、论文 DOI）→ 月度收益明细表 → 多空持仓表。
   - 选中 `reversal_momentum` 时，表单侧还会根据你填的标的数**实时显示多空分组提示**（留空 top_n 时自动十分位 = `max(1, floor(标的数×0.1))` 只/边；填了 top_n 则每边上限 `floor(标的数/2)`；标的 < 10 只时提示十分位分组退化）。

**Cross-Sectional Top-N / Mean-Reversion Top-N（两者参数 schema 与默认值完全一致）**：

- `universe_id` 股票池：默认 `etf`（下拉来自 `GET /api/universes`）。
- `factor_ids` 因子：多选勾选框，默认 `["momentum", "volatility", "liquidity"]`（来自 `GET /api/factors`）。
- `weights` 权重：因子权重映射，只对已勾选的因子显示输入框，默认 `{momentum:1.0, volatility:0.5, liquidity:0.5}`，单个默认 1。
- `top_n`：默认 `3`。
- `benchmark_symbol` 基准：默认 `SPY`。
- `start` / `end` 开始 / 结束日期：默认 `2024-01-02` / `2024-06-28`。
- `provider` 数据源：默认 `sample`（下拉 futu / sample / tiingo；futu 不可达时该项禁用）。

**Short-Term Reversal / Longer-Term Momentum（reversal_momentum）**：

- `symbols` 标的：文本域，逗号分隔，默认 `SPY,QQQ,IWM,DIA,XLK,XLF,XLV,XLY`（接口要求**至少 2 个、至多 50 个**）。
- `start` / `end`：默认 `2023-01-01` / `2026-05-22`。
- `provider`：默认 `futu`（注意与上面两个策略默认 `sample` 不同）。
- `initial_cash` 初始资金：默认 `1.0`（这里是"1 块本金"的归一化起点，方便直接读权益倍数）。
- `top_n`：类型 `integer_or_null`，默认 `None`（留空 = 用**默认十分位**多空分组；填 1–10 则改为取头部 / 尾部各 N 个）。

> 默认值取自后端 `default_payload`。前端 `FieldRenderer` 会优先用你填的值，其次用 schema 的 `default`。

## 字段与指标含义（逐项解释 UI 上出现的术语 / 指标）

**通用 / 表单层**

- **`result_type` 徽章**：策略的性质标签。`backtest` = 结果走回测器、持久化、有 `run_id`；`replication` = 研报复现、持久化为复现运行记录、有 `run_id`，但不进入 backtest 运行列表。
- **`supports_account_rebalance`**：是否能被 `/paper-trading` 的持续模拟账户“一键再平衡”使用。当前只有两个 backtest-engine 策略为 `true`；`reversal_momentum` 是研报复现，保持 `false`，不会出现在账户再平衡下拉里。
- **论文出处 Paper source**：`paper_source` 字段。只有 `reversal_momentum` 有真实出处；两个 backtest 策略为 `null`，此时退回显示 `description`。
- **Top N**：选股 / 分组的数量。在 backtest 策略里是"取分数排名前 N 的标的等权持有"；在复现里是"多空两端各取 N 个"（留空则用十分位）。

**backtest 策略选股逻辑**（来自 `backtest/pipeline.py` 的 `_BACKTEST_STRATEGY_BUILDERS`）

- **Cross-Sectional Top-N**：对股票池按"加权因子复合分"做横截面排序，**只保留 `score > 0`**，取前 `top_n` 等权持有。
- **Mean-Reversion Top-N**：反向版本——取复合分**最低**的 `top_n`（近期最弱者），赌短期均值回归，等权持有。

**reversal_momentum 复现结果字段**（来自 `build_reversal_momentum_replication` 返回字典）

- **`paper`**：论文元数据（标题、作者、DOI、期刊）。
- **`methodology`**：方法学说明（formation = 分组方式；reversal_signal = 过去 1 月收益、逆向排名；momentum_signal = t-12 到 t-2 收益、顺势排名；holding_period = 持有下一月；price_filter = 剔除上月末 < $1）。
- **`metrics`**：复合策略的绩效——`total_return` / `annualized_return` / `volatility` / `sharpe` / `max_drawdown` / `turnover`（按年化因子 12 计算的月频指标），外加 `observation_months`（有效月数）、`average_monthly_return`（复合月均）、`average_reversal_return` / `average_momentum_return`（反转 / 动量两条腿的月均）。
- **`diagnostics`**：诊断指标——`reversal_momentum_return_correlation`（反转与动量月收益相关性）、`high_noise_average_reversal_return` / `low_noise_average_reversal_return`（按当月横截面收益离散度的中位数切两半后，高 / 低噪声环境下反转腿的平均收益，用来观察"噪声越大反转越强"这一论文假设）。
- **`equity_curve`**：复合策略月度复利权益序列（`timestamp` / `equity` / `monthly_return`）。
- **`monthly_returns`**：三条腿（reversal / momentum / composite）每个再平衡月的明细（`long_return` / `short_return` / `return` = 多减空 / 多空数量）。
- **`positions`**：**只有 composite 这条腿**的逐月多空成分（`symbol` / `side` / `one_month_return` / `momentum_return_12_2` / `composite_score` / `next_month_return`）。
- **`legs`**：三条腿的信号文字说明。
- **`warnings`**：诚实告警，例如"股票池 < 10 只不是完整全球复现""剔除了 N 个上月末 < $1 的观测""可投标的不足 2 个无法构造多空"等。
- **`run_id` / `paths`**：复现运行 ID 与本地落盘路径（`metadata.json` / `result.json`）。
- **`source` / `request`**：接口补充的实际数据源与回显的请求参数。

## 当前的局限与"为什么看起来奇怪"（诚实列出令人困惑之处及其代码层面的原因）

这个界面**最大的问题不是 bug，而是"名实不符 + 两类策略强行同居一处"**，这正是使用者"看了界面理解不了它在干什么"的根源：

1. ~~路由叫 `/replications`，但 3 个里 2 个根本不是"复现"。~~ **已通过 `/strategies` 正名缓解**。`cross_sectional_top_n` 和 `mean_reversion_top_n` 是普通回测策略，跟独立的"回测器 /backtest"跑的是**同一个 `run_backtest` 流水线、同一个 `/api/backtests/run` 接口**。真正算"研报复现"的只有 `reversal_momentum` 一个；旧 `/replications` 仅作为兼容 redirect 保留。

2. **索引层是 best-effort 镜像，不是事实来源。** 同一个"运行"按钮，backtest 策略和复现策略都会落盘并给 `run_id`；可选 PostgreSQL run index / recent mirror 会尽力索引这些运行，但数据库关闭、慢或不可用时，页面仍必须能从文件系统和详情接口复看。

3. ~~丰富的复现结果被压成 ≤20 行扁平 key/value~~ **已于 2026-06-11 修复**：复现结果改为富渲染（指标卡 + 权益曲线图 + 方法学 / 诊断卡 + 月度收益与持仓表）；`flattenResult` 仅保留作 backtest 路径的返回摘要兜底。

4. **`strategy_id` 由前端"偷偷"注入，参数表单里看不见。** backtest 接口靠 `strategy_id` 分发到具体策略，但它**不在 `parameter_schema.fields` 里**，所以表单上看不到这一项。前端在 `submit()` 里对 `result_type === "backtest"` 的策略**手动补 `payload.strategy_id = strategy.id`**。这是个合理的折中（schema 不该把分发键暴露成用户可编辑字段），但对读代码 / 调接口的人来说是一处"隐式约定"，不看源码不会知道。

5. ~~存在一个并行的、几乎成孤儿的 `ReversalMomentumReplicationForm`~~ **已于 2026-06-11 消除**：该组件已删除，其图表能力（权益曲线等）并入目录结果区的富渲染；现在复现只有目录这一个入口，不再双轨分叉。

6. **次要：默认数据源在策略间不一致。** 两个 backtest 策略默认 `provider=sample`，复现策略默认 `provider=futu`。这本身合理（sample 适合冒烟、futu 是本地真数据），但切换策略时数据源默认值会跟着变，初次使用容易没注意到。另外当 `GET /api/strategies` 返回空时，前端 `fallbackStrategies()` 只会硬编码兜底出 `cross_sectional_top_n` 一项——属于降级显示，正常后端在线时不会触发。

## 合理性评估与改进建议

**设计意图是好的，落差出在"统一了入口、没统一结果体验"。** 注册表驱动 + schema 自动建表单，是这套平台里扩展性最强的一处设计：后端加策略、前端零改动。这个方向应当保留并强化。

**已落地的改进**：

- 2026-06-11：结果区已按 `result_type` 分流渲染——backtest 给 `run_id` + "打开回测"入口，replication 给指标卡 / 权益曲线 / 方法学与诊断卡 / 月度收益与持仓表；孤儿组件 `ReversalMomentumReplicationForm` 已删除，重复入口消除。
- 2026-06-15：`/api/replications/reversal-momentum/run` 生成 `replication-*` run_id，写入 `data/api_runs/replications/<run_id>/metadata.json` 与 `result.json`；新增 `GET /api/replications/reversal-momentum/{run_id}` 与前端复现详情页，复现结果刷新后可复看。
- 2026-06-23：前端策略目录路由正名为 `/strategies`，旧 `/replications` 通过 redirect 兼容；复现详情页迁移为 `/strategies/{run_id}`。
- 2026-06-15：策略注册表新增 `supports_account_rebalance` 能力位；`/paper-trading` 的账户再平衡下拉和 `POST /api/paper/account/rebalance` 都以该字段为准，避免研报复现策略误入持续账户执行路径。

仍可操作的改进建议（按性价比排序）：

1. **继续统一运行历史体验**：如果后续要把 backtest、factor、paper、replication 运行都放进一个用户可筛选的 Recent Runs 页面，需要把 `kind`、详情跳转和缺失文件兜底行为写成统一契约。
2. **UI 文案继续正名**：蓝色徽章可从"仅在本目录运行"调整为"研报复现 · 可复看"，进一步减少用户对临时结果的误解。

## 相关代码入口（列出关键文件）

- 前端页面（拉取 strategies / universes / factors / health 并装配）：`src/frontend/app/strategies/page.tsx`
- 前端复现详情页（读取已落盘结果并预加载到目录组件）：`src/frontend/app/strategies/[runId]/page.tsx`
- 前端主组件（schema 自动建表单、`strategy_id` 注入、复现结果富渲染 + `flattenResult` 兜底）：`src/frontend/components/forms/StrategyCatalogWorkbench.tsx`（`ReversalMomentumReplicationForm.tsx` 已于 2026-06-11 删除并并入此组件）
- 策略注册表（唯一事实源，3 个策略的元数据 / schema / 默认值 / 账户再平衡能力位）：`src/quant_system/strategies/registry.py`
- 列表接口 `GET /api/strategies`：`src/quant_system/api/routes/strategies.py`
- 复现接口 `POST /api/replications/reversal-momentum/run` 与 `GET /api/replications/reversal-momentum/{run_id}`：`src/quant_system/api/routes/replications.py`
- 复现核心算法（月末重采样 / 反转 + 动量打分 / z-score 合成 / 多空分组 / 月度复利 / 诊断）：`src/quant_system/replication/reversal_momentum.py`
- 回测接口 `POST /api/backtests/run`（backtest 策略的落盘与 `run_id` 来源）：`src/quant_system/api/routes/backtest.py`
- 回测流水线与策略分发（`_BACKTEST_STRATEGY_BUILDERS`）：`src/quant_system/backtest/pipeline.py`
- 回测请求 schema（默认值参考）：`src/quant_system/api/schemas/backtest.py`
