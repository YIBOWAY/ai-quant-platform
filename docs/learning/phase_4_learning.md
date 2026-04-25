# Phase 4 学习文档

## 当前阶段核心概念

Phase 4 的目标是把“单次回测”升级成“可复现的实验”。

本阶段关注的问题是：

- 多个因子如何统一到一个 score？
- 不同因子的方向如何处理？
- 不同参数组合如何批量运行？
- 每次实验的配置、结果和时间戳如何保存？
- 如何用 walk-forward 明确训练区间和验证区间？
- 后续 AI Agent 如何读取实验结果并总结？

本阶段仍然不做真实交易，也不会自动选择策略上线。

## 从零解释知识点

### 多因子标准化

不同因子的数值范围不同。动量可能是百分比，流动性可能是成交额，波动率又是另一个尺度。

标准化会在同一个时间点，把同一个因子的横截面值转换成可比较的数值。

本阶段使用的是按 `signal_ts` 的横截面标准化，不会使用未来数据。

### 因子方向

有些因子越大越好，例如动量。

有些因子越小越好，例如波动率。

所以配置里需要写清楚：

- `higher_is_better`
- `lower_is_better`

方向处理后，所有因子都能统一成“分数越高越偏多”。

### 因子加权合成

每个因子可以配置权重。

例如：

- momentum：1.0
- volatility：0.5
- liquidity：0.5

系统会把标准化后的因子按权重合成一个总 score。

### 参数 sweep

参数 sweep 会自动尝试多组参数。

例如：

- `lookback = [3, 5]`
- `top_n = [1, 2]`

这会生成 4 次实验运行：

- lookback 3, top_n 1
- lookback 3, top_n 2
- lookback 5, top_n 1
- lookback 5, top_n 2

### walk-forward

walk-forward 是一种滚动验证方式。

它会明确记录：

- train_start
- train_end
- validation_start
- validation_end

本阶段没有复杂模型训练，所以 train 区间主要用于提供过去历史和明确边界。系统只在 validation 区间评估结果。

## 代码和概念如何对应

- `src/quant_system/experiments/models.py`：实验配置、因子权重、walk-forward 配置、实验结果模型。
- `src/quant_system/experiments/config.py`：读取 JSON 配置，生成样例配置。
- `src/quant_system/experiments/scoring.py`：多因子标准化、方向处理、加权合成。
- `src/quant_system/experiments/sweep.py`：展开参数组合。
- `src/quant_system/experiments/walk_forward.py`：生成滚动验证区间。
- `src/quant_system/experiments/runner.py`：运行实验、调用因子和回测。
- `src/quant_system/experiments/storage.py`：保存配置、结果、folds 和 AI 摘要。
- `src/quant_system/experiments/reporting.py`：生成实验对比报告。
- `src/quant_system/cli.py`：提供 `experiment run-sample` 和 `experiment run-config`。

## 常见错误

1. 把全样本统计量用于标准化。

   本阶段不会这样做。标准化只在同一个 `signal_ts` 的横截面上进行。

2. 忘记因子方向。

   波动率这类因子通常是越低越好。如果不反向，会把风险高的标的打高分。

3. 只保存最终收益，不保存配置。

   本阶段每次实验都会保存 config、参数、metrics、时间戳。

4. walk-forward 区间重叠混乱。

   本阶段每个 fold 都明确保存 train 和 validation 边界。

5. AI Agent 直接选择策略上线。

   当前 AI 摘要只用于辅助研究，不用于自动上线。

## 自检清单

- 是否能运行 `experiment run-sample`？
- 是否生成 `experiment_config.json`？
- 是否生成 `experiment_runs.parquet`？
- 是否生成 `agent_summary.json`？
- 是否能用 JSON 配置运行 `experiment run-config`？
- walk-forward 是否生成 fold 边界？
- 每个 run 是否有 run_id、created_at、参数和指标？
- `python -m pytest` 是否通过？
- `ruff check .` 是否通过？

## 下一阶段如何复用

Phase 5 会复用 Phase 4 的实验结果，开始加入风控和模拟交易循环。

AI Agent 也可以读取 `agent_summary.json` 来总结实验表现、失败原因和下一轮候选参数。
