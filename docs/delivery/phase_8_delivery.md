# Phase 8 交付记录

## 本阶段完成内容

Phase 8 已交付 prediction market 扩展骨架。

完成项：

- 新增 `quant_system.prediction_market` 包。
- 新增 deterministic sample provider。
- 新增 Polymarket live stub，调用即拒绝。
- 新增 CLOB order book 数据模型。
- 新增 YES/NO scanner。
- 新增 outcome set consistency scanner。
- 新增 profit threshold checker。
- 新增 greedy dry optimizer。
- 新增 LP optimizer 占位。
- 新增 partial fill 状态机骨架。
- 新增 settlement risk placeholder。
- 新增 prediction-market CLI。
- 新增 Phase 8 测试。

## 交付的 CLI

```powershell
quant-system prediction-market scan-sample --output-dir data/pm_sample
quant-system prediction-market dry-arbitrage --output-dir data/pm_sample --optimizer greedy
quant-system prediction-market doctor
```

## 安全结果

- 没有 HTTP 请求。
- 没有 WebSocket。
- 没有链上 RPC。
- 没有私钥读取。
- 没有签名。
- 没有 token 转账。
- 没有订单提交。
- dry arbitrage 只写 `prediction_market/proposals/*.json`。

## 测试覆盖

新增测试覆盖：

- sample provider 至少包含一组 YES/NO sum < 1 的样例。
- YES=0.40、NO=0.50 时 scanner 检出约 10% edge。
- 三 outcome sum=1.05 时 scanner 检出约 5% edge。
- 低于阈值的 candidate 被拒绝。
- Polymarket stub 调用即抛 `NotImplementedError`。
- dry arbitrage 只写 proposal，不写 orders、fills、token transfers。
- partial fill 状态机初始状态正确。
- settlement risk tracker 是显式占位。

## 当前限制

- 样例数据不是市场真实数据。
- scanner 只覆盖最简单的不一致。
- `GreedyStub` 只是 dry proposal，不是完整优化器。
- `LPStub` 只是可选 scipy 入口，不实现高级求解。
- 不处理真实 partial fill。
- 不处理真实 settlement / resolution risk。

## 验收标准

- `prediction-market scan-sample` 能输出候选和报告。
- `prediction-market dry-arbitrage` 能写 proposal JSON。
- 输出目录没有 orders / fills / token_transfers。
- `prediction-market doctor` 明确显示 live API disabled。
- `python -m pytest` 全部通过。
- `ruff check .` 无错误。
