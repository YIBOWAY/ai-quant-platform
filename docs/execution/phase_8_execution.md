# Phase 8 执行文档

## 环境要求

- Windows PowerShell
- conda 环境：`ai-quant`
- Python 3.11+
- 已安装项目开发依赖

## 安装步骤

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

如果以后要测试 `LPStub`：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[prediction_market]"
```

当前默认流程不需要 scipy。

## 扫描样例市场

```powershell
quant-system prediction-market scan-sample --output-dir data/pm_sample
```

成功标志：

```text
candidates=<n> report=data\pm_sample\prediction_market\reports\prediction_market_report.md
```

## 生成 dry proposal

```powershell
quant-system prediction-market dry-arbitrage `
  --output-dir data/pm_sample `
  --optimizer greedy
```

成功后会写入：

```text
data/pm_sample/prediction_market/proposals/*.json
```

不会写入：

```text
orders/
fills/
token_transfers/
```

## 体检

```powershell
quant-system prediction-market doctor
```

关键输出：

```text
live_api_disabled=yes
orders_disabled=yes
signing_disabled=yes
```

## 测试步骤

```powershell
conda activate ai-quant
python -m pytest tests/test_prediction_market_phase8.py -q
python -m pytest --tb=short -q
ruff check .
```

## 常见报错排查

| 报错 | 处理 |
| --- | --- |
| `Polymarket live integration is intentionally not wired` | 正常；Phase 8 不接 live |
| `Install quant-system[prediction_market] to use LPStub` | 需要可选 scipy；默认 greedy 不需要 |
| 没有真实套利结果 | 正常；sample provider 是确定性假数据 |

## 完成标志

- 能扫描 sample market。
- 能输出 dry proposal。
- 没有真实订单、签名、转账或 live API 调用。
