# Paper Strategy Sleeves MVP-1 设计文档

> 状态：设计草案，待实现。  
> 日期：2026-06-15。  
> 命名说明：本文的 **MVP-1** 指「Paper Strategy Sleeves」这条新业务线的第一实施阶段，**不是**项目历史阶段地图里的 Phase 1「数据层 MVP」。后续实现和提交信息应避免写成 `Phase 1`，统一写 `Paper Strategy Sleeves MVP-1`。

## 1. 背景与问题

当前平台已经有一个持久模拟账户：用户可以手动下单，也可以调用现有的一键策略再平衡。这个账户模型对「手动 + 策略共同落到账户」已经有基础，但它还不是用户现在想要的业务语义。

现有 `/api/paper/account/rebalance` 更接近「把整个账户调到策略目标」。它会把当前账户所有持仓纳入再平衡求差，因此可能卖出用户手动买入的仓位。这对「我只是想启动一个策略观察它，或者给它单独分配一笔模拟资金」来说语义过重。

这次新设计要引入 **strategy sleeve**：同一个模拟账户下的独立资金段。策略默认先观察信号；只有用户显式分配现金后，策略才可以在自己的资金段内做模拟执行。策略不能默认接管或卖出 `manual` 持仓。

## 2. 当前代码事实

这些事实来自当前代码阅读，后续实现前仍需以代码为准复核。

- `PaperAccount` 当前只有一份 `cash`，没有 sleeve 级现金。
- `AccountPosition.source_quantity` 可以记录持仓来源占比，例如 `manual` 或 `strategy:<id>`，但当前卖出时按来源比例扣减，不能表达「只卖某个 sleeve 的 lot」。
- `PaperAccountService.rebalance_to_strategy()` 当前按整个账户权益计算目标，并把目标标的与账户全部现有持仓都纳入再平衡。
- Futu 行情提供方已支持 `5m` K 线；但账户策略再平衡链路当前没有传 `interval`，实际仍走默认 `1d`。
- 现有文件存储和运行索引方向是：本地文件为事实来源，PostgreSQL 只是可选索引。

## 3. 已锁定业务不变量

这些是不应在实现阶段随意改变的规则。若后续必须改变，需要显式更新本文的决策日志。

1. **启动策略不等于立即交易。** 默认模式是 `signal_only`，只生成信号和建议，不动账户现金和持仓。
2. **allocated 执行必须显式分配现金。** 策略资金从现有模拟账户现金划拨，不能凭空创造新本金。
3. **一个持久模拟账户，多 sleeve。** 不做多个独立账户；总账户用于合并净值、持仓地图、账本和风险视图。
4. **sleeve 级资金和 lot 必须隔离。** `manual`、`strategy:<instance_id>` 等来源分别拥有现金和 lot。
5. **策略不能默认卖 manual lot。** 策略只能卖自己的 lot；用户若要转移或干预，必须显式操作并记录。
6. **手动交易默认作用于 manual sleeve。** 手动干预某个策略 sleeve 必须显式选择，并记为 `manual_intervention`。
7. **主视图可以合并，底层必须分账。** 持仓地图可显示一行 AAPL，但底层必须保存每个 sleeve 的数量、均价和归属。
8. **allocated 执行禁止 sample/fallback 合成数据。** 真实数据不可用时记录 `data_unavailable`、`missed` 或 `skipped`，不伪造成交。
9. **第一执行模型是 daily。** 默认 EOD 生成信号，下一交易日开盘模拟成交。near-close 5 分钟模式可后续加入，但不能补造错过的成交。
10. **用户操作优先于自动化。** 账户冻结、sleeve 暂停、状态变化或价格过期，都会阻止策略执行并记录原因。
11. **策略配置版本化。** 影响交易逻辑的配置变更必须生成新版本；运行中的 sleeve 绑定固定版本，升级必须显式操作。
12. **第一版只支持股票/ETF。** 期权和 Polymarket 保持研究/只读，不进入 sleeve 执行。

## 4. MVP-1 目标

MVP-1 的目标是建立正确的业务和会计基础，而不是一次性完成自动执行系统。

MVP-1 交付：

- 保存策略配置和版本。
- 创建 strategy sleeve：
  - `signal_only`
  - `allocated`
