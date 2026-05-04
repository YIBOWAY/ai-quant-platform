# 平台总览

这是一个本地运行的 AI 量化研究平台。它的目标是帮助你做研究、回测、模拟交易、只读市场扫描和实验管理，而不是直接实盘交易。

当前状态：**Phase 14 已完成**。

## 现在能做什么

股票 / ETF 方向：

- 读取真实历史行情，当前主力数据源是 Futu OpenD。
- 保留 sample / Tiingo 作为回退或兼容数据源。
- 运行因子研究。
- 运行回测。
- 记录实验结果。
- 运行 paper trading。

期权方向：

- 读取 Futu 美股期权链和快照。
- 运行单标的卖方期权筛选器。
- 每日扫描 `S&P 500 union Nasdaq 100`，生成 Options Radar 快照。
- 在 `/options-radar` 页面查看筛选结果。
- 运行买方期权策略助手（看涨方向，只读量化决策辅助），在 `/options-buyside` 页面查看推荐与情景实验室。

Prediction market / Polymarket 方向：

- 只读获取公开市场数据。
- 采集历史快照。
- 运行时间序列回放。
- 生成报告和图表。

AI Agent 方向：

- 生成候选因子、候选实验配置和报告。
- 所有产物进入候选区，必须人工审核。
- Agent 不能直接修改因子库，不能上线策略，不能下单。

## 不能做什么

- 不实盘交易。
- 不下真实订单。
- 不连接钱包。
- 不签名。
- 不解锁 Futu 交易账户。
- 不接入真实 broker 下单接口。
- 不允许 AI Agent 绕过审核或风控。

## 安全边界

这些默认值必须保持保守：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`
- `no_live_trade_without_manual_approval = true`

任何新功能都必须遵守这些边界。

## 如何启动

后端：

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

前端：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

打开：

```text
http://127.0.0.1:3001
```

## 新人阅读顺序

1. [README.md](../README.md)
2. [INDEX.md](INDEX.md)
3. [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)
4. [execution/phase_13_execution.md](execution/phase_13_execution.md)
5. [delivery/phase_13_delivery.md](delivery/phase_13_delivery.md)
6. [execution/phase_14_execution.md](execution/phase_14_execution.md)
7. [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md)

如果只想快速验证系统能跑，先看 README 和 Phase 14 执行文档。
