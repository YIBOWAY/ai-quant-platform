# Phase 2 学习文档

## 当前阶段核心概念

Phase 2 的目标是把 Phase 1 保存下来的价格和成交量数据，变成可以研究、比较和保存的因子结果。

这里的“因子”可以理解成一个打分规则。例如：

- 过去一段时间涨得多，动量更强。
- 过去一段时间波动小，风险可能更低。
- 过去一段时间成交额大，流动性更好。

本阶段只研究这些信号是否有统计意义，不做完整回测，也不下单。

## 从零解释知识点

### 因子值

因子值是某个时间点、某个标的的一组数字。比如 `SPY` 在 `2024-01-10` 的 3 日动量是 `0.02`。

### signal_ts 和 tradeable_ts

这是 Phase 2 最重要的防错设计。

- `signal_ts`：因子被计算出来的时间。
- `tradeable_ts`：下一根 K 线，也就是这个信号理论上最早可以被交易系统使用的时间。

这样做的原因是：如果用当天收盘价算出信号，就不能假装自己还能在同一天收盘前交易。

### lookback

`lookback` 是向过去看多少根 K 线。比如 20 日动量只看过去 20 个交易日，不允许看未来。

### IC 和 Rank IC

IC 用来衡量因子值和后续收益之间的关系。

- IC 看数字大小之间的线性关系。
- Rank IC 看排序关系。

如果一个因子长期有稳定的正向 Rank IC，说明它的排序可能有研究价值。但这不是交易结论，还需要 Phase 3 之后的回测验证。

### 分组收益

分组收益会把标的按因子值从低到高分桶，然后观察不同桶的后续收益。

如果高分组长期比低分组表现更好，说明因子可能有方向性。

## 代码和概念如何对应

- `src/quant_system/factors/base.py`：定义因子的共同结构，统一输出 `signal_ts` 和 `tradeable_ts`。
- `src/quant_system/factors/examples.py`：实现三个示例因子：动量、波动率、流动性。
- `src/quant_system/factors/registry.py`：管理可用因子，方便以后扩展。
- `src/quant_system/factors/pipeline.py`：把数据、因子计算、评分结果串起来。
- `src/quant_system/factors/evaluation.py`：计算 IC、Rank IC 和分组收益。
- `src/quant_system/factors/storage.py`：保存因子结果、信号表和分析结果。
- `src/quant_system/factors/reporting.py`：生成 Markdown 因子报告。
- `src/quant_system/cli.py`：提供 `factor list` 和 `factor run-sample` 命令。

## 常见错误

1. 把未来收益用于因子计算。

   因子计算只能使用 `signal_ts` 当时已经知道的数据。未来收益只能用于事后评估。

2. 忘记区分信号时间和可交易时间。

   本项目会把最后一根 K 线的信号排除掉，因为它没有下一根 K 线作为 `tradeable_ts`。

3. 样本太短导致没有因子结果。

   如果 `lookback=20`，但只给 10 个交易日，滚动窗口不够，报告会很空。

4. 标的太少导致 IC 没意义。

   IC 是横截面比较。只有一个标的时不能计算有效相关性。

5. 把 Phase 2 的报告当成策略收益。

   Phase 2 只做因子研究，不能代替回测。

## 自检清单

- 是否能运行 `python -m quant_system.cli factor list`？
- 是否能运行 `factor run-sample` 并生成报告？
- 报告里是否能看到 IC 和分组收益？
- 因子结果里是否同时有 `signal_ts` 和 `tradeable_ts`？
- 每个因子是否有测试？
- `python -m pytest` 是否全部通过？
- `ruff check .` 是否通过？

## 下一阶段如何复用

Phase 3 会使用 Phase 2 生成的信号表作为策略输入。

Phase 3 不应该让策略直接读取原始因子内部逻辑，而应该读取统一的输出：

- `symbol`
- `signal_ts`
- `tradeable_ts`
- `score`
- 单个因子列，例如 `momentum`、`volatility`、`liquidity`

这样以后增加新因子时，回测引擎不需要大改。
