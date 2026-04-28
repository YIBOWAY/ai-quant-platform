# Phase 8 学习文档

## 当前阶段核心概念

Prediction market 和股票多因子系统最大的不同是：它交易的是"事件结果"。

例如一个二元市场有两个 outcome：

- YES
- NO

如果市场完整且互斥，YES + NO 的理论 payoff 合计为 1。价格偏离这个关系时，scanner 可以标出候选不一致。

## Order Book 是什么

Order book 是买卖挂单表。

Phase 8 只保留最小信息：

- bid：别人愿意买的价格
- ask：别人愿意卖的价格
- size：挂单数量

本阶段只读 order book，不提交订单。

## Mispricing Candidate 是什么

Scanner 发现价格关系不一致时，会输出 `MispricingCandidate`。

它不是交易指令，只是一条研究候选。

例如：

```text
YES ask = 0.40
NO ask  = 0.50
sum     = 0.90
edge    = 10%
```

这只是样例数据中的候选，不代表真实市场存在机会。

## Profit Threshold 是什么

阈值层用于过滤太小的 edge。

默认：

```text
min_edge_bps = 200
```

也就是 2%。低于这个阈值的候选不会进入 optimizer。

## Optimizer Stub 是什么

`GreedyStub` 只把候选转换成 `ProposedTrade`。

它不会：

- 下单
- 连接 broker
- 签名
- 转账
- 处理真实 partial fill

`LPStub` 只是接口占位，不实现高级求解。

## Partial Fill 为什么重要

多腿套利最危险的地方是：一条腿成交，另一条腿没成交。

Phase 8 只做状态机骨架：

```text
NEW -> LEG1_FILLED -> ROLLBACK_PENDING
```

真实执行前必须补齐 rollback、hedge、timeout 和风险限制。

## Settlement Risk 是什么

Prediction market 最后要 resolution。风险包括：

- 事件描述歧义
- oracle / resolution 延迟
- 市场关闭或争议
- token redeem / settlement 机制变化

Phase 8 只保留 `SettlementRiskTracker` 占位，不做真实建模。

## 常见错误

1. 把 sample mispricing 当成真实套利。

   错。它只是测试数据。

2. 看到 `ProposedTrade` 就理解成订单。

   错。它只是本地 JSON proposal。

3. 在 Phase 8 加 Polymarket HTTP。

   错。本阶段明确不接 live。

4. 忽略 partial fill。

   错。真实多腿执行必须先解决 partial fill 风险。

## 自检清单

- 是否只用了 sample provider？
- `PolymarketStub` 是否仍然调用即拒绝？
- 输出目录是否只有 proposals 和 reports？
- 是否没有 orders / fills / token_transfers？
- 是否没有私钥、签名、HTTP、WebSocket？
- 是否没有实现 Frank-Wolfe、整数规划或 LMSR？

## 下一阶段如何复用

后续可以在这个骨架上逐步加入：

- 只读 market discovery。
- 只读 CLOB snapshot。
- 更完整的逻辑约束。
- 更严格的 optimizer。
- partial fill 风险模拟。

在这些完成之前，不能进入真实执行。

## 设计取舍故事

### 为什么不直接实现 Frank-Wolfe / 整数规划 / LMSR

[docs/SYSTEM_DESIGN_RESEARCH.md](../SYSTEM_DESIGN_RESEARCH.md) §7.4 已经把 Frank-Wolfe / Barrier Frank-Wolfe / 整数规划 / LMSR cost function 列为"高级阶段才做"。本阶段只留 `OptimizerInterface` Protocol 的原因：

1. **求解器是配角，执行才是主角**。即使 Frank-Wolfe 算出"最优组合"，没有可靠的多腿原子下单、partial fill recovery、settlement 风控，这些"最优解"在真实市场上是不可执行的；先把执行层设计好，再换求解器。
2. **求解器质量难以单测**。Frank-Wolfe 收敛速度、数值稳定性、约束违反容忍度，这些都依赖具体实例，不是 5 个 unit test 就能锁住的；放进 MVP 只会让 PR review 失焦。
3. **依赖膨胀**。完整 IP 求解需要 Gurobi（要 license） 或 OR-Tools（体量大、Windows 安装坑多）。MVP 阶段把这些塞进 `pyproject.toml` 会把"5 分钟跑通"的承诺破坏掉。
4. **Protocol 先行**。`OptimizerInterface.solve(opportunity) -> ProposedTrade | None` 这个签名就够把 GreedyStub / LPStub / 未来的 FrankWolfeOptimizer 全装进去；先把契约定死，比先把实现写完更重要。

代价：当前 GreedyStub 真的只能解最 trivial 的问题（单腿、capital 受限）。这是 deliberately 的下限，不是疏忽。

### 为什么 YES + NO 套利在真实 Polymarket 上往往 < 50 bps

学习这个模块时容易产生一个误解："YES + NO 经常 < 1，套利唾手可得"。Phase 8 的 sample provider 故意造了一个 YES=0.40 / NO=0.50 的极端案例，方便 scanner 测试 —— 但**真实市场上这种 10% edge 几乎不存在**。原因：

1. **专业 market maker 抢 sub-cent**：Polymarket CLOB 上有专门的做市机器人，YES + NO 偏离 1 超过 1–2 cent 通常在秒级被填平；散户 retail bot 永远跑不赢。
2. **手续费 + gas + slippage**：Polymarket 的 trading fee 0–2%、Polygon gas 也要钱，再加上 best ask 不一定 fill 满数量、要走多档口；扣完之后 50 bps 的 paper edge 大概率变 0 或负。
3. **流动性深度**：很多 mispricing 发生在 size = $50 的小单上，往里塞 $5000 立刻把 spread 顶回去。
4. **resolution risk 不计 edge**：YES + NO < 1 的"无风险套利"只在事件 100% 会 resolve 的前提下成立。真实事件可能延迟 / 争议 / 协议条款变更，这部分尾部风险吃掉了大部分 paper edge。

所以 Phase 8 把 `min_edge_bps` 默认设成 200（2%）只是为了**让 scanner 在 sample 数据上能跑出非空结果**。要做真实策略研究，这个阈值要根据实际成本和资金规模重新校准，**而且需要先做 Phase 6 的真 broker adapter 才能验证**。

### 为什么 PolymarketStub 选择"调用即抛 NotImplementedError"

更"友好"的写法是返回空数据 / mock data。我们刻意没这么做，原因：

- 返回空数据会让上层代码"看起来在工作"，等到一个新人不小心写了 `provider = PolymarketProvider()` 就以为接通了 live；真实场景下他可能已经把 sample 测下来的 5% Sharpe 拿去做交易决策了。
- `NotImplementedError("Polymarket live integration is intentionally not wired in Phase 8")` 这条异常信息直接指向 [docs/architecture/phase_8_architecture.md](../architecture/phase_8_architecture.md) §8.4 —— 报错本身是文档的一部分。

这是一种"防御性失败"：把误用爆炸的位置控制在最早，而不是最晚。

