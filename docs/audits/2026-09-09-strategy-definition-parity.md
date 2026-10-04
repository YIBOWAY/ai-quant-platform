# StrategyDefinition 第二次独立复核

审计日期：2026-09-09。对象是新增 StrategyDefinition 历史研究、验证、候选与模拟执行路径。审计者未参与这些实现；本次只读源码和已保存数据，密封反例使用内存或自动清理的临时目录。

**当前结论：P1、P2、P3、P4 四项发现均已完成窄修后的独立反例验收，本次范围内没有未关闭的原发现。** 初次审计发现两个目标生成分歧和候选收据复用、分析收据身份检查问题。下文保留触发条件与影响，并分别记录修复后证据，不以旧反例仍缺新必填字段而报错冒充修复通过。这是四项特定问题的复核结果，不是全仓、部署或真实自动日程认证。

已知 `paper_cycle.py` 在无预计订单时漏开盘检查的问题由主任务处理，本报告不重复列为新发现。当前该文件未修改，`definition_schedule_available=False`，正式新定义策略启用仍被阻断；密封测试中的日程能力替身不能证明自动日程可用。

## 正常路径已核验的事实

- `strategy_runtime.decision_for_session` 与 `evaluate_definition` 使用同一 `_decision`；因子方向、rank/z-score、权重、Top N、目标总仓位、单票上限、缺失交集、调仓周期均进入定义摘要。
- `None` 表示本次不调仓，`{}` 表示目标现金；`definition_orders` 对二者分别返回不下单和卖出已持有数量。周、月边界由 NYSE 日历确认，并校验历史价格日期连续性。
- paper 信号使用前一个已结束日历日之前的最近交易日；provider 额外返回的未来价格被截掉。初次审计时，真实保存的 24 股动量在 2026-08-31 按原 paper 的 800 日请求窗口重算，24 股分数与原结果一致。当前修复已改成定义必填的 `history_start`；历史与 paper 均使用相同起点，此前 800 日实测仅保留为历史证据。
- 验证路径明确用 $10,000 重新执行历史计算，没有把 $100,000 的绝对最小订单门槛按比例改写。paper 实际预算来自 sleeve 的现金与自有持仓；实际开盘时重新计算目标订单，预估收盘订单不作为实际成交数量依据。
- `DefinitionOpenPriceSource` 按明确 target date 请求 Futu 1d 开盘价，要求 `futu / qfq / 1d`、单行、正且有限，并要求该 NYSE 开盘时点已到。成交服务复核 quote 的来源、`futu_daily_open` 类型、标的与精确日历开盘时间。未发现向普通 snapshot 价格退回的定义执行路径。
- library 的原生 Qlib 路径重新消费本次价格和 Platform result；真实使用 `SimulatorExecutor` / `backtest_daily`。主链核对输入价格、Platform result、定义摘要、$10,000、美元单位与收益日期。
- `tests/test_strategy_definition_runtime.py` 与 `tests/test_definition_paper_bridge.py` 的既有定向测试全部退出 0。下列独立反例说明这些测试尚未覆盖全部相关输入。

## 发现与修复状态

### P1 / Medium：未持仓标的缺失导致历史与 paper 分歧

观察：历史内核允许未持仓股票缺少决策日数据，剔除该股票后继续对完整交集排名；paper 信号服务在调用内核前要求定义内所有股票都有当日 close，任何一只缺失都会拒绝整次决策。

证据：初次复核的 `paper_strategy_signal_service.py:252` 执行全池价格要求；`strategy_runtime.py:297–322` 则对非空有效交集生成目标。密封三股 SPY/QQQ/IWM、$10,000，单独删除未持有 QQQ 在 2026-09-03 的一行价格；历史评价 2026-09-04 为 `available`，目标 SPY=0.4/IWM=0.4，生成两笔买入；paper 同一日期与定义为 `data_unavailable / strategy_definition_decision_prices_missing`，没有订单。

影响：同一策略在该输入下从历史的 80% 目标仓位变成 paper 不执行。当前完整 24 股真实快照未触发，但上市／停牌／provider 缺行等情况会造成两端行为分叉。

