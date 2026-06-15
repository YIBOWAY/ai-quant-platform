# 回测器 Backtester（界面路由：/backtest）

> 适用范围声明：本平台为**纯本地、仅研究 / 仅模拟**的量化研究工具。回测器只回放历史数据、做撮合模拟，**绝不接触真实下单、钱包、签名或任何券商接口**。这里出现的"订单 / 成交"全部是内存里的模拟记录。

## 一句话定位

把一个因子打分策略在历史行情上完整跑一遍——**因子打分 → 横截面排序选股 → 生成目标权重 → 下单 → 撮合 → 组合盯市 → 绩效统计**——用来在投入模拟交易之前，先证明这个想法"在历史上至少不离谱"。

## 它解决什么问题 / 为什么存在

平台的六个界面里，回测器是**最名副其实、落差最小的一个**：它真的把一条完整的研究流水线从头到尾算了一遍，产物（权益曲线、基准曲线、成交、订单、持仓、归因、绩效 JSON、文本报告）都是真算出来并落盘的，不是占位数据。

它的定位是"先证明、再去模拟"。你在这里得到一条策略的历史权益曲线和夏普 / 回撤，判断它是否值得进入 Paper Trading 环节。如果一个策略在回测里都跑不出像样的曲线，就没必要去模拟交易里浪费时间。

## 它实际能做什么（基于真实代码）

后端入口是 `run_backtest`（`src/quant_system/backtest/pipeline.py`），完整流程：

1. **解析输入**：把 `symbols` / `universe_id` 解析成最终股票池（自定义标的优先；留空则用所选股票池；都没有则回退到 `["SPY", "QQQ"]`）；解析 `strategy_id`、`factor_ids`、`weights`。
2. **取行情**：`build_ohlcv_provider` 按 `provider`（sample / futu / tiingo）取 OHLCV。
3. **算因子**：`compute_factor_pipeline` 对每个选中的因子按 `lookback` 计算，每行带 `signal_ts`（数据所属日）和 `tradeable_ts`（可交易日，即下一根 K 线）。
4. **合成单一打分**：`build_multifactor_score_frame`（`experiments/scoring.py`）对每个因子做**横截面 z-score**，按方向（`higher_is_better` / `lower_is_better`）取符号，按权重归一化（除以权重绝对值之和）后相加，得到每个标的每个 `tradeable_ts` 的单一 `score`。
5. **选股 → 目标权重**（`backtest/strategy.py`）：
   - `cross_sectional_top_n`（`ScoreSignalStrategy`）：在每个可交易时点，**只保留 `score > 0` 的标的**，按分数从高到低取前 `top_n`，**等权**（权重 = 1 / 选中数量）。
   - `mean_reversion_top_n`（`MeanReversionTopN`）：取分数**最低**的 `top_n`（近期最弱者），不做 `score > 0` 过滤，同样等权。
6. **按再平衡频率触发**（`backtest/engine.py` 的 `_should_rebalance`）：`every_bar` 每根有信号的 K 线都调仓；`weekly` / `monthly` 只在新 ISO 周 / 新自然月的第一根有信号 K 线调仓，中间只盯市持有不动。
7. **权重约束**（`order_generation.py` 的 `_apply_weight_constraints`）：把超过 `max_weight_per_symbol` 的单标的权重**向下压**到上限；`sector_cap`（行业上限）按 `sector_map` 分组缩放。**只向下缩放、不再分配**——见局限一节。
8. **生成订单**（`OrderGenerator`）：用当前 bar 的 **open 价**估算组合权益，计算每个标的"目标市值 − 当前市值"的差额，差额超过 `min_order_value`（默认 0）就生成买 / 卖单，数量 = 金额差 / 价格。若 `whole_share_orders=true`，订单数量会向下取整到整股；取整后低于最小订单金额的订单会被跳过。
9. **撮合**（`broker.py` 的 `BrokerSimulator`）：以同一根 K 线的 **OPEN 价**为基准撮合（卖单先于买单执行）；买单加滑点、卖单减滑点；收取佣金 `commission_bps`；受**现金约束**（买单买不起就部分成交，状态标 `partial`），卖单不超过现有持仓。若启用整股模式，现金不足导致的部分成交也会向下取整到整股。
10. **盯市与归因**：每根 K 线对持仓按 close 价盯市，记录权益曲线；归因 = 进入该 bar 时的持仓数量 ×（本 bar close − 上一 bar close）逐 bar 累加。
11. **绩效**（`metrics.py` 的 `calculate_performance_metrics`）：算 `total_return` / `annualized_return` / `volatility` / `sharpe` / `max_drawdown` / `turnover`，并把归因按标的汇总。
12. **落盘**：六个 parquet（equity_curve / benchmark_curve / trade_blotter / orders / positions / attribution）+ `metrics.json` / `benchmark_metrics.json` + 文本报告，全部保存在独立 `run_id` 目录并写入 `metadata.json`。`metadata.json` 还包含 `timings_ms`，按毫秒记录 `data_fetch` / `engine` / `persist` / `total` 四段耗时，方便区分慢在取数、计算还是落盘。API 回测路径不再为每个 run 额外写 `quant_system.duckdb` 副本；历史遗留的逐 run DuckDB 可用 `scripts/cleanup_api_run_duckdb.py` 清理。

