# 模拟交易 Paper Trading（界面路由：`/paper-trading`）

> 适用读者：第一次打开这个界面、却"看不懂它到底在干什么"的使用者。
> 安全红线：本平台**纯本地、仅研究 / 仅模拟**，永不接触真实下单、钱包、私钥签名或券商账户。本页面也**无法**提交任何真实订单（前端没有这条通路，后端 `live_trading_enabled` 默认 `False`）。

---

## 一句话定位

`/paper-trading` 自 2026-06-11 重构起分成**两个标签页**（共享 `Tabs` 组件，`role="tab"`）：

1. **「实时账户」标签页（默认，主角）** — 一个**持续存在、初始 100 万美元**的虚拟账户。你可以**手动买卖美股**，也可以**一键按策略再平衡**；两种操作都汇入同一个账户，并实时反映到[持仓地图](position-map.md)。这是大多数人对"模拟盘"的预期。
2. **「历史回放（研究）」标签页（次要）** — 填"标的 + 起止日期 + 初始资金"，对历史区间做一次批量回测式回放。它**不影响**账户，本质是穿着交易台外衣的研究回测；标签页顶部有"仅研究"的信息横幅。

本文先讲账户，再讲历史回放。

---

## 它解决什么问题 / 为什么存在

把"研究"和"模拟操盘"分成两件事：

- 想**练手 / 体验持仓与盈亏**：用上方的**模拟账户**，像在券商 App 里一样买卖，或让策略替你调仓。
- 想**验证一个策略在历史上的表现**：用下方的**历史回放**（与 `/backtest` 同源的执行链路）。

---

## 它实际能做什么（基于真实代码）

### A. 模拟账户

账户是一个**持久实体**（`src/quant_system/execution/account.py` 的 `PaperAccount`）：现金 + 持仓（含均价 `avg_cost`）+ 已实现盈亏 + 一条完整审计账本。账户状态与账本一起落盘在 `<data>/api_runs/paper_account/default/account.json`，最新持仓另存为 `positions_snapshot.parquet`，跨请求、跨重启持续存在。

**手动下单**（`POST /api/paper/account/orders`）：
- 选标的、买/卖、按**数量（股）**或**金额（美元）**下单（二选一），可选**限价**。
- 成交价：**优先 Futu 实时快照**（`fetch_market_snapshots`，需 OpenD 在线）；OpenD 不在线时只回退到**本地缓存或 Tiingo 的真实历史收盘价**；都拿不到就拒单。持续账户绝不会用 sample 演示价格成交。UI 与账本都标注 `price_kind`（`futu_snapshot` / `last_close`）。
- 限价单**真正生效但不持久挂单**：买单仅在市价 ≤ 限价时成交，卖单仅在市价 ≥ 限价时成交；价格条件不满足时记为 `unfilled`，不会进入挂单队列等待下一次价格刷新。
- 资金或持仓不足时，订单会明确显示为“部分成交”，并写明实际成交数量，不会再误报为全部成交。

**一键策略再平衡**（`POST /api/paper/account/rebalance`）：
- 选一个策略（`cross_sectional_top_n` / `mean_reversion_top_n`）、候选标的、`top_n`、`lookback`。
- 后端用账户**当前净值**算目标权重，与现有持仓求差（先卖后买），逐单过风控 → 撮合 → 更新账户，成交来源标记为 `strategy:<id>`。
- 再平衡只接受 Futu / Tiingo 等真实历史数据；sample 演示策略历史不能改变持续账户。
- **原子性保证**：再平衡先在账户副本上**全量试算**，只有"所有腿都能成交"才提交到真实账户；只要有一腿被拒，**整体中止、不动账户**（不会出现"卖光了却买不进、变成全现金"），并如实返回 `aborted=true`。

**账户冻结开关**（`POST /api/paper/account/kill-switch`）：账户级冻结，**默认关闭**（账户可交易）。冻结后任何新单返回 409。这是一个**真正可切换**的开关，取代了旧版那个"点了只弹说明"的假按钮。

**账本与重置**：每一笔成交、拒单、未成交、冻结、再平衡中止都写入账本（`GET /api/paper/account/ledger`，最新在前）。重置（`POST /api/paper/account/reset`）会先把旧账户**归档**到 `archive/` 再开新账户。

并发安全：网页请求会在进程内串行，网页与 CLI / 定时任务之间还会使用账户锁文件串行；定时再平衡与手动下单同时发生也不会丢记录。

### B. 历史回放（`POST /api/paper/run`，在「历史回放（研究）」标签页）

