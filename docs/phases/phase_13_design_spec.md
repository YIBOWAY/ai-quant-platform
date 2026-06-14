# Phase 13 设计规范 - 期权雷达 (Options Radar)

## 范围

Phase 13 新增一个只读的每日期权雷达，用于卖方风格 (seller-style) 的筛选。它会扫描
一个已提交入库的 `S&P 500 ∪ Nasdaq 100` 股票池，对 `sell_put` 与 `covered_call`
运行现有的单标的期权筛选器 (Options Screener)，在全局范围内对候选项进行排序，
将快照保存在本地，通过本地 API 暴露，并在前端 `/options-radar` 页面展示。

## 非目标

- 不下单。
- 不涉及 Futu 交易上下文 (trade context)。
- 不解锁账户。
- 不涉及钱包、签名、私钥或实盘交易。
- 不在运行时对股票池或财报数据进行网页抓取。
- 不保证候选项能够按所显示的价格成交。

## 数据流

```text
Committed universe CSV
        |
        v
OptionsUniverse.load()
        |
        v
RateLimitedFutuProvider or SampleOptionsProvider
        |
        v
run_options_screener() per ticker / strategy
        |
        v
IV history + earnings calendar + VIX regime penalty hook
        |
        v
OptionsRadarReport
        |
        v
RadarSnapshotStore
        |
        v
GET /api/options/daily-scan
        |
        v
/options-radar frontend table + CSV export
```

## 数据提供方切换

- `futu`：默认的生产研究数据提供方。仅通过现有的只读 Futu 提供方使用
  `OpenQuoteContext`。
- `sample`：用于测试、演示和 CI 的确定性离线数据提供方。

可使用 `QS_OPTIONS_RADAR_PROVIDER=sample` 进行离线运行。CLI 也接受
`--provider sample`。

## 存储

每日输出写入 `data/options_scans/` 目录下：

- `{YYYY-MM-DD}.jsonl`：每行一个候选项
- `{YYYY-MM-DD}_meta.json`：运行元数据与失败记录
- `iv_history/{ticker}.jsonl`：累积的 IV 样本

存储以 `(run_date, ticker, contract_symbol, strategy)` 为键保证幂等。

## 评分

全局评分为：

```text
rating weight + clipped APR score + 0.4 * IV Rank
- earnings-window penalty - wide-spread penalty + market-regime penalty
```

评级权重为 `Strong=100`、`Watch=30`、`Avoid=0`。

## 市场状态 (Market Regime)

本地项目 `E:\programs\APEXUSTech_Inter\quantplatform` 使用 VIX、VIX3M
以及市场趋势，将市场风险划分为 `Normal`、`Elevated` 和 `Panic`。
Phase 13 将该 VIX 分类逻辑移植为一个可复用、经过测试的模块。

2026-05-03 的手动 Futu 探测：

- `US.VIX`：返回 "unknown stock"
- `US.VIX3M`：返回 "unknown stock"
- `US.SPY`：返回历史 K 线数据

因此雷达保留了市场状态惩罚的挂钩 (hook)，但尚未接入运行时
VIX 数据。这样可以避免将 Yahoo Finance 混入每日运行时路径。

> **2026-05-03 更新：** 市场状态现已端到端接入。每日扫描会
> 读取 `data/options_universe/vix_history.csv`（通过
> `scripts/refresh_vix_history.py` 手动刷新，数据源为 `query1.finance.yahoo.com`），
> 计算 V5 双因子状态，并通过 `run_options_radar(market_regime=...)`
> 应用按策略区分的惩罚。实时设计详见
> `docs/architecture/phase_13_architecture.md#vix-data-source` 与
> `docs/learning/phase_13_learning.md#vix-regime`。

## 安全边界

所有 Phase 13 代码均为只读。它从不导入或调用 Futu 交易 API，
也不暴露任何能够提交、修改、签名或下单的路由。