> 关于"次 bar 撮合"的准确说法：撮合本身发生在**与 `tradeable_ts` 相等的那根 K 线的 OPEN 价**上。"在 T 日数据上打分、在 T+1 开盘成交"这个滞后，是由因子流水线的 `tradeable_ts`（= 下一根 K 线）实现的，**不是引擎在撮合时又往后顺延了一根**。引擎只是忠实地在 `tradeable_ts` 这根 bar 的 open 撮合。这条很重要：它保证了回测没有"用未来数据下单"的前视偏差。

## 操作步骤（一步一步，结合真实输入项与默认值）

界面左侧是 `BacktestForm`（`src/frontend/components/forms/BacktestForm.tsx`），表单默认值（`DEFAULTS`）如下：

表单也会读取 URL 查询参数来预填常用字段。Factor Lab 的「发送至回测」会带入 `provider / universe_id / benchmark_symbol / factor_ids`；Experiments 的「Send to Backtest」会带入最佳参数与相同数据源。这些入口只预填表单，仍需在 Backtester 手动点击运行。

1. **策略 Strategy**：下拉，默认 `cross_sectional_top_n`（Cross-Sectional Top-N）。下拉只列出后端 `result_type === "backtest"` 的可运行策略；目前另有 `mean_reversion_top_n`。
2. **股票池 Universe**：默认 `etf`。它决定默认比较范围；留空"自定义标的"时就用这个池子的成分股。
3. **基准 Benchmark**：默认 `SPY`，纯文本输入。基准曲线会在本次回测运行时一起计算并保存，详情页和最新运行面板复用保存产物，不再打开页面时现场重拉。
4. **自定义标的 Custom Symbols**：可选，逗号分隔。填了就**覆盖**股票池。⚠️ 只填一个标的会弹黄色警告——因为排序选股策略需要"同类标的"才能横截面排序并买入正信号，单标的常常什么都不买、曲线保持水平。
5. **开始 / 结束日期**：默认是**截至 UTC 今天的滚动 180 天窗口**（结束 = 今天，开始 = 今天 − 180 天；2026-06-11 起，原固定 2024 上半年的写死区间已移除）。
6. **数据源 Data Source**：`futu` / `sample` / `tiingo`。futu 不可达时该选项被禁用并给提示。默认 `futu`（2026-06-11 起「真实数据优先」，与后端 schema 默认一致）。
7. **因子组合 Factor Mix**：勾选已登记因子并填权重。默认勾选 `momentum`（权重 1）、`volatility`（0.5）、`liquidity`（0.5）。**未勾选的因子其权重输入框被禁用**，提交时只发送已勾选的因子及其权重。至少要选一个因子。
8. **回看窗口 Lookback**：默认 `20`，正整数。所有因子共用这一个 lookback。
9. **Top N**：默认 `3`，正整数。选股数量。
10. **初始资金 Initial Cash**：默认 `100000`。
11. **佣金 Commission bps / 滑点 Slippage bps**：默认 `1` / `5`（bps，万分之一）。
12. **最小订单金额 Min order value**：默认 `0`，表示保留原始精确目标权重行为。调高后，小于该金额的目标差额不会生成订单；整股模式下，取整后的订单金额也必须达到该门槛。
13. **整股下单 Whole-share orders**：默认关闭以兼容历史研究结果。勾选后，订单生成和现金不足的部分成交都会向下取整到整股，可减少 `0.0071` 股这类噪声订单。
14. **再平衡频率 Rebalance**：`every_bar`（默认）/ `weekly` / `monthly`。
15. **单标的上限 Max weight / name**：可选，留空表示不限制；填则须在 0–1 之间。
16. 点 **运行回测 Run Backtest**：前端 POST 到 `/api/backtests/run`，成功后 toast 提示 `回测已创建：<run_id>` 并跳转到 `/backtest/<run_id>` 详情页。

