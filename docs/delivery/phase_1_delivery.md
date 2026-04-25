# Phase 1 交付清单

## 阶段目标说明

本阶段解决数据层 MVP：

- 能生成样例 OHLCV
- 能读取本地 CSV
- 能通过 Tiingo 下载日线 OHLCV
- 能统一数据格式
- 能做数据质量检查
- 能保存 Parquet 和 DuckDB
- 能重新加载
- 能生成数据质量报告

为什么重要：

后续因子、回测和模拟交易都依赖干净、可重复的数据。数据层不可靠，后续结果没有意义。

本阶段不做：

- 不做因子
- 不做策略
- 不做回测
- 不做真实交易
- 不做新闻和 X/Twitter 另类数据
- 不做 Polymarket

如何衔接下一阶段：

Phase 2 会直接读取 Phase 1 生成的 Parquet / DuckDB 数据，开始计算基础因子。

## 当前目录树

```text
.
├── .env.example
├── environment.yml
├── pyproject.toml
├── README.md
├── docs/
│   ├── architecture/
│   │   ├── phase_0_architecture.md
│   │   └── phase_1_architecture.md
│   ├── delivery/
│   │   ├── phase_0_delivery.md
│   │   └── phase_1_delivery.md
│   ├── execution/
│   │   ├── phase_0_execution.md
│   │   └── phase_1_execution.md
│   ├── learning/
│   │   ├── phase_0_learning.md
│   │   └── phase_1_learning.md
│   └── SYSTEM_DESIGN_RESEARCH.md
├── src/
│   └── quant_system/
│       ├── cli.py
│       ├── config/
│       │   └── settings.py
│       └── data/
│           ├── __init__.py
│           ├── pipeline.py
│           ├── schema.py
│           ├── storage.py
│           ├── validation.py
│           └── providers/
│               ├── __init__.py
│               ├── base.py
│               ├── csv.py
│               ├── sample.py
│               └── tiingo.py
└── tests/
    ├── test_data_pipeline_cli.py
    ├── test_data_schema.py
    ├── test_data_storage.py
    ├── test_data_tiingo_provider.py
    └── test_data_validation.py
```

## 完整代码文件

完整代码已按文件落盘，主要新增：

- `src/quant_system/data/schema.py`
- `src/quant_system/data/validation.py`
- `src/quant_system/data/storage.py`
- `src/quant_system/data/pipeline.py`
- `src/quant_system/data/providers/base.py`
- `src/quant_system/data/providers/sample.py`
- `src/quant_system/data/providers/csv.py`
- `src/quant_system/data/providers/tiingo.py`

同时修改：

- `src/quant_system/cli.py`
- `src/quant_system/config/settings.py`
- `.env.example`
- `README.md`

## 学习文档

见：

- `docs/learning/phase_1_learning.md`

## 执行文档

见：

- `docs/execution/phase_1_execution.md`

## 架构文档

见：

- `docs/architecture/phase_1_architecture.md`

## 测试与验收

运行：

```powershell
python -m pytest
ruff check .
quant-system data ingest-sample --symbol SPY --symbol AAPL --start 2024-01-02 --end 2024-01-05 --output-dir data/phase1_sample
quant-system config show
```

通过标准：

- 所有测试通过
- 代码检查通过
- 本地生成 Parquet、DuckDB、数据质量报告
- `config show` 不明文输出 API key
- Tiingo provider 有 mock 测试覆盖

## 数据源评估

Phase 1 主数据源建议：

1. 样例数据和本地 CSV：用于测试和开发，不消耗 API 额度。
2. Tiingo EOD：作为首选联网日线源。
3. Alpha Vantage：作为备用日线源，免费请求额度较紧。
4. Polygon：更适合后续升级数据源或付费后使用。
5. Finnhub / Twelve Data：后续作为补充或备用。
6. NewsAPI / X：后续另类数据阶段使用，不进入 Phase 1 主路径。

## 暂停点

Phase 1 完成后暂停，等待用户确认后再进入 Phase 2。
