# 模拟交易 + 持仓地图 重设计（设计文档 + 分阶段实现计划）

> 状态：**阶段 1-5 已全部实现并验证（2026-06-04）**。本文件原为设计与分阶段实现计划，现作为该设计的记录保留；落地后的操作说明见 [../guides/paper-trading.md](../guides/paper-trading.md) 与 [../guides/position-map.md](../guides/position-map.md)。
> 安全红线不变：纯本地、仅模拟、只读真实行情。**绝不**新增真实下单 / 解锁账户 / 钱包 / 签名 / 券商交易上下文。
> 已交付要点：单一持久账户（默认 100 万）、手动下单（数量/金额、限价单可进入 `pending_orders`，会预留购买力/可卖数量，并通过账户页手动检查触价或逐单取消）、策略一键再平衡（由策略注册表 `supports_account_rebalance` 能力位准入，plan-then-commit 原子性）、账户级冻结开关、Futu 实时快照取价（离线只回退真实最近收盘）、逐持仓报价来源、账户驱动的持仓地图、CLI 定时再平衡、网页与定时任务跨进程串行保护、移动端导航。代码入口见本文第 10 节与 [../../AGENTS.md](../../AGENTS.md) 的「Paper Account」一节。未完成：后台定时撮合、停机期间日内高低价回溯补判。

## 1. 目标与动机

使用者反馈：当前「模拟交易」与「持仓地图」两个界面**难以理解、彼此脱节**，看不出要干什么。这不是错觉，而是真实的实现落差（见第 2 节现状诊断）。

本次重设计要把这两个界面合并成一个连贯的故事：

- **一个持续存在的模拟账户**，初始资金 **1,000,000 美元**（可配置），跨多次操作**持续累积**，而不是每次跑完即弃。
- **两种下单方式，汇入同一个账户**：
  1. **自动**：选择一个策略，点一下「按该策略再平衡到目标持仓」，把策略目标仓位应用到账户；并提供**可选的定时调度**（如每个交易日触发一次）。
  2. **手动**：自己挑选美股标的，输入买/卖、数量或金额，直接对账户下单。
- **统一的持仓地图**：无论自动还是手动下的单，都实时反映在**同一张持仓地图**里——账户净值 vs 100 万基准、现金、各标的暴露、盈亏、以及每个仓位来自「策略」还是「手动」的归因。

成交价格策略（已与使用者确认）：**优先 Futu 实时快照报价**；当 OpenD 未运行 / 未登录时，**只回退到本地缓存或 Tiingo 的真实历史收盘价**，并在 UI 明确标注用的是哪种价格。演示数据绝不能用于改变持续模拟账户；真实价格都拿不到时直接拒单。

## 2. 现状诊断（基于真实代码）

> 全部结论来自对 `src/quant_system/execution/`、`src/quant_system/api/routes/paper.py`、`src/frontend/app/paper-trading/`、`src/frontend/app/position-map/` 的实读。

### 2.1 「模拟交易」其实是第二个回测引擎

`POST /paper/run`（`api/routes/paper.py`）→ `run_paper_trading`（`execution/pipeline.py`）需要 `start`/`end` 日期区间，对历史 OHLCV 做**批量回放**：逐 bar 让 `ScoreSignalStrategy` 算目标权重 → `_generate_rebalance_requests`（先卖后买）→ `OrderManager.create_and_submit` → `RiskEngine.check_order` → `PaperBroker` 以**当根 bar 的 open 价**撮合。

落差：
- **没有「现在」**：必须填历史起止日期，本质是回测，不是实时模拟。
- **没有手动下单**：代码里没有任何手动/自选下单路径。
- **没有持续账户**：每次 run 都 `PaperPortfolio(initial_cash=...)` 新建一个内存组合，run 结束即弃。
- **初始资金默认 10 万**（schema `PaperRunRequest.initial_cash=100_000`、pipeline 默认 `100_000.0`），不是 100 万。