> 表单里**没有** `sector_cap` / `sector_map` 入口（行业上限），但后端 schema 和引擎都支持。要用只能直接调 API。

## 字段与指标含义（逐项解释 UI 上出现的术语 / 指标）

主页与详情页出现的术语：

- **总收益 Total Return**：`last_equity / initial_cash − 1`。注意分母是初始资金，不是首行权益。
- **夏普比率 Sharpe**：逐 bar 收益率的均值 / 标准差 × √252（年化因子 252，硬编码）。无波动或样本不足时为 0。
- **最大回撤 Max Drawdown**：权益相对历史峰值的最大跌幅（取绝对值，正数显示）。
- **BMK / 基准**：右侧每个指标下方小字给出的基准对应值，来自本次 run 保存的 `benchmark_metrics.json`。
- **Turnover 换手率**：累计成交额（`gross_value` 之和）/ 初始资金。在主指标卡里不直接展示，但写进 `metrics.json`。
- **权益曲线 Equity Curve / 策略 vs 基准**：把策略与本次 run 保存的基准曲线各自**归一化到首个正值 = 1** 后叠加对比，所以看的是相对走势而非绝对金额。
- **成交记录 Trade Blotter**：模拟成交。列含 `side`（buy/sell）、`quantity`、`requested_price`（撮合基准价 = bar open）、`fill_price`（含滑点后的成交价）、`gross_value`、`commission`、`slippage_bps`、`status`（`filled` / `partial`，部分成交多因现金不足）。
- **订单 Orders**：撮合前生成的目标订单，列含 `reason`（固定 `rebalance_to_target_weight`）。订单数 ≥ 成交数（被现金或持仓约束掉的不成交）。
- **持仓 Positions**：每根 bar 的逐标的持仓快照（数量、close 价、市值）。
- **收益归因 Return Attribution**：逐标的对组合盈亏的贡献，按 `持仓数量 ×（close − 上一日 close）` 盯市累加。列含 `contribution`（金额）和 `contribution_pct`（÷ 初始资金）。
- **数据源徽章 / 合成数据警告**：`source` 为 sample 等合成数据源时，页面会显示"指标基于合成数据"的提醒，提示别把这种结果当真。
- **Run notes / Warnings**：后端 `_build_backtest_warnings` 生成的提示，例如"单标的运行""所有分数为 0""未产生任何成交"。
- **timings_ms**：写在 `metadata.json` 和详情接口的 `metadata` 中，记录本次 run 的取数（`data_fetch`）、因子/策略/引擎/基准计算（`engine`）、artifact/report 落盘（`persist`）和总耗时（`total`），单位毫秒。它只用于诊断性能，不参与指标计算。

## 当前的局限与"为什么看起来奇怪"（诚实列出令人困惑之处及代码层面的原因）

1. **`max_weight` 上限会悄悄降低总仓位，而不是再分配**。`_apply_weight_constraints` 注释写得很清楚："caps only ever scale weights *down*; freed weight is not redistributed"。例如 3 只等权各 0.333、上限设 0.25，结果是三只各 0.25、合计只有 0.75，**剩下 0.25 变成现金闲置**，而不是把多出的权重摊给别人。看起来像"明明满仓却留了一堆现金"，根源就在这里。

2. **归因不与总收益对账**。归因只算 `数量 ×（close − prev_close）` 的纯盯市，**忽略了佣金、滑点和现金部分**。所以把所有标的的 `contribution` 加起来，不会等于权益曲线给出的总收益。这是设计取舍（归因衡量"持仓选得好不好"，不是完整 P&L 分解），但容易让人误以为数据不一致。

3. **行业上限 `sector_cap` / `sector_map` 有后端没前端**。schema、`BacktestConfig`、`_apply_weight_constraints` 都支持，且 `sector_cap` 必须配 `sector_map`（否则报错），但表单上完全没有入口。想用得自己拼 JSON 调 API。

4. **主页指标永远显示"最近一次"运行，看起来像表单被忽略**。`/backtest` 主页顶部的三张指标卡、权益曲线、成交 / 订单表，全部来自 `selectDisplayRun` 选出的**最新一次运行**（`getBacktests` 列表里最近的那条），**不是**你刚填的表单。你提交后会**跳转到 `/backtest/<run_id>` 详情页**才看到本次结果。如果停在主页改参数却不提交，指标纹丝不动是正常的——它展示的是历史，不是预览。

