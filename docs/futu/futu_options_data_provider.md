# 富途期权数据提供方 (Futu Options Data Provider)

## 适用范围

富途期权提供方是一个用于美股期权研究的只读数据适配器。

它支持：

- 期权到期日查询
- 期权链查询
- 用于卖方风格 DTE 窗口扫描的期权链区间查询
- 期权报价快照查询
- 标的股票快照查询
- 面向期权筛选器 (Options Screener) 的归一化字段

它不支持：

- 账户解锁
- 下单
- 改单
- 行权或指派操作
- 钱包或私钥处理
- 实盘交易

## OpenD 前置要求

在提供方查询期权之前，OpenD 必须处于运行并已登录状态。

默认连接配置：

| 设置项 | 默认值 |
|---|---:|
| `QS_FUTU_HOST` | `127.0.0.1` |
| `QS_FUTU_PORT` | `11111` |
| `QS_FUTU_OPTIONS_ENABLED` | `true` |

## 数据流

```text
Frontend Options Screener
  -> /api/options/*
  -> FutuMarketDataProvider
  -> local OpenD quote context
  -> Futu public market data
  -> normalized response
```

仅使用行情类 API，不创建任何交易上下文。

卖方期权筛选器不再需要手动选择到期日。它会读取富途的到期日，将这些日期限制在已配置的 DTE 窗口内，按日期区间请求期权链，并对报价快照进行分批处理，从而不超过富途单次请求的标的数量上限。

## 期权链完整性与过滤行为

富途的官方 API 将到期日发现与期权链获取分离：

- `get_option_expiration_date(code)` 返回标的可用的到期日。当目标是扫描所有挂牌到期日时，应首先使用它。
- `get_option_chain(code, start, end, option_type, option_cond_type, data_filter)`
  返回到期日落在所请求 `[start, end]` 窗口内的静态合约。
- 期权链调用本身**不会**返回实时的 bid / ask / IV / 希腊字母。本项目随后会对返回的期权代码调用 `get_market_snapshot` 来获取报价字段。

来自官方文档的重要行为：

| 情形 | 行为 |
|---|---|
| `start` 和 `end` 均已设置 | 返回在该明确日期区间内到期的合约。 |
| `start=None`，`end` 已设置 | `start` 默认为 `end` 之前 30 天。 |
| `start` 已设置，`end=None` | `end` 默认为 `start` 之后 30 天。 |
| 两者均省略 | 区间默认为当前日期至 30 天之后。 |
| 无 `option_type` | 同时返回看涨和看跌期权。 |
| 无 `option_cond_type` | 同时返回价内和价外合约。 |
| 无 `data_filter` | 不应用任何 IV / 希腊字母 / OI / 成交量过滤。 |

协议层文档说明，单次期权链请求最多覆盖约一个月的到期日。该接口没有 `page_req_key` 风格的分页机制。为覆盖更宽的 DTE 窗口，本项目将到期日切分为 <=30 天的区间，并反复调用 `get_option_chain`。换句话说：

- 单次 `get_option_chain` 调用返回所请求到期窗口内的可用行权价/合约，而非历史上挂牌过的所有到期日。
- 当所请求窗口内存在周度到期日时，它并不局限于月度到期日。
- 除非显式提供 `data_filter` 或 `option_cond_type`，否则它不会刻意局限于流动性强的行权价。本项目目前仅使用 `option_type`，将 `option_cond_type=ALL`，且不传入 `data_filter`，因此由富途负责返回该日期窗口内的所有可用合约。
- 如果某个挂牌合约没有可用的 bid / ask，或 OI / 成交量稀疏，当富途返回它时，它仍应出现在静态期权链中，但后续的快照步骤可能返回可空 (nullable) 或空的报价字段。

当前项目行为：

- `fetch_option_expirations()` 调用 `get_option_expiration_date`。
- `fetch_option_chain()` 调用一个精确的到期窗口。
- `fetch_option_chain_range()` 和 `fetch_option_quotes_range()` 会在调用富途之前，自动将较宽的窗口切分为 <=30 天的区间。这对买方助手和其他长 DTE 扫描很重要。
- `run_options_screener()` 可以将其已配置的 DTE 窗口直接传给提供方；由提供方负责安全切分。
- `fetch_option_quotes_range()` 会对相同的标的 / 到期窗口 / 期权类型保留一份短生命周期的进程内缓存。当同一页面被重新运行或刷新时，这可以避免立即再次触发富途每 30 秒 10 次调用的报价限制。
- 当 `QS_FUTU_USE_CACHE=true`（默认值）时，成功的期权报价窗口也会持久化到位于
  `data/futu/options_cache.duckdb` 的本地 DuckDB 缓存中。
  该缓存会被筛选器、雷达、买方助手和本地期权工具在后端重启后复用。
- 可用 `quant-system options prune-cache` 清理已过期的持久化快照。该命令默认
  dry-run，只报告候选数量；加 `--apply` 才会删除过期快照：

```powershell
quant-system options prune-cache
quant-system options prune-cache --apply
```

  如需针对非默认缓存文件验证，可传 `--cache-path <path>`。该命令只操作本地
  DuckDB 期权报价缓存，不连接券商、不下单、不触发 Futu 交易接口。

2026-05-04 在 OpenD 已登录状态下进行的本地只读检查：

- `US.SPY` 返回了从 2026-05-04 至 2028-12-15 的 35 个到期日。
- 第一个到期日返回了 318 份合约：159 份看涨、159 份看跌、159 个唯一行权价。
- 这印证了预期行为：到期日被单独发现；每次期权链调用返回所请求到期窗口的可用看涨 / 看跌行权价。

参考：

