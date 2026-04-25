# Phase 1 执行文档

## 环境要求

- 已完成 Phase 0
- 已创建并激活 `ai-quant` 环境
- 已安装项目依赖

激活环境：

```powershell
conda activate ai-quant
```

如果需要重新安装：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

真实 API key 保存在本地 `.env`，不要提交。

`.env.example` 中只保留空占位符：

```text
QS_TIINGO_API_TOKEN=""
QS_ALPHA_VANTAGE_API_KEY=""
QS_POLYGON_API_KEY=""
```

Phase 1 默认不自动联网。默认 provider 是：

```text
QS_DEFAULT_DATA_PROVIDER="sample"
```

## 启动步骤

生成样例 OHLCV 数据：

```powershell
quant-system data ingest-sample --symbol SPY --symbol AAPL --start 2024-01-02 --end 2024-01-05 --output-dir data/phase1_sample
```

使用 Tiingo 下载日线数据：

```powershell
quant-system data ingest-tiingo --symbol SPY --start 2024-01-02 --end 2024-01-05 --output-dir data/tiingo_sample
```

查看配置，并确认 key 不会明文显示：

```powershell
quant-system config show
```

## 测试步骤

运行全部测试：

```powershell
python -m pytest
```

运行代码检查：

```powershell
ruff check .
```

## 成功运行标志

样例数据命令成功时会输出类似：

```text
quality_passed=True rows=8 parquet=data/phase1_sample/parquet/ohlcv.parquet duckdb=data/phase1_sample/quant_system.duckdb report=data/phase1_sample/reports/data_quality_report.md
```

本地会生成：

- `parquet/ohlcv.parquet`
- `quant_system.duckdb`
- `reports/data_quality_report.md`

## 常见报错排查

### 1. Tiingo token 未配置

现象：

```text
QS_TIINGO_API_TOKEN is not configured
```

处理：

确认 `.env` 中存在：

```text
QS_TIINGO_API_TOKEN="..."
```

### 2. API 免费额度或网络失败

处理：

- 先用 `ingest-sample` 验证本地流程。
- 减少 symbol 和日期范围。
- 不要把联网 API 作为自动测试默认路径。

### 3. 找不到 Parquet 引擎

处理：

确认安装了 `pyarrow`：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pyarrow
```

### 4. DuckDB 文件被占用

处理：

- 关闭正在打开该 DuckDB 文件的程序。
- 换一个 `--output-dir`。

## 数据源选择建议

Phase 1 推荐主用 Tiingo EOD，原因是它更适合股票/ETF 日线历史缓存。

其他 key 的定位：

- Alpha Vantage：适合作为备用日线源，但免费额度较紧。
- Polygon：后续如果升级付费或需要更完整美股数据，可以作为更强数据源。
- Finnhub：适合后续补充公司数据、新闻、部分行情能力。
- Twelve Data：可作为备用跨资产行情源。
- NewsAPI：适合 Phase 7 之后做新闻/文本研究，不属于 Phase 1 OHLCV 主路径。
- X/Twitter：适合后续另类数据研究，不属于 Phase 1 OHLCV 主路径。

参考：

- Tiingo EOD API: https://api.tiingo.com/documentation/end-of-day
- Alpha Vantage docs: https://www.alphavantage.co/documentation/
- Finnhub stock candles: https://finnhub.io/docs/api/stock-candles
- Twelve Data time series: https://twelvedata.com/docs#time-series
- Polygon aggregates: https://polygon.io/docs/stocks/get_v2_aggs_ticker__stocksticker__range__multiplier___timespan___from___to
- NewsAPI docs: https://newsapi.org/docs