### 2.2 开箱即用「0 成交」的陷阱

`RiskEngine.check_order`（`risk/engine.py:25`）把 `kill_switch` 当成**每一笔订单的违规项**：

```python
if self.limits.kill_switch:
    breaches.append(self._breach(request, "kill_switch", "kill switch is enabled"))
```

而全局安全默认 `QS_KILL_SWITCH=True`。于是默认配置下**每一单都被拒**：订单数 > 0、成交数 = 0、`final_equity` 不变、一堆 `risk_breach`。对新用户来说看起来像「坏了」。同时 `POST /paper/run` 在全局 kill switch 打开、且请求未带 `enable_kill_switch` 时直接返回 **409**。

### 2.3 持仓地图根本读不到模拟持仓

`execution/pipeline.py:_persist_paper_run` 只落盘 `orders / order_events / trades / risk_breaches` 四个 parquet，**从不写持仓快照**。`PaperPortfolio.positions`（`execution/portfolio.py`）在 run 期间是有完整持仓的，但 run 一结束就被丢弃。

因此 `src/frontend/app/position-map/page.tsx` 的暴露条形图实际上来自**最近一次回测**（`getBacktestDetail` 的 `positions.parquet`），模拟交易侧只贡献一个 `risk_breach_count`。「持仓地图」与「模拟交易账户」之间**没有任何数据关系**——这正是使用者觉得莫名其妙的根因。

### 2.4 可复用的健康基件（好消息）

执行层本身是干净、可复用的，重设计**不必推倒重来**：

| 基件 | 文件 | 能力 |
|---|---|---|
| `PaperPortfolio` | `execution/portfolio.py` | `cash` + `positions` + `apply_fill()` + `equity(prices)`，已是一个账本雏形 |
| `PaperBroker` | `execution/paper_broker.py` | `process_market_data(prices)` 按价格撮合、滑点/佣金、现金与持仓约束 |
| `OrderManager` | `execution/order_manager.py` | `create_and_submit()` 串起风控→撮合，记录 order/event/trade/breach |
| `RiskEngine` | `risk/engine.py` | 逐单 + 组合层风控检查 |
| `OrderRequest` / `ExecutionFill` | `execution/models.py` | 已有完整订单/成交模型，含 `reason` 字段可承载来源标记 |
| Futu 实时快照 | `data/providers/futu.py:319/341` | `fetch_market_snapshots()` / `fetch_underlying_snapshot()`（**已存在**，只读） |

> 关键判断：**手动下单 + 持续账户所需的撮合与风控原语已经全部存在**。缺的是「持久账户实体」「手动下单入口」「实时报价取价」「持仓快照持久化」以及把 kill switch 与「拒绝下单」解耦。这是一个后端工程，但增量明确、风险可控。

## 3. 目标形态（重设计后）

### 3.1 核心概念：持久模拟账户（Paper Account）

引入一个**单一、持续、可持久化**的模拟账户实体，与「不可变的历史回放 run」彻底分开。

```text
PaperAccount
├─ account_id            固定单账户，如 "default"（为将来多账户预留）
├─ base_currency         "USD"
├─ initial_cash          1_000_000.00（开户时一次性写入，可配置）
├─ cash                  当前总现金
├─ available_cash        扣除待处理买入限价单预留后的可用现金
├─ reserved_cash         待处理买入限价单预留现金
├─ positions            { symbol -> { quantity, avg_cost } }   # avg_cost 用于盈亏
├─ created_at / updated_at
└─ ledger               追加式事件流（见 3.2）
```

账本（ledger）是账户的**完整审计流水**。当前实现把现金、持仓、已实现盈亏和完整账本一起保存在 `account.json`；读取时直接校验并加载这份账户快照，而不是仅靠账本单独回放恢复。每一条账本事件携带：

