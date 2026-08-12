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

## 本地指数页签（Phase 2 Slice 2A，2026-08-11 起）

市场详情的「指数」页签对部分市场展示**真实本地指数**，与 ETF 代理并排对照：

- 中国香港 → 恒生指数 `HK.800000`（HKD，Asia/Hong_Kong）；日本 → 日经225
  `JP..N225`（JPY，Asia/Tokyo）。两者均来自本机 Futu OpenD 真实日线（经
  `normalize_symbol(allow_local_markets=True)` opt-in 通道；通用 `/ohlcv` 与美股
  路径仍拒绝这两类代码）。
- 其余 10 个市场保持「待接入」空态并如实标注原因：A 股指数权限未开通
  （`permission_not_granted`，在 Futu 侧开通后可解锁沪深300）、Futu 不支持
  韩/台市场格式（`market_format_unsupported`）、其余无已验证通道
  （`no_verified_channel`）。**不会**用 ETF 代理曲线冒充指数。
- 指数只做展示对照：本地币种、本地交易日历（HK 16:00 / TYO 15:00 收盘纪律），
  独立 as_of；不与 ETF 代理（美元、美股日历）混合计算任何指标。指数失败只会
  让该市场页签显示不可用，不影响 12 ETF 主宇宙。响应 schema_version 为 1.2，
  `local_index` overlay 挂在每个 market 上。

## 龙头驱动页签（Phase 2 Slice 2B，2026-08-12 起）

市场详情的「龙头驱动」页签对部分市场展示**真实本地龙头篮子**
（`driver_basket` overlay，schema_version 1.3），与本地指数同一纪律：

- 中国香港 → 腾讯 `HK.00700`、阿里巴巴 `HK.09988`、汇丰 `HK.00005`，走已加白
  名单的 Futu 本地通道（HKD 仅展示，与 HK.800000 指数 overlay 同一口径）。
- 日本 → 丰田 `TM`、索尼 `SONY`、三菱日联 `MUFG`、本田 `HMC`；中国台湾 →
  台积电 `TSM`、联电 `UMC`。均为美股上市 ADR，经 Polygon grouped-daily
  （一次调用覆盖全部 ADR 一个交易日；稳态 1 次/天，free tier 已验证），bar
  以 `provider=polygon` / `adjustment=adjusted` 累积进同一个
  `EquityBarCache` 文件，与 Futu 键空间互不可见。冷启动每次读取最多回填
  5 个交易日；累积不足 20 根时龙头如实显示 `insufficient_history`，
  不虚构曲线。
- 韩国保持如实「待接入」：三星电子与 SK 海力士无流动性充足的美国上市凭证
  （`no_liquid_us_listing`，伦敦 GDR / 场外 SSNGY 等因 provenance 风险被拒），
  Futu 不支持 KS 格式，Twelve Data 免费档对 KR 市场 plan-gate。
- 其余市场：`permission_not_granted`（A 股龙头待 Futu 权限）或
  `no_verified_channel`。**不会**用 ETF 代理或合成篮子冒充龙头篮子。
- 篮子为非加权展示（`basket_note` 明示无 point-in-time 指数权重）：ADR 通道
  与 ETF 代理共享美元与美股日历，可并排对照；港股通道为 HKD 仅展示。
  龙头序列只在 ETF 指标全部算完后挂载（`attach_driver_basket_overlays`），
  永不进入 `build_asia_radar_overview`；任一通道失败只降级该市场的篮子，
  12 ETF 主路径与 local_index 页签不受影响。汇总路径（daily brief）完全跳过
  本通道。