- allocated sleeve 的现金划拨与状态展示。
- manual 与 strategy sleeve 的现金/lot 分账模型。
- daily signal 生成并落盘。
- CLI 手动触发 signal generation。
- `/paper-trading` 增加最小 Strategy Sleeves 区域，能看到 sleeve、模式、状态、分配资金和最新信号。
- 新增执行文档，记录 CLI 命令和手动工作流。

MVP-1 成功标准：

- 用户可以保存一个策略配置版本。
- 用户可以创建一个 signal-only sleeve 并生成一条 daily 信号。
- 用户可以从账户现金划拨资金创建 allocated sleeve，但策略不会自动成交。
- 账户仍能明确区分 manual cash / strategy cash / manual lots / strategy lots。
- 现有全账户 rebalance 不被误认为新策略 sleeve 主入口。

## 5. MVP-1 非目标

这些内容不进入 MVP-1，防止范围失控。

- 不做完整自动成交。
- 不做 Windows Task Scheduler 调度落地，只记录后续 CLI 方向。
- 不做 next-open 自动撮合。
- 不做 near-close 5 分钟成交。
- 不做 pending execution 生命周期。
- 不做跨 sleeve 自动风险优化或再分配。
- 不做期权/Polymarket sleeve。
- 不允许裸因子直接运行伪实盘。
- 不进行 `/paper-trading` 全页面大改。
- 不引入复杂交易工作台 UI。
- 不改成多账户模型。

## 6. 领域模型（tentative）

字段名是暂定的。实现时可以调整，但必须保持第 3 节业务不变量。

### 6.1 StrategyConfig

保存一组可运行策略配置。它是 sleeve 的输入，不是一次性表单状态。

```text
StrategyConfig
├─ strategy_config_id
├─ version
├─ name
├─ description
├─ strategy_id                 # cross_sectional_top_n / mean_reversion_top_n
├─ universe_id
├─ symbols
├─ factor_ids
├─ weights
├─ lookback
├─ top_n
├─ rebalance_frequency
├─ max_weight_per_symbol
├─ min_order_value
├─ data_provider               # futu / tiingo for real paths
├─ execution_timing            # next_open by default; near_close_5m future
├─ created_at / updated_at
├─ archived
└─ metadata
```

交易逻辑字段变更必须生成新 `version`。`name`、`description`、`tags`、`archived` 可原地修改。

### 6.2 StrategySleeve

同一模拟账户下的策略资金段。

```text
StrategySleeve
├─ sleeve_id
├─ account_id
├─ strategy_config_id
├─ strategy_config_version
├─ mode                         # signal_only / allocated
├─ status                       # running / paused / stopped
├─ initial_allocated_cash
├─ cash
├─ created_at / updated_at
├─ paused_at
├─ stopped_at
├─ stop_reason
└─ metadata
```

`signal_only` sleeve 可以没有 `initial_allocated_cash`。`allocated` sleeve 必须从账户现金划拨。

### 6.3 SleeveLot

按 sleeve 保存持仓 lot 和成本。主视图可以聚合，但卖出和绩效必须以 lot 为准。

```text
SleeveLot
├─ lot_id
├─ account_id
├─ sleeve_id                    # manual 或 strategy sleeve id
├─ symbol
├─ quantity
├─ avg_cost
├─ opened_at
├─ updated_at
└─ source                       # manual / strategy:<sleeve_id>
```

MVP-1 可以先把 `manual` 也视为一个特殊 sleeve，方便统一处理。

### 6.4 StrategySignal

daily signal 的不可变记录。

```text
StrategySignal
├─ signal_id
├─ sleeve_id
├─ strategy_config_id
├─ strategy_config_version
├─ signal_date
├─ generated_at
├─ data_provider
├─ data_as_of
├─ target_weights
├─ proposed_orders
├─ warnings
├─ status                       # generated / data_unavailable / invalid
└─ metadata
```

MVP-1 只生成和展示信号，不执行订单。

## 7. 因子到策略配置的路线

MVP-1 不允许裸因子直接进入 sleeve。

后续因子优化路线：

```text
Factor Lab
  -> strategy draft
  -> backtest
  -> saved StrategyConfig version
  -> signal-only sleeve
  -> allocated sleeve
```

