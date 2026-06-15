# Futu 行情数据提供方

## 功能说明

Futu 现已成为股票研究流程的主要美股实时数据提供方。

它支持：

- `AAPL -> US.AAPL`
- `NVDA -> US.NVDA`
- `MSFT -> US.MSFT`
- `SPY -> US.SPY`
- 日线及受支持的日内 K 线请求
- 为现有的因子、回测和模拟交易流水线提供归一化的 OHLCV 数据行

它是只读的。

## 不提供的功能

它不会：

- 解锁账户
- 创建交易上下文
- 下单
- 改单
- 撤单
- 处理私钥
- 启用实盘交易

## 提供方选择

支持的股票数据提供方：

- `futu`
- `sample`
- `tiingo`（作为回滚兼容方案）

前端研究页面使用以下默认值：

- 行情数据 (Market Data) 的初始加载遵循 `QS_DEFAULT_DATA_PROVIDER`。
- 若配置的默认提供方失败，行情数据会返回一个明确标注的 sample 回退结果。
- 若请求显式传入 `provider=sample|futu|tiingo`，后端会严格按该 provider
  处理：未知 provider，或显式请求但不可用的真实 provider，会返回
  `400 provider_unavailable`，不会静默替换为 sample。
- 因子实验室 (Factor Lab)、回测器 (Backtester) 和模拟交易 (Paper Trading) 的表单中默认使用 `futu`。

## 配置

| 名称 | 默认值 | 用途 |
|---|---:|---|
| `QS_FUTU_ENABLED` | `true` | 启用只读 Futu 提供方选择 |
| `QS_FUTU_HOST` | `127.0.0.1` | OpenD 主机 |
| `QS_FUTU_PORT` | `11111` | OpenD API 端口 |
| `QS_FUTU_MARKET` | `US` | 当前市场范围 |
| `QS_FUTU_REQUEST_TIMEOUT_SECONDS` | `15` | 请求超时 |
| `QS_FUTU_DEFAULT_KLINE_FREQ` | `1d` | 默认 K 线频率 |
| `QS_FUTU_CACHE_DIR` | `data/futu` | 本地 Futu 缓存目录 |
| `QS_FUTU_USE_CACHE` | `true` | 启用本地 Futu 期权 DuckDB 缓存 |

## API 示例

```powershell
curl "http://127.0.0.1:8765/api/market-data/history?ticker=SPY&start=2024-01-02&end=2024-01-12&freq=1d&provider=futu"
```

`freq=1d` 可走 `sample`、`tiingo` 或 `futu`。日内频率（例如 `1h`、`30m`、
`15m`、`5m`、`1m`）仅允许 `provider=futu`，并且 OpenD 不可用时不会回退到
sample 数据；底层 `SampleOHLCVProvider` 与 `TiingoEODProvider` 也会在收到非
`1d` interval 时直接拒绝。

预期结构：

```json
{
  "symbol": "SPY",
  "source": "futu",
  "frequency": "1d",
  "row_count": 9,
  "rows": [
    {
      "timestamp": "2024-01-02T00:00:00Z",
      "open": 459.515,
      "high": 460.984,
      "low": 457.889,
      "close": 459.991,
      "volume": 123007793
    }
  ]
}
```

## 手动验证

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

预期：

- `PASS read_only_quote_connectivity`
- `US.AAPL`、`US.NVDA`、`US.MSFT`、`US.SPY` 的股票 K 线数据行

## 已知限制

- OpenD 必须处于运行状态且已登录。
- 数据权限决定了可查询的内容。
- 日内历史数据取决于 Futu 的权限和 API 限制。
- 回退的 sample 提供方仍可用于离线测试，但只适用于未显式指定 provider
  的默认日线读取路径，或用户明确选择 `provider=sample` 的日线场景。
- `sample` 与 `tiingo` 股票 OHLCV provider 是日线 provider；非 `1d` interval
  必须走 Futu。
