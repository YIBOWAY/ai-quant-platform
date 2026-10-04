# PostgreSQL 必要测试名单迁移

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

本次修复的是验收名单与已退役产品不一致的问题，不通过添加空测试凑数，也不把数据库测试失败变成通过。

## 精确差异

2026-07-30 的 `d33913e0ffcd8a06a8ad051abf80d0e2eb786713` 首次设置最少 245 项。
在该提交的独立具名 checkout 中，仅执行 `pytest --collect-only -m pg`，确实收集到 245 个节点。
当前 `e08dba69767dd0b965624dd6c31f5933d51e57ab` 的显式 PG 文件扫描与全 tests 的 PG 收集均为 238 个，零发现遗漏。

实际变化为 **245 − 40 + 33 = 238**，不是七个测试无故失踪。

| 变化 | 文件 | 节点数 |
|---|---|---:|
| 退役 | `test_candidate_evidence_v3_integration.py` | −20 |
| 退役 | `test_paper_gate_authority.py` | −20 |
| 新增 | `test_candidate_paper_epoch_fence_postgres.py` | +16 |
| 新增 | `test_assistant_remote.py` | +9 |
| 新增 | `test_brief_rollups_migration.py` | +3 |
| 新增 | `test_api_brief_archive.py` | +2 |
| 新增 | `test_local_research_resource_postgres.py` | +2 |
| 新增 | `test_candidate_admission_authority.py` | +1 |

其余 205 个节点身份保留，没有其它节点重命名或参数数量减少。两组退役节点均由
`417be6d7bec1d05a3633cc4526861b86beb22734`（2026-08-23，Retire superseded research products）
删除；该提交同时退役旧 paper Gate/审批/研究产品代码与入口，但明确保留迁移和历史数据。
这里确认的是节点与产品退役关系，不宣称新增 33 项逐条替代了旧 40 项的每个断言。

原始收集和逐节点差异保留在：

- `artifacts/full-e2e-2026-09-15/backend/pg-population-audit/baseline-d33913e0.{json,log}`
- `artifacts/full-e2e-2026-09-15/backend/pg-population-audit/current-{explicit,all}.{json,log}`
- `artifacts/full-e2e-2026-09-15/backend/pg-population-audit/difference.json`

本过程只收集测试，不执行测试函数或启动数据库。临时收集目录清理，历史 commit 仍在 Git 中。

## 新合同

`src/quant_system/ops/postgres_population.py` 固定保存：当前必要的 238 个 JUnit 规范节点 ID、
退役的 40 个 ID、新增的 33 个 ID，以及各历史提交。名单不在运行时从当前 collect 或通过结果生成。
当前必要集合与本次 canonical PG JUnit 的全部 238 个节点完全相等，**包含本次尚待修复验证的三个失败节点**。

按 `canonical_json_bytes(sorted(required_nodes))` 计算的集合 SHA-256：

`e784afa48b0b9e23bcdf49fcfd63ddd290759b1307b600021cdd08a2960dfa0d`

新门要求：

1. 必要名单非空、没有重复 ID。
2. 每一个必要节点必须实际出现；即使总数足够，增加无关测试也不能代替缺失的必要节点。
3. 允许新增测试，但所有实际执行节点仍须零失败、错误、跳过、预期失败和意外通过。
4. 数字下限由固定必要名单长度计算，不再使用已经包含退役产品的旧总数。
5. 原五个 dispatch 测试另按五个精确 JUnit 节点检查，不接受其它五项替代。

每批在执行前保存不可覆盖的 `.required.json`，执行后仍保留 JUnit 与实际 `.nodes.json`；
收据包含必要名单摘要、缺失节点和额外节点。原 PG 文件全发现、覆盖范围检查、备份恢复、
全局角色清理及数据库/容器清理门保持不变。`QS_TEST_HQA_ROOT` 的单路径验证、转发和记录也保持。

## 验证边界

纯合同测试 **14 项通过**，包含整份 238 节点的 JUnit 编解码、额外节点、缺失但总数够、
重复名单、失败/错误/skip/xfail/xpass 拒绝，以及已有环境验证。这里的 JUnit 是明确的隔离测试输入，
不构成真实 PG 执行收据。Ruff 与 diff 检查通过。

本分工没有提交或重跑真实 PostgreSQL。完整 PG 套件需在根代理审查、提交后，由原正式隔离脚本重新执行。