第一阶段的重点是让「因子如何变成可解释策略」清楚，而不是自动挖掘因子或自动上线。

策略草案至少需要补齐：

- universe / symbols
- factor_ids / weights
- top_n
- rebalance_frequency
- max_weight_per_symbol
- min_order_value
- data_provider
- execution_timing

保存为 StrategyConfig 前，应先跑回测并显示准入 checklist。

## 8. 策略准入 checklist

第一版采用软门槛，不替用户做投资判断。

建议状态：

- `ready`
- `review_recommended`
- `not_recommended`

检查项：

- 是否使用真实数据，而非 sample。
- 回测区间是否足够长。
- 是否有基准对比。
- 是否产生实际成交，不是 0 trade。
- 最大回撤是否低于用户设定阈值。
- 换手率是否过高。
- 是否存在 sample/fallback 数据警告。
- 是否通过 basic leakage check。
- 策略配置是否保存并版本化。

进入 `signal_only` 时可以继续。进入 `allocated` 时若存在严重红项，需要二次确认。

## 9. 文件存储（tentative）

MVP-1 继续采用本地文件作为事实来源。

```text
data/api_runs/paper_strategy_sleeves/
  strategy_configs/
    <strategy_config_id>/
      config.v1.json
      config.v2.json
      metadata.json
  sleeves/
    <sleeve_id>/
      sleeve.json
      signals.jsonl
      lots.parquet
      performance.parquet        # MVP-1 可为空或暂不生成
```

总账户账本仍记录实际账户事件。MVP-1 由于不做自动成交，主要新增事件是：

- sleeve created
- cash allocated
- signal generated
- sleeve paused/resumed/stopped
- manual intervention marker（若前端支持）

PostgreSQL 可选索引不作为 MVP-1 必需项。若启用，也只索引元数据和最近状态。

## 10. API 草案（tentative）

