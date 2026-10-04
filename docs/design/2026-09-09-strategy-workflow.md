# 研究结果到同规则模拟运行

本轮用户于2026-09-09明确要求修复研究页、核验800%收益、展示Top5排名、更新研究窗口并接通多因子流程。本文是本次实施设计，不替代HQA唯一现行计划。

## 采用的范围

- 统一策略描述与版本，不统一策略参数。各策略保留自己的因子、窗口、权重、股票池、日/周/月调仓、现金规则、仓位上限和最小交易额。
- 首批覆盖既有9种日线只做多研究、白名单量价公式、注册因子的明确组合。未知策略类型不退化成每日Top1；暂不增加盘中、期权或任意模型代码执行。
- 回测与模拟共享无副作用的决策内核；行情与成交是不同适配器。`targets=None`是保持，`targets={}`是清仓，必须分开。
- 新策略模拟仍沿既有候选、DSR0.95、相关0.7、成本检查和$10,000分配路径。原正式策略无新definition字段时不改变行为；不手工运行正式周期、不动实盘。
- 给定相同价格和持仓，新路径应生成相同分数、目标和开盘预算。手续费/滑点为1bp+5bp，不能用当时快照冒充开盘价。

## 研究与展示

- 固定研究总表、策略身份、实际排名/成交/现金核对可追溯到精确run/profile/date，不把候选池等同Top5。
- 最新数据用于最近四年研发，成熟标签才进入统计。历史已被查看，不冒充未见holdout；新定义冻结后才产生前瞻事实。旧探索及旧日期永久可复看。
- 现有Qlib滚动线性模型和因子增量保留；本轮不把一个APIBackend调用宣传成完整RDLoop。
- 多因子包括方向、预处理、覆盖/冗余、组合或学习器、股票选择、仓位和交易规则，固定权重只是其中一种。

## 实施与证据状态

- [x] 真实FileNotFoundError定位为后台PATH缺docker；固定解析与阶段恢复已实现，失败run已仅补Qlib诊断。
- [x] 800.10% / 806.38%已独立从价格、排名、现金、股数复算，报告见`docs/audits/2026-09-09-study-return-replication.md`。
- [x] 新总表、按日期Top5、策略身份和资金核对前端实现；真实浏览器预览已完成日期、策略、利润贡献切换。
- [x] 移除模型输入固定2021限制；真实Grok 4.6/xhigh使用2022-09-01至2026-09-08研发窗口，冻结三条新公式并保存全部结果。
- [x] 不可变StrategyDefinition与共享决策内核、真实快照一致性验证；独立反例审计四项发现修复后通过。
- [x] 研究库保存、验证和候选关联API，回测/固定研究/公式入口连接；Hermes新增同领域CLI/Skill。
- [ ] 新definition最终自动日程：信号、真实开盘取价/预算、候选/资金适配已实现，但`paper_cycle.py`明确禁止修改；无预计订单的开盘检查尚未接入，`execution_ready=false`阻止正式启用，待主人明确允许这一处修改。
- [x] 最新数据真实研究、回测与Qlib独立比较，保留未通过原因；组合新增组件IC/冗余/删一因子与7折真实Ridge滚动对照。
- [x] 主体本地提交、部署与真实API/页面保存/验证验收，保留原工作区改动；跨Python精确结果差异由网页固定3.11研究解释器解决，最终验证记录见本轮收据。

## 已调研的实现依据

Qlib v0.9.7 `RollingGen`、`DatasetH`、`CSRankNorm`、`LinearModel`及权重策略为可复用组件。RD-Agent的因子runner会合并新旧特征并训练模型，但默认反馈读取名为test的结果，外部不可把该反馈区间再称为未见样本。首批以明确、可复算规则和少量模型对照为主，不开启无限迭代。

来源：

- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/workflow/task/gen.py
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/data/dataset/processor.py
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/model/linear.py
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/strategy/signal_strategy.py
- https://github.com/microsoft/RD-Agent/blob/main/rdagent/components/workflow/rd_loop.py
- https://github.com/microsoft/RD-Agent/blob/main/rdagent/scenarios/qlib/developer/factor_runner.py
- https://github.com/microsoft/RD-Agent/blob/main/rdagent/scenarios/qlib/developer/feedback.py

这些来源说明组件能力，不是本项目已完成的证明；完成状态只依实现与本轮收据更新。
