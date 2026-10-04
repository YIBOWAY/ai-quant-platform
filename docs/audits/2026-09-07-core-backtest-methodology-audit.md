# 回测核心与九项用途研究：独立方法复核

审计日期：2026-09-07。审计者：独立 Model QA 子 Agent。

## 结论与证据范围

原回测的四组具体反例已经闭合；新增九项固定用途研究在本次检查的日期、信号、同池对照、训练截断与月度标签范围内，没有发现需要阻断研究的数学错误。

这是源码和计算方法的独立复核，**不是策略有效性、可交易 alpha、生产发布或模拟运行资格的认可**。本报告不引用尚未见到的新九方案真实收益，也不替代根 Agent 的总体执行收据。

- 源码 checkout：[ai-quant-platform](https://github.com/YIBOWAY/ai-quant-platform/tree/main/)。
- 审计时 Git HEAD：`fe08b2c71ecf47e76ddb0e3d73a165b03cbdfe6b`；结论同时依赖当时未提交的修复和新增文件，不能仅用该 HEAD 重现修复后结果。
- 审计者没有参与产品实现或修复。先报告原反例，由其他实施者修改，再独立复核；最后仅获准新增本文档。
- 验证只使用纯函数、既有只读输入和密封合成样本。未调用 `run_studies`、行情提供商、真实模型请求、研究 worker、候选/账户写入或模拟观察周期；未重生成正式评价缓存。
- 环境：Python `3.11.15`、NumPy `1.26.4`、pandas `2.3.3`；实际 Qlib 统计检查使用 `hqa-qlib-evaluation:0.1.0`，容器断网、根文件系统及源码挂载只读，`/tmp` 为 tmpfs。

## 一、原回测缺陷的修复复核

| 原发现 | 原影响及直接证据 | 修复后独立复核 | 状态 |
|---|---|---|---|
| Medium：Qlib 最后标签止于开盘，组合却计到收盘 | 所有开盘价为 100、标签全部为 0，仅把末个标签退出日的选中资产收盘改为 150，报告收益由 -0.059969% 变为 +49.910046% | 同样扰动后，策略和 QQQ 的指标、曲线、费用完全不变；前后收益均 -0.059969% | 已解决 |
| Low：底层指标漏首日收益和初始本金峰值 | 首日买入后收盘跌 10%、次日不变，原引擎总收益 -10.053972%，却报告回撤 0、波动 0；旧 reference wrapper 已补偿这一问题 | 引擎回撤为 10.053972%，波动 0.7980092971、Sharpe -15.8745078664；与 reference wrapper 一致，没有重复添加初始状态 | 已解决 |
| Medium：MACD 绝对价格柱值直接跨 ETF 排序 | 保持收益和成交额不变，将既有真实输入的 QQQ 全段 OHLC 乘 10、volume 除 10；2,180 个信号日中 200 日 Top-3 改变 | 相同反例改变日数为 0；归一化 MACD 最大绝对差 `4.32e-16` | 已解决 |
| Medium：缺 bar 压缩形成/执行日历 | 既有 XLE 缺口使 19 日动量偏离固定交易日口径，最大差 1.78607 个百分点；低波 20 日、流动性 19 日仍错误给出完整窗口数值。另有缺 QQQ bar 导致其他资产信号延迟成交的反例 | 形成窗口与完整日历保留 NaN 的独立计算差值均 0；QQQ 缺 bar 报 `benchmark_session_prices_missing`，待成交资产缺 bar 报 `prediction_execution_prices_missing` | 已解决 |

### 1. 标签退出时刻与组合终点

`qlib_evaluation._portfolio` 现在显式传入 `terminal_valuation="open"`。策略与基准都由该配置在末个标签退出日开盘盯市；结果标记 `terminal_liquidation=false`，没有制造平仓，也没有扣虚构的退出费用。引擎权益、持仓估值和该终点的归因使用相同价格。

此前用既有运行的预测精确重放得到，2026-09-02 最后信号在 09-04 开盘到期时净值为 $293,867.68，旧报告收盘净值为 $293,569.77，额外日内暴露令总收益少 0.297913 个百分点。这只是旧运行的错误影响量化，不是新九方案收益。

### 2. 初始状态与风险指标

`calculate_performance_metrics` 已把初始现金至首个盯市状态计作首期收益，并将历史峰值下界设为初始现金。reference wrapper 移除了自行补初始行的逻辑，防止首期重复计算。

该反例的高波动、负 Sharpe 来自仅两期且首期骤跌的人工样本，不能用作任何真实策略结论。

### 3. MACD 的变换边界

原登记 MACD 定义没有改写。参考特征明确使用 `histogram / signal_day_close`，并在元数据保存 `reference_transform` 和解释。价格尺度不变性反例取 2018-01-01—2026-09-04 的已记录信号日，共 2,180 日。

### 4. 形成日历与缺失 bar

真实输入中 XLE 缺少 2017-05-02。修复后重新计算参考特征，分别与下列独立口径比较缺口及随后 65 个自然日：

- 动量：公共日历上的 `close.pct_change(20, fill_method=None)`。
- 低波：公共日历上的每日收益，再取 20 日、完整窗口标准差并反向。
- 流动性：公共日历上的 `log1p(rolling_mean(close * volume, 20))`，要求完整窗口。

三项最大数值差均为 0，预期缺失但仍给数值的行数也均为 0。成交映射不再使用“全部标的都有价格”的日期交集；不相关的未入选资产缺 bar 不会把交易延到后一天，必要成交/基准价格缺失则明确失败。

上述真实输入只读位置：

```text
$HOME/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform/data/research_evaluations/runs/evaluation-1e59f4fba6c14372a8c4b370a7d931fa/prices.parquet
```

本独立审计未写入或重算旧报告；旧 `reference.json` / `qlib-result.json` 不会因源码修复自动成为新结果。主线程后续实际重算见 [本批收据](../receipts/2026-09-07-purpose-specific-research.md)。

## 二、九项固定用途研究的方法复核

检查文件为 `study_profiles.py`、`profile_backtests.py`、`study_signal_diagnostics.py`、`strategy_study_service.py`，并沿模型输入和冻结输出调用边界查看 `bounded_discovery.py`。

| 方案 | 本次独立验证 |
|---|---|
| 科技 9 股 12–2 月动量 Top3 | 月度端点、次日开盘、同资格集合 peer、未来扰动不影响训练 |
| 跨行业 24 股 12–2 月动量 Top5 | 同上，另核训练期月度 IC 配对 |
| 跨行业 24 股价格三因子 Top5 | 三列百分位 rank 后等权、252 日低波窗口、共同资格、训练配对 |
| 五资产 ETF 3/6/12 月动量 Top3 | 不跳月的三个收益窗口、次月首次开盘、同池 peer |
| 五资产 ETF 动量加趋势防守 | 每个未通过趋势的 1/3 份额转 SHY，不重新加给其余风险资产 |
| SPY / QQQ 两项 10 月均线趋势 | 完整 10 月末价格、收盘与自身均线比较、下一 session 执行 |
| SPY / QQQ 两项 Improved R2 | Wilder RSI2、SMA200、三日条件、事件驱动进出且均在下一 session 开盘 |

### 1. French 12–2 月定义

French 的原说明规定，持有月 t 的组合在 t−1 月末形成，使用 prior 2–12 月收益，并需要 t−13 月末价格。对应价格比为：

```text
holding month t: P(t−2 month-end) / P(t−13 month-end) − 1
signal month m=t−1: monthly.shift(1) / monthly.shift(12) − 1
```

当前代码符合这一端点定义。来源已现场读取：[Kenneth French：Monthly Momentum Factor](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor.html)。股票池、权重与多空方式的改编仍按 profile 中的限制说明，不能称完整复现 French 因子。

独立数值例：2019 年各月价格按月翻倍，2020-01-31 形成信号、2020-02-03 入场，读取 2019-12 月末除以 2019-01 月末，得到 `2**11 - 1 = 2047`；把被跳过的 2020 年 1 月价格再乘 7，信号和目标完全不变。

### 2. 九方案前缀不变性与实际执行时刻

构造密封行情，公共日历为 2016-01-01—2023-04-07 的工作日，NumPy seed 为 734，覆盖九方案所需的全部符号。然后仅将 2022-01-01 起各标的 OHLC 乘以各自不同的正数，保持此前数据不变。

逐一比较九方案后确认：

- 2018–2021 的策略、benchmark、peer 指标和样本期数完全不变。
- 训练期信号记录完全不变。
- 每条记录的 `trade_date` 都等于其 `signal_date` 后的下一条 benchmark session，不是同日开盘，也没有使用固定“加一天”替代真实日期。
- 五个横截面方案的 peer 恰好等权持有当期 `eligible_symbols`；不足 Top N 时双方目标都为空。
- 单指数趋势/R2 的 peer 按已公开规则是全窗口指数买入持有，没有被误标成与择时策略具有相同风险暴露。

月度边界由相邻真实 benchmark session 的月份变化识别；最终部分月份没有借未来日历产生可执行月末信号。已有测试同时覆盖跨周末月界、月末收盘至下一开盘跳空、上市历史不足、SHY 防守及持仓价格缺失。

### 3. 月度 IC 使用实际 entry / next entry

`monthly_pairs` 读取相邻两条月度信号的实际 `trade_date`，标签为这两个日期的开盘价格比。只有相邻自然月且两端价格可用才配对，最后没有后续入场日期的部分持有期不参与 IC。

在断网只读 Qlib 容器内，用三个资产、五个实际入场日期验证：

```text
entry dates: 2021-11-01, 2021-12-01, 2022-01-03, 2022-02-01, 2022-03-01
asset j opening price at entry i: 100 * (1 + 0.1 * (j+1))**i
scores: 1, 2, 3
```

结果为 12 个配对、4 个完整月份，标签分别恒为 10%、20%、30%，Qlib 全段 Rank IC 为 1。训练统计只保留 1 个在 2021 年内完成标签的月份；验证统计只保留 1 个信号和标签均满足验证边界的月份。跨训练截止的标签和末个未完成月份均未混入。这是用于验证计算的人工数列，绝非策略业绩。

前缀扰动例中，两个 24 股方案各有 1,104 个训练配对、46 个完整月份，最后标签退出日为 2021-12-01；改动 2022 年后行情，配对表完全不变。46 月而非 48 月来自“信号日起点＋标签成熟终点”的分段规则，不能把 IC 样本误称为包含每个日历月的净收益分区。这些数量仅属于该密封样本，不声称是真实新研究的最终样本数。

### 4. 模型输入与提议后的评价顺序

`_training_facts` 只抽取两个既定股票方案的 `splits.train` 指标和训练 IC。输出顶层恰好为：

```text
training_start, training_end, universe, factor_statistics
```

将输入研究的 validation/test 指标及其 IC 替换为极大哨兵值，提取后的训练事实完全不变。`bounded_discovery._training_input` 也拒绝额外 holdout 字段，而不是把整份报告送给模型。

源码顺序为先生成并独占保存至多三条提议，再逐条运行仅截至 2021-12-31 的公式评价，检查缺失、常数及本批相同排序；通过这一训练检查后才计算完整时间段。没有根据后续结果回调模型继续修改提议的路径。生产模型调用本次没有执行；这里验证的是可见的调用顺序、输入白名单和封存机制。

对 `$close / Ref($close, 20)` 再作训练截止反例，2022 年后的行情变化不影响训练信号和回报；训练曲线最后日期为 2021-12-31，最后入场月为 2021-12-01。AST 白名单编译的正文在 `frame.timestamp <= end` 的数据上执行，未加载模型生成的 Python 或候选模块。

## 三、检查命令与复现线索

从源码 checkout 使用本地 venv，关闭字节码和 pytest 缓存：

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -o addopts='' -p no:cacheprovider \
  tests/test_backtest_engine_metrics.py tests/test_reference_backtests.py tests/test_qlib_evaluation.py
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -o addopts='' -p no:cacheprovider \
  tests/test_profile_backtests.py
```

实际结果：第一组 21 passed、11 skipped；第二组 20 passed。第一组跳过的是需要 Qlib 镜像的原模型训练测试，新增直接调用真实 `_portfolio` 的端点回归已经运行通过。另行运行的真实 Qlib 月度配对统计检查没有 stub `calc_ic`。

九方案未来扰动的核心复现脚本如下，只在内存计算：

```python
import numpy as np
import pandas as pd
from quant_system.research.profile_backtests import run_profile
from quant_system.research.study_profiles import list_study_profiles

profiles = list_study_profiles()
symbols = sorted({s for p in profiles for s in [*p["symbols"], p["benchmark_symbol"]]})
dates = pd.bdate_range("2016-01-01", "2023-04-07", tz="UTC")
rng = np.random.default_rng(734)
rows = []
for j, symbol in enumerate(symbols):
    values = 100 * np.exp(np.cumsum(rng.normal(
        .0002 + j * .000006, .005 + .0001 * j, len(dates))))
    for day, price in zip(dates, values, strict=True):
        rows.append(dict(timestamp=day, symbol=symbol, open=price * 1.001,
                         close=price, high=price * 1.01, low=price * .99,
                         volume=1_000_000., provider="futu",
                         price_adjustment="qfq", interval="1d"))
prices = pd.DataFrame(rows)
changed = prices.copy()
mask = changed.timestamp >= pd.Timestamp("2022-01-01", tz="UTC")
multipliers = changed.loc[mask, "symbol"].map({s: 5+j for j, s in enumerate(symbols)})
changed.loc[mask, ["open", "high", "low", "close"]] *= multipliers.to_numpy()[:, None]
for profile in profiles:
    left = run_profile(prices, profile["id"], start="2018-01-01", end="2023-04-07")
    right = run_profile(changed, profile["id"], start="2018-01-01", end="2023-04-07")
    assert left["status"] == right["status"] == "available"
    for key in ("metrics", "benchmark_metrics", "peer_metrics", "sessions"):
        assert left["splits"]["train"][key] == right["splits"]["train"][key]
    prefix = lambda r: [s for s in r["signals"] if s["trade_date"] < "2022-01-01"]
    assert prefix(left) == prefix(right)
```

## 四、明确保留的限制与未验证范围

- 当前固定股票名单不是历史逐日成分（非 PIT），存在静态名单和幸存者偏差；本次没有消除或隐去它。
- Futu QFQ 不保证等于含分红再投资的总回报，ETF/SHY 代理也不等于原研究的指数总回报和现金；不能据此宣称完整论文复现。
- 2018–2021、2022–2024、2025 起是已固定的时间分区；历史可能已被看过。固定参数和训练截止不自动创造真正未见的前瞻样本。
- 模型即使只收到 2021 年底前的统计，其预训练知识也可能包含后续历史；本次没有验证或清除这种知识。
- 同池等权对照用于识别池子与排序/择时的差异，并不保证同风险、同暴露；原指数对照也不能成为必须跑赢的验收目标。
- 本报告没有评估新真实研究的收益、统计显著性、交易容量、长期模拟效果或后续自动化运行；没有声称发现可交易 alpha。

## 五、审计时源码指纹

以下 SHA-256 在写本文档前读取，绑定本次工作树。后续若相关文件继续修改，应检查其差异是否影响本结论，而不是把旧指纹当作新版本证据。

```text
af9fe454b0d4ea8dcf798a9983c82734c27bf6a8d9c05d4a7138f2ecc8d1f8d5  backtest/models.py
acaf79d5dbdaea5acaccb48f915ae72aceac68ce92eb2f2d657a3dc8c15adcc8  backtest/engine.py
279c9d582fc117ccbf9745bcf715b83b3d3075b338b81a859f250fcd588617f1  backtest/metrics.py
da7cf3a96134eb920d307b6fe6e7d91f69d9e820304f08073abad7f76ef9a3d2  research/reference_backtests.py
60d63e23bf2ae334fa43246183601aca87a45cb70fe99e4d8930d68a4639874f  research/qlib_evaluation.py
b5f7a550cc31c8f2122eb7af32f4e13fc317e9bb5328cab6450d6ac7faa38c93  research/study_profiles.py
b5c45b617f170eea4127eb6f524d0930eadc42bbf35e50c494831edea2864980  research/profile_backtests.py
1dc7084e6a1dd53ce0070fae379971ecdd78b97206a9bc2ba4ab70b42eac9f2a  research/study_signal_diagnostics.py
f1d318e9b6dcd1428d4ca37ba03805e671e6fd50442d56c8c43d4e4ea8a00fee  research/strategy_study_service.py
861914f50d017e806cd9c5fcd7b18efd7a8038e28d1e8d6ce47ad6d63fbe8308  research/bounded_discovery.py
```

上述相对路径均以 `src/quant_system/` 为根。独立审计意见限于本文列出的反例和方法检查；未来研究成果仍需各自的真实证据。
