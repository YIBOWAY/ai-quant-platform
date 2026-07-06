# Phase 7 执行文档

> 历史文档提示（2026-07-03）：HQA D-19 已将因子源码生成职责收归
> `/Users/sunyibo/programs/Hermes-quant-agent`。新 Scene-B 流程不要走
> 平台 `--llm openai`；使用 `agent propose-factor --source-file <path>`。

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

## 历史 OpenAI 可选路径（不用于 HQA）

Phase 7 交付时曾保留平台侧 OpenAI client 作为显式可选路径。2026-07-03
之后，HQA Scene-B 不再使用这条路径；因子源码由 Hermes 会话生成，平台用
`agent propose-factor --source-file <path>` 接收确定性 artifact。保留本节只为
解释旧错误信息和历史交付边界。

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
| `OpenAI API key is required` | 命中了历史平台 LLM 路径；HQA 流程应改用 `--source-file` |
| 找不到 candidate id | 先运行 `agent list-candidates --output-dir ...` 确认目录 |
| 生成了 `.candidate` 但不能 import | 这是预期行为；候选文件必须人工审查后才能改名接入 |

## 完成标志

- 候选文件写入 `agent/candidates/`。
- 审计日志写入 `agent/audit/`。
- 人工 review 只改变候选状态。
- 没有任何真实交易路径。
