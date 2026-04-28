# Phase 7 执行文档

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

Phase 7 默认不需要 OpenAI API key。

## 生成候选因子

```powershell
quant-system agent propose-factor `
  --goal "low-vol momentum" `
  --universe SPY,QQQ `
  --output-dir data/agent_run
```

成功标志：

```text
candidate_id=<id> status=pending path=<...factor.py.candidate> metadata=<...metadata.json>
```

## 生成候选实验配置

```powershell
quant-system agent propose-experiment `
  --goal "test momentum and low volatility blend" `
  --universe SPY,QQQ `
  --output-dir data/agent_run
```

成功后会生成 `experiment_config.json` 候选文件。它可以被 `ExperimentConfig` 加载，但不会自动运行。

## 查看候选

```powershell
quant-system agent list-candidates --output-dir data/agent_run
```

输出包含：

- `candidate_id`
- `type`
- `status`
- `path`

## 人工 review

```powershell
quant-system agent review `
  --candidate-id <id> `
  --decision approve `
  --note "manual review passed" `
  --output-dir data/agent_run
```

approve 只生成 `approved.lock`。它不会注册因子，也不会触发 paper trading。

## 生成实验摘要

```powershell
quant-system agent summarize `
  --experiment-id <id> `
  --output-dir data/agent_run
```

如果本地找不到对应实验，会写出一份明确标注 `found=false` 的候选摘要。

## 因子泄漏检查清单

```powershell
quant-system agent audit-leakage `
  --factor-id momentum `
  --output-dir data/agent_run
```

输出是人工 review 用的 Markdown 清单。

## 使用 OpenAI 可选路径

默认不调用 OpenAI。如果显式使用：

```powershell
$env:QS_OPENAI_API_KEY="..."
quant-system agent propose-factor --goal "low-vol momentum" --llm openai
```

缺少 key 或 SDK 时，CLI 会直接报错，不会回退到不透明行为。

## 测试步骤

```powershell
conda activate ai-quant
python -m pytest tests/test_agent_phase7.py -q
python -m pytest --tb=short -q
ruff check .
```

## 常见报错排查

| 报错 | 处理 |
| --- | --- |
| `QS_OPENAI_API_KEY is required` | 不使用 OpenAI 时去掉 `--llm openai` |
| 找不到 candidate id | 先运行 `agent list-candidates --output-dir ...` 确认目录 |
| 生成了 `.candidate` 但不能 import | 这是预期行为；候选文件必须人工审查后才能改名接入 |

## 完成标志

- 候选文件写入 `agent/candidates/`。
- 审计日志写入 `agent/audit/`。
- 人工 review 只改变候选状态。
- 没有任何真实交易路径。
