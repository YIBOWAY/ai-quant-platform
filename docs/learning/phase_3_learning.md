# Phase 3 学习文档

## 当前阶段核心概念

Phase 3 的目标是把 Phase 2 的信号放进一个最小但可信的回测流程里。

本阶段回答的问题是：

- 信号出来以后，什么时候能交易？
- 目标仓位如何变成订单？
- 订单用什么价格成交？
- 手续费和滑点如何扣掉？
- 交易后现金和持仓如何变化？
- 最终收益、回撤、换手率如何计算？

这仍然不是实盘系统，也不是 paper trading。它只是本地模拟。

## 从零解释知识点

### 信号

信号来自 Phase 2 的 `factor_signals`。它包含：

- `symbol`
- `signal_ts`
- `tradeable_ts`
- `score`

回测引擎只在 `tradeable_ts` 那一天处理信号。

### 策略和执行分离

策略只回答“想持有什么”。它不会下单。

执行层负责：

- 把目标权重变成订单
- 用指定价格成交
- 扣除手续费和滑点
- 更新现金和持仓

这样做可以避免把研究逻辑和交易逻辑混在一起。

### next bar open

本阶段默认成交假设是下一根 K 线开盘价。

如果因子在 `2024-01-02` 收盘后生成信号，它最早在 `2024-01-03` 开盘成交。

这避免了一个常见错误：用当天收盘价算信号，却假装自己还能用当天收盘价成交。

### 手续费和滑点

手续费按成交金额的 basis points 计算。

滑点会让买入价格略高、卖出价格略低。

例如开盘价 100，滑点 10 bps：

- 买入成交价是 100.10
- 卖出成交价是 99.90

### 资金曲线

资金曲线记录每天收盘后的账户状态：

- 现金
- 持仓市值
- 总权益
- 当日成交换手

### 交易记录

交易记录记录每一笔成交：

- 时间
- 标的
- 买卖方向
- 数量
- 成交价
- 成交金额
- 手续费
- 滑点

### 基础绩效指标

当前实现：

- total return：总收益
- annualized return：年化收益
- volatility：年化波动
- Sharpe：夏普
- max drawdown：最大回撤
- turnover：累计换手

这些指标只是初步评估，不能单独作为实盘依据。

## 代码和概念如何对应

- `src/quant_system/backtest/models.py`：订单、成交、配置、目标权重。
- `src/quant_system/backtest/strategy.py`：把 score 变成目标权重。
- `src/quant_system/backtest/order_generation.py`：把目标权重变成订单。
- `src/quant_system/backtest/broker.py`：模拟成交、滑点和手续费。
- `src/quant_system/backtest/portfolio.py`：维护现金和持仓。
- `src/quant_system/backtest/engine.py`：驱动整个回测循环。
- `src/quant_system/backtest/metrics.py`：计算绩效指标。
- `src/quant_system/backtest/storage.py`：保存回测结果。
- `src/quant_system/backtest/reporting.py`：生成回测报告。
- `src/quant_system/backtest/pipeline.py`：串联样例数据、因子、信号和回测。
- `src/quant_system/cli.py`：提供 `backtest run-sample` 命令。

## 常见错误

1. 同一根 K 线同时算信号和成交。

   本项目不这样做。信号在 `signal_ts`，成交在 `tradeable_ts`。

2. 忽略手续费和滑点。

   本阶段把手续费和滑点放进现金更新里。

3. 策略直接下单。

   当前策略只输出目标权重。订单由回测层生成。

4. 用收盘价成交但又用收盘价算信号。

   本阶段默认下一根 K 线开盘成交，避免这个问题。

5. 只看收益，不看回撤和换手。

   回测报告同时输出收益、波动、回撤、换手。

## 自检清单

- `backtest run-sample` 是否能生成报告？
- 成交记录里的第一笔交易是否发生在 `tradeable_ts`？
- 买入价格是否包含滑点？
- 手续费是否从现金中扣除？
- 持仓数量是否随成交变化？
- 资金曲线是否每天有记录？
- 测试是否覆盖订单、成交、现金、持仓和指标？
- `python -m pytest` 是否通过？
- `ruff check .` 是否通过？

## 下一阶段如何复用

Phase 4 会在这个回测引擎上增加：

- 多因子组合
- 参数搜索
- walk-forward
- 实验记录
- 结果对比

Phase 3 的输出会成为 Phase 4 的实验结果基础。
