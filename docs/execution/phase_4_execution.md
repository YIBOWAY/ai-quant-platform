# Phase 4 执行文档

## 环境要求

- Python 3.11+
- 推荐使用 `ai-quant` 独立环境
- 本阶段不需要真实 API key
- 本阶段不会真实下单

## 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

本阶段可以直接使用 CLI 参数，也可以使用 JSON 配置文件。

默认仍然不启用任何实盘功能：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_KILL_SWITCH=true`

## 启动步骤

运行样例参数 sweep：

```powershell
python -m quant_system.cli experiment run-sample --symbol SPY --symbol AAPL --symbol QQQ --start 2024-01-02 --end 2024-03-15 --lookback 3 --lookback 5 --top-n 1 --top-n 2 --output-dir data/phase4_sample
```

成功后会生成：

- `data/phase4_sample/experiments/experiment_config.json`
- `data/phase4_sample/experiments/experiment_runs.parquet`
- `data/phase4_sample/experiments/walk_forward_folds.parquet`
- `data/phase4_sample/experiments/agent_summary.json`
- `data/phase4_sample/reports/experiment_comparison_report.md`
- `data/phase4_sample/quant_system.duckdb`

## JSON 配置示例

可以创建一个 JSON 文件，例如 `configs/phase4_experiment.json`：

```json
{
  "experiment_name": "phase4-json-example",
  "symbols": ["SPY", "AAPL", "QQQ"],
  "start": "2024-01-02",
  "end": "2024-04-15",
  "initial_cash": 100000,
  "commission_bps": 1,
  "slippage_bps": 5,
  "factor_blend": {
    "factors": [
      {"factor_id": "momentum", "weight": 1.0, "direction": "higher_is_better"},
      {"factor_id": "volatility", "weight": 0.5, "direction": "lower_is_better"},
      {"factor_id": "liquidity", "weight": 0.5, "direction": "higher_is_better"}
    ],
    "rebalance_every_n_bars": 2
  },
  "sweep": {
    "lookback": [3, 5],
    "top_n": [1, 2]
  },
  "walk_forward": {
    "enabled": true,
    "train_bars": 12,
    "validation_bars": 8,
    "step_bars": 8
  }
}
```

运行：

```powershell
python -m quant_system.cli experiment run-config --config configs/phase4_experiment.json --output-dir data/phase4_config_run
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

只运行 Phase 4 测试：

```powershell
python -m pytest tests/test_experiment_scoring.py tests/test_experiment_config_sweep.py tests/test_experiment_walk_forward.py tests/test_experiment_runner_cli.py
```

## 成功运行标志

- CLI 输出包含 `experiment_id`
- `experiment_runs.parquet` 中有多组 run
- `agent_summary.json` 可以打开，且写明不会自动上线
- JSON 配置能成功运行
- walk-forward 配置开启后能生成 fold 边界
- 测试和代码检查通过

## 常见报错排查

### 没有任何 run

检查 `sweep` 是否为空或配置格式是否正确。空 sweep 会生成一个默认 run。

### walk-forward 没有 fold

通常是日期范围太短，不能满足：

```text
train_bars + validation_bars <= 总可用交易日数量
```

可以缩小 `train_bars` 或延长日期范围。

### 因子 id 不存在

当前默认支持：

- `momentum`
- `volatility`
- `liquidity`

其他因子需要先在因子注册表中实现和注册。

## 验收标准

- 多因子标准化、方向配置和加权合成有测试
- 参数 sweep 有测试
- walk-forward 边界有测试
- CLI 能生成实验结果和报告
- 每个 run 都有配置、参数、结果、指标、时间戳
- AI Agent-readable summary 已生成
- 不包含真实交易、自动上线、复杂模型或 Polymarket solver