建议：由共享缺失策略决定未持仓标的是否剔除；持仓估值缺失仍明确失败。不要在 paper 包装层另设全池门槛。

状态：**已修复并独立复核。** 用新定义明确 `history_start=2025-01-02`，重跑同一缺失 QQQ 的反例，历史仍 `available`、两笔订单，paper 现为 `generated`，目标 SPY=0.4/IWM=0.4，scores 完全一致、无 warning。前置估值只要求 benchmark 与实际持仓价格；共享内核选股后再要求入选股票有价。benchmark／已持有股票缺价以及内核返回无价目标的负例仍明确拒绝。

### P2 / Medium：MACD 递归初值没有绑定，有限取数窗口改变整仓目标

观察：历史评价对完整保存序列计算 EMA；paper 只取 `max(800, definition.required_history_days)` 个日历日。`MACDFactor` 使用 `ewm(adjust=False)`，其状态依赖历史起点。满足最小形成窗口不等于恢复同一 EMA 初值。

证据：`strategy_definition.py` 的 `required_history_days`、`paper_strategy_signal_service.py:213/239` 与 `factors/examples.py:101–120`。密封 MACD lookback=100、rank、Top1、AAA/ZZZ，最近 800 天价格都恒为 100，ZZZ 在更早时期为 1,000：同日 2026-09-08，完整历史目标 ZZZ=100%；paper 请求窗口中两者分数并列，按 symbol 排名成为 AAA=100%。该定义的 `required_history_days=632`，paper 实际取 800 天。

影响：这是 100% 目标仓位替换，不是可忽略的净值舍入差。现有 paper History 测试夹具忽略 `start` 并返回所有历史，因此没有发现这一分叉。当前 24 股月末价格动量不使用递归 EMA，不受此反例影响。

建议：统一并绑定递归状态／历史起点，或者明确拒绝暂不能保证一致的递归因子；增加任意固定天数不能证明精确重放一致。

状态：**已修复并独立复核。** 定义现在必须明确 `history_start`，并将其纳入摘要；历史在初始化递归指标之前截取该起点，paper provider 请求完全相同的起点。原 AAA/ZZZ 反例以 `history_start=2019-01-02` 重跑：真实按请求日期过滤的密封 provider 接到 start=2019-01-02，paper 和完整历史均选 ZZZ=100%，scores 完全一致。让 provider 只返回旧的 800 日窗口，同一合法定义明确返回 `data_unavailable / strategy_benchmark_calendar_incomplete`，不会选择 AAA。MACD 与 Wilder RSI 的起点前数据扰动测试均通过。

可在源码环境执行以下修复验收代码；历史起点取价格首个 session，不访问 provider 或账户：

```python
import pandas as pd
from tests.test_strategy_definition_runtime import prices_for
from quant_system.research.strategy_definition import StrategyDefinition, StrategyFactor
from quant_system.research.strategy_runtime import decision_for_session

p = prices_for(["AAA", "ZZZ", "SPY"], start="2019-01-02", end="2026-09-08")
d = StrategyDefinition(
    kind="factor_blend", title="sealed EMA initialization parity",
    history_start=p.timestamp.min().date().isoformat(),
    symbols=["AAA", "ZZZ"], benchmark_symbol="SPY", top_n=1, normalization="rank",
    factors=[StrategyFactor(factor_id="macd", lookback=100, direction="higher_is_better")],
)
start = pd.Timestamp("2026-09-08", tz="UTC") - pd.Timedelta(days=800)
p[["open", "close"]] = 100.0
p.loc[(p.symbol == "ZZZ") & (p.timestamp < start), ["open", "close"]] = 1000.0
p["high"], p["low"] = p.close * 1.01, p.close * 0.99
assert decision_for_session(p, d, "2026-09-08")["targets"] == {"ZZZ": 1.0}
try:
    decision_for_session(p.loc[p.timestamp >= start], d, "2026-09-08")
except ValueError as exc:
    assert str(exc) == "strategy_benchmark_calendar_incomplete"
else:
    raise AssertionError("Same definition accepted a different recursive history origin")
```

