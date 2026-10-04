# Phase 2 审查修复（源码，未部署）

2026-09-20；起点e23e39ed，按主人“有计划问题则修正后停止汇报”的要求执行。
主报告与计划在HQA：
[独立审查](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/audits/2026-09-20-plan-and-phase2-independent-review.md)、
[计划v3.1](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/plans/2026-09-14-alpha-research-reset.md)。

本批修复：

- gate_v2集中度使用原始equity_returns，缺原始值不回退active_returns；已有仓无可比日期/方差时不得通过；残差诊断也按共同日期对齐。
- 记分卡h日收益按252/h年化，日均除h，beta中性alpha一致；h=1不变。
- S&P成员构建的data build_id与validation_digest分离，绑定规则/阈值/来源/断言；A8标源内诊断，独立完整性未知，不回滚阈值、不重写旧产物。
- 新版受管采集脚本`python scripts/probe_tiingo_backfill.py --out <明确的新产物目录> ...`保留历史采集方法，修408/未知4xx/200错误/未知短正文被永久墓碑化；重复空体只记待复核，不永久退役。只有明确not-found可判缺码。原artifacts探针保留为历史，不建议再调用。没有运行真实采集。

10个相关测试文件首批141通过、0失败、0跳过；新增3例后相关性42与探针14另行通过，最终为144个唯一已覆盖节点（88未变节点沿用），未混加重复执行。Ruff与diff检查通过；日志/JUnit在HQA的
`evidence/2026-09-20-independent-plan-review/`。成员原料只在tmp重建，原成员表和255份价格未修改。
gate_v2/审核代理未启用；升级目标与其他仓分流仍是切换前待办。不合并T2.5分支、
不重启、不推远端、不触发正式研究或模拟周期。
