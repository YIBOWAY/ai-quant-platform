# Phase 7 学习文档

## 当前阶段核心概念

Phase 7 的核心不是让 AI 自动交易，而是让 AI 帮助研究流程变快，同时把风险限制在候选区。

它遵守三条原则：

1. AI 可以提出想法。
2. AI 不能直接上线想法。
3. 所有 AI 动作都要可审计。

## Candidate Pool 是什么

Candidate Pool 可以理解成"候选箱"。

AI 生成的因子源码、实验配置、报告、检查清单都会先进入候选箱。它们只是文件，不会自动运行。

候选因子尤其要用 `.candidate` 后缀：

```text
factor.py.candidate
```

这样做的原因是：即使 AI 生成了危险代码，系统也不会 import 或执行它。

## Audit Log 是什么

Audit Log 是一份流水账，记录 Agent 做过什么。

例如一次因子提案会记录：

- 创建了什么 task
- 调用了哪些白名单工具
- 写出了哪个 candidate

这让之后复盘时可以知道候选产物从哪里来。

## Safety Gate 是什么

Safety Gate 是人工 review 的闸门。

默认情况下：

```text
allow_promotion(candidate_id) = False
```

只有候选目录里出现 `approved.lock`，它才会返回 True。

但是 Phase 7 即使 approve，也不会自动注册因子。这一步仍然必须人工完成。

## Stub LLM 是什么

Stub LLM 是一个不联网、不花钱、输出固定的假 LLM。

它的作用是：

- 让测试稳定。
- 让本地 smoke test 不依赖 API key。
- 让 Agent 工作流先验证工程链路。

真实 LLM 只能通过显式 `--llm openai` 选择。

## 常见错误

1. 把 AI 生成的候选因子直接复制进注册表。

   错。必须先人工审查、补测试、确认没有未来函数。

2. 把 approve 理解成上线。

   错。approve 只是候选通过人工初审。

3. 让 Agent 调 shell、改风险参数或访问 broker。

   错。Agent 工具箱只有固定白名单。

4. 用 AI 报告替代实验结果。

   错。AI 报告只是解释层，真实判断仍看数据和测试。

## 自检清单

- 候选因子是否只保存为 `.candidate`？
- metadata 里是否包含 `auto_promotion=false`？
- 是否有 audit jsonl？
- review 是否只写 `approved.lock` 或 `rejected.lock`？
- 是否没有任何 broker 或 live trading 调用？
- 新候选进入因子库前是否补了测试？

## 下一阶段如何复用

Phase 8 的 prediction market 模块也要沿用同样的边界：

- 先做只读数据模型和 scanner。
- 只输出 proposed trade 或 candidate。
- 不签名、不转账、不下单。
- 所有高级优化器先做接口，不直接接执行系统。
