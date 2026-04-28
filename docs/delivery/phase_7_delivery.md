# Phase 7 交付记录

## 本阶段完成内容

Phase 7 已交付一个本地 AI 研究助手骨架，默认离线运行。

完成项：

- 新增 `quant_system.agent` 包。
- 新增候选池，把 Agent 产物写入 `agent/candidates/`。
- 新增审计日志，把 task、tool_call、candidate_written、review_recorded 写入 JSONL。
- 新增安全门，默认拒绝候选升级。
- 新增确定性 `StubLLMClient`。
- 新增可选 `OpenAIClient`，仅在显式 `--llm openai` 时尝试使用。
- 新增 Agent CLI 命令组。
- 新增 Phase 7 自动化测试。

## 交付的 CLI

```powershell
quant-system agent propose-factor --goal "low-vol momentum" --universe SPY,QQQ --output-dir data/agent_run
quant-system agent propose-experiment --goal "test factor blend" --output-dir data/agent_run
quant-system agent summarize --experiment-id <id> --output-dir data/agent_run
quant-system agent audit-leakage --factor-id momentum --output-dir data/agent_run
quant-system agent list-candidates --output-dir data/agent_run
quant-system agent review --candidate-id <id> --decision approve --note "reviewed" --output-dir data/agent_run
```

## 安全结果

- Agent 不连接 broker。
- Agent 不生成订单。
- Agent 不修改风险参数。
- Agent 不注册候选因子。
- 候选因子只保存为 `.candidate` 文件。
- 人工 approve 只生成 `approved.lock`，不触发任何自动上线动作。
- 默认 LLM 是离线 deterministic stub。

## 测试覆盖

新增测试覆盖：

- 未人工 approve 时，安全门拒绝升级。
- propose-factor 会写审计日志。
- 恶意候选源码不会被执行。
- metadata 永远包含 `auto_promotion=false`。
- approve 只生成锁文件，不把候选塞进默认因子注册表。
- stub LLM 同输入输出完全一致。
- propose-experiment 生成的 JSON 能被 `ExperimentConfig` 加载。

## 当前限制

- Agent 产出的候选代码没有自动静态扫描。
- `OpenAIClient` 是可选路径，默认测试不调用真实 API。
- 候选进入真实因子库仍需要人工改名、代码审查、测试和显式注册。
- result summary 当前是轻量 Markdown，不做复杂归因。

## 验收标准

本阶段完成的判断标准：

- `quant-system agent propose-factor` 可以写入候选文件。
- `quant-system agent list-candidates` 能看到 pending 状态。
- `quant-system agent review --decision approve` 只写 `approved.lock`。
- `python -m pytest` 全部通过。
- `ruff check .` 无错误。
