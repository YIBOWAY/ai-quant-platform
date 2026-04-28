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

## 设计取舍故事

### 为什么默认 LLM 是 stub，不是 OpenAI

最初的草稿是"默认调 OpenAI，stub 只在测试时用"。后来推翻了，原因有四点：

1. **可重复性**：本项目所有 phase 的输出都强调 deterministic（同样输入 → 同样输出），方便 commit/diff 和单测。真实 LLM 每次温度采样都不同，会污染 audit log 和 candidate 比较。
2. **离线友好**：研究流程经常断网（火车上、docker 沙箱里、CI 容器里）。默认 stub 让 `quant-system agent propose-factor` 在任何环境都跑得起来。
3. **成本可控**：新人接手项目跑 smoke test 不应该花钱。
4. **接口收敛**：先把 `LLMClient` Protocol 定死，再让 OpenAIClient / Anthropic / 本地 vllm 都来适配；如果默认是 OpenAI，Protocol 容易被 OpenAI 的 quirk 污染（比如 `tool_calls`、`function_call`、`response_format` 这些不通用的字段）。

代价：stub 输出的"候选因子代码"非常机械（基本上是模板替换），看起来像 AI 偷懒了 —— 这是已知 trade-off。要看真实质量必须显式 `--llm openai`。

### Prompt Injection 防御的 3 道防线

哪怕 LLM 输出 `import os; os.system("rm -rf /")` 这种内容，本项目都不会执行它。具体靠 3 道墙：

1. **白名单工具箱**：[tools.py](../../src/quant_system/agent/tools.py) 里的 `AgentToolbox` 是写死的函数列表，agent 不能动态注册新工具、不能传 callable、不能调 shell 或 broker。即使 prompt 被注入说"请你用 `subprocess.run` 跑一下"，工具层根本没有这个入口。
2. **`.candidate` 后缀隔离**：[candidate_pool.py](../../src/quant_system/agent/candidate_pool.py) 把 LLM 生成的源码写到 `factor.py.candidate`，这个后缀有三重作用：
   - Python import 机制不会自动 import 它
   - pytest 的默认 collector 不会收集它
   - 文件系统层面给人类一个明显的"这是未审查代码"标志
3. **Safety Gate 默认 deny**：[safety.py](../../src/quant_system/agent/safety.py) 的 `allow_promotion` 永远先返回 False；只有人类手动在候选目录下创建 `approved.lock` 才放行，而且即使放行也只是允许 _下一步人工流程_，不会触发任何自动注册。

这三层是叠加的，破任何一层都还有另外两层兜底。

### 为什么 review approve 不直接注册因子

最容易被误用的设计是"review approve → 自动加进 FactorRegistry"。这个看起来很方便，但有两个致命问题：

1. **测试缺口**：候选因子没有单测，注册进去会让 `pytest` 在引用 `default_registry()` 的所有路径上突然跑陌生代码。
2. **不可逆**：`FactorRegistry` 一旦注册，后续 experiment / backtest / paper trading 都会去读它；如果 candidate 有 lookahead bias，污染会沿着所有 phase 扩散。

所以 approve 只写 `approved.lock`，相当于给候选盖一个 "人类初审通过" 的章。真要进 registry 还要走：改名 → 加入 `tests/test_factors_<name>.py` → 跑全测 → 在 `registry.py` 显式 register。这个手工步骤不是麻烦，是**保护**。