5. **`top_n` 超过实际可选数量时静默少持仓**。策略用 `.head(top_n)`，若正分标的（或整个 universe）不足 `top_n`，就只买到实际数量，不会报错也不会补足。`top_n=10` 但只有 3 个正分标的，就只持 3 只。

6. **单标的 = 通常什么都不买**。`cross_sectional_top_n` 依赖横截面 z-score 排序：只有一个标的时 z-score 恒为 0、过不了 `score > 0` 这道闸，于是不买、曲线水平。表单已就此给了黄色警告，但仍是新手第一大困惑点。

7. ~~**DuckDB 只留最近一次，API 目录留全部**~~ **已于 2026-06-15 后续修复**。HTTP API 的 backtest / factor / paper / experiment run 现在都不再生成逐 run DuckDB 副本，测试会断言 `api_runs` 下没有 `.duckdb` 文件。DuckDB 仍保留在本地 ingest / 期权缓存等有真实读者的路径上；历史遗留的 `data/api_runs/**/quant_system.duckdb*` 可用 `scripts/cleanup_api_run_duckdb.py` 先 dry-run 再 `--apply` 删除。

8. ~~**前端 / 后端默认数据源不一致**~~ **已于 2026-06-11 修复**：前端表单默认值改为 `futu` + 滚动 180 天窗口，与后端 schema 一致；走 UI 与直接打 API 的默认行为不再分叉。

9. **年化因子硬编码 252**。无论数据是日线还是别的频率，夏普 / 年化收益都按 252 个交易日年化。非日线数据下这些年化指标会失真。

## 合理性评估与改进建议

整体评估：**这是平台里最扎实的一环**，流水线完整、避免了前视偏差（`tradeable_ts` 滞后）、撮合考虑了佣金 / 滑点 / 现金约束、产物齐全。作为"研究回放 + 进入模拟前的体检"，它名副其实。

可优先改进的点（按性价比）：

1. **权重约束补"再分配"开关**：给 `_apply_weight_constraints` 增加一个可选的归一化模式，把封顶释放的权重摊回未触顶的标的，让"满仓"真的满仓；保留当前"只向下缩放"为默认以维持向后兼容。
2. **归因加一行"残差"对账**：在归因表追加一行 `costs / cash drag`，让 Σcontribution + 残差 = 总收益，消除"加不齐"的困惑。
3. **主页加一句话说明**："以下指标来自最近一次运行，提交表单后请到详情页查看本次结果"，直接消解第 4 条困惑。
4. **暴露 `sector_cap` / `sector_map` 入口**，或在表单上明确标注"行业上限暂仅 API 可用"。
5. **`top_n` 超额时给软提示**：当实际持仓数 < `top_n` 时，往 warnings 里加一条说明。
6. **年化因子随数据频率自适应**，或在 UI 上标注"按 252 日年化"。
7. ~~**统一默认数据源**~~ 已于 2026-06-11 完成（前端默认 `futu` + 滚动 180 天，与后端 schema 一致）。

## 相关代码入口（关键文件）

- 前端主页：`src/frontend/app/backtest/page.tsx`
- 前端运行详情：`src/frontend/app/backtest/[runId]/page.tsx`
- 表单组件：`src/frontend/components/forms/BacktestForm.tsx`
- 编排入口：`src/quant_system/backtest/pipeline.py`（`run_backtest`）
- 引擎主循环 / 再平衡 / 盯市 / 归因：`src/quant_system/backtest/engine.py`
- 选股与目标权重：`src/quant_system/backtest/strategy.py`（`ScoreSignalStrategy` / `MeanReversionTopN`）
- 多因子合成打分：`src/quant_system/experiments/scoring.py`
- 订单生成与权重约束：`src/quant_system/backtest/order_generation.py`
- 撮合（佣金 / 滑点 / 现金约束）：`src/quant_system/backtest/broker.py`
- 绩效与归因汇总：`src/quant_system/backtest/metrics.py`
- 基准曲线：`src/quant_system/backtest/benchmark.py`
- 配置与数据模型：`src/quant_system/backtest/models.py`（`BacktestConfig` / `Order` / `Fill` / `TargetWeight` / `RebalanceFrequency`）
- API 路由与请求 schema：`src/quant_system/api/routes/backtest.py`、`src/quant_system/api/schemas/backtest.py`
