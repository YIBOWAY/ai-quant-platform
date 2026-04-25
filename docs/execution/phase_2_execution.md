# Phase 2 执行文档

## 环境要求

- Python 3.11+
- 推荐使用 `ai-quant` 独立环境
- 依赖通过 `pyproject.toml` 管理
- 本阶段不需要真实 API key

## 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

如果是第一次创建环境：

```powershell
conda env create -f environment.yml
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

本阶段可以不改 `.env`。

如果需要自定义输出目录，可以设置：

```powershell
$env:QS_DATA_DIR="data"
$env:QS_REPORTS_DIR="reports"
```

## 启动步骤

查看可用因子：

```powershell
python -m quant_system.cli factor list
```

生成样例因子报告：

```powershell
python -m quant_system.cli factor run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-02-15 --lookback 3 --output-dir data/phase2_sample
```

成功后会生成：

- `data/phase2_sample/factors/factor_results.parquet`
- `data/phase2_sample/factors/factor_signals.parquet`
- `data/phase2_sample/factors/factor_ic.parquet`
- `data/phase2_sample/factors/quantile_returns.parquet`
- `data/phase2_sample/reports/factor_report.md`
- `data/phase2_sample/quant_system.duckdb`

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

- `factor list` 能显示 `momentum`、`volatility`、`liquidity`
- `factor run-sample` 命令退出码为 0
- 输出目录里有因子结果、信号表、IC 结果、分组收益和报告
- `python -m pytest` 全部通过
- `ruff check .` 无报错

## 常见报错排查

### 没有生成因子结果

通常是日期范围太短或 `lookback` 太大。先用：

```powershell
--lookback 3
```

并把日期范围拉长到至少一个月。

### IC 为空

通常是标的太少。IC 需要横向比较，建议至少传 3 个 symbol。

### 找不到 quant_system

说明当前环境没有安装本项目。运行：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

### yfinance 说明

本阶段临时测试了 yfinance，可以取到 `SPY` 的小段历史数据。但它没有被加入正式依赖，也不作为主数据源。原因是它适合作为零额度兜底，不适合作为 Phase 1/2 主线数据源。yfinance 官方说明它不隶属于 Yahoo，且 Yahoo Finance API 更偏个人用途，因此后续如果加入，也应放在可选 provider，而不是主数据源。

参考：yfinance 项目主页 https://github.com/ranaroussi/yfinance
