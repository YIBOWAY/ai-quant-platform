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

## 演练结果摘要

为了证明上述功能可端到端跑通，本节记录一次 smoke run 的产出。

命令：

```powershell
conda activate ai-quant
quant-system prediction-market scan-sample --output-dir data/_smoke_p8
quant-system prediction-market dry-arbitrage --output-dir data/_smoke_p8
quant-system prediction-market doctor
```

scan-sample 输出（节选）：

```text
candidates=3 report=data\_smoke_p8\prediction_market\reports\prediction_market_report.md
candidate_id=pm-a3e9e55fbdb2 market_id=sample-binary-001 scanner=yes_no_arbitrage edge_bps=500.00 direction=underpriced_complete_set
candidate_id=pm-29f0a62974a3 market_id=sample-binary-001 scanner=outcome_set_consistency edge_bps=500.00 direction=underpriced_complete_set
candidate_id=pm-5c0512371db9 market_id=sample-three-way-001 scanner=outcome_set_consistency edge_bps=500.00 direction=overpriced_complete_set
```

dry-arbitrage 输出（节选）：

```text
proposed_trades=3 report=data\_smoke_p8\prediction_market\reports\prediction_market_report.md
proposal_id=proposal-d88294cd8d47 dry_run=True capital=1000.00 expected_profit=50.00
```

落盘验证：

| 路径 | 是否存在 | 说明 |
| --- | --- | --- |
| `prediction_market/candidates/*.json` | ✅ | 3 条 mispricing candidate（sample 数据特意构造） |
| `prediction_market/proposals/*.json` | ✅ | 3 条 dry proposal，**全部 `dry_run=true`** |
| `prediction_market/reports/prediction_market_report.md` | ✅ | 人类可读报告 |
| `prediction_market/orders/` 或 `fills/` 或 `token_transfers/` | ❌ | 永远不会出现，符合 dry-only 边界 |
| 任何 HTTP 请求 / WebSocket 连接 / 私钥读取 | ❌ | 整个调用链没有这些代码路径 |

doctor 输出（节选）：

```text
live API disabled = True
http calls allowed = False
websocket connections allowed = False
private key access = False
scipy available = True   # 可选依赖
```

⚠️ 重要提醒：`edge_bps=500.00`（5%）只是 sample provider 故意构造的极端值，**不代表真实 Polymarket 上能找到这种 edge**。具体原因见 [phase_8_learning.md §设计取舍故事](../learning/phase_8_learning.md)。

测试：`pytest tests/test_prediction_market_*` → 全部通过；`ruff check .` clean。
