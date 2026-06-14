# 因子实验室 Factor Lab（界面路由：/factor-lab）

> 安全红线：本平台是纯本地、仅研究 / 仅模拟系统，**绝不接触真实下单、钱包、私钥签名或券商账户**。本页所有「择时」「交易数」「Sharpe」都只是历史样本上的统计诊断，不产生任何真实委托。

> 本文已对齐 2026-06-11 前端全面重构后的实现。旧版「页面没有任何输入控件、运行表单未挂载」的描述已过时。

## 一句话定位

`/factor-lab` 是一个**因子体检面板**：对所选股票池（默认 ETF 池）的 5 个内置技术因子算出横截面有效性指标（IC、衰减、分位收益差、换手、覆盖度），并对所选择时标的（默认 QQQ）做一个 z-score 择时回测（Sharpe / 最大回撤 / 胜率 / 交易数）。2026-06-11 重构后，侧栏提供**数据源 / 股票池 / 择时标的 / 基准**四个查询控件（默认 `futu` 真实数据），以及一个**「运行新研究」表单**（FactorRunForm）用来生成可持久保存、可在详情页复看的因子研究运行。

## 它解决什么问题 / 为什么存在

做量化最常踩的坑是「先写了一个因子，再去回测组合，发现根本没用」。Factor Lab 想在你把一个因子放进组合 / 回测之前，先回答两个更基础的问题：

1. **横截面层面**：在同一天对一篮子标的打分，分数高的标的未来真的涨得更多吗？（用 IC、分位收益差衡量）这个因子稳不稳定、衰减快不快、换手高不高、能覆盖多少样本？
2. **单标的择时层面**：把这个因子在择时标的上做成「z-score 偏离均值就开仓」的简单择时信号，历史上能不能赚钱？（用 Sharpe、最大回撤、胜率衡量）

它定位是「探索性体检」，不是「策略生成器」。代码里也明确写了 `exploratory_only: True` 和「容易过拟合」的护栏提示。

## 它实际能做什么（基于真实代码）

后端入口是 `build_factor_lab_dashboard()`（`src/quant_system/factors/lab.py`），它做的事情：

1. 取**默认因子注册表**里的全部 5 个因子：动量 `momentum`、波动 `volatility`、流动性 `liquidity`、RSI `rsi`、MACD 柱 `macd`（见 `registry.py` / `examples.py`）。
2. 取所选股票池（默认 `etf`：`SPY, QQQ, IWM, DIA, XLK, XLF, XLV, XLY, XLP, XLE`），再与择时标的求并集。
3. 按所选 `provider`（默认 `futu`，可选 `tiingo` / `sample`）拉日线 OHLCV；时间窗与 lookback 用后端默认值（2024-01-02 ~ 2024-12-31、`lookback=20`），UI 暂不暴露这两项。
4. 跑 `compute_factor_pipeline` 算出每个因子在每个标的每一天的因子值。
5. 算两张表：
   - **横截面体检**（`_cross_sectional_rows`）：每个因子一行，给出 `ic_mean / ic_decay / quantile_spread / turnover / coverage / sample_count`。
   - **择时诊断**（`_timing_rows`）：每个因子一行，给出 `sharpe / max_drawdown / win_rate / trade_count / coverage`。
6. 计算两条「护栏」展示信息：walk-forward 切分折数（`fold_count`）、leakage 泄漏检查状态（`leakage_audit.status`）。
7. 把整个结果**缓存到** `factor_lab/factor_lab_cache.json`。下次同参数请求直接读缓存（`cache.status` 显示 `cached`），否则重算（`recomputed`）。

前端（`app/factor-lab/page.tsx`）从 **URL 查询参数**读取 `provider / universe_id / symbol / benchmark_symbol`（缺省回退 `futu / etf / QQQ / QQQ`），传给 `getFactorLabDashboard()`。侧栏的 `FactorLabControls` 改这四项后点「应用」，会以新参数重新跳转本页、触发服务端重取。**`start / end / lookback` 仍不暴露**，沿用后端默认值。

