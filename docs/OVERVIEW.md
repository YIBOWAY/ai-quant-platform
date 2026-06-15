# 平台总览

本仓库是一个**本地优先**的 AI 量化研究与模拟交易平台。它面向研究、测试、报告与只读行情分析而构建，**不是实盘交易平台**。

当前状态：Phase 14 已交付；在初始交付之后，又新增了本地期权工具、雷达下钻、运行详情页、实验回顾，以及本地 Futu 期权报价缓存等内容。

## 它能做什么

股票研究：

- 读取真实的美股与 ETF 历史数据。
- 在因子实验室查看横截面与择时诊断（2026-06-11 起默认 `futu` 真实数据，数据源/股票池/择时标的/基准可在侧栏调整），并可保存因子研究运行。
- 运行策略、universe、因子权重与基准回测。
- 从 API 读取已注册的策略目录与股票 universe 目录。
- 运行可选数据源（`sample` / `futu` / `tiingo`）的实验扫描并存储结果。
- 在持久模拟账户（初始 100 万美元）里手动买卖美股，或让策略一键再平衡，并在持仓地图查看。
- 运行历史回放式模拟交易仿真。

期权研究：

- 读取 Futu 美股期权链与报价快照。
- 运行单标的期权卖方收益筛选器（Options Income Screener）。
- 在本地 universe 上运行每日期权雷达（Options Radar）扫描。
- 从雷达 UI 刷新本地的雷达 universe、财报与 VIX 缓存；默认使用公开数据源，sample 数据仅作为明确的测试源。
- 查看单标的雷达候选，并可选地加载实时期权链。
- 使用 VIX/VIX3M 历史对市场状态（regime）进行分类。
- 运行买方期权助手（Buy-Side Options Assistant），用于看涨的多头权利金结构。
- 使用本地 AlphaGBM 风格的期权工具，进行希腊字母、波动率微笑、曲面、打分、策略排序与仅研究用途的提醒/自选清单。

预测市场研究：

- 读取公开市场数据。
- 采集历史快照。
- 运行回放式时间序列回测。
- 生成报告与图表。

AI 研究助手：

- 生成候选因子、实验配置与报告。
- 将候选项存入评审池。
- 任何内容晋级前都必须经过人工评审。

## 它不能做什么

- 不做实盘交易。
- 不做真实券商下单。
- 不连接钱包。
- 不做签名。
- 不解锁 Futu 账户。
- 不创建 Futu 交易上下文。
- 不把策略自动晋级到实盘执行。
- 不提供投资建议。

## 安全边界

默认的安全姿态必须保持保守：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`
- `no_live_trade_without_manual_approval = true`

每一个新功能都必须维持这些边界。

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

## 界面操作指南（新）

如果你看着界面"理解不了它在干什么"，先读这些基于真实代码写的中文操作与说明文档：

- [因子实验室 Factor Lab](guides/factor-lab.md)
- [回测器 Backtester](guides/backtester.md)
- [策略目录 Strategy Catalog](guides/strategy-catalog.md)
- [实验管理 Experiments](guides/experiments.md)
- [模拟交易 Paper Trading](guides/paper-trading.md)
- [持仓地图 Position Map](guides/position-map.md)

模拟交易与持仓地图的设计与实现记录（单一 100 万模拟账户、策略一键再平衡 + 手动美股下单、统一持仓地图，**阶段 1-5 已实现**）：

- [模拟交易 + 持仓地图 重设计](design/paper_trading_position_map_redesign.md)

前端于 2026-06-11 完成全页面重构（统一设计令牌、固定视口外壳、模拟交易双标签页、账户驱动持仓地图、E2E 38/38），详见 [delivery/frontend_refactor_2026-06-11_delivery.md](delivery/frontend_refactor_2026-06-11_delivery.md)。

## 新贡献者阅读顺序

1. [README.md](../README.md)
2. [INDEX.md](INDEX.md)
3. [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)
4. [execution/phase_13_execution.md](execution/phase_13_execution.md)
5. [delivery/phase_13_delivery.md](delivery/phase_13_delivery.md)
6. [execution/phase_14_execution.md](execution/phase_14_execution.md)
7. [delivery/phase_14_delivery.md](delivery/phase_14_delivery.md)

期权方向，另读：

- [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md)
- [options/options_screener_learning.md](options/options_screener_learning.md)
- [options/buyside_strategy_learning.md](options/buyside_strategy_learning.md)

下一步数据库/缓存方向，请读：

- [architecture/database_cache_plan.md](architecture/database_cache_plan.md)
