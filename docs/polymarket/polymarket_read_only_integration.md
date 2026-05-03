# Polymarket 只读接入说明

## 1. 这份文档讲什么

这份文档说明平台是怎么接入 Polymarket 的，以及为什么它始终只做只读研究。

---

## 2. 当前支持的能力

- 读取公开市场列表
- 读取公开盘口
- 做当前快照扫描
- 采集历史快照
- 做时间序列 simulated replay

---

## 3. 明确不支持

- 真实下单
- 钱包连接
- 私钥处理
- 签名
- 链上交互
- 赎回

---

## 4. provider 模式

平台里有两种模式：

### sample

给离线测试和联调用的稳定样本。

### polymarket

显式选择后，才会打真实公开只读接口。

默认不会自动切到真实公开接口。

---

## 5. 真实接口的现实情况

公开接口可以用于只读研究，但它不保证一直稳定。

你应该把它理解成：

- 能用时，拿真实样本
- 不稳时，回到本地历史或 sample

所以平台的重点不是“永远在线拉最新”，而是“拿到后能保留下来，后面还能稳定回放”。

---

## 6. 与 Phase 12 的关系

Phase 11 解决的是：

- 只读接入
- 当前快照扫描
- 当前快照下的研究结果

Phase 12 继续往前做的是：

- 历史采集
- 历史回放
- 图表与报告

---

## 7. 建议阅读顺序

1. [polymarket_safety_boundaries.md](polymarket_safety_boundaries.md)
2. [polymarket_history_collection.md](polymarket_history_collection.md)
3. [polymarket_timeseries_backtest_learning.md](polymarket_timeseries_backtest_learning.md)
4. [polymarket_troubleshooting.md](polymarket_troubleshooting.md)