页面布局（`FactorLabDashboard.tsx`，左侧栏 320px + 右侧主区）：

- 左侧栏从上到下：**范围卡**（FactorLabControls 四个控件 + 当前股票池/基准只读行 + 数据源徽标）、**「运行新研究」卡**（FactorRunForm，见下）、**最近保存结果卡**（最多 5 条 run，带「打开结果」链接；有被隐藏的 sample 运行时给出 `?include_sample=1` 链接）、**护栏卡**（仅探索 / 滚动验证折数 / 泄漏检查状态）、**因子清单卡**（默认折叠，列出 5 个因子的方向与说明）、**缓存卡**（状态 + 生成时间）。
- 右侧主区：sample 数据警告条（仅 source 为 sample 时显示）+ 共享 `Tabs` 组件（`role="tab"`）的两个视图——「横截面体检」和「单标的择时」，各是一张带**列头悬停释义**的只读表格。

**「运行新研究」链路**（2026-06-11 起在页面上可用）：`FactorRunForm` → `POST /api/factors/run` → `run_factor_research()`，会落盘 parquet + 报告、生成 run id，结果出现在「最近保存结果」列表，并可在 `/factor-lab/[runId]` 详情页复看。

## 操作步骤（一步一步，结合真实的输入项与默认值）

1. 启动后端（默认 `127.0.0.1:8765`）和前端 dev（默认 `:3001`）。
2. 打开 `http://localhost:3001/factor-lab`。默认按 `futu / etf / QQQ / QQQ` 查询（futu 需 OpenD 在线）。
3. 要换查询范围：在侧栏「范围」卡里改**数据源 / 股票池 / 择时标的 / 基准**，点「应用」。参数会写进 URL（可收藏 / 分享），页面整体重取。
4. 左侧「缓存」卡显示本次结果是 `recomputed`（重算）还是 `cached`（命中 `factor_lab_cache.json`）。
5. 看右侧 Tab：
   - 默认是**「横截面体检」**：每行一个因子，列为 `factor_id / factor_name / direction / ic_mean / ic_decay / quantile_spread / turnover / coverage / sample_count`，列头悬停有定义。
   - 点**「单标的择时」**：每行一个因子，列为 `factor_id / factor_name / sharpe / max_drawdown / win_rate / trade_count / coverage`，只用择时标的一只；无数据的行显示 `--` 而不是误导性的 0。
6. 要生成**可保存**的因子研究运行：在侧栏「运行新研究」卡填表（FactorRunForm）提交，成功后「最近保存结果」出现新 run，点「打开结果」进 `/factor-lab/[runId]` 详情页。
7. 仍想调 `start / end / lookback / force_refresh`：UI 不暴露，需直接向 `/api/factors/lab` 传参。

## 字段与指标含义（逐项解释 UI 上出现的术语 / 指标）

### 左侧栏

- **范围 / 股票池（Universe）**：当前所选股票池及其成分数（默认 `ETF Core (10)`）。
- **基准（Benchmark）**：默认 QQQ，可在控件里改。注意 `etf` 股票池定义里的官方基准是 SPY——面板用的是你在控件 / URL 里给的值。
- **数据源（Source）**：徽标显示当前 provider（默认 `futu`）。
- **护栏 - 仅探索（Exploratory only）**：固定文案，提醒「容易过拟合，因子进别的流程前要看滚动验证和泄漏检查」。
- **护栏 - 滚动验证（Walk-forward）**：显示 `fold_count`，即对时间轴按 `train=60 / validation=20 / step=20 根 K 线` 切出的折数。**这只是展示，不参与上面任何指标计算，也不拦截任何东西。**
- **护栏 - 泄漏检查（Leakage）**：显示 `leakage_audit.status`，正常是 `basic_passed`。它做的唯一检查是「每行因子的 `tradeable_ts` 是否都晚于 `signal_ts`」（即信号生成时刻 vs 可交易时刻），通过则 `basic_passed`，否则 `failed`，空数据 `empty`。同样只展示、不拦截。
- **缓存 - 状态 / 生成时间**：`recomputed`（重算）或 `cached`（命中缓存）；时间戳取自结果生成时的 UTC 时间，截断到秒。