- 富途官方文档：`get_option_expiration_date` 说明应与 `get_option_chain` 配合使用，以获取完整的期权链。
- 富途官方文档：`get_option_chain` 记录了 30 天默认区间行为、可选过滤器以及仅返回静态合约的语义。

## 归一化期权字段

| 字段 | 含义 |
|---|---|
| `code` | 富途期权代码 |
| `underlying` | 归一化标的，例如 `US.AAPL` |
| `option_type` | 可用时为 `call` 或 `put` |
| `strike` | 行权价 |
| `expiry` | 到期日 |
| `bid` | 最优买价，可空 |
| `ask` | 最优卖价，可空 |
| `last` | 最新成交价，可空 |
| `volume` | 当前成交量，可空 |
| `open_interest` | 未平仓量，可空 |
| `implied_volatility` | 富途提供的 IV，可空 |
| `delta` | 富途提供的 delta，可空 |
| `gamma` | 富途提供的 gamma，可空 |
| `theta` | 富途提供的 theta，可空 |
| `vega` | 富途提供的 vega，可空 |
| `source` | 对本提供方始终为 `futu` |
| `fetched_at` | UTC 本地抓取时间戳 |

缺失字段以 `null` 返回。系统不会凭空编造 IV 或希腊字母。

## 权限说明（所需行情权限）

本项目所有者的运行权限为：

- 美股 **LV3** 数据
- 美股期权 **LV1** 数据

**重要 —— 富途美股期权权限模型：** 富途的美股期权行情数据等级**仅为 LV1**。美股期权没有单独的 "LV2" 升级；LV1 已经包含本筛选器 / 雷达所使用的全部字段（实时 bid / ask / mid、IV、delta / gamma / theta / vega、未平仓量、成交量）。早期内部草稿中提到的 "LV2 依赖" 是错误的，现已更正。

在 LV1 权限下进行的人工验证表明，OpenQuoteContext 会返回：

- 美股历史 K 线数据（LV3 股票权限覆盖盘口深度；仅 LV1 股票权限对本项目使用的 OHLCV 同样足够）
- `get_option_expiration_date` —— 期权到期日
- `get_option_chain` —— 含行权价的完整期权链
- 对期权代码调用 `get_market_snapshot` —— bid、ask、IV、delta、gamma、theta、vega、未平仓量、成交量、成交额、总市值

如果某个字段返回 null，**不要**假设需要升级到 LV2。请按以下顺序重新检查：

1. OpenD 进程是否正在运行并已登录？
2. 账户是否已实名认证？
3. 是否处于交易时段（美股期权报价在盘前/盘后稀疏）？
4. 合约本身是否有流动性（极深度价外的周度合约常常没有报价）？
5. 单接口限速（10 次调用 / 30 秒）是否已耗尽？

## 股票侧说明

筛选器的标的快照（价格、成交量、市值）从股票代码读取，而非期权代码。LV1 股票权限在此同样足够；LV2/LV3 仅增加盘口深度，而筛选器并不使用盘口深度。

## Phase 13 期权雷达说明

期权雷达使用相同的只读富途行情路径。它遵循富途文档规定的每 30 秒 10 次报价调用的节奏，并默认将快照批次保持在 200 个标的及以下。

2026-05-03 还对 `US.VIX` 和 `US.VIX3M` 测试了富途。本地 OpenD 会话对这两个代码均返回 "unknown stock"，而 `US.SPY` 的 K 线数据正常。由于富途不提供这些 CBOE 指数代码，期权雷达现在从由
`scripts/refresh_vix_history.py` 维护的本地 CSV 缓存加载 `^VIX` / `^VIX3M`。该刷新脚本优先尝试 Yahoo Chart，并在 Yahoo 返回 403 时回退到 Cboe 的公开每日 CSV。随后的每日扫描会计算 VIX 状态 (regime)，并将 `market_regime` / `market_regime_penalty` 写入每个雷达候选项。

富途 OpenAPI 条款不允许本项目将行情数据作为对外数据 API 进行再分发。雷达仅用于本地自用研究。

## 人工验证

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

预期输出包含：

- `PASS read_only_quote_connectivity`
- 期权到期日数量
- 期权链行数
- 期权快照字段样本

## API 示例

```powershell
curl "http://127.0.0.1:8765/api/options/expirations?ticker=AAPL&provider=futu"
```

```powershell
curl "http://127.0.0.1:8765/api/options/chain?ticker=AAPL&expiration=2026-05-04&provider=futu"
```

## 安全失败模式

| 情形 | 响应 |
|---|---|
| OpenD 未运行 | 前端可读的连接错误 |
| 无权限 | 权限错误，无堆栈回溯 |
| 无效 ticker | 校验错误 |
| 触发单接口限速 | 在一次只读重试后返回带类型的 `rate_limited` 错误 |
| 期权链字段缺失 | 可空字段 |
| 空期权链 | 带清晰来源元数据的空列表 |

## 交互式限速行为

OpenD 对每个报价接口大致强制执行每 30 秒 10 次调用。单次期权请求可能消耗多次调用，因为平台会获取标的快照、到期窗口、期权链、期权快照，有时还会获取股票历史数据用于 HV/趋势检查。

对于交互式页面，`FutuMarketDataProvider` 现在会检测常见的中英文限速消息，按已配置的重试间隔等待一次，然后重试同一只读请求。如果第二次尝试仍失败，API 会返回带类型的 `rate_limited` 响应，以便前端显示清晰的临时错误，而非原始的提供方消息。

对于诸如 `quant-system options daily-scan --top 100` 之类的大范围扫描，预期在富途节奏限制下运行会耗时较长。进行人工验证时，请先从较小的 `--top 10` 或 `--top 20` 开始。

## 安全边界

本提供方严格只读。它不创建任何交易上下文，也不暴露任何能够提交订单的 API 路径。
