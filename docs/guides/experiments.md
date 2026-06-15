# 实验管理 Experiments（界面路由：`/experiments`）

> 安全红线：本页面纯本地、仅研究/仅模拟。它**只跑回测、只生成本地文件**，绝不接触真实下单、钱包、签名或券商账户。生成的 `agent_summary.json` 里明确写死 `live_trading=false`、`paper_trading=false`、`auto_promotion=false`——即"实验结果不会被任何机制自动晋级成实盘或模拟盘"。

## 一句话定位

这是一个**参数网格扫描研究台**：对一个**写死的三因子打分策略**，在你选择的 OHLCV 数据源上遍历 `lookback`（回看窗口）× `top_n`（持仓只数）两个维度的所有组合，每个组合各跑一次回测，最后按夏普比率（Sharpe）挑出"最佳"组合供人工查看。

## 它解决什么问题 / 为什么存在

做量化最常见的动作之一是"调参"：同一套策略逻辑，换不同的回看窗口、换不同的持仓集中度，表现会差很多。手动一个个改、一个个跑、再把结果抄进表格对比，既慢又容易出错。

这个页面把这件事自动化成一次提交：你只填两组候选值，系统就把它们的**笛卡尔积**全部跑一遍，把所有结果落成 parquet 表，并用热力图、柱状图、对比表帮你一眼看出哪个参数组合的夏普最高。它的定位是**离线研究 / 参数敏感性分析**，不是交易工具。

## 它实际能做什么（基于真实代码）

以下行为全部来自代码，不是宣传：

1. **被扫描的策略是写死的，你无法在 UI 改。** `create_sample_experiment_config`（`config.py`）固定构造三因子打分：
   - `momentum`（动量），权重 `1.0`，方向 `higher_is_better`（越高越好）；
   - `volatility`（波动率），权重 `0.5`，方向 `lower_is_better`（越低越好）；
   - `liquidity`（流动性），权重 `0.5`，方向 `higher_is_better`。

   打分逻辑（`scoring.py`）：每个因子在**每个信号时点做横截面 z-score 标准化**，按方向乘 `±1`，再按"权重 / 权重绝对值之和"加权求和，得到每只标的的综合 `score`。选股逻辑（`ScoreSignalStrategy`）：每个可交易时点取 `score > 0` 的标的按分数降序选前 `top_n` 只，**等权做多（long-only）**。

2. **数据源可显式选择。** `/api/experiments/run` 的 `ExperimentRunRequest.provider` 支持 `sample` / `futu` / `tiingo`。前端表单默认 `futu`，也可切到 `sample` 或 `tiingo`；后端通过 `build_ohlcv_provider` 构造 OHLCV provider。若显式请求的真实 provider 不可用，API 返回 `400 provider_unavailable`，不会静默改跑 sample。

3. **遍历参数网格。** `expand_parameter_grid`（`sweep.py`）对 `{"lookback": [...], "top_n": [...]}` 做笛卡尔积，每个组合得到一个 `run-001`、`run-002`… 的 run，逐一调用 `_run_single_backtest`。运行次数 = `len(lookbacks) × len(top_ns)`。

4. **按 Sharpe 选最佳。** `best_run = max(runs, key=sharpe)`（`runner.py`），写进 `agent_summary.json` 的 `best_run_id`。

5. **落地产物（写到本地 `experiments/<实验ID>/` 目录）：**
   - `experiment_config.json`：本次实验的完整配置（因子、权重、sweep、walk_forward 等）；
   - `experiment_runs.parquet`：每个 run 一行的指标表（驱动"参数扫描热力图"和"运行对比"）；
   - `walk_forward_folds.parquet`：滚动验证折表——**当前永远是空表**（见下文局限）；
   - `agent_summary.json`：只读 JSON 摘要（驱动"代理摘要"标签页）；
   - 一份对比报告。

6. **"发送至回测"按钮（Send to Backtest）。** 在结果区找到最佳 run 后会出现该按钮，点它跳到 `/backtest`，把 `lookback`、`top_n`、成本参数和数据源一起带过去。数据源来自 `agent_summary.data.source`；旧实验如果缺少该字段，会按 `sample` 处理，避免把 sample 实验静默切到真实数据。

## 操作步骤（一步一步，结合真实输入项与默认值）

页面左侧是"运行实验"表单（`ExperimentRunForm`），右侧是结果区。

1. **填表单**（默认值来自 `ExperimentRunForm.tsx` 的 `DEFAULTS`）：
   - **标的 Symbols**：默认 `SPY,QQQ,IWM,DIA`。逗号分隔，**至少两个**（后端 `min_length=2`；因子排序需要一个可比较的标的池，只有一只标的横截面 z-score 无意义）。
   - **开始 Start / 结束 End**：默认 `2024-01-02` / `2024-02-15`。日期选择器。
   - **数据源 Data Source**：默认 `futu`。可选 `sample` / `futu` / `tiingo`；`sample` 适合离线流程验证，真实 provider 不可用时会明确失败。
   - **回看窗口 Lookbacks**：默认 `3,5,10`。逗号分隔的正整数，每个值是一个候选回看窗口。
   - **Top N 数值**：默认 `1,2`。逗号分隔的正整数，每个值是一个候选持仓只数。
   - **初始资金 Initial Cash**：默认 `100000`。
   - **佣金（基点）Commission bps**：默认 `1`。
   - **滑点（基点）Slippage bps**：默认 `5`。

   按默认值，运行次数 = 3（lookback）× 2（top_n）= **6 个 run**。

