# 阶段 13 架构：期权推荐

本模块从真实 Futu 期权链生成本地卖方研究快照。它没有交易上下文、账户解锁或下单
路径。现役用户合同见[期权推荐指南](../guides/options-recommendations.md)。

## 组件

```text
src/quant_system/options/
  universe.py          策展 34 标的与隔离宽池加载
  data_refresh.py      财报、除息事件、VIX 和维护用 universe 刷新
  daily_task.py        输入刷新、进度状态、逐标的扫描和终态编排
  rate_limiter.py      Futu 只读调用节流
  iv_history.py        ATM30 Call+Put 双腿 IV history 与 IVR warming
  seller_score.py      报价/事件硬条件与物理预期赔付 EV
  radar.py             跨标的扫描、partial 结果和 Top-20 排序
  radar_storage.py     v3 generation 文件、哈希校验和原子 meta 指针
  scan_lock.py         定时与手动任务共用的跨进程锁

src/quant_system/api/routes/options_radar.py
  POST /api/options/daily-scan/run
  GET  /api/options/daily-scan/status
  GET  /api/options/daily-scan/dates
  GET  /api/options/daily-scan
  GET  /api/options/daily-scan/symbol/{ticker}
  POST /api/options/refresh/universe      # 维护接口，页面不调用
  POST /api/options/refresh/earnings
  POST /api/options/refresh/vix

src/frontend/components/forms/OptionsRadarView.tsx
  六态页面、立即更新、进度轮询、每秒耗时、筛选、紧凑表格、详情和 CSV 导出
```

## 数据流

```text
HQA 22:00 Hermes cron ─┐
                       ├─> Platform daily-task ─> refresh earnings/dividends/VIX
页面“立即更新” POST ────┘                         │
                                                 v
tracked curated_wheel.csv (exact 34) ─> RateLimitedFutuProvider
                                                 │
                     ┌───────────────────────────┼─────────────────────┐
                     v                           v                     v
                option chains              ATM30 IV history      event evidence
                     └───────────────────────────┼─────────────────────┘
                                                 v
                             hard gates + physical expected payout EV
                                                 v
                                 partial-capable global Top 20
                                                 v
                     {date}.{generation}.jsonl + atomic {date}_meta.json
                                                 v
                                      GET API -> /options-radar
```

## 调度与手动任务

HQA 拥有 macOS 调度，Platform 不在 FastAPI lifespan 内启动扫描：

- 现役 Hermes cron job `hqa-options-collect` 周一至周六北京时间 22:00 调用同一套
  `daily-task`；dormant `com.aiquant.options-collect` LaunchAgent 不得同时加载。
- 工作日正式输出固定为真实 Futu、跟踪的 exact 34 标的和正式目录。
- 周六先写正式 34 标的快照，再顺序运行 top-100 宽池；宽池写入独立 `wide`
  目录，但可复用正式真实 Futu IV history。
- `POST /api/options/daily-scan/run` 获得同一把锁后返回 `202 queued`，后台继续；
  已有任务时返回 `409 options_scan_already_running`。
- API 启动补跑已经退役。服务启动本身不刷新 universe、事件、VIX 或推荐快照。

正式 `daily-task` 必须使用 tracked curated universe 和 `top=34`。CLI `daily-scan`
只允许写非正式输出目录，用于有界诊断；sample 的所有输入、输出与 IV history 还必须
全部隔离。

## 输入证据

每次任务按顺序处理：

1. 加载 tracked 34 标的（正式路径不联网替换该名单）。
2. 刷新公开财报日历；策展标的的新结果按 ticker 合并进既有宽表。
3. 刷新公开除息日期和每股股息证据。
4. 刷新 VIX/VIX3M 本地历史。
5. 用 Futu 逐标的取得标的快照、到期日、期权链与报价。

页面「高级数据源」只提供财报和 VIX 的维护按钮，不提供 universe 刷新按钮。
`POST /api/options/refresh/universe` 仍是维护 API，不属于正式页面流程。
财报 fallback 与除息 yfinance 获取最多使用 6 个并发请求，写盘仍在汇总后单线程完成，
结果按 ticker 排序；单标的失败保留为缺失证据，不伪造事件。

## 推荐模型

报价、价差、OI、Delta、DTE、IV、目标 session 报价与无风险利率先作为硬条件；
非 ETF 还要求财报证据，备兑看涨要求除息证据。除息日落入到期窗口时，外在价值还
必须高于每股股息。

物理测度 EV 使用：

```text
sigma = min(IV, HV) when valid HV exists, otherwise IV
mu = risk_free_rate + equity_risk_premium
expected_value = extrinsic_premium - lognormal_physical_expected_payout
recommendation_score = annualized_expected_value * liquidity_factor
```

`QS_OPTIONS_RADAR_EQUITY_RISK_PREMIUM` 默认 `0.04`，可配置。只有正的
`expected_value` 进入推荐排序。IVR 少于 30 个正式 session 时是 `warming`，不作为
缺失硬门；非法 IVR 仍拒绝。

## Partial 与状态

每个 ticker 独立失败。成功标的继续形成候选，失败标的进入 `failed_tickers`，任务终态
为 `completed_with_warnings`。raw meta 的 `empty` 只说明 generation 候选行数为 0，
不证明 34 个标的完整成功；API 再结合覆盖率、freshness 与数据证据投影
`empty|unavailable`，两者不能脱离 task/coverage 混读。

`daily_task_status.json` 采用原子替换，记录 queued/running/terminal、步骤、目标 session、
进度、成功/失败覆盖率和错误。状态接口检测到遗留 running 但扫描锁已不存在时，会投影
为 interrupted failure，不把僵尸状态展示成仍在运行。

## v3 快照

`options_recommendations/v3` 每次写入新的 generation JSONL，再原子替换当天 meta
指针。当前评分模型名仍为 `seller_ev_liquidity_v1`。meta 固定记录数据文件名、
SHA-256、行数、策展 universe digest、覆盖率、`as_of`、risk-free rate、
`equity_risk_premium` 和 shortfall 原因。读取器不只校验结构和哈希，还会用当前
物理 EV、股息与评分公式逐行重算。版本字符串相同不代表旧 generation 一定兼容：
缺少当前必填字段或由旧公式生成的较早 v3 会读成 `unavailable`，不会继续展示。

同一 session 的新写入会替换 meta 指针；当前防止 `as_of` 回退，但尚未防止覆盖率
回退。因此较晚的 partial generation 可能替换较早的完整 generation。这个已知边界必须
在页面和验收中通过 scanned/failed 覆盖率显式呈现。

## 只读边界

Futu 仅使用行情上下文；公开事件/VIX 刷新仅写本地研究缓存。所有 API、CLI、定时任务
与页面都不能提交订单、解锁账户或修改 paper/live 账户。