路径名可在实现前调整，但不要复用现有全账户 rebalance 作为 sleeve 主入口。

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/paper/strategy-configs` | 创建策略配置 v1 |
| `GET` | `/api/paper/strategy-configs` | 列出策略配置 |
| `POST` | `/api/paper/strategy-configs/{id}/versions` | 创建新版本 |
| `POST` | `/api/paper/strategy-sleeves` | 创建 signal-only 或 allocated sleeve |
| `GET` | `/api/paper/strategy-sleeves` | 列出 sleeves |
| `GET` | `/api/paper/strategy-sleeves/{id}` | 查看 sleeve 详情 |
| `POST` | `/api/paper/strategy-sleeves/{id}/signals` | 手动生成 daily 信号 |
| `POST` | `/api/paper/strategy-sleeves/{id}/pause` | 暂停 |
| `POST` | `/api/paper/strategy-sleeves/{id}/resume` | 恢复 |
| `POST` | `/api/paper/strategy-sleeves/{id}/stop` | 停止，默认保留持仓 |

旧接口处理：

- `/api/paper/account/rebalance` 保留为 legacy/advanced 全账户再平衡。
- UI 和文档必须明确它不是 strategy sleeve。
- 后续可隐藏到高级区或标记 deprecated。

## 11. CLI 草案（tentative）

MVP-1 必须记录 CLI 命令到执行文档。命令名称可在实现前调整。

```powershell
quant-system paper strategies config-create ...
quant-system paper strategies sleeve-create ...
quant-system paper strategies generate-signal --sleeve <id>
quant-system paper strategies sleeve-show --sleeve <id>
```

MVP-2 方向：

```powershell
quant-system paper strategies execute-pending --window next-open
quant-system paper strategies execute-pending --window near-close
```

CLI 不能只存在于代码里。新增或改名时必须同步更新：

- `docs/execution/paper_strategy_sleeves.md`
- `docs/guides/paper-trading.md`
- `docs/INDEX.md`

## 12. 前端 MVP-1

MVP-1 只做最小入口，不做全页面重设计。

在 `/paper-trading` 的实时账户标签页加入 `Strategy Sleeves` 区域：

- sleeve 名称
- 模式：`signal-only` / `allocated`
- 状态：running / paused / stopped
- allocated cash
- 最新信号时间
- 最新信号摘要
- 创建 signal-only sleeve
- 创建 allocated sleeve（分配现金）
- 暂停/恢复
- 更多操作：停止，默认保留持仓

UI 原则：

- 主操作只放暂停/恢复。
- 停止类操作放入更多操作。
- 清仓类操作不在 MVP-1。
- 不展示复杂交易工作台。
- 不弱化 paper-only / no live trading 安全文案。

## 13. 后续 UX Redesign 阶段

前端大改不属于 MVP-1。单独设阶段：

**Paper Strategy Sleeves UX Redesign**

推荐时机：MVP-1 完成后，MVP-2 自动执行设计定稿前后。

目标定位：

- 研究流水线管理台为主。
- 交易工作台为辅。

这个阶段应使用前端设计 skills 做 2-3 个信息架构/设计方案，再选定一个落到现有 Next.js / Tailwind 代码。

设计必须表达清楚：

```text
research -> backtest -> signal-only -> allocated sleeve -> pseudo-live execution -> review
```

重点展示：

- 状态
- 证据
- 信号解释
- 执行失败原因
- 手动干预
- 风险来源

交易按钮保持克制。实现后用 Playwright 做桌面和移动端截图验证。

## 14. MVP-2 自动执行方向

MVP-2 才进入自动成交。

默认路径：

- EOD 生成信号。
- 下一交易日开盘模拟成交。
- 真实数据不可用则跳过并记录。
- 不伪造成交。

near-close 方向：

- 使用上一交易日 EOD 信号。
- 在下一交易日收盘前约 5 分钟用真实 snapshot 或 5m bar 模拟成交。
- 若错过窗口，记录 `missed_window`，不事后用历史 5m K 线补造成交。

第一版自动化建议使用 CLI + Windows Task Scheduler，而不是把常驻调度器放进 FastAPI 进程。

## 15. 账户级风险方向

MVP-1 不做复杂账户级风险优化，但需要保留扩展方向。

后续可以增加：

- 总账户单标的暴露监控。
- 多 sleeve 同向持仓重叠提示。
- 可选硬上限，例如单标的总暴露不得超过 40%。
- 命中硬上限时跳过或缩小订单，并记录 `blocked_by_account_risk_limit`。
- 更长期可做风险预算、策略冲突检测、重叠持仓压缩和统一风险仪表盘。

不要在第一版做跨 sleeve 自动再分配。那会污染 sleeve 绩效归因。

## 16. MVP-1 实现拆分

实现顺序应先固化共享领域模型，再进入 API、CLI、前端和文档。不要从前端页面或调度器开始，否则容易把旧的全账户 rebalance 语义误带进新功能。

### 16.1 串行基础层

这些任务相互依赖，建议按顺序实现。

1. **领域模型与 schema**
   - 新增 `StrategyConfig`、`StrategySleeve`、`SleeveLot`、`StrategySignal` 的后端模型。
   - 明确枚举：`signal_only` / `allocated`、`running` / `paused` / `stopped`、`generated` / `data_unavailable` / `invalid`。
   - 明确哪些字段属于交易逻辑字段，哪些字段可原地编辑。

2. **本地文件存储**
   - 新增 strategy config、sleeve、signal 的读写模块。
   - 文件仍是 source of truth。
   - 写入需要保持原子性；失败时不能留下半写状态。

3. **账户分账能力**
   - 为 `manual` 和 strategy sleeve 建立现金/lot 分账语义。
   - allocated 创建时从账户可用现金划拨到 sleeve cash。
   - 不改动旧 `/api/paper/account/rebalance` 的行为。
   - 策略路径不能按比例卖出 `source_quantity`，必须能定位到自己的 sleeve lot。

4. **策略信号生成服务**
   - 从保存的 `StrategyConfig` 生成 daily signal。
   - MVP-1 只写入 `StrategySignal`，不产生实际 fill。
   - 数据不可用时写 `data_unavailable`，不使用 sample/fallback 合成数据。

5. **API contract**
   - 新增 strategy config 和 strategy sleeve API。
   - 保持旧全账户 rebalance 为 legacy/advanced。
   - mutation 路径沿用账户锁或同等互斥机制，避免现金划拨并发写冲突。

### 16.2 可并行工作

基础层稳定后，这些工作可以相对独立推进。

- **CLI**：实现 config-create、sleeve-create、generate-signal、sleeve-show。
- **前端最小入口**：在 `/paper-trading` 加 Strategy Sleeves 区域，调用已稳定 API。
- **用户指南更新**：补 `docs/guides/paper-trading.md` 的用户心智说明。
- **执行文档更新**：等 CLI/API 可运行后，再写 `docs/execution/paper_strategy_sleeves.md`。

### 16.3 验证闭环

每个阶段的验收应优先证明边界没有被破坏：

- signal-only 不改现金和持仓。
- allocated 创建只划拨现金，不自动成交。
- strategy sleeve 不卖 manual lot。
- sample/fallback 数据不能进入 allocated 信号或后续执行路径。
- legacy full-account rebalance 仍保持原行为，且不会被 UI 当作新 sleeve 主入口。

## 17. 测试与验收

MVP-1 需要测试：

- 创建 StrategyConfig v1。
- 修改交易逻辑字段生成新版本。
- 创建 signal-only sleeve 不改变账户现金。
- 创建 allocated sleeve 从 manual cash 划拨资金。
- manual sleeve 与 strategy sleeve 现金隔离。
- 同 symbol 多 sleeve lot 可并存。
- 策略不能卖 manual lot。
- 生成 daily signal 写入 `signals.jsonl`。
- sample 数据不能用于 allocated 路径。
- 暂停 sleeve 后不能生成执行计划。
- 现有 `/api/paper/account/rebalance` 行为不被误改。

文档验收：

- `docs/design/paper_strategy_sleeves_plan.md` 存在并说明 MVP-1 非目标。
- `docs/execution/paper_strategy_sleeves.md` 记录 CLI 命令。
- `docs/guides/paper-trading.md` 说明 Strategy Sleeves 的用户心智。
- `docs/INDEX.md` 有入口。

## 18. 决策日志

| 日期 | 决策 |
|---|---|
| 2026-06-15 | 主闭环是：真实行情数据 -> 因子/策略研究 -> 回测验证 -> 可选持久模拟账户执行 -> 持仓地图/账本/风险复盘。 |
| 2026-06-15 | 策略启动默认 signal-only；allocated 必须显式分配现金。 |
| 2026-06-15 | 一个持久账户，多 sleeve；不做多个独立策略账户。 |
| 2026-06-15 | 策略资金从账户现金划拨，不能创造新本金。 |
| 2026-06-15 | 主视图可合并持仓，底层必须按 sleeve lot 分账。 |
| 2026-06-15 | daily 默认 EOD 信号 + next open 成交；near-close 5 分钟作为后续可选模式。 |
| 2026-06-15 | 停止行为分 pause / stop keep holdings / stop liquidate；MVP-1 只做 pause/resume 和 stop keep holdings。 |
| 2026-06-15 | 裸因子不能直接运行 sleeve，必须先形成策略草案并回测后保存为 StrategyConfig。 |
| 2026-06-15 | MVP-1 不做完整自动成交，不做前端大改。 |
| 2026-06-15 | 后续前端大改单独命名为 Paper Strategy Sleeves UX Redesign，使用前端 skills 做多方案设计。 |

## 19. 相关代码入口

| 关注点 | 当前入口 |
|---|---|
| 持久账户模型 | `src/quant_system/execution/account.py` |
| 账户持久化 | `src/quant_system/execution/account_storage.py` |
| 账户服务 | `src/quant_system/execution/account_service.py` |
| 账户取价 | `src/quant_system/execution/price_source.py` |
| Futu OHLCV / snapshot | `src/quant_system/data/providers/futu.py` |
| 回测策略 | `src/quant_system/backtest/strategy.py` |
| 回测流水线 | `src/quant_system/backtest/pipeline.py` |
| 策略注册表 | `src/quant_system/strategies/registry.py` |
| Paper API | `src/quant_system/api/routes/paper.py` |
| Paper schemas | `src/quant_system/api/schemas/paper.py` |
| Paper Trading 前端 | `src/frontend/app/paper-trading/page.tsx` |
| 账户交易面板 | `src/frontend/components/forms/AccountTradePanel.tsx` |
| 持仓地图 | `src/frontend/app/position-map/page.tsx` |
