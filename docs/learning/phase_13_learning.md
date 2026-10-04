# Phase 13 学习笔记

## 单标的筛选与每日推荐的区别

Options Screener 回答“这只股票有哪些合约符合我输入的筛选条件”；Options
Recommendations 回答“固定策展标的中，哪些合约通过统一证据和风险条件后排名靠前”。
推荐页最多显示 20 条，但不会为了凑数放宽条件。

## 为什么 0 条仍可能是健康结果

raw generation 有真实 Futu 报价且没有合约通过硬条件时，meta 可以是 `empty`；它只
说明已成功扫描部分没有候选。只有 freshness 合格且覆盖率完整时，页面才能把它解释成
“今日完整扫描没有合规机会”。缺少真实报价证据、旧合同、损坏 generation、过期快照
或覆盖率不足时，API 可以投影为 `unavailable`。

Partial 也必须单独看：成功标的可以保留结果，但 scanned/failed 覆盖率说明它不是完整
34 标的结论。

## IV Rank 冷启动

IVR 来自约 30 天到期、同执行价附近的 Call + Put 双腿 ATM30 straddle IV。少于
30 个正式美股交易 session 时，IVR 是 `null`，状态为 `warming`，页面显示
“积累中 n/30”。它不再阻断推荐。达到 30 个 session 后自动进入 `ready` 并显示
诊断值；当前推荐硬门和排序不依赖 IVR 高低，非法或伪造 IVR 仍拒绝。

## 为什么用物理预期赔付

推荐排序不是简单地把权利金年化，也不是把期权市场风险中性价格直接当成卖方利润。
当前 `seller_ev_liquidity_v1` 先估计到期物理赔付：

```text
sigma = min(IV, HV)  # HV 有效时；否则使用 IV
mu = risk_free_rate + equity_risk_premium
expected_value = extrinsic_premium - physical_expected_payout
score = annualized_expected_value * liquidity_factor
```

Equity risk premium 默认 `0.04`，由 `QS_OPTIONS_RADAR_EQUITY_RISK_PREMIUM`
配置。模型仍是研究假设，不是未来分布或收益保证；风险参数必须随 generation 记录，
读取时再用当前公式复核。

## 财报与除息证据

非 ETF 卖方合约需要明确的下一次财报证据，并排除到期日前的财报事件。备兑看涨还需要
除息日期和每股股息证据；若除息日在到期窗口内，外在价值必须高于股息。`(无日期, 0)`
可以表示数据源明确断言没有股息，完全缺失的证据不能当作零。

这些事件在每次 `daily-task` 扫描前从公开只读来源刷新。正式页不允许 sample 事件
进入结果。

## VIX Regime

Futu 不提供项目需要的 `US.VIX` / `US.VIX3M` 指数代码，因此 Platform 从公开的
Yahoo Chart（必要时 Cboe）刷新 `^VIX` / `^VIX3M` 本地历史，并计算 Normal、
Elevated、Panic 或 Unknown。Regime 进入旧的 seller composite/展示字段；最终推荐
主排序仍以物理 EV × 流动性为准。

## 为什么扫描慢

每个标的需要标的快照、到期日、分段期权链和批量报价，还要遵守 Futu 报价节奏。
34 标的任务是后台长任务，所以 POST 只返回 `202 queued`，页面轮询进度。重复请求返回
409，不会以并发双扫换取表面速度。

## 快照为什么仍叫 v3

当前合同版本仍是 `options_recommendations/v3`，但读取器会校验必填字段、哈希、
universe、报价水位，并按当前 physical EV / dividend 公式重算候选。旧 v3 若字段不足
或由旧公式生成，会变成 `unavailable`；版本名相同不等于永久兼容。
