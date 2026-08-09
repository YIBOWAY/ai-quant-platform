# Brief 日涨跌与三线收益交付记录

日期：2026-07-28

## 交付结果

- `/brief` 账户表格把原展示用的「权重」列替换为「日涨跌」，上涨为绿、下跌为红、
  零值或缺失为中性。公共账户 API 仍保留 `weight`，因此不影响持仓地图等消费者。
- 模拟盘收益支持近 7 日、近 1 月、近 3 月，并同时展示 Paper、SPY、QQQ。
- 三条曲线按共同可用交易日对齐并在区间首日归零；日期来自实际 Futu 日线，不用
  序号或伪造自然日。
- 显式保存 Brief 时归档 3 个月 master 数据和当前所选区间。历史页从已保存数据
  截取并重新归零，不随之后行情变化；3 个月 master 请求失败时阻止新归档，
  旧版 v1 snapshot 继续兼容读取。

## 数据与持久化边界

- 持仓日涨跌读取 Futu snapshot 的 `prev_close`，计算
  `last_price / previous_close - 1`。没有昨收就返回 `null`，不使用均价替代。
- Paper 日收益不是旧 equity-curve 的交易事件折线，也不是不规则的 PostgreSQL
  position audit snapshots。它从 repository factory 读取持久账户和 ledger，按日
  回放现金、成交、佣金及持仓，再用 Futu QFQ 日收盘价估值。
- SPY、QQQ 和持仓日线使用同一个严格 Futu read-only provider。某一基准失败只降级
  自己；Paper 在任一已持有交易日缺少当日价格时 fail closed，不前向填充，也不使用
  sample 或成本价补线。
- 行情日线以请求窗口和 provenance 为键写入
  `<data>/api_runs/_cache/futu_equity_bars.duckdb`，默认 24 小时 TTL。GET 不创建或
  修改账户；这里唯一允许的写入是行情缓存。
- API contract：
  `GET /api/paper/account/performance?range=7d|1m|3m&granularity=1d&benchmarks=SPY,QQQ`。

## 失败与兼容语义

- 返回 `requested_start/end`、`actual_start/end` 和 `coverage_complete`，账户在
  窗口中途建立时标记 `partial`，不伪装完整三个月历史。
- 每条 series 独立返回 `available`、`partial` 或 `unavailable`，并携带
  `source`、`as_of`、`error_code`。
- Brief `schema_version` 仍为 `brief_snapshot_v1`；新增字段均为可选或可空，旧归档
  不需要迁移。
- 本交付没有 scheduler、数据库 migration、真实交易接口、订单逻辑或 sample
  fallback。
- 当前没有盘中入金/出金公共入口；若账本已有外部现金流，daily performance 会以
  事件前最近完成的收盘价做子期间分段并重置基数。未来若开放且要求盘中精确 TWR，
  仍需接入现金流时点行情。提前收市日当前保守等到纽约 16:00 后才视为完成。

## 验收范围

- Python：账户日涨跌、严格缓存窗口、自然月边界、账本回放、佣金、外部现金流中性、
  基准独立降级、缺价 fail closed、Brief 新旧归档兼容。
- Frontend：范围解析、三线图、颜色语义、3 个月 master 归档与历史截取。
- Playwright：`QS_FUTU_ENABLED=false`、隔离端口 8766/3002，复用已有严格行情缓存，
  验证 1440px 与 390px、范围切换、API series ID、页面无横向溢出及 Brief 保存
  失败关闭；测试过程不调用 live Futu。
- 当前本机 8765/3001 的既有运行进程未重启，避免影响 Hermes/用户正在使用的环境。