逐 bar 回放：因子信号 → `ScoreSignalStrategy` 目标权重 → 先卖后买生成订单 → 风控 → 模拟撮合（次 bar 开盘价）。产出订单 / 成交 / 风控触发 parquet + 报告，列在运行索引里。标签页内：左侧 360px 卡是回放表单（`PaperRunForm`，默认 `SPY,QQQ` + `futu` + 截至今天的滚动 180 天窗口；安全锁开关常开，点它弹出说明对话框），右侧是最新运行指标、运行历史表（可切换显示被隐藏的 sample 运行）、成交 / 订单生命周期 / 风控触发明细表。当一次运行 0 成交且风控触发 > 0 时，页面会显示「全局安全锁拦截了订单」的解释卡。注意它受**全局** `QS_KILL_SWITCH` 约束（默认开 → 该路径会拦截订单），这条与上面的账户级冻结是两回事。

---

## 操作步骤

### 手动买入一只美股
1. 打开 `/paper-trading`，默认在「实时账户」标签页：左侧是账户摘要卡（净值 / 总盈亏（金额+%）/ 现金 / 已投资比例）、持仓面板（逐标的「手动 vs 策略」来源徽章 + 权重条 + 报价来源）和最近 8 条账本流水（带「在持仓地图查看」链接）；右侧 360px 栏是交易面板（AccountTradePanel）与安全状态徽章（paper / live / 账户冻结 / 回放安全锁）。
2. 在交易面板「手动下单」：填标的（如 `AAPL`）、选「买入」、选「数量」或「金额」、填数值，可选限价。
3. 点「提交订单」。成交后账户摘要与[持仓地图](position-map.md)立即更新；右上角提示成交状态。

「实时账户」与「历史回放（研究）」分属两个标签页，互不混淆；历史回放的全局安全锁提示不代表当前账户已冻结。手机端通过顶部菜单进入各主要页面。

### 让策略替你调仓
1. 在「策略再平衡」面板选策略、候选标的（如 `SPY,QQQ,IWM,DIA`）、`top_n`、`lookback`。
2. 点「按策略再平衡」。若全部腿可成交则提交并提示成交数；若中止会提示原因（不动账户）。

### 冻结 / 解冻
- 「账户冻结」面板一键切换。冻结时手动下单与再平衡都会被挡下。

### 定时自动再平衡（可选，阶段 5）
命令行 `quant-system paper rebalance --account default --strategy cross_sectional_top_n`，可挂到 Windows 任务计划程序按交易日定时触发。**完全失败时该命令以非零码退出**（不会假报成功）。

---

## 字段与指标含义

| 名称 | 含义 |
|---|---|
| 账户净值 equity | 现金 + 持仓市值（按当前报价） |
| 总盈亏 pnl | 净值 − 初始本金（金额与百分比） |
| 现金 cash | 可用现金 |
| 持仓数 | 当前持有的不同标的数量 |
| avg_cost 均价 | 建仓加权成本（含买入手续费），卖出时据此结算已实现盈亏 |
| price_kind | 报价来源：`futu_snapshot`（实时）/ `last_close`（最近收盘） |
| source_breakdown | 该持仓中「手动 / 策略」各自占比 |
| aborted | 再平衡是否因某腿被拒而整体中止 |

---

## 当前的局限与注意

- 暂不支持做空 / 杠杆（先支持多头 + 卖出已持有）；负持仓未开放。
- 暂为单一账户（`default`）、单一币种（USD）；数据模型已为多账户预留 `account_id`。
- 历史回放路径仍受全局 `QS_KILL_SWITCH` 约束，与账户级冻结互不相同，别混淆。
- 期权 / 预测市场不纳入这个现货账户。

---

## 合理性评估与改进建议

账户模型把"研究"和"模拟操盘"清晰分开，修复了旧版"名为模拟实为回测""默认 0 成交""持仓地图读不到模拟持仓"的核心落差。后续可做：实时逐笔行情流（当前为手动 / 30 秒轮询刷新）、做空与保证金建模、多账户。

设计与分阶段实现详见 [模拟交易 + 持仓地图 重设计](../design/paper_trading_position_map_redesign.md)。

---

## 相关代码入口

- 账户模型 / 账本：`src/quant_system/execution/account.py`
- 账户持久化：`src/quant_system/execution/account_storage.py`
- 取价（Futu 快照→最近收盘）：`src/quant_system/execution/price_source.py`
- 下单 / 再平衡服务：`src/quant_system/execution/account_service.py`
- 撮合 / 风控（复用）：`src/quant_system/execution/paper_broker.py`、`order_manager.py`、`src/quant_system/risk/engine.py`
- API：`src/quant_system/api/routes/paper.py`、`src/quant_system/api/schemas/paper.py`
- CLI 定时再平衡：`src/quant_system/cli.py`（`paper rebalance` / `paper account-show`）
- 前端：`src/frontend/app/paper-trading/page.tsx`、`src/frontend/components/forms/AccountTradePanel.tsx`
- 历史回放（旧路径）：`src/quant_system/execution/pipeline.py`
