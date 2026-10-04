# T2.3 并行阶段解读与切换评审（不自动切换）

> 本地路径说明（公开版）：文中未随本版提供的 `artifacts/`、`evidence/` 和运行目录是本地证据坐标或路径示例，原件未公开；不能把路径存在当作公开证据。详见[公开范围说明](../publication-20261004.md)。

- 日期：2026-09-18
- 分支：`feat/t23-gate-v2`（HEAD 起点 `4e4ae8ad`；其后为本修复批提交，逐条见 §9）
- 本批状态：**未切换**。`GATE_V2_AUTHORITATIVE = False`、`GATE_V2_ENABLED = False`。
  v1 常量、v1 代码、v1 落盘键一律零改动。

## 1. 交付物

- 新增包 `src/quant_system/research/gate_v2/`（纯函数 + 单一写面 `append_verdict_v2`）。
- 新增 `src/quant_system/research/fingerprint_grading.py`（观察层分级骨架，默认关，见另一评审文档）。
- 新增测试 `tests/test_gate_v2_*.py`：`4e4ae8ad` 时 **11 个**，本修复批新增 3 个
  （`test_gate_v2_sensitivity.py` / `test_gate_v2_switch.py` / `test_gate_v2_exports.py`），
  合计 14 个；另有 `tests/test_fingerprint_grading.py`。

## 2. 并行不变量（L0–L5）与验证

| 层 | 不变量 | 验证（测试） |
|---|---|---|
| L0 | 开关关闭时零 v2 字节 | `test_gate_v2_parallel.py::test_disabled_emission_writes_no_v2_bytes` |
| L1 | v2 只新增同级键 `gates_v2`；v1 键取值逐字节相等 | `test_gate_v2_parallel.py`（validation / book candidate / `_validation` 视图三处） |
| L2 | 不构造可写 `TrialsLedger`、不 append、`trials.jsonl` 不变 | `test_gate_v2_isolation.py`、`test_gate_v2_parallel.py::test_a_v2_run_leaves_trials_jsonl_untouched` |
| L3 | 不碰资金与激活；唯一 mutator 是 `append_verdict_v2` | `test_gate_v2_isolation.py`（AST callee/name 扫描） |
| L4 | `gate_v2`/`fingerprint_grading` 不进三处指纹表 | `test_gate_v2_fingerprint_neutral.py` |
| L5 | v1 消费方不 import `gate_v2`；`tier` 只写不驱动资金 | `test_gate_v2_isolation.py`、`test_gate_v2_tier.py::test_activation_paths_are_insensitive_to_tier` |

## 3. 判定口径要点（与 v1 的关系）

- **DSR**：数学一字不改（`trials.deflated_sharpe_ratio`）；只换输入——候选与每个族成员都用
  **主动收益**（`strategy - benchmark`，经 T2.2 `active_metrics` 的 `_daily_returns`/`_aligned`）
  以 `performance_from_daily_returns` 现算。接线恒等式（含 ddof 修正）
  `sharpe_period_v2 == IR/sqrt(252) * sqrt((n-1)/n)` 列在 `tests/test_gate_v2_dsr.py`。
- **族**：显式成员规则（仅 `platform_backtest` + digest 校验），修复 v1 `trial_sharpes()` 无 kind 过滤
  的族灌水缺陷；不可重算者进 `excluded[reason]` 并计入 `coverage_shortfall`。小族（<10）走保守固定阈值
  `DSR_V2_SMALL_FAMILY_PASS_MIN = 0.99`（**主路径**，因为绑定 validation 才写 `equity_curve_digest`）。
- **集中度**：原始日收益 Pearson（`> CORRELATION_MAX_V2`，可断仓，别名 v1 的 0.7）；残差相关为
  **诊断级**，按空分布 p95 校准，**永不单独断仓**。升级路径用配对增量（`ci95_low > 0`）。
