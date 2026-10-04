# RD-Agent / Qlib 当前用途与扩展价值

> 2026-09-07 更新：参考回测、Qlib 滚动模型/因子增量、Grok 模拟复盘已实现并本地部署，见 [实际计算与部署收据](../receipts/2026-09-07-qlib-research-evaluation.md)。下文保留 09-06 的调研快照，“尚未接入”不能作为当前状态；本轮仍没有让 RD-Agent 完整研发循环接管账户或任意改写公式。

核查日期：2026-09-06。研究链路核查基线为 Platform `008e9973`；下文介绍生成环节来自本批源码工作区。本文记录代码接线和采用建议，不代表新增研究已运行，也不替代本批部署与真实调用收据。

## 结论

Qlib 已真实参与因子计算和回测，但其模型训练、时间分段和信号评价能力尚未接入当前双引擎链路。RD-Agent 的接入更窄：当前主要使用它的模型调用接口和成本统计，没有运行微软的完整研发循环。

这不意味着需要把两个开源项目全部装成另一套助手。对这个个人量化项目，最有价值的是让研究过程可读、用新数据检查策略、判断新因子的增量价值，以及持续解释已启用策略的表现。它们可以接入已有 Hermes、研究任务和模拟账户，不需要重复建立前台或交易运行时。

## 当前实际接线

固定版本见 [Dockerfile](../../docker/d34/Dockerfile)：RD-Agent `274e274d5dbb72cc2ea139d1a7c93d73ce9b1198`，Qlib `da920b7f954f48ab1bb64117c976710de198373e`。

| 环节 | 当前实际行为 | 代码证据 |
|---|---|---|
| 真实数据进入 Qlib | 将绑定身份的 Futu 行情快照转换为 Qlib 本地数据；不是使用微软示例数据替代本项目行情 | [qlib_adapter.py](../../src/quant_system/d34/qlib_adapter.py)，`build_qlib_provider` |
| 给定公式复现 | 编译给定公式，只做一次实验；此分支不调用 RD-Agent 模型，也不自动改写公式 | [research_driver.py](../../src/quant_system/d34/research_driver.py)，`execute_research_request` 的 `fixed_proposal`；[rdagent_qlib_runtime.py](../../src/quant_system/d34/rdagent_qlib_runtime.py)，`run_container_research` |
| 非固定公式研究 | 自写提议循环，通过 RD-Agent `APIBackend` 请求 JSON 公式；后续提议能读取先前实验结果；最多 3×3 次实验 | [rdagent_qlib_runtime.py](../../src/quant_system/d34/rdagent_qlib_runtime.py)，`RDAgentProposalProvider`、`RDAgentCostMeter` |
| 因子实现 | 将受支持的公式确定性转换为因子源码，不是调用 RD-Agent 的自由 Python 编程循环 | [research_driver.py](../../src/quant_system/d34/research_driver.py)，`render_factor_source` |
| Qlib 计算与回测 | `D.features` 计算公式；`TopkDropoutStrategy` 形成组合；下一交易日开盘执行，计入成本；输出收益序列、目标权重、Sharpe、年化收益、最大回撤和观察数 | [rdagent_qlib_runtime.py](../../src/quant_system/d34/rdagent_qlib_runtime.py)，`QlibExperimentRunner` |
| 实验记录与选择 | 保存成功、失败实验和 trial；非固定公式模式在同一研究窗口中按 Sharpe 选择最高者 | [research_driver.py](../../src/quant_system/d34/research_driver.py)，`history`、`TrialsLedger.append`、`selected = max(...)` |
| 第二引擎 | Platform 使用同一行情和 Qlib 目标权重独立回放，保存净值、订单、成交、持仓、归因与指标；随后比较两引擎 | [platform_replay.py](../../src/quant_system/d34/platform_replay.py)，`run_platform_replay`；[engine_comparison.py](../../src/quant_system/d34/engine_comparison.py)，`compare_engine_receipts` |

