# 市场横截面 `/market-cross-section`

市场横截面是一个只读市场研究页：对**预设标的篮子**做 YTD 热力图 + 排序表。
所有价格均来自本机 Futu OpenD 的真实 1d QFQ 日线；页面不会在 Futu 失败时回退到
sample、静态或演示曲线。

与亚洲雷达的分工：亚洲雷达 `/asia-radar` 是固定 12 国 ETF 代理宇宙（跨国家观察）；
横截面是主题/板块篮子（自选维度）。两者共享数据通路与指标口径，不共享宇宙。
`data-explorer` 保持单标的 OHLCV 诊断面，不在其中嵌入热力图。

## 数据范围

预设篮子（Phase 1.5，无自选/持仓依赖、无写路径）：

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

不提供 PE、PB、ERP、行业拥挤度或个股风险名单。

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
`/market-cross-section` 或 `/zh/market-cross-section`。也可以直接检查 API：

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
