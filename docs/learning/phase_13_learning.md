# Phase 13 学习笔记

## 为什么需要 Options Radar

单标的的 Options Screener 回答的是："对于这一只股票，什么看起来比较合理？"
而 Options Radar 回答的是："在一个宽泛的标的池中，今天哪些合约的排名最高？"

## 为什么这不是交易建议

雷达仅通过报价、IV、流动性、DTE 以及简单的风险标签来筛选和排序合约。它并不了解你的账户、税务情况、被行权 (assignment) 风险承受能力或投资组合。它也无法下单。

## IV Rank 冷启动

IV Rank 需要每日 ATM IV 的历史数据。在某个标的累计至少 30 个样本之前，IV Rank 为 `null`，并对全局评分贡献零分。

## 财报日历

在本项目中，Futu OpenAPI 并未提供完整的财报日历。Phase 13 改为读取一份离线 CSV。刷新脚本是手动执行的，从而让运行时扫描保持确定性。

## VIX Regime

Futu 并未暴露 CBOE 指数（`US.VIX` 返回 `unknown stock`），因此雷达通过
`quant_system.options.vix_data` 从 Yahoo Chart REST 端点
（`query1.finance.yahoo.com/v8/finance/chart/{ticker}`）获取 `^VIX` 和 `^VIX3M` 的每日收盘价。该实现参照了参考项目
`quantplatform` 的 `_fetch_yahoo_single`，并且是只读的。

获取到的序列由 `scripts/refresh_vix_history.py` 缓存为
`data/options_universe/vix_history.csv`（`date,vix,vix3m`）。CLI 在每次每日扫描开始时加载这份
CSV，调用 `compute_vix_regime`（V5 双因子：Density + 期限结构），并将得到的快照传入
`run_options_radar(market_regime=...)`。各策略的惩罚项
（`seller_regime_penalty`）会流入 `global_score`，并在每个候选合约上以
`market_regime` / `market_regime_penalty` 的形式呈现。

当该 CSV 缺失或为空时，雷达仍会运行，但会输出
`market_regime=Unknown reason=no_vix_history` 且不施加任何惩罚，而不是让扫描失败。

## 速率限制

全市场扫描在设计上可能较慢。这个限制是有意为之：扫描器应当尊重 Futu 的报价节奏，而不是追求低延迟。