```text
LedgerEntry
├─ entry_id, timestamp
├─ kind                 "deposit" | "fill" | "rebalance_fill" | "fee" | "reset"
├─ source              "manual" | "strategy:<strategy_id>" | "system"
├─ symbol, side, quantity, price, gross_value, commission
├─ price_kind          "futu_snapshot" | "last_close"   # 成交价来源，UI 据此标注
└─ note
```

> `source` 字段让持仓地图能把每个仓位/每笔盈亏拆分成「策略 vs 手动」归因——这正是使用者想要的统一视图。底层复用现有 `ExecutionFill`，`source` 可先借 `OrderRequest.reason` 承载，物化时落到独立列。

### 3.2 两条下单路径，汇入同一账户

```text
                       ┌────────────────────────┐
   手动下单表单 ──────▶ │                        │
   (symbol/side/qty)   │   取价层 PriceSource     │──▶ OrderRequest
                       │  Futu 快照→回退最近收盘   │        │
   策略「一键再平衡」──▶ │                        │        ▼
   (strategy_id)        └────────────────────────┘   RiskEngine.check_order
                                                            │ 批准
                                                            ▼
                                                   PaperBroker 撮合(现价)
                                                            │
                                                            ▼
                                            PaperAccount.apply_fill + 追加 ledger
                                                            │
                                                            ▼
                                              持久化账户快照 + 持仓快照
```

**路径 A — 自动（一键再平衡 + 可选定时）**
- 用户选一个已注册且 `supports_account_rebalance=true` 的策略（复用 `StrategyRegistry`，当前支持 `cross_sectional_top_n` / `mean_reversion_top_n`）。
- 后端用账户当前净值算目标权重 → 目标市值 → 与当前持仓求差（先卖后买；所有当前持仓和目标标的都必须有有限正价格，否则整体中止）→ 逐单过 `RiskEngine` → `PaperBroker` 以**当前价**撮合 → 更新账户 + 写账本，`source="strategy:<id>"`。
- **触发方式**：默认「按需」——用户点「按此策略再平衡」按钮触发一次。**可选定时**：一个轻量调度（见 4.3 阶段，复用 Phase 13 已有的 Windows Task Scheduler 模式 `quant-system` CLI 子命令），如每个交易日收盘后触发一次再平衡。调度是**增强项**，不阻塞主流程。

**路径 B — 手动（自选美股）**
- 用户在下单票里填 `symbol`（美股）、`side`（买/卖）、`quantity` 或 `notional`（金额，二选一）、可选 `limit_price`。
- 后端取价 → 构造 `OrderRequest(reason="manual")` → `RiskEngine.check_order` → `PaperBroker` 撮合 → 更新账户 + 写账本，`source="manual"`。
- 金额单 `notional` 在取价后换算成 `quantity = notional / price`。

> 两条路径在「构造 OrderRequest 之后」完全共用同一套风控/撮合/账本代码，保证两种来源的成交对账户的影响完全一致。

### 3.3 取价层（PriceSource）

新增一个薄取价抽象，专为「现价成交」服务：

```python
class PaperPriceSource:
    def get_price(self, symbol: str) -> PricedQuote:
        # 1) 若 Futu OpenD 可达：fetch_market_snapshots([symbol]) 取最新价
        #    -> PricedQuote(price=..., price_kind="futu_snapshot", as_of=...)
        # 2) 否则回退：该 symbol 最近一根可得历史收盘价（Tiingo / 本地缓存）
        #    -> PricedQuote(price=..., price_kind="last_close", as_of=...)
        # 3) 都拿不到：抛出可读错误，下单前置失败（不静默成交）
```

- 复用 `FutuMarketDataProvider.fetch_market_snapshots()`（已存在，只读）。
- `price_kind` 一路带到账本与 UI，用户永远知道这笔是按「实时快照」还是「最近收盘」成交的。
- 持续账户严格排除 sample 演示价格与 sample 策略历史；它们只可用于研究回放和测试。
- 严格只读：取价绝不触发任何下单/解锁。

