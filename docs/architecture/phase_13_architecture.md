# 阶段 13 架构 - 期权雷达 (Options Radar)

## 模块

```text
src/quant_system/options/
  universe.py          committed S&P 500 + Nasdaq 100 universe loader
  rate_limiter.py      token-bucket pacing for read-only Futu calls
  iv_history.py        local IV history and IV Rank
  earnings_calendar.py offline earnings-date lookup
  market_regime.py     VIX regime classifier (V5 dual factor)
  vix_data.py          Yahoo Chart REST fetcher + CSV cache for ^VIX/^VIX3M
  radar.py             cross-ticker scanner and score calculation
  radar_storage.py     daily JSONL snapshot store
  sample_provider.py   deterministic offline provider

src/quant_system/api/routes/options_radar.py
  POST /api/options/refresh/universe
  POST /api/options/refresh/earnings
  POST /api/options/refresh/vix
  POST /api/options/daily-scan/run
  GET /api/options/daily-scan/dates
  GET /api/options/daily-scan

src/frontend/app/options-radar/page.tsx
  src/frontend/components/forms/OptionsRadarView.tsx
  daily scan viewer with filters, detail expansion, CSV export
```

## ASCII 架构图

```text
           +----------------------+
           | sp500_nasdaq100.csv  |
           +----------+-----------+
                      |
                      v
           +----------------------+
           | OptionsUniverse      |
           +----------+-----------+
                      |
                      v
+---------------------+----------------------+
| RateLimitedFutuProvider / SampleProvider   |
+---------------------+----------------------+
                      |
                      v
           +----------------------+
           | Existing Screener    |
           +----------+-----------+
                      |
      +---------------+----------------+
      | IV Rank | Earnings | VIX regime |
      +---------------+----------------+
            ^                   ^
            |                   |
  iv_history/*.csv    vix_history.csv (Yahoo Chart REST)
                      |
                      v
           +----------------------+
           | RadarSnapshotStore   |
           +----------+-----------+
                      |
        +-------------+-------------+
        v                           v
  Local API                    Frontend table
```

## 故障隔离

每个标的 (ticker) 都是独立扫描的。单个 OpenD、权限或无数据的失败会被记录在 `failed_tickers` 中，并且不会中断整个运行。

## 快照写入

雷达快照以运行日期为键。对同一日期再次运行扫描时，会用新的报告重写当天的 JSONL 和元数据文件，并在写入前合并掉重复的标的/合约/策略行。这样可以防止来自同一天较早运行的过期行被并入当前快照。

## 限速

Futu 行情接口默认按每 30 秒 10 次调用进行节流。市场快照的批量大小默认为 200，低于 Futu 文档中记载的 400 代码上限。

## VIX 数据源

VIX/VIX3M 收盘价通过普通的 HTTPS GET 从 `query1.finance.yahoo.com/v8/finance/chart` 获取。该抓取器为只读，且不使用任何 API key。错误会被记录并降级为一个空 Series，因此短暂的中断不会中止扫描；CLI 会降级为 `market_regime=Unknown`，并且不施加任何卖方惩罚。

市场状态 (regime) 在每次扫描时计算一次，并被序列化进每个候选项中，包括 `market_regime`（`Normal` / `Elevated` / `Panic` / `Unknown`）和 `market_regime_penalty`（按策略从 `global_score` 中扣减的分数）。前端 `RegimeBanner` 从 API 载荷中读取这些字段。

## 刷新数据源

雷达 UI 和 API 默认使用公开只读的刷新方式：

- universe：来自 GitHub 支持的来源的公开 S&P 500 + Nasdaq 100 快照
- earnings：Nasdaq 公开日历，同时仍明确支持 `yfinance`
- VIX：Yahoo Chart，然后回退到 Cboe 公开 CSV

`sample` 数据源仍可用于确定性的离线测试，并在 UI 中作为单独的本地样本选项展示。

## 只读边界

仅行情数据方法被封装。Yahoo VIX 抓取为匿名公开 GET。这里没有交易上下文，也没有任何路由或按钮能够下单。
