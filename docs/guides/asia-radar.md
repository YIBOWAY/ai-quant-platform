# 亚洲雷达 `/asia-radar`

亚洲雷达是一个只读市场研究页。Phase 1 用 12 只美国上市 ETF 映射亚洲主要市场，
所有价格均来自本机 Futu OpenD 的真实 QFQ 日线；页面不会在 Futu 失败时回退到
sample、静态或演示曲线。

## 数据范围

固定标的是：`EWY EWT EWJ ASHR INDA EIDO EWH EWS THD EWM EWA EPHE`。
每个市场对象都显式携带：

- `provider=futu`
- ETF `symbol`
- `currency=USD`
- 该 ETF 的 `as_of`
- `adjustment=qfq`

“真实行情”描述价格来源，“ETF 代理”描述市场覆盖方式，两者不是互斥状态。指数
页签在 Phase 1 可以为空；龙头驱动页签只有 UI 壳，不展示虚构的个股权重或贡献。

## Phase 1.1 口径补强

- `timezone=America/New_York` 进入契约；所有市场对齐到**最新共享交易日**的 `as_of`，
  某一 ETF 缺当日 bar 即整体 503。
- 响应含 `provenance`：`futu` = 实时拉取，`futu_cache` = 命中本地 DuckDB bar 缓存
  （`data/futu_equity_bars.duckdb`，TTL 1 天）。缓存失败不会静默替代为 sample。
- 每个市场需要至少 64 根历史 bar；不足直接 503，不会给出“被截断的周/月收益”。
- 当日未完成的美股 bar 不计入；K 型序列只覆盖自然年。
- 详情 history 只保留最近 90 根作 sparkline，减小首屏体积。

## 指标口径

- 周收益：5 个交易日。
- 月收益：21 个交易日。
- YTD：当前自然年首个可用收盘至最新收盘。
- 波动：最近 63 个交易日收益率的年化已实现波动。
- 回撤：当前自然年的最大回撤。
- 动态 K 型：每个交易日按当日 YTD 收益重新排序，前三只 ETF 组成赢家篮子，
  后三只组成输家篮子；当前名单和历史分化序列都由数据计算，不使用固定名单。

Phase 1 不提供 PE、PB、ERP、行业拥挤度或个股风险名单。

## API

```text
GET /api/asia-radar/overview?provider=futu
```

该 API 强制 `provider=futu`。传入其他 provider 返回 400；OpenD 不可达、Futu
读取失败或 12 ETF 合同不完整时返回结构化 503，不返回替代曲线。API 只读，不写入
行情缓存、账户、订单或研究候选（Phase 1.1 起会复用只读的 `EquityBarCache` bar 缓存，
并以 `provenance=futu_cache` 明示，缓存本身永不回退为 sample）。

## 本地检查

先确认 OpenD 在 `127.0.0.1:11111`，再启动正常 Mac stack。浏览器打开
`/asia-radar` 或 `/zh/asia-radar`。也可以直接检查 API：

```bash
curl -fsS 'http://127.0.0.1:8765/api/asia-radar/overview?provider=futu'
```

若页面显示 provider 错误，应恢复 OpenD 后重试；不要用 sample 数据“修复”页面。