### 3.4 kill switch 语义修正（仅模拟侧）

当前 `RiskEngine` 把 kill switch 当成「拒绝每一单」，导致默认 0 成交。重设计：

- **模拟账户路径**：kill switch 表达「**冻结这个模拟账户**」的用户意图，默认 **关闭（账户可交易）**。它仍是一个真实的闸门（打开时拒绝该账户的新单），但不再是「开箱即用全拒」的默认值。
- 全局 `QS_KILL_SWITCH`（实盘保护）语义**不动**——它继续保护任何「实盘」概念（本平台并不存在实盘路径，因此它对模拟账户不应是硬阻断）。
- UI 提供一个**真正可切换**的账户级冻结开关（取代当前「点了只弹说明、要改 .env」的假按钮）。

> 安全说明：这不削弱安全红线。平台从来没有、也不会有真实下单路径；kill switch 在本平台的意义是「暂停模拟账户活动」，把它从「让模拟功能默认不可用」改成「用户可控的账户冻结」，是修正一个 UX bug，不是放开任何真实交易能力。

### 3.5 统一持仓地图

持仓地图改为**账户驱动**（而非「最近一次回测驱动」）：

- 顶部：账户净值、相对 100 万基准的总盈亏（金额 + %）、可用现金、已投资比例 / 杠杆%、未实现盈亏。
- 暴露条形图：每个 symbol 一条，宽度 = 该仓位市值 / 总市值；颜色区分多/空；**每条标注「策略 / 手动」来源占比**。
- 持仓表：symbol、数量、均价（avg_cost）、现价、市值、权重、未实现盈亏、来源。
- 价格来源标注：整页显示「报价来源：Futu 实时 / 最近收盘（as_of 时间）」。
- 「最近一次回测暴露」作为**独立的对比区块**保留（不再冒充账户持仓），让「研究 vs 模拟账户」一目了然。

## 4. API 设计（新增 / 调整）

