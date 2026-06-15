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
  GET /api/options/daily-scan/status
  GET /api/options/daily-scan

src/quant_system/cli.py
  quant-system options daily-scan   manual scan over existing local inputs
  quant-system options daily-task   scheduled refresh + scan task

src/quant_system/api/server.py
  optional startup catch-up when QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true

src/frontend/app/options-radar/page.tsx
  src/frontend/components/forms/OptionsRadarView.tsx
  daily scan viewer with filters, scheduled-task status, detail expansion, CSV export
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

## 调度任务

`quant-system options daily-task` 是 Windows 任务计划程序的推荐入口。它按顺序：

1. 通过 `options/data_refresh.py` 刷新本地标的池 CSV。
2. 通过同一刷新模块刷新本地财报日历 CSV。
3. 刷新本地 VIX/VIX3M 历史 CSV。
4. 使用刷新后的路径调用 `run_options_radar`。
5. 写入每日 JSONL 快照、元数据和 `daily_task_status.json`。

`daily-scan` 保留为人工调试和只扫描已有输入缓存的命令。
`GET /api/options/daily-scan/status` 只读返回最近一次
`daily_task_status.json`；`/options-radar` 用它显示调度任务最近状态。
`daily-task`、CLI `daily-scan`、`POST /api/options/daily-scan/run` 和启动补跑共享
雷达输出目录下的 `options_radar_scan.lock`，避免多个进程同时写每日快照、IV history
或状态文件。

API 启动补跑默认关闭，避免服务启动时意外触发慢速 OpenD 扫描。设置
`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true` 后，FastAPI lifespan 会检查
`RadarSnapshotStore.latest_date()`；如果最近一个 UTC 工作日快照缺失，会在后台运行一次
`daily-scan` 等价扫描，并把 `source="startup_catchup"` 的 running /
completed / failed 状态写入 `daily_task_status.json`。周末启动会回退到上一个周五，
但仍未内置完整交易所节假日历。该补跑复用已有本地输入缓存，不替代 `daily-task`
的标的池、财报和 VIX 刷新流程。若扫描锁已被调度或手动扫描持有，启动补跑直接跳过，
不写入 running/failed 状态，也不覆盖现有 `daily_task_status.json`。

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
