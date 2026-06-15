# 历史审计

本文件夹中的文件作为历史背景资料予以保留。它们记录了早期的评审发现与修复计划，其中部分发现至今已得到解决。

如需了解平台当前状态，请从以下文档开始：

- [../../README.md](../../README.md)
- [../INDEX.md](../INDEX.md)
- [../OVERVIEW.md](../OVERVIEW.md)
- [../delivery/phase_13_delivery.md](../delivery/phase_13_delivery.md)
- [../delivery/phase_14_delivery.md](../delivery/phase_14_delivery.md)
- [FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](FRONTEND_REAL_DATA_REVIEW_2026-05-31.md)

2026-06-15 状态补充：评估报告中“显式 provider 请求失败静默降级 sample”的
小项已加固。股票数据 provider override 现在只接受 `sample` / `futu` /
`tiingo`；未知显式 provider 会返回 `400 provider_unavailable`，不会当作 sample
继续返回 200。未传 provider 的只读行情默认路径仍可使用带标注的 sample fallback。