> 全部在现有 FastAPI `/api` 前缀下，loopback-only 默认不变。原有 `POST /paper/run`（批量历史回放）**保留**，重定位为「策略回放 / 历史模拟」，不再承担「账户」职责。

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/paper/account` | 返回账户：总现金、可用现金、预留现金、净值、持仓（含均价/现价/盈亏/来源）、相对基准盈亏、价格来源标注 |
| `POST` | `/api/paper/account/orders` | 手动下单：`{symbol, side, quantity\|notional, limit_price?}` → 取价 → 风控 → 撮合 → 更新账户 |
| `POST` | `/api/paper/account/orders/process` | 手动检查待处理限价单：按当前真实纸面价格重新撮合，触价则更新账户 |
| `POST` | `/api/paper/account/orders/{order_id}/cancel` | 取消单个待处理限价单：移出 `pending_orders` 并写入 `order_cancelled` 账本事件 |
| `POST` | `/api/paper/account/rebalance` | 自动：`{strategy_id, params?}` → 先校验策略注册表 `supports_account_rebalance` → 按账户净值算目标 → 批量再平衡到目标持仓 |
| `GET` | `/api/paper/account/ledger` | 账本事件流（分页），用于流水/审计/盈亏归因 |
| `POST` | `/api/paper/account/kill-switch` | 切换账户冻结开关（真正可切换，取代假按钮） |
| `POST` | `/api/paper/account/reset` | 重置账户回初始资金（写一条 `kind="reset"` 账本，便于复盘） |
| `GET` | `/api/health` | 不变；账户冻结状态从账户接口读，不再混用全局 flag |

返回示例（`GET /api/paper/account`，示意）：

```json
{
  "account_id": "default",
  "base_currency": "USD",
  "initial_cash": 1000000.0,
  "cash": 742130.55,
  "equity": 1013874.20,
  "pnl_abs": 13874.20,
  "pnl_pct": 0.0139,
  "price_source": { "kind": "futu_snapshot", "as_of": "2026-06-04T20:00:00Z" },
  "kill_switch": false,
  "positions": [
    {
      "symbol": "AAPL", "quantity": 800, "avg_cost": 188.40,
      "last_price": 195.10, "market_value": 156080.0, "weight": 0.154,
      "unrealized_pnl": 5360.0, "source_breakdown": { "manual": 0.6, "strategy:cross_sectional_top_n": 0.4 }
    }
  ]
}
```

## 5. 数据与持久化

- 账户与账本持久化到本地（与现有 run 工件并列）：
  - 文件形态：`data/api_runs/paper_account/<account_id>/account.json`（含完整账本）+ `positions_snapshot.parquet` + `archive/`。
  - 可选索引：复用现有**可选 PostgreSQL run index**（`storage/runs_repository.py`）的模式，新增账户/账本表；默认仍以文件为准、DB 不可用时回退（与现有策略一致）。
- **修复 §2.3**：无论账户路径还是保留的历史回放路径，`_persist_paper_run` / 账户写盘都要**输出持仓快照**（`positions_snapshot.parquet`：symbol/quantity/avg_cost/last_price/market_value/weight/source），这样持仓地图可以直接读账户持仓，而不是回退到回测。
- 账户是**长期可变**实体（与不可变 run 相反）：每次下单/再平衡后原子更新 `account.json`，并重写最新持仓快照；重置前归档旧账户。

## 6. 分阶段实现计划

> 每个阶段都能独立交付、独立验证（pytest + 前端 lint/build），不破坏现有功能。**默认安全不变**：仅模拟、只读行情、无真实下单。

### 阶段 1 — 持久账户后端骨架（无 UI 改动）
- 新增 `PaperAccount` + `Ledger` 模型与本地读写（账户快照与完整审计流水一并保存）。
- 新增 `GET /api/paper/account`、`POST /api/paper/account/reset`；默认开户 100 万。
- 复用 `PaperPortfolio.apply_fill` 语义，新增 `avg_cost` 跟踪（买入加权、卖出不动均价）。
- 测试：开户、入金、成交后得到正确现金/持仓/均价，并能跨请求和重启恢复。
- 验收：`GET /api/paper/account` 返回干净的 100 万空账户。

### 阶段 2 — 取价层 + 手动下单
- 新增 `PaperPriceSource`：Futu 快照优先（复用 `fetch_market_snapshots`），只回退本地/Tiingo 的真实最近收盘；带 `price_kind`/`as_of`，绝不以 sample 数据成交。
- 新增 `POST /api/paper/account/orders`：取价 → `OrderRequest(reason="manual")` → `RiskEngine` → `PaperBroker` → 更新账户 + 写账本。
- kill switch 解耦：账户级冻结开关，默认关闭；`POST /api/paper/account/kill-switch`。
- 测试：手动买/卖改变现金与持仓；部分成交如实提示；OpenD 不可达时仅回退真实最近收盘并正确标注；没有真实价格时拒单；冻结时拒单。
- 验收：能对空账户手动买入 AAPL，账户与账本正确反映。

### 阶段 3 — 策略「一键再平衡」
- 新增 `POST /api/paper/account/rebalance`：按账户净值算目标权重（复用 `StrategyRegistry` + 现有再平衡求差逻辑）→ 批量过风控/撮合 → 写账本 `source="strategy:<id>"`。
- 测试：再平衡把账户带到目标持仓；与手动持仓正确合并（同 symbol 合并、来源占比正确）。
- 验收：在已有手动持仓的账户上跑一次策略再平衡，持仓/现金/来源归因正确。

### 阶段 4 — 统一持仓地图（前端）
- `position-map` 改为读 `GET /api/paper/account`：净值/基准盈亏/可用现金/暴露/持仓表/来源归因/价格来源标注。
- 把「最近一次回测暴露」降级为独立对比区块。
- 模拟交易页：加「手动下单票」+「选策略一键再平衡」+ 真正的账户冻结开关；保留「历史回放」入口但更名澄清。
- 持仓快照持久化接入（§5），供地图与详情页读取。
- 测试：前端 lint/build；E2E 冒烟（下单→地图更新）。
- 验收：手动买入与策略再平衡都即时反映在同一张持仓地图。

### 阶段 5 —（可选增强）定时调度 + 实时刷新
- 复用 Phase 13 的 Windows Task Scheduler 模式，新增 `quant-system paper rebalance --account default --strategy <id>` CLI 子命令，可挂到每个交易日定时触发。
- 持仓地图可选轮询/手动刷新，按 Futu 快照重算盈亏（仍只读）。
- 验收：定时任务跑通一次自动再平衡并落账本；地图刷新显示最新盈亏。

## 7. 与安全红线的关系（务必维持）

- 全程**仅模拟**：`PaperBroker` 是模拟撮合，**不**新增任何 Futu 交易上下文 / `unlock_trade` / `place_order` / 钱包 / 签名。
- Futu 仅用于**只读取价**（snapshot/历史 OHLCV），与现有用法一致。
- kill switch 修正只影响「模拟账户能否下模拟单」，不触碰任何实盘概念（本平台无实盘路径）。
- `/api/health` 的 `live_trading_enabled=false` 等标志保持不变。
- 新接口同样走现有 safety-footer 中间件与 loopback-only 默认绑定。

## 8. 暂不在本次范围内（Non-goals）

- 实时逐笔行情流 / WebSocket 推送（阶段 5 仅做手动/轮询刷新）。
- 做空、保证金、杠杆的完整建模（先支持多头 + 卖出已持有；负持仓暂不开放）。
- 多账户 / 多币种（数据模型预留 `account_id`，但先固定单一 USD 账户）。
- 期权/预测市场纳入同一账户（本次仅美股现货模拟）。
- 真实成交、真实下单、任何触达券商的能力（**永久 non-goal**）。

## 9. 待确认的开放问题

1. 手动下单是否允许「金额单（notional）」与「数量单（quantity）」并存？（建议：并存，notional 取价后换算。）
2. 是否需要「整数股」约束（不允许碎股）？（建议：先允许碎股以简化，后续可加整数股选项。）
3. 策略再平衡触发后，是否保留每次再平衡的「快照对比」（再平衡前/后持仓 diff）？（建议：阶段 3 顺手记录到账本，便于复盘。）
4. 账户重置是否需要保留历史账户归档（而非直接清空）？（建议：reset 写账本事件 + 归档旧 `account.json`，可回溯。）

## 10. 相关代码入口（已实现）

| 关注点 | 文件 |
|---|---|
| 账户/账本 | `src/quant_system/execution/account.py`、`account_storage.py` |
| 下单/再平衡服务 | `src/quant_system/execution/account_service.py` |
| 取价（Futu 快照→最近收盘） | `src/quant_system/execution/price_source.py`（复用 `data/providers/futu.py` 的 `fetch_market_snapshots`） |
| 撮合 / 风控（复用） | `execution/paper_broker.py`、`execution/order_manager.py`、`risk/engine.py` |
| 组合/成交模型（复用） | `execution/portfolio.py`、`execution/models.py` |
| API | `api/routes/paper.py`（`/api/paper/account*`）、`api/schemas/paper.py` |
| 历史回放（保留） | `execution/pipeline.py`（`run_paper_trading`/`run_signal_paper_trading`） |
| 前端 | `src/frontend/app/paper-trading/page.tsx`、`components/forms/AccountTradePanel.tsx`、`lib/accountRebalanceStrategies.ts`、`app/position-map/page.tsx`、`components/AccountRefreshControl.tsx`、`lib/api.ts` |
| CLI 定时再平衡 | `src/quant_system/cli.py`（`paper rebalance` / `paper account-show`） |
