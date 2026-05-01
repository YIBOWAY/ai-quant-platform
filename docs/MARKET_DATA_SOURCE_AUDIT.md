# Market Data Source Audit — 为什么 SPY 还是假数据

> 用户问题原文："前端显示 SPY market data 仍然是假数据。.env 里已经配置了专业数据接口。"

## 1. 一句话结论

[.env](../.env) 中的 `QS_TIINGO_API_TOKEN`（以及 polygon/twelvedata/alpha_vantage/finnhub）**确实被 [Settings](../src/quant_system/config/settings.py) 加载到内存**，但 **Phase 9 API 路由层从来没有调用过任何一个真实 provider**。`/api/symbols` 和 `/api/ohlcv` 在源码层面只挂了两条路径：本地 parquet → fallback 到 [SampleOHLCVProvider](../src/quant_system/data/providers/sample.py)。**Tiingo provider 类已存在但未被任何路由实例化**。

## 2. 数据流转链路（实测）

```
[ Frontend Server Component ]
  src/frontend/app/data-explorer/page.tsx
        |
        v  fetch (Node 进程)
  src/frontend/lib/api.ts :: getOhlcv(symbol="SPY", start, end)
        |
        v  HTTP GET /api/ohlcv?symbol=SPY&start=2024-01-02&end=2024-01-12
[ Backend FastAPI ]
  src/quant_system/api/routes/data.py :: ohlcv()
        |
        +-- 检查 storage.parquet_path 是否存在 (data/parquet/...)
        |     |
        |     +-- 不存在 → frame=None, source="sample"
        |     +-- 存在    → frame=本地数据, source="local"
        |
        +-- 若 frame is None:
        |     SampleOHLCVProvider().fetch_ohlcv([symbol], start, end)
        |     ↑ 这里硬编码 close = 100 + i + 0.5（合成等差序列）
        |
        v  返回 rows
[ 前端再渲染 ]
  data-explorer/page.tsx 仅把最后 6 行塞进表格；
  主 chart **不**用这些数据，是 5 个硬编码 <div> bar
```

实测响应（2024-01-02 SPY）：

```json
{
  "symbol":"SPY",
  "source":"sample",
  "rows":[
    {"timestamp":"2024-01-02T00:00:00+00:00","open":100.0,"high":101.5,"low":99.0,"close":100.5,"volume":1000},
    {"timestamp":"2024-01-03T00:00:00+00:00","open":101.0,"high":102.5,"low":100.0,"close":101.5,"volume":1100},
    ...9 行...
  ]
}
```