### 横截面体检表

- **factor_id / factor_name**：因子代号与名称（动量 / 波动 / 流动性 / RSI / MACD 柱）。
- **direction**：因子方向——值越高越好（`higher_is_better`）还是越低越好（`lower_is_better`），决定 IC 正负怎么读。
- **ic_mean**：信息系数均值。**注意：代码里取的是 `rank_ic`（Spearman 秩相关）按各信号日求平均，不是 Pearson IC**，尽管列名叫 `ic_mean`（列头悬停提示已写明这一点）。直观含义：因子值排序与「未来 1 日收益」排序的相关性，越正说明「因子越大→未来越涨」越成立。
- **ic_decay**：IC 衰减，定义为 `IC(horizon=5) − IC(horizon=1)`。负值表示信号随持有期变长而变弱（衰减），正值表示更长持有期反而更有效。
- **quantile_spread**：分位收益差。把每天的因子值分成 5 组，最高分位组的「未来 1 日平均收益」减最低分位组的平均收益。正且大，说明高分组确实跑赢低分组。
- **turnover**：换手率。每个信号日按因子方向选「前一半」标的（`higher_is_better` 选最大的一半，`lower_is_better` 选最小的一半），相邻两日选中集合的对称差占并集的比例，再取平均。越高说明持仓越频繁变动、交易成本越大。
- **coverage**：覆盖度 = 该因子实际有值的行数 / (标的数 × 信号日数)。因为各因子要 rolling 窗口预热（如动量要 20 天、RSI 要 14 天），开头若干天没有值，所以覆盖度通常小于 1。
- **sample_count**：该因子产生的因子值行数（非空 + 空都算，是该因子结果子集的总行数）。

### 择时诊断表（只用所选择时标的一只）

逻辑（`_timing_rows`）：对择时标的的因子值算 `lookback=20` 的**滚动 z-score**；按因子方向定方向（`lower_is_better` 取 −1，否则 +1）；`zscore × 方向 > 0` 就持仓（position=1），否则空仓（0）；用「持仓 × 未来 1 日收益」当作策略收益。

- **sharpe**：年化夏普 = 策略日收益均值 / 标准差 × √252。无收益或零波动时为 0。
- **max_drawdown**：最大回撤，基于策略收益累乘净值算的最深回撤（负数）。
- **win_rate**：胜率 = 在「持仓」的那些日子里，策略收益 > 0 的占比。
- **trade_count**：交易数 = position 序列差分绝对值之和，即开仓 / 平仓切换的总次数。
- **coverage**：有有效 z-score 的行数 / 该因子在该标的上的总行数（同样受滚动窗口预热影响）。

## 当前的局限与「为什么看起来奇怪」（诚实列出令人困惑之处及其代码层面的原因）

> 旧版指南列出的两条最大局限——「页面完全只读、参数写死」「FactorRunForm 未挂载、保存结果永远是空的」——已在 2026-06-11 重构中修复，下面只保留仍然成立的条目。

1. **时间窗与 lookback 仍然写死。** 控件只暴露数据源 / 股票池 / 择时标的 / 基准；`start / end / lookback / force_refresh` 仍是后端默认（2024 全年、20），想改只能直接打 `/api/factors/lab`。

2. **存在两套互不相同的「signal」定义。**
   - 面板择时表里的 signal = 单标的的**滚动 z-score 择时**（时间序列上偏离自身均值就开仓）。
   - 「运行新研究」（`run_factor_research`）链路里的 signal = `build_factor_signal_frame` 算的**横截面 z-score 均值**（同一天对一篮子标的标准化后取多因子平均分）。
   两者完全不是一回事，但都叫「signal / 信号」。同时看面板和详情页时注意区分。

3. **`ic_mean` 这个列名仍有误导性（已用悬停提示缓解）。** 它实际上是 `rank_ic`（Spearman 秩相关）的均值，而 evaluation 里其实同时算了 Pearson `ic` 和 `rank_ic` 两列。2026-06-11 起列头悬停提示已写明真实口径，但列名本身未改，严格说应叫 `rank_ic_mean`。

