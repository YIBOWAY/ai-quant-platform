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

2026-06-15 状态补充：评估报告中“CLI doctor 仍停留在 Phase 0 foundation
口径”的小项已更新。`quant-system doctor` 现在输出离线本地平台健康摘要，覆盖
环境、安全开关、默认数据源、Futu/OpenD 端点、可选数据库索引设置和
`data/_runtime/logs/backend.jsonl` 路径；该命令不连接行情源或 PostgreSQL。

2026-06-15 状态补充：评估报告中“.env.example 声称默认 sample 而代码默认
futu”的小项已对齐。`.env.example` 现在使用
`QS_DEFAULT_DATA_PROVIDER="futu"`，并说明 `sample` 只用于显式离线流程测试；
`tests/test_environment_file.py` 会锁定示例文件与 `DataSettings` 默认值一致。

2026-06-15 状态补充：评估报告中“错误响应格式不一致”的一部分已收敛。
持续模拟账户 API 的领域错误现在返回结构化 `detail.code` / `detail.message`，
覆盖账户冻结、缺价、策略数据不可用、未知或不支持的账户再平衡策略等常见失败态。
其他历史回放和跨模块 404 仍未做全局统一。

2026-06-15 状态补充：评估报告中“前端纯函数缺测试”的一部分已补强。
Strategy Catalog 的 schema-driven payload 构建逻辑已抽到
`src/frontend/lib/strategyPayload.ts`，并由 `strategyPayload.test.ts` 覆盖
symbol list、number、integer_or_null 和 factor weight map 转换。

2026-06-15 状态补充：评估报告中“Futu 实盘交易脚本需作为红线处理”的小项
已补强回归测试。`tests/test_api_safety.py` 现在会扫描本地已安装的
`.agents/skills/futuapi` Python 脚本，禁止重新引入 `.place_order(` /
`.modify_order(` / `.cancel_order(` / `unlock_trade(` 等 mutating broker 调用；
若本地存在 `place_order.py`、`modify_order.py`、`cancel_order.py`，测试还会执行
它们的 `--json` 模式并要求返回 disabled 错误。`.agents/` 是本地忽略目录，
因此该测试在未安装本地 skill 的干净 checkout 上会跳过入口执行检查。

2026-06-15 状态补充：评估报告中“`getOptionsRadarDates` 是死代码”的小项
已复核并收敛。该 helper 对应的后端端点仍在 `OptionsRadarView` 中使用，只是
组件曾直接调用 `apiRequest("/api/options/daily-scan/dates")`，导致 API client
helper 未被复用；现在日期查询已改为调用 `getOptionsRadarDates()`。