当前产品代码未调用 RD-Agent 的 `RDLoop`、`FactorRDLoop`、`CoSTEER` 或 `fin_quant`，也未在这条研究链路接入 Qlib 的 `DatasetH` 训练/验证/测试分段、`RollingGen` 或机器学习模型训练。微软的完整 RDLoop 包含假设、实验任务、编码、运行和反馈组件，范围明显大于当前接口用途。[固定版本 RDLoop 源码](https://github.com/microsoft/RD-Agent/blob/274e274d5dbb72cc2ea139d1a7c93d73ce9b1198/rdagent/components/workflow/rd_loop.py#L23)

## 双引擎通过证明什么

当前比较要求两引擎的数据快照、标的集合、交易日历和目标权重身份一致，并检查：

- 日收益序列相关性至少 `0.995`。
- 最终净值差不超过 `25 bp`。
- 单标的期末权重差不超过 `50 bp`。

标准来自 [engine_comparison.py](../../src/quant_system/d34/engine_comparison.py) 的 `ComparisonPolicy.initial`。它主要说明同一交易计划在两套执行计算中结果一致，有助于发现日期、成交、成本和记账语义差异。

它没有单独证明策略有预测能力。两引擎可以一致地计算出亏损，也可以一致地回放一个在历史区间中被过度挑选的策略。两次使用同一目标权重和同一历史区间，不等于两份独立的样本外证据。

项目已经有其他质量检查，并非只比较引擎：

- **DSR** 根据已记录的试验族和收益分布调整 Sharpe 的可信度，避免只看最终胜者。[trials.py](../../src/quant_system/research/trials.py)，`evaluate_candidate_dsr`
- **相关性检查** 比较候选与已启用策略的收益，识别高度相似的结果。[assistant_remote.py](../../src/quant_system/execution/assistant_remote.py)，`_max_hung_correlation`
- **成本敏感性** 使用已记录的换手和收益评价两倍成本，缺证据与未通过分别有明确结果。[assistant_remote.py](../../src/quant_system/execution/assistant_remote.py)，`_certify_cost_sensitivity`

这些检查不能代替未参与公式选择的新区间测试。当前非固定公式研究没有独立的训练、验证、测试分段，所以其最高 Sharpe 不能直接称作样本外表现。

### 对卡片指标的含义

策略模板、单个因子和一次具体研究不是同一个对象。只有绑定数据、参数、日期与运行结果后，收益和 Sharpe 才有明确含义。Qlib 和 Platform 都会产出回测指标；卡片空值可能是未运行、运行失败、未绑定对应收据或指标本身不可计算，不能仅凭空值断言引擎没有计算，也不能把另一策略或样本运行的指标拿来补齐。

## 本批已补上：基于源码的介绍

本批 [collection_catalog.py](../../src/quant_system/research/collection_catalog.py) 已实现介绍生成。输入包括实际源码、参数、实现状态、对应证据和说明；输出包含简介、计算逻辑、使用方式和限制。介绍保存源码与输入指纹、模型、推理强度和生成时间，避免源码改变后继续冒用旧介绍。

客户端使用 `grok-4.6`，通过共享 [RollupLlmClient](../../src/quant_system/brief/rollup_llm.py) 发送 `reasoning_effort=xhigh`。历史项目可通过显式生成命令补充；[research_cli.py](../../src/quant_system/d34/research_cli.py) 已在新研究返回 `candidate_ready` 后调用 `generate_completed_job_introduction`。介绍失败单独记录，不修改已经保存的研究或模拟启用结果。

这是项目自己的源码说明环节，不应称作“已经接入 RD-Agent 完整研发循环”。微软 Finance Data Copilot 的名称、描述、公式、变量与实验反馈机制可作为后续复盘结构的参考。[官方说明](https://rdagent.readthedocs.io/en/latest/scens/data_copilot_fin.html)

## 最值得的四个方向

以下优先级是采用建议，不是自动执行的新计划；除上述源码介绍外，其余扩展未在本次实施。

| 优先级 | 用户能得到什么 | 适合借鉴的机制与落点 |
|---|---|---|
| 1：当前说明继续完善 | 知道一个策略怎样计算、为何成功或失败、与论文规则有何差别 | 源码介绍已实现；实验完成后按真实结果生成复盘仍可扩展。借 RD-Agent 的假设与反馈结构，将复盘放到现有研究详情。给定公式原样复现，改进建议与原复现分开 |
| 2：优先补足的研究能力 | 看见未参与选择的新年份、新窗口是否仍有效，而非只有一个最高 Sharpe | 借 Qlib 时间分段、`RollingGen`、`SigAnaRecord` 和 `PortAnaRecord`，展示滚动样本外、IC/RankIC、成本后收益、基准对比与换手；结果回到现有回测产物 |
| 3：判断新因子的增量价值 | 知道加入新因子是否真的比原组合更好 | 在相同数据和分段下比较“原因子集”与“原因子集＋新因子”，先用简单线性模型或 LightGBM。之后才考虑在一个明确研究任务中借 RD-Agent 因子—模型联合优化 |
| 4：解释持续模拟的效果变化 | 知道已启用策略最近为何赚钱、亏钱或信号减弱 | 借 Qlib 预测更新、到期标签评价与滚动记录；接现有每日日程，由 Hermes 解释预测相关性、成本、换手和回撤变化，不重复建立账户或另启交易运行时 |

Qlib 的标准工作流本来涵盖数据处理、训练推断、信号评价和回测，并提供相应记录机制；因此扩展重点可以是研究质量，而不只是增加一个回测按钮。[Qlib 工作流](https://qlib.readthedocs.io/en/latest/component/workflow.html)

滚动时间分段与信号分析组件在本项目固定的 Qlib 提交中已经存在，但当前尚未调用：[RollingGen](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/workflow/task/gen.py#L132)、[SigAnaRecord / PortAnaRecord](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/workflow/record_temp.py#L272)。因子—模型联合优化和持续预测更新分别可参考 [RD-Agent Finance Quant Agent](https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html) 与 [Qlib Online Serving](https://qlib.readthedocs.io/en/latest/component/online.html)。这些是组件能力证据，不是它们在本项目获得收益的证明。

## 核查范围

本项完成了当前相关源码、固定版本上游源码与官方文档的只读核对；没有执行新研究、训练、回测、数据库修改或交易。没有把上游宣传收益、示例市场数据或演示成绩转写为本项目结果。新增源码介绍的实际生成数量与部署状态，以本批交付收据为准。
