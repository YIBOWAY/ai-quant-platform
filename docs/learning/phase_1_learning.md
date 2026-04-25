# Phase 1 学习文档

## 当前阶段核心概念

Phase 1 做数据层 MVP。数据层的目标不是“拿到一份数据就算完”，而是让数据可校验、可缓存、可重复读取。

后续因子、回测、模拟交易都依赖数据。如果数据有重复、缺失、未来信息或格式混乱，后面的结果会被污染。

## 从零解释知识点

### 1. OHLCV

OHLCV 是最基础的行情数据：

- O：open，开盘价
- H：high，最高价
- L：low，最低价
- C：close，收盘价
- V：volume，成交量

Phase 1 先处理股票/ETF 日线 OHLCV。

### 2. Canonical Schema

不同数据源字段名可能不同。系统内部必须统一格式，这就是 canonical schema。

本阶段统一字段包括：

- `symbol`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `provider`
- `interval`
- `event_ts`
- `knowledge_ts`

### 3. event_ts 和 knowledge_ts

这两个字段用来防止未来函数：

- `event_ts`：市场事件发生的时间
- `knowledge_ts`：系统能知道这条数据的时间

例如财报数据的 `event_ts` 可能是财报对应季度，`knowledge_ts` 是实际公告时间。行情日线里两者可以先保持简单，但字段必须提前存在。

### 4. 数据质量报告

数据质量报告回答几个问题：

- 数据是不是空的
- 是否缺字段
- 是否有重复日期
- OHLC 价格关系是否合理
- 成交量是否非负
- 是否有缺失值

Phase 1 把这些检查写成程序，避免人工肉眼检查。

### 5. Parquet 和 DuckDB

Parquet 是本地列式文件格式，适合保存行情数据。

DuckDB 是本地分析数据库，适合用 SQL 查询数据质量和样本。

本阶段同时保存两份：

- Parquet 用于后续 Python pipeline
- DuckDB 用于本地查询和报告

## 代码和概念如何对应

| 概念 | 文件 |
|---|---|
| 标准数据格式 | `src/quant_system/data/schema.py` |
| 数据质量检查 | `src/quant_system/data/validation.py` |
| 本地存储 | `src/quant_system/data/storage.py` |
| 样例数据源 | `src/quant_system/data/providers/sample.py` |
| CSV 数据源 | `src/quant_system/data/providers/csv.py` |
| Tiingo 数据源 | `src/quant_system/data/providers/tiingo.py` |
| 数据流水线 | `src/quant_system/data/pipeline.py` |
| CLI 命令 | `src/quant_system/cli.py` |

## 常见错误

1. **只看 close，不检查 OHLC 关系**

   如果 `high < low` 或 `close > high`，说明数据有问题。

2. **不检查重复数据**

   同一个 symbol 同一天重复，会让因子和回测结果失真。

3. **API key 写进代码**

   key 只能放 `.env`，不能放进 git。

4. **自动测试直接调用免费 API**

   免费 API 有额度限制。测试必须使用样例数据或 mock。

5. **把新闻和社交数据混进 Phase 1**

   NewsAPI 和 X/Twitter 以后可做另类数据，但不是 OHLCV MVP 的主路径。

## 自检清单

- 样例数据能生成
- 本地 CSV 能读取
- Tiingo provider 能把返回数据转成标准格式
- 数据质量检查能发现重复、价格错误和负成交量
- Parquet 能保存并重新读取
- DuckDB 能写入并统计行数
- API key 不会被 `config show` 明文输出

## 下一阶段如何复用

Phase 2 因子研究会复用 Phase 1 的数据输出：

- 从 Parquet 或 DuckDB 读取行情
- 用标准 OHLCV 字段计算因子
- 用数据质量报告判断是否允许进入因子计算
- 继续沿用 `event_ts` 和 `knowledge_ts` 防止未来函数