`open=100,101,102,...` 完美等差，是 [sample.py L23-L33](../src/quant_system/data/providers/sample.py#L23) 生成的。**真实 SPY 在 2024-01-02 收盘 ≈ 472.65 USD，绝不会是 100.5。**

## 3. 假数据的 6 个具体来源（按严重度）

| # | 位置 | 类型 | 说明 |
| --- | --- | --- | --- |
| 1 | [api/routes/data.py L13](../src/quant_system/api/routes/data.py) `_DEFAULT_SAMPLE_SYMBOLS` | 后端硬编码 | 本地 parquet 不存在时返回 `["SPY","QQQ","IWM","TLT","GLD"]`，与 Tiingo 是否可用无关 |
| 2 | [api/routes/data.py L46](../src/quant_system/api/routes/data.py) `SampleOHLCVProvider().fetch_ohlcv(...)` | 后端 fallback | 实际 fallback 链路只有 sample，**没有走 Tiingo 这一步** |
| 3 | [api/routes/benchmark.py L15](../src/quant_system/api/routes/benchmark.py) | 后端硬接 sample | benchmark 路由直接 `SampleOHLCVProvider().fetch_ohlcv(...)`，连 parquet 都不查 |
| 4 | [data-explorer/page.tsx L88-L107](../src/frontend/app/data-explorer/page.tsx) | 前端硬编码 | 主 candle/volume chart 是 5 个固定高度的 `<div>`，从不读 `ohlcv.rows` |
| 5 | [data-explorer/page.tsx L113-L117](../src/frontend/app/data-explorer/page.tsx) | 前端硬编码 | Y 轴刻度 195/190/185 写死 |
| 6 | [data-explorer/page.tsx L168-L196](../src/frontend/app/data-explorer/page.tsx) | 前端硬编码 | Coverage 99.98% / Missing Days (MLK Day) / Spike 0 都是死字 |

## 4. 为什么 .env 的 token 不起作用

1. [Settings](../src/quant_system/config/settings.py) **能**加载 `QS_TIINGO_API_TOKEN`（验证：`curl /api/settings` 看到 `"tiingo_api_token":"**********"`，所以是被加载的）。
2. 但 **API 层没有任何代码 import [TiingoEODProvider](../src/quant_system/data/providers/tiingo.py)**：

   ```
   grep -r "TiingoEODProvider" src/quant_system/api/
   → 0 命中
   ```

3. `QS_DEFAULT_DATA_PROVIDER="sample"`（[.env L18](../.env)）也没有任何路由读取它。

简单说：**provider 选择逻辑根本没写**。Phase 1 把 Tiingo provider 实现了，Phase 9 把 API 写了，但**两者之间缺一根线**。

## 5. 修复方案（推荐 P0 实施）

### 5.1 后端最小改动

新增 [src/quant_system/data/provider_factory.py](../src/quant_system/data/provider_factory.py)（**唯一的新文件**）：

```python
def build_ohlcv_provider(settings: Settings, *, requested: str | None = None):
    """Pick an OHLCV provider based on settings + requested override."""
    name = (requested or settings.data.default_data_provider).lower()
    token = settings.api_keys.tiingo_api_token
    if name == "tiingo" and token:
        return TiingoEODProvider(api_token=token), "tiingo"
    if name == "tiingo" and not token:
        # 显式失败：用户要 tiingo 但没 token
        return SampleOHLCVProvider(), "sample (tiingo: missing token)"
    return SampleOHLCVProvider(), "sample"
```

修改 [data.py / benchmark.py](../src/quant_system/api/routes/) 把 `SampleOHLCVProvider()` 替换为 `build_ohlcv_provider(settings)`。

新增 query 参数：`/api/ohlcv?symbol=SPY&...&provider=tiingo` 强制指定。

[Settings.data](../src/quant_system/config/settings.py) 中 `default_data_provider="sample"` 改为读 env，默认仍 sample 但 [.env](../.env) 里建议改 `QS_DEFAULT_DATA_PROVIDER="tiingo"`（用户已有 token）。

### 5.2 前端最小改动

1. 任何返回 `source` 字段的页面顶部加 **DataSourceBadge**：

   - `tiingo` → 绿色 "Live · Tiingo"
   - `local`  → 蓝色 "Local Parquet"
   - `sample` → 黄色 "Sample (illustrative only)"
   - 含 `(failed: ...)` → 红色 + tooltip
2. 删除 [data-explorer/page.tsx](../src/frontend/app/data-explorer/page.tsx) 主图 5 个硬编码 bar，改用 `lightweight-charts` 渲染 `ohlcv.rows`。
3. 删除 Y 轴硬编码刻度。
4. 删除假 Coverage / Missing Days / Spike 三块（或接 `/api/data/quality`，先删除即可）。

### 5.3 验证

```powershell
# .env 设置 QS_DEFAULT_DATA_PROVIDER="tiingo"
curl "http://127.0.0.1:8765/api/ohlcv?symbol=SPY&start=2024-01-02&end=2024-01-12"
# 期望 source=tiingo，close 在 470 左右
```

## 6. 不应该做的事

- ❌ 不要把 Tiingo token 直接发给前端（前端永远只看 masked settings）。
- ❌ 不要在前端硬编码任何 K 线数据。
- ❌ 不要把"现实数据"和"sample 数据"在 UI 上混着画却不标 source。
- ❌ 不要默默 fallback 到 sample 而不告诉用户（用户会以为是真数据，做出错误研究决策）。