2. **点"运行实验"。** 前端 POST 到 `/api/experiments/run`。成功后弹 toast：`实验已创建：<id>（<n> 次运行）`，并自动刷新列表。

3. **在左侧列表选实验。** 列表按目录修改时间倒序，每条显示实验 `id`、`最佳: <best_run_id>`、本地路径；最新一条带「latest」徽章。2026-06-11 起**每条都是可点击链接**（`?experiment=<id>` 查询参数），点击即切换右侧详情，选中项高亮（绿色边框 + `aria-current`）；不带参数进入页面时默认选最新一个实验。页头还有一行汇总指标（本地实验数 / 当前选中 / 最佳 run / 回测次数）。

4. **在右侧四个标签页查看结果**（`ExperimentTabs`）：
   - **参数扫描热力图（Sweep heatmap）**：每个 run 一个卡片，显示 `lookback=… / top_n=…` 和该组合的 Sharpe，背景绿色深浅按 Sharpe 在 [min, max] 区间归一化着色。
   - **滚动验证折（Walk-forward folds）**：**当前总是空**，显示"滚动验证折不可用"。
   - **运行对比（Run comparison）**：按 Sharpe 降序的柱状图 + 明细表（列：`run_id, lookback, top_n, sharpe, total_return, max_drawdown, turnover`），最佳 run 行高亮。
   - **代理摘要（Agent summary）**：渲染 `agent_summary.json`，含 `notes` 列表，可"复制 JSON"。

5. **（可选）点"发送至回测"。** 跳到 `/backtest` 并预填最佳参数和同一数据源；旧实验缺少 source 时按 `sample` 预填。

## 字段与指标含义（逐项解释 UI 术语）

- **experiment（实验）**：一次完整的参数扫描批次。对应本地一个目录 `experiments/<实验ID>/`。实验 ID 形如 `phase4-sample-experiment-20240115T...Z`。
- **sweep（扫描）**：参数网格本身，即 `{lookback: [...], top_n: [...]}` 的笛卡尔积。
- **run（运行）**：网格中的一个格子 = 一次回测，编号 `run-001`…。
- **fold（折）**：滚动验证（walk-forward）里的一个"训练窗+验证窗"切片。**本页当前不产生 fold**（见局限）。
- **best（最佳）**：所有 run 里 Sharpe 最高的那个 run 的 `run_id`。
- **lookback（回看窗口）**：计算因子时往回看多少根 K 线。同一个 lookback 同时作用于动量/波动/流动性三个因子（`_create_factors` 用同一个 lookback 实例化全部因子）。
- **top_n**：每次调仓时按综合分选前几名等权做多。
- **sharpe（夏普比率）**：风险调整后收益，本页**唯一的排序/择优指标**。
- **total_return（总回报）**：回测期累计收益率。
- **annualized_return（年化收益）** / **volatility（波动率）**：年化口径的收益与波动。
- **max_drawdown（最大回撤）**：期间净值从峰值到谷底的最大跌幅。
- **turnover（换手率）**：调仓造成的成交规模代理量。
- **commission_bps / slippage_bps（佣金 / 滑点，基点）**：1 基点 = 0.01%。回测撮合时扣的交易成本。
- **score（综合分）**：三因子横截面 z-score 加权和，决定选股顺序（UI 不直接展示，但它是选股的依据）。
- **Agent summary（代理摘要）**：一个**静态 JSON 文件**，不是 AI 实时推理。里面有 `purpose`、`safety` 三个 false 标志、`data.source`、`best_run_id`、全部 run 的指标、以及三条固定 `notes`。摘要描述写得很明确："仅供人工查阅的只读摘要，不会推广或部署任何内容。"
- **Data source（数据源）**：当前实验实际使用的 OHLCV 来源。新实验会写入 `agent_summary.data.source`；旧实验缺少该字段时，前端按 `sample` 标注。

## 当前的局限与"为什么看起来奇怪"（诚实列出）

这些正是让人"看了界面却理解不了它在干什么"的根源，逐条对应到代码：

1. **"滚动验证折"是头部大标签页，却永远是空的。**
   `create_sample_experiment_config` 把 `walk_forward=WalkForwardConfig(enabled=False)` 写死。`runner.py` 里 `_run_combination` 只在 `config.walk_forward.enabled` 为真时才走 `_run_walk_forward_combination`——从 UI 进来永远是 `False`，所以 `walk_forward.py`（train/validation/step 折叠逻辑）、`_run_walk_forward_combination`、`_aggregate_fold_metrics` 全是**对 UI 而言的死代码**，`walk_forward_folds.parquet` 永远写空表，标签页永远显示"不可用"。这是"承诺（UI 摆了个折验证标签）vs 实现（功能被关掉）"的典型落差。