4. **护栏（walk-forward / leakage）只展示、不拦截。** 「滚动验证折数」和「泄漏检查状态」是算出来摆在那里给你看的，**不会**阻止任何因子被「使用」，也不参与 IC / 择时计算。它们是提醒，不是闸门。

5. **基准与股票池官方基准可能不一致。** 默认 benchmark=QQQ 来自 URL 参数 / 控件，而 `etf` 股票池定义里的 `benchmark_symbol` 是 SPY。这是参数覆盖的结果，不是 bug；现在控件里能自己改，混淆程度已大幅降低。

6. **MACD 不是经典 (12,26,9)。** `MACDFactor` 用 `(fast=L, slow=2L, signal=L)` 的简化参数化（代码注释已写明），在 `lookback=20` 时是 (20,40,20)，无法精确复现经典 MACD。

7. **指标只在所取数据窗内成立（默认 2024 全年）。** 数据源默认已是 futu 真实数据，但时间窗仍固定，结论**不能**外推到其他时间段。覆盖度普遍 < 1 也是正常的（滚动窗口预热）。选 sample 数据源时页面会显示合成数据警告条。

## 合理性评估与改进建议

**合理的地方**：把「横截面有效性」和「单标的择时」分开看是对的；明确标注「仅探索 / 容易过拟合」、加 leakage 与 walk-forward 提示，方向上专业；查询参数经 URL 透传，可收藏可复现。

**2026-06-11 已落地的改进**（原建议 1/2(部分)/4(部分)/6/7）：FactorRunForm 挂上页面、保存运行闭环；列头悬停释义（含 ic_mean 真实口径）；provider / universe / symbol / benchmark 四项控件；基准显示当前值；sample 数据自动显示警告条。

**仍可改进（按性价比排序）**：

1. **暴露 `start / end / lookback` 控件**：后端 `/api/factors/lab` 已支持，前端补 UI 即可，让「换个时间窗看看」不用打 API。
2. **重命名 `ic_mean → rank_ic_mean`**：悬停提示已说明口径，改列名才是根治。
3. **统一或显式区分两套 signal 定义**：在 UI 文案里讲清「面板=单标的 z-score 择时」「保存运行=横截面多因子打分」。
4. **给护栏一个「是否拦截」的明确标识**，或在文案里写明「仅提示、不拦截」，避免被误解为质量闸门。

## 相关代码入口（列出关键文件）

- 前端页面（读 URL 参数并装配）：`src/frontend/app/factor-lab/page.tsx`
- 前端看板组件：`src/frontend/components/forms/FactorLabDashboard.tsx`
- 前端查询控件（数据源/股票池/择时标的/基准）：`src/frontend/components/forms/FactorLabControls.tsx`
- 前端运行表单（挂载于看板侧栏「运行新研究」卡）：`src/frontend/components/forms/FactorRunForm.tsx`
- 前端详情页：`src/frontend/app/factor-lab/[runId]/page.tsx`
- 前端 API 封装：`src/frontend/lib/api.ts`（`getFactorLabDashboard / getFactorRuns / getFactorRunDetail`）
- 后端面板计算（横截面体检 + 择时 + 缓存）：`src/quant_system/factors/lab.py`
- 后端持久化研究链路（parquet + 报告 + 横截面打分）：`src/quant_system/factors/pipeline.py`
- 后端 IC / 分位收益 / 前瞻收益：`src/quant_system/factors/evaluation.py`
- 后端因子注册表：`src/quant_system/factors/registry.py`
- 后端 5 个因子实现与方向：`src/quant_system/factors/examples.py`
- 后端 ETF 股票池定义：`src/quant_system/universe/registry.py`
- 后端 API 路由：`src/quant_system/api/routes/factors.py`（`GET /factors/lab`、`POST /factors/run`、`GET /factors/runs`、`GET /factors/{run_id}`）
