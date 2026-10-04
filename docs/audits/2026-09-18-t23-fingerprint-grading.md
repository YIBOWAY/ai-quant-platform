# T2.3 观察层分级评审（指纹 lumping）

- 日期：2026-09-18
- 适用范围：`strategy_definition._COMMON_SOURCES` 的 fail-closed 行为
- 本批状态：**只出评审文档 + 默认关闭的实现骨架；未改动 `validate_definition`，未翻转任何默认**

## 1. 议题

`research/strategy_definition.py:21-39` 的 `_COMMON_SOURCES`（18 个文件）把
**观察/执行层**文件与**算法层**文件混在同一指纹集；`validate_definition`
（`:297-306`）只要 `source_fingerprints` 任一不等即抛
`strategy_algorithm_source_mismatch`。于是「仅改观察层」与「改算法」被一视同仁地
fail-closed —— T2.2 `1acf259d` 编辑两处 seam 就击穿了所有已记录的定义指纹。

## 2. 分级白名单

- **算法层（断仓）**：`backtest/{engine,models,broker,order_generation,portfolio,metrics}.py`、
  `trading_kernel/*`、`research/strategy_definition.py`、`d34/qlib_expr.py`、
  factor 身份、`dependency:exchange_calendars`。未知条目**默认算法**（fail-closed）。
- **观察层（提示）**：`research/definition_paper.py`、`execution/definition_open_prices.py`、
  `execution/paper_strategy_signal_service.py`、`execution/paper_strategy_execution_service.py`。

分类实现见 `research/fingerprint_grading.py:classify_source`。

## 3. 诚实的残留歧义（双角色文件）

`research/strategy_runtime.py` 与 `research/reference_backtests.py` 同时承载算法**与**
T2.2 的 `active_metrics` 观察发射，属**双角色文件**。在把 `active_metrics` 发射抽到
独立观察模块（`research/active_metrics_seam.py`）之前，这两个文件**仍归算法类**
（`classify_source` 返回 `dual_role`，按 fail-closed 处理）。
**迁移未做，本条挂账。**

## 4. 同类同问题（列出但不修）

- `strategy_study_service.calculation_digest`（`:30,41-55`，10 文件表 + `VERSION`）
- `validation_receipts.receipt_bindings`（`:10-11,32-36`，绑 3 个 source 的 sha）

两者是同一类 lumping，本批仅登记。

## 5. 分级语义（需主人闸门批准才生效）

- 算法漂移 → `strategy_algorithm_source_mismatch`（断仓，**现行为**）。
- 观察漂移 → `strategy_observation_source_drift`（提示，写 receipt，不阻断）。

## 6. 骨架与本批不变量

`research/fingerprint_grading.py`：

```python
def classify_source(path) -> Literal["algorithm","observation","dual_role"]
def current_source_fingerprints_v2(definition, *, graded=False) -> {"algorithm": {...}, "observation": {...}, "advisory": [...]}
def validate_definition_v2(definition, *, observation_mode: Literal["fail_closed","advisory"] = "fail_closed")
```

- 默认 `observation_mode="fail_closed"` ⇒ 行为与 v1 **完全一致**（测试
  `tests/test_fingerprint_grading.py::test_observation_drift_is_fail_closed_by_default` 断言同抛同错）。
- 仅显式传 `"advisory"` 时，**纯观察层**漂移降级为 `advisory` 列表且不抛；算法层与双角色文件
  在 advisory 下仍断仓。
- **不编辑** `strategy_definition.validate_definition`，**不翻转**默认；`FINGERPRINT_GRADING_ENABLED = False`。

## 7. 待主人决策

1. 是否批准 `observation_mode='advisory'` 生效（Owner 闸门）。
2. `research/active_metrics_seam.py` 迁移（把双角色文件降为观察层）是否立项。
3. 是否把 `strategy_study_service` / `validation_receipts` 的同类 lumping 一并分级。