2. **被比较的策略写死且不可见。** UI 上你只有 `lookback` 和 `top_n` 两个旋钮，但真正决定收益的三因子组合（动量 1.0 / 波动 0.5 / 流动性 0.5）藏在后端 `config.py` 里，界面完全不展示。用户看到一堆 Sharpe 差异，却不知道"被比的到底是什么策略"。

3. **sample 实验仍然只是流程验证，不代表真实行情结论。**
   现在 sample 实验不会再被"发送至回测"静默切到 `futu`，但 sample 数据上最优的 lookback/top_n 对真实行情仍没有统计意义上的迁移保证。需要真实研究时，应直接选择 `futu` 或 `tiingo` 运行实验。

4. **"Agent summary"听起来像 AI，其实是静态 JSON。** 名字带"代理（Agent）"，容易让人以为有模型在分析；实际只是把配置和指标序列化成文件再渲染出来，`notes` 也是三条硬编码文案。

5. **专业术语全程零解释。** experiment / sweep / run / fold / best 在界面里直接出现，没有任何 tooltip 或说明，非量化背景的使用者无从下手（本文档即为补这个缺口）。

6. ~~默认只看最新实验、列表项不可点击~~ **已于 2026-06-11 修复**：列表项是 `?experiment=<id>` 链接，点击即切换详情；不带参数时回退到最新实验。

7. **择优维度单一。** 只按 Sharpe 选最佳，不看最大回撤、换手率等。对成本敏感或风险厌恶的研究者，"最佳"未必是他想要的那个。

## 合理性评估与改进建议

**合理的部分**：作为一个离线、纯研究的参数敏感性工具，整体架构是干净的——配置/扫描/打分/回测/落地各司其职，产物全部是可复查的本地文件，安全标志明确，没有任何实盘通路。用合成数据做"管道自检"也合理。

**主要问题**：UI 暴露的能力与后端实际开启的能力仍有不一致（folds 死标签、策略不可见），导致使用者困惑。2026-06-15 起，数据源选择与"发送至回测"的数据源语义已对齐。

**改进建议（按性价比排序）**：

1. **要么打开 walk-forward，要么从 UI 移除该标签页。** 既然 `walk_forward.py` 的逻辑已经写好，最干净的做法是给表单加一个"启用滚动验证 + train/validation/step"开关并透传到 `WalkForwardConfig`；若短期不做，则隐藏该标签页，避免摆一个永远空的功能。
2. **在结果区显式展示被扫描的策略与因子权重。** 把 `experiment_config.json` 里的三因子组合渲染成一个只读卡片，让用户知道"在比什么"。
3. ~~修正"发送至回测"的数据源语义~~ **已于 2026-06-15 修复**：跳转会沿用实验记录的 `agent_summary.data.source`；旧实验缺少 source 时按 `sample` 处理。
4. **给关键术语加 tooltip**（experiment/sweep/run/fold/best/lookback/top_n）。
5. **让最佳判定可配置或多指标呈现**（如同时标注回撤最小、换手最低的 run）。
6. ~~支持点击左侧历史实验切换详情~~ 已于 2026-06-11 完成（`?experiment=` 链接切换）。

## 相关代码入口

- 前端页面：`src/frontend/app/experiments/page.tsx`
- 运行表单（provider 选择、默认值、请求 payload）：`src/frontend/components/forms/ExperimentRunForm.tsx`
- 结果四标签页（热力图/折/对比/摘要、source 标注、`buildBacktestHref` 跳转逻辑）：`src/frontend/components/forms/ExperimentTabs.tsx`
- 前端 payload/helper 测试：`src/frontend/lib/experimentRunPayload.ts`
- 后端路由（list / run / detail）：`src/quant_system/api/routes/experiments.py`
- 请求 schema（provider 支持 sample/futu/tiingo、字段约束）：`src/quant_system/api/schemas/experiments.py`
- 实验编排（可注入 provider、按 Sharpe 选最佳、写产物）：`src/quant_system/experiments/runner.py`
- 写死的三因子配置 + `walk_forward.enabled=False`：`src/quant_system/experiments/config.py`
- 参数网格笛卡尔积：`src/quant_system/experiments/sweep.py`
- 滚动验证切分（当前为死代码）：`src/quant_system/experiments/walk_forward.py`
- 横截面 z-score 多因子打分：`src/quant_system/experiments/scoring.py`
- 数据模型（ExperimentConfig / WalkForwardConfig / ExperimentRunSummary 等）：`src/quant_system/experiments/models.py`
- 选股策略（top_n 等权做多、score>0）：`src/quant_system/backtest/strategy.py`