- **升级证据**：只有**主**证据（配对增量区间下界 `ci95_low > 0`）能升级；次要统计量
  （`fraction_bootstrap_positive`）*不足以*升级——升级被拒落在 `D0_insufficient`
  （reason `paired_increment_rejected`），不会软化为 `D1`。`grade_v2` 里不存在
  "次要证据升级" 分支（详见 §9 G2）。
- **健康**：总收益口径 PSR>0.5（明示为地板、非判别器）、DD≤0.30、Vol≤0.35。
- **等级**：`D0_insufficient→T0`、`D1_marginal→T1`、`D2_supported→T2`；`TIER_CAPITAL_USD` 只有
  `T2=10_000`（即既有 `_HANG_ALLOCATION_CASH`），T0/T1 为 0（影子）。**advisory only，本批无消费者。**

## 4. 随机对照

`gate_v2.control.random_control_v2`：族在整个对照中**冻结**为真实 v2 族；变体默认 2000（硬下限 500）；
同 seed 全等、异 seed 不同；仅经 `np.random.default_rng`（全局 legacy RNG 有禁用测试）。
判据：单侧二项，观测通过数 ≤ `binom.ppf` 精确临界值（`n=2000` 时为 116），并报告 Clopper–Pearson
单侧 95% 上界。收据 `artifacts/gate-v2-control-<date>/summary.json`（由 `write_control_summary` 落盘）。

## 5. 结论改变集合（只推导）

`gate_v2.switch.derive_conclusion_changes_v2(verdicts)` 遍历已落盘 `gates_v2` 记录，产出
`{changed, changed_count, unchanged_count, undecidable_count}`，`switch_authorized=False`；
`switch_review_document` 渲染 Markdown 评审底稿。**本批不实现、不触发切换。**
两个函数是纯函数、零 IO（`test_gate_v2_switch.py` 用 AST 扫描断言无 `open/write/dump`、
无 `Path`、无对开关的赋值），输入账本调用前后逐字节相等。

**读者登记（切换批次交付）**：`gates_v2/verdicts.jsonl` 的**唯一读者**就是这两个函数，
而它们**按设计属于切换批次**——并行阶段不写盘（开关关闭，零 v2 字节），故本期没有可读的
账本，读者也就无对象可读。理由：其一，L0 不变量要求开关关闭时零落盘，任何"提前读空账本"
的接线都只会制造一个恒为空的假消费者；其二，切换评审的全部输入就是这批判定，把它与开关
翻转放在同一批次（同一 Owner 闸门）才有一个原子、可复核的交付面。因此本期只交付读者代码
+ 单元测试，账本本身留待切换批次产生。

## 6. Owner 闸门（本批均不触发）

1. `gate_v2.authoritative` 翻转 —— v2 取得判定权。2. `gate_v2.enabled` 打开 —— 开始发射记录。
3. 观察层 `observation_mode='advisory'` 生效。4. 四处 `10_000` 字面量收敛到 `TIER_CAPITAL_USD`。
5. `validation.json["schema_version"]` 新增。6. `HEALTH_*` / `DSR_V2_SMALL_FAMILY_*` 等阈值定稿。

## 7. 挂账（不改）

- `strategy_library.py:620` 硬编码 `0.7`（v1 硬化，改常量不会跟随）。
- `strategy_runtime.py` / `reference_backtests.py` 双角色归类，依赖 `active_metrics_seam.py` 迁移。
- `trial_sharpes()` 无 kind 过滤（v1 路径仍在跑 polluted 族）。
- `strategy_study_service.calculation_digest`、`validation_receipts.receipt_bindings` 同类 lumping。

## 8. 明确声明

**本批未切换。** 三条候选写面（W1 `validation.json` 的 `gates_v2` 同级键、W2 book candidate 的
`candidate["gates_v2"]`、W3 `<data_dir>/gates_v2/verdicts.jsonl`）中，**本批只实现了 W3**，
且 W3 由默认关闭的 `GATE_V2_ENABLED` 守卫；W1/W2 **未接线**。因此本期**没有任何生产路径
写出 v2 字节**，v1 判定仍是唯一落盘结论；"与 v1 并列落盘"是 W1/W2 接线后的目标态，
不是当前实况。只有 v1 驱动可用性；切换是主人闸门。

