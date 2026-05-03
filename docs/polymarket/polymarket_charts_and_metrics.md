# Polymarket 图表与指标说明

## 1. 当前主要图表

Phase 12 重点看四张图：

1. `daily_opportunities.png`
2. `edge_distribution.png`
3. `cumulative_estimated_profit.png`
4. `parameter_sensitivity.png`

---

## 2. 每张图分别表示什么

### Daily Opportunity Count

某一天被扫出的机会数。

### Edge Distribution Histogram

机会 edge 的分布情况。

### Cumulative Estimated Profit

在当前统一假设下，把每次 simulated 结果累计起来后的曲线。

### Parameter Sensitivity Heatmap

参数变化时，结果是否稳定。

---

## 3. 主要指标

回放结果里重点看这些字段：

- `market_count`
- `snapshot_count`
- `market_snapshot_count`
- `opportunity_count`
- `simulated_trade_count`
- `mean_edge_bps`
- `median_edge_bps`
- `max_edge_bps`
- `cumulative_estimated_profit`
- `max_drawdown`

---

## 4. 怎么解释这些指标

### opportunity_count

说明有多少次机会被扫描出来。

### simulated_trade_count

说明在当前阈值和资金限制下，有多少次机会真的进入了模拟成交。

### cumulative_estimated_profit

只能理解为“当前假设下的累计估计值”，不能当真实利润。

### max_drawdown

看这条 simulated 曲线有没有明显回撤。

---

## 5. 最重要的提醒

这些图和这些指标都只是研究输出，不是实盘成绩单。

必须一直记住三件事：

- 只读
- simulated
- no real fills
