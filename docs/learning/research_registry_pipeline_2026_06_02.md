# 研究流水线注册表改造说明

这次改造把“因子、策略、股票池、回测、Factor Lab”接成更清晰的研究流水线。

## 1. 总体方向

新的工作方式是：

1. 研究者阅读研报或提出想法。
2. 开发者在后端实现并测试新因子，再把它登记进因子注册表。
3. 新策略进入后端策略注册表。
4. 前端从注册表读取可用因子、策略和股票池。
5. 回测器负责把因子组合、股票池和策略拼起来验证。
6. Factor Lab 只做只读体检，不再让用户手动输入单只股票后得到难解释的结果。

这条线仍然只用于研究和模拟，不会下单，也不会接入真实交易上下文。
因子开发是后台代码优先的流程：不计划在前端提供自由输入因子表达式的
“造因子”界面。这样可以把因子逻辑、测试、泄漏检查和注册表元数据放在同一
条受控路径里。

## 2. 新增注册表

### StrategyRegistry

策略目录由后端 `StrategyRegistry` 提供。

当前登记了三个条目：

- `cross_sectional_top_n`：横截面排序买入 Top-N。
- `reversal_momentum`：短期反转 / 长期动量论文复现。
- `mean_reversion_top_n`：均值回归，买入综合打分最低的 Top-N（横截面 Top-N 的反向对照）。

前端 `/replications` 现在是“策略目录”，会读取 `GET /api/strategies`，按每个策略声明的参数表单自动渲染，不再为每个策略单独手写一整页。每个策略会标注它是“可在独立回测器运行”还是“仅在目录内运行（论文复现）”。

### UniverseRegistry

股票池由后端 `UniverseRegistry` 提供。

当前预设包括：

- `etf`
- `technology`
- `defense`
- `healthcare`

前端通过 `GET /api/universes` 读取这些股票池，回测器可以直接选择。

## 3. 回测器变化

回测器不再只使用写死的默认因子。

现在 `POST /api/backtests/run` 支持：

- `strategy_id`
- `universe_id`
- `factor_ids`
- `weights`
- `benchmark_symbol`
- `rebalance_frequency`：`every_bar`（默认，逐K线再平衡）/ `weekly` / `monthly`，按周/月只在周期边界再平衡，期间持仓不动。
- `max_weight_per_symbol`：单标的权重上限（0–1，留空不限制）。
- `sector_cap` + `sector_map`：行业权重上限（仅向下缩放超限行业，不再分配释放出的权重）。这个能力保留在 API / 后端代码层，必须同时提供行业映射；只传 `sector_cap` 会被拒绝。前端回测器当前只展示更明确的单标的上限。

这些新参数默认等同于原行为，不影响已有运行结果；其中行业上限只有在提供 `sector_map` 时才生效。回测结果新增**收益归因**（按持仓数量做盯市的每标的贡献），通过 `metrics.attribution`、`attribution.parquet` 落盘，并在回测详情页以 "Return Attribution" 表展示。

默认基准改为 `SPY`，不再拿输入列表第一个标的当基准。用户也可以在回测器里手动填写基准。

当前回测器可运行的 `result_type="backtest"` 策略有 `cross_sectional_top_n` 和
`mean_reversion_top_n`，两者都走 `POST /api/backtests/run`。回测引擎按 `strategy_id`
分发（`src/quant_system/backtest/pipeline.py` 的 `_BACKTEST_STRATEGY_BUILDERS`）。
新增一个回测策略 = 在 `strategies/registry.py` 登记 metadata（`result_type="backtest"`）
+ 在 builder 表里加一个构造项，前端无需改动即可选用并运行。论文复现策略
`reversal_momentum` 仍走自己的论文复现接口。

## 4. Factor Lab 变化

Factor Lab 现在是只读看板，不再是用户输入表单。

它分成两个引擎：

### 引擎 A：横截面体检

在固定股票池上，对全部已登记因子计算：

- IC
- IC 衰减
- 分位收益差
- 换手
- 覆盖度

这个结果用于判断因子有没有横向区分能力。

### 引擎 B：单标的择时

默认用 `QQQ` 做单标的时序测试。

每个因子会按 z-score 形成一个简单的进出场信号，然后输出：

- Sharpe
- 最大回撤
- 胜率
- 交易次数
- 覆盖度

这个结果用于判断因子在单一标的上是否有择时价值。

## 5. 护栏

Factor Lab 页面明确标注：

- 结果是探索性的。
- 因子很容易过拟合。
- 使用前需要继续做滚动验证和泄漏检查。

后端返回里包含：

- `WalkForwardConfig`
- 基础 leakage audit 状态
- 本地缓存路径

当前缓存是本地 JSON 文件，后续可以升级成 DuckDB 定时刷新，和期权缓存保持一致。

刷新方式：

```powershell
quant-system factor refresh-lab --provider sample --universe-id etf --symbol QQQ --benchmark-symbol QQQ
```

这个命令适合放进 Windows 任务计划程序或其他定时任务里。前端 Factor Lab 页面只读取缓存和后端返回结果，不提供手动下单或交易相关操作。

## 6. 新增接口

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/strategies` | 读取策略目录 |
| GET | `/api/universes` | 读取股票池目录 |
| GET | `/api/factors/lab` | 读取 Factor Lab 只读看板 |
| POST | `/api/backtests/run` | 支持策略、股票池、因子组合、权重和基准 |

## 7. 安全边界

这次改造没有新增真实交易能力。

仍然保持：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `kill_switch = true`

所有结果都是研究和模拟用途，不是投资建议。
