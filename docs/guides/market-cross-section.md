# 美股风险与市场对照（路由：`/watch?pane=cross`）

## 当前页面（2026-09-20按源码核对）

导航名称为“市场研判 → 美股风险”。主区是市场风险观察，不再只是热力图：

- 分别查看“行情与波动”和“宏观与估值”。每项有当前值、可用历史对照、日期、来源、评分和权重。
- 系统实际完成的数据检查与Grok生成的解释分开显示。模型失败时保留已取得数据并显示失败原因，不把固定规则冒充AI回答。
- “更新数据与Grok研判”会明确启动刷新；普通GET只读取已保存结果，超过36小时标明过期。
- “查看价格、波动与板块对照”是可展开/收起的按钮式区域，保留原市场横截面对照工具。

主区读取 `GET /api/market-assessment?scope=us`。估值和宏观指标来自各自公开来源，
不能将下方Futu价格接口的来源、覆盖或可用状态泛化到整页。
评分是透明规则下的观察值，不是经过校准的崩盘概率，也不是已经执行的调仓指令。
历史数值和来源以页面本次保存快照为准；本次文档核对未触发新的行情或模型刷新。

## 保留的价格对照组件与接口

以下为原价格对照组件的实现说明，适用于下方展开区，不是整个当前页面的功能边界。

旧 `/market-cross-section`（含 `/en`、`/zh` 前缀）是保留查询参数的 301 兼容别名。

市场横截面对照组件是只读工具：对**预设标的组**做 YTD 热力图 + 排序表。
所有价格均来自本机 Futu OpenD 的真实 1d QFQ 日线；页面不会在 Futu 失败时回退到
sample、静态或演示曲线。

与亚洲雷达的分工：亚洲雷达 `/watch?pane=radar` 是固定 12 国 ETF 代理宇宙（跨国家观察）；
横截面对照是主题/板块分组（自选维度）。两者共享价格数据通路与指标口径，不共享标的范围。
`/watch?pane=quotes` 保持单标的 OHLCV 诊断面，不在其中嵌入热力图。

## 数据范围

预设分组（原Phase 1.5价格组件，无自选/持仓依赖、无写路径）：

- `ai_watch`：SPY QQQ SOXX IGV SMH NVDA MSFT GOOGL AMZN META AAPL TSLA
- `us_sectors`：SPY XLB XLE XLF XLI XLK XLP XLU XLV XLY XLC XLRE

另支持显式 `symbols=` 列表（白名单、≤16 只）。

每个标的对象都显式携带 `provider=futu`、`symbol`、`currency=USD`、
`timezone=America/New_York`、`as_of`、`adjustment=qfq` 与 `provenance`
（`futu` 实时 / `futu_cache` 本地 DuckDB bar 缓存，TTL 1 天）。

## 指标口径

与亚洲雷达完全一致：周收益 5 个交易日、月收益 21 个交易日、YTD 为当前自然年
首个可用收盘至最新收盘（不含元旦后首个交易日相对上年末的跳空）、波动为最近
63 个交易日年化已实现波动、回撤为当前自然年最大回撤；rank 按当前 YTD 动态计算。
所有标的对齐到最新**共享**交易日；任一标的缺当日 bar、历史不足 64 根或
provenance 非 futu 即整体 503。当日未完成的美股 bar 不计入。

此价格对照接口不提供 PE、PB、ERP、行业拥挤度或个股风险名单；当前页面主区的估值指标走独立接口。

## API

```text
GET /api/market-cross-section?basket=ai_watch|us_sectors
GET /api/market-cross-section?symbols=SPY,QQQ,…   # ≤16 只，白名单字符
```

该 API 强制 `provider=futu`（显式传其他 provider 返回 400）。OpenD 不可达、
Futu 读取失败或数据合同不完整时返回结构化 503，不返回替代曲线。API 只读，
不写账户、订单或研究候选。

## 本地检查

先确认 OpenD 在 `127.0.0.1:11111`，再启动正常 Mac stack。浏览器打开
`/watch?pane=cross` 或 `/zh/watch?pane=cross`。也可以直接检查 API：

```bash
curl -fsS 'http://127.0.0.1:8765/api/market-cross-section?basket=ai_watch'
```

若页面显示 provider 错误，应恢复 OpenD 后重试；不要用 sample 数据“修复”页面。

## 已知限制

- 自定义 symbol 只接受纯字母数字美股 ticker（`[A-Z0-9]{1,12}`）；`BRK.B`、
  `US.SPY` 等写法返回 400（与 Futu `normalize_symbol` 接受集对齐）。
- `basket` 与 `symbols` 只能二选一，同时传或空列表均返回 400。
- 2026-08-11 复审 findings（400/503 归类、首字符白名单、切篮子旧数据、ETF 角标、
  深链等 9 条）已全部修复并复验，记录见 HQA 接入 spec §2.8b。
