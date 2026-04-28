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
