# Phase 11 后续路线说明

这份文档原来记录的是“Phase 12 还没做时，下一步应该做什么”。

现在 Phase 12 已经落地，所以这份文档的作用改成：

- 告诉你 Phase 11 之后真正往前走的是哪条路
- 把已经完成的 Phase 12 和后续候选方向分开

## 已完成

Phase 12 已经完成了两件关键事：

1. Polymarket 历史快照采集
2. Polymarket 时间序列 simulated replay

对应文档：

- [phase_12_design_spec.md](phase_12_design_spec.md)
- [architecture/phase_12_architecture.md](architecture/phase_12_architecture.md)
- [execution/phase_12_execution.md](execution/phase_12_execution.md)
- [learning/phase_12_learning.md](learning/phase_12_learning.md)
- [delivery/phase_12_delivery.md](delivery/phase_12_delivery.md)

## 后续建议

如果继续往后做，建议按下面顺序：

1. 扩大真实历史样本窗口
2. 增加更多 scanner
3. 做更细的撮合假设
4. 把预测市场结果并入实验管理

## 仍然不做

无论后面做到哪一阶段，这几条都不应该在当前平台里被打开：

- 真实下单
- 钱包连接
- 私钥处理
- 签名
- 链上能力
