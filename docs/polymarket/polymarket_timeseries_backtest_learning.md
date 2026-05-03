# Polymarket 时间序列回放入门

## 1. 30 分钟上手

建议按下面顺序做：

1. 用 sample 采一轮历史
2. 跑一次时间序列回放
3. 打开报告
4. 看四张图

---

## 2. 最短命令

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

---

## 3. 会生成什么

- `result.json`
- `report.md`
- `daily_opportunities.png`
- `edge_distribution.png`
- `cumulative_estimated_profit.png`
- `parameter_sensitivity.png`

---

## 4. 这些图怎么看

### Daily Opportunity Count

某一天扫描出了多少个机会。

### Edge Distribution

机会的 edge 主要集中在哪些区间。

### Cumulative Estimated Profit

在当前假设下，把每次 simulated 结果累计起来，曲线怎么变化。

### Parameter Sensitivity

参数一变，结果变化有多大。

---

## 5. 结果怎么读

先看四件事：

1. 机会是不是太少
2. edge 是不是只集中在极少数点
3. 曲线是不是全靠个别时间点撑起来
4. 阈值稍微改一下，结果会不会明显变形

如果第 4 条很脆弱，就说明这套结果还不稳。

---

## 6. 最容易犯的误解

- 把 simulated trades 当成真实成交
- 看到累计曲线上升就急着下结论
- 忽略样本窗口本身很短
- 忽略 sample 和真实历史的区别

---

## 7. 下一步建议

最值得继续做的两件事：

1. 拉更长时间的真实历史
2. 增加更多 scanner 和参数组合再做对比