## 9. 修复批（G1–G6，不改变 §1–§8 的任何口径）

- **G1（真缺陷）** `evaluate_sensitivity_v2` 重标定时忽略 `dsr['reason']`：`reason='family_too_small'`
  且 `value=0.999 >= 0.99*0.9` 的失败记录在 `scale=0.9` 被重读为通过，`D0_insufficient`
  翻成 `D1_marginal`。修法：新增 `_DSR_NON_NUMERIC_REASONS`（族过小 / 成员窗口过短 / 候选窗口过短 /
  输入或矩无效），这类**非数值型**失败在任意缩放下保持失败，并在每条结果里给出 `pinned_reason`
  （不是静默排除）。前后对照与反例见 `tests/test_gate_v2_sensitivity.py`。
- **G2（死代码）** 删除 `grade_v2` 中 `accepted_evidence=='secondary_only'` 的 `D1` 分支：唯一
  生产者只产出 `'primary'`/`None`。判定落点写清——次要证据不足以升级，落在 `D0`
  （`paired_increment_rejected`）；并把"接受"收紧为 `upgrade_accepted is True and
  accepted_evidence=='primary'`（fail-closed）。测试：生产者词表 + 可产出 / 不可产出两种形态均 `D0`。
- **G3（footgun）** `DEFAULT_TIER` 由 `'T2'`（一万美元档）改为 `'T0'`（未配资档），与
  `tier_for_grade` 的未知等级兜底一致；测试断言"无等级信息时兜底是未配资档"。
- **G4（覆盖缺口）** 补 `tests/test_gate_v2_switch.py`：分区计数、评审列、只读推导（输入不变 +
  AST 无写调用）、渲染底稿；`verdicts.jsonl` 读者在 §5 登记为**切换批次交付**并给出理由。
- **G5（复算覆盖面）** `verify_verdict_v2` 现在复算 `upgrade`（含 bootstrap，由内嵌增量序列 + seed
  重跑）、显式校验 `tier_recommendation`（`tier` / `tier_source` / `allocated_cash` 与
  `TIER_CAPITAL_USD` 绑定）与 `verdict_parallel` 一致性，并新增 `envelope_digest` 覆盖
  `config` / `thresholds` / `tier_recommendation` / `verdict_parallel` / 版本与 provenance 戳。
  未测导出补齐测试：`evaluate_sensitivity_v2`、`thresholds_block`、`load_null_calibration_v2`、`ols_resid`。
  **可验证边界（显式）**：封套**无签名**。以下情形**可被篡改而不被发现**，且明确接受：
  (a) `code` 块（源码哈希随磁盘变动，不入摘要）——它是 provenance 不是证据；
  (b) 只要写入者把**全部**被覆盖字段连同 `envelope_digest` 一起重写成自洽的新值（含重造
  inputs 与每个复算块），本原语会接受——它防的是**意外 / 局部篡改**，不是**真实性**。
  真实性由主人的 digest-pinned 收据 + append-only 账本承担，不由该原语承担。另注：早期
  不带 `envelope_digest` 的记录会校验失败，但开关从未打开、落盘为零，故无此类记录存在。
- **G6（文档）** 本文件：HEAD 更正为 `4e4ae8ad`；测试文件数更正为 11（+本批 3）；§8
  改为准确表述（仅 W3 实现且默认关，W1/W2 未接线）；`_constants.py` docstring 不再自称
  "无 0.7/0.95 字面量"，改为显式说明唯一的 `0.95` 是 `NULL_P95_LEVEL`（统计分位、非断仓阈值），
  且被红线 AST 测试按名白名单覆盖。