### P3 / Medium：同定义再次验证可能沿用旧 candidate 的绩效与比较收据

观察：library 以 `strategy-<definition_digest[:24]>` 固定 candidate ID 记录验证。`record_verified_candidate` 遇到既有 candidate，仅检查定义的 source/factor/universe lineage 后返回，不核对本次 comparison、returns 与 dates。

证据：初次复核 `strategy_library.py:467`，`assistant_remote.py:459–485`。在自动清理 tmp 中调用真实 `record_verified_candidate`，第一次 comparison=a×64、returns=[0.01,0.02,0.03]、1 月日期；第二次 comparison=b×64、returns=[−0.01,−0.02,−0.03]、2 月日期。第二次实际仍返回 a×64、旧正收益、旧 1 月日期，candidate 总数为 1。

影响：entry 展示新验证，候选继续保存旧比较和绩效；后续准入重查不能保证使用当前页面所展示的验证依据。反例证明了复用行为，不证明当前真实 candidate 已发生该错配。

建议：候选绑定具体 validation receipt，或幂等返回时要求 comparison 与完整绩效序列一致；单独更新 entry 不足以完成重验证。

状态：**已修复并独立复核。** 合法 `history_start=2026-01-02`、完整密封 validation receipt 和真实 tmp candidate 存储下，完全相同输入重复写入幂等返回；仅改变 comparison、returns 或 dates，分别得到 `candidate_validation_changed`。library 现在把具体 validation receipt SHA 纳入 candidate ID；两个不同 receipt 产生两个不同 ID，保留各自历史记录，候选数为 2。没有复用旧绩效，也没有覆盖旧记录。

当前修复验收代码只写 tmp 策略定义、密封 receipt 与研究候选记录，没有账户或成交。`sealed_validation` 生成的是明确测试收据，不是真实 Qlib 验证：

```python
import tempfile
from pathlib import Path
from quant_system.config.settings import load_settings
from quant_system.research import strategy_library as lib
from quant_system.research.strategy_definition import StrategyDefinition, StrategyFormula
from quant_system.execution import assistant_remote as remote
from tests.test_validation_receipts import sealed_validation

with tempfile.TemporaryDirectory(prefix="candidate-revalidation-audit-") as raw:
    s = load_settings()
    s.data.data_dir = Path(raw)
    d = StrategyDefinition(kind="formula", title="sealed", symbols=("AAA",), top_n=1,
                           history_start="2026-01-02",
                           formula=StrategyFormula(expression="$close"))
    e = lib._save_definition(s, d, {"type": "compose"})
    directory = lib._directory(s, e["strategy_id"])
    _, receipt_sha = sealed_validation(
        directory / "validations" / "validation-sealed", d.content_digest, "a" * 64
    )
    kw = dict(settings=s, candidate_id=e["strategy_id"], objective="sealed",
              source="strategy_definition",
              source_path=str(lib._directory(s, e["strategy_id"]) / "definition.json"),
              source_digest=e["source_sha256"], factor_id="definition_" + d.content_digest[:24],
              universe=["AAA"], top_n=1, turnover_period=1.0,
              verification_receipt_digest=receipt_sha)
    remote.record_verified_candidate(**kw, comparison_digest="a" * 64,
        daily_returns=[.01, .02, .03], return_dates=["2026-01-02", "2026-01-05", "2026-01-06"])
    try:
        remote.record_verified_candidate(**kw, comparison_digest="b" * 64,
            daily_returns=[-.01, -.02, -.03],
            return_dates=["2026-02-02", "2026-02-03", "2026-02-04"])
    except remote.AssistantRemoteError as exc:
        assert str(exc) == "candidate_validation_changed"
    else:
        raise AssertionError("Same candidate ID accepted different validation evidence")
```

### P4 / Medium：信号／源码收据身份与写入顺序，已修复并独立复核

初始消费路径仅加载 `signal-analysis.json`，没有核对身份或状态。密封反例放入 foreign definition/prices/result hash 且 `status=failed` 的收据，原路径仍 `validated / passed`，并调用 candidate 写入。

实现方已补三项身份核对及状态门槛。独立重跑分别替换 `definition_digest`、`prices_sha256`、`result_sha256`，均返回 `validation_failed / strategy_signal_analysis_identity_mismatch`，candidate 调用次数为 0。身份正确但 `status=failed/partial/unavailable`，均由 `signal_validation_unavailable` 阻断；`available/not_applicable` 对照通过。

新增 `validation_receipts.py` 后，进一步独立实测四份输入／输出文件逐一改变、Native replay／signal analysis／`qlib_evaluation.py` 三份源码 SHA 逐一漂移，全部拒绝。将输出内三种源码 SHA 换成外来值并重算外层文件 hash，仍由 `strategy_validation_outputs_mismatch` 拒绝。旧收据没有 `receipts`、候选没有 receipt digest 的负例也被拒绝。

完整 receipt 首次接入后，还发现过一个先后顺序缺口：先写 validation 并登记 candidate，到函数末尾 `read_strategy` 才核完整收据。合法 history_start 与完整三日密封数据／数值对照中，仅将 native `replay_source_sha256` 换成 f×64，当时返回 `validation_failed / strategy_validation_receipt_requires_refresh`，但磁盘 `entry.status=validated`，真实 tmp book 已新增一条 `status=verified` candidate。

实现方随后将完整 `verify_validation_receipt` 移至登记 candidate 之前。**原样集成反例独立复跑通过：** 合法收据返回和落盘均为 `validated`，真实 tmp book 新增一条 verified；同一 native 源码 SHA 变异返回和落盘均为 `validation_failed`、错误为 `strategy_validation_outputs_mismatch`，candidate 数为 **0**。没有以空夹具或构造失败作为通过证据。后续 read/enable/hang 的拒绝仍存在；本次从未发现激活绕过。

## 窄修验收执行记录

- P1 原始三股缺行反例和 P2 原始 AAA/ZZZ MACD 反例均独立重跑；所有价格输入与临时状态都在内存或自动清理 tmp 内。
- P1/P2 的七项定向用例退出 0：未持仓缺价、benchmark／held 缺价两例、入选缺价、真实过滤 provider 的 MACD 起点、必需历史起点、MACD／Wilder RSI 初始化前截断。没有重新跑全仓测试。
- P3/P4 的三个对应既有聚焦测试通过，并完成上述 candidate 字段逐一变异、文件／源码逐一变异及最后两项真实 tmp candidate 集成对照。已有通过的检查未因最后一处顺序修复而重复扩测。
- 当前报告中的两个 Python 验收片段补齐了 `history_start` 和完整密封 receipt，可在新实现下运行；旧 fixture 缺新字段造成的构造异常没有计为修复成功。
- 本轮审计只更新此报告，不改产品、不调参、不提交、不创建正式研究、候选、模型或 paper 周期。日程能力未授权的状态保留，未用密封 capability stub 表示真实可运行。

## 初次审计时已保存验证的只读核对

初次审计时 deployment mirror 下实际已有以下记录，均未被本审计修改。它们生成于本轮 history_start／receipt 修复之前，不能作为当前新定义已验证或已启用的证明：

| 定义／validation | 保存状态与资金 | 实际身份核对 | 边界 |
|---|---|---|---|
| `strategy-f5efa6d4481e1c55af6c8414` / `validation-4659c10ded374b7297539c6805ec02e7` | passed，$10,000；DSR 0.98345686、n=8 | Qlib available，definition/prices/result hash 匹配 | 较早生成，目录没有 signal-analysis.json；不能视作后来完整验证链已覆盖 |
| `strategy-e3433aa3fcc3ccd33d1d762c` / `validation-d4220e8a449c4cca840311a7bd968d39` | passed，$10,000；DSR 0.97554765、n=14 | Qlib 与 signal-analysis 均 available，各自三项 identity 匹配 | 只证明这份保存收据互相绑定；后续源码修复是否要求重新验证，须按新 fingerprint 检查 |

DSR 数字是这些保存时点的门槛结果，不能替代未查看历史或前瞻收益证明。这里没有真实启用、paper 成交或正式周期证据，审计也未制造这些证据。
