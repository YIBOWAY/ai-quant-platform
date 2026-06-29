# 界面操作与说明指南

这些文档面向"看着界面理解不了它在干什么"的使用者。每篇都**基于真实代码**编写，诚实说明每个界面**实际**能做什么、怎么操作、字段含义，以及当前"承诺 vs 实现"的落差与改进建议。

## 研究流水线六个界面

| 指南 | 界面路由 | 一句话 |
|---|---|---|
| [因子实验室 Factor Lab](factor-lab.md) | `/factor-lab` | 因子诊断面板（IC、IC 衰减、分位收益、择时）+ 可保存的因子研究运行；数据源/股票池/择时标的/基准可在侧栏调整，并可把当前上下文发送至回测器预填表单。 |
| [回测器 Backtester](backtester.md) | `/backtest` | 真正能跑的回测引擎：因子打分→选股→下单→撮合→绩效；六个界面里最名副其实。 |
| [策略目录 Strategy Catalog](strategy-catalog.md) | `/replications` | 注册表驱动的策略启动器，按 schema 自动生成参数表单。 |
| [实验管理 Experiments](experiments.md) | `/experiments` | 在 sample/futu/tiingo 数据源上做参数网格扫描，可显式开启滚动验证折，按 Sharpe 选最佳，并保持发送至回测的数据源一致。 |
| [模拟交易 Paper Trading](paper-trading.md) | `/paper-trading` | 持久 100 万模拟账户：手动下单 + 策略一键再平衡；另含历史回放（研究）。 |
| [持仓地图 Position Map](position-map.md) | `/position-map` | 模拟账户实时持仓地图（净值/暴露/来源归因），另含回测暴露对比块。 |

## 重设计

- [模拟交易 + 持仓地图 重设计](../design/paper_trading_position_map_redesign.md) — 单一 100 万模拟账户、策略「一键再平衡」+ 可选定时、手动美股下单（优先 Futu 实时快照，离线时只回退到真实最近收盘价，绝不使用演示价格）、统一持仓地图。**阶段 1-5 已实现**；该文档记录目标形态、API 设计与分阶段实现，落地后的操作说明见上面两份指南。
- [Paper Strategy Sleeves](../design/paper_strategy_sleeves_plan.md) — 策略资金段 / signal-only / allocated 分账设计。MVP-2 已完成手动 pending execution 与 next-open paper execution processor；自动运维路线见 [MVP-3 Operations & Automation](../design/paper_strategy_sleeves_mvp3_operations_plan.md)，执行状态见 [Paper Strategy Sleeves 执行说明](../execution/paper_strategy_sleeves.md)。

## 阅读建议

- 先读 [回测器](backtester.md) 建立"因子→策略→下单→绩效"的整体直觉，其余界面都是围绕这条链路的不同切面。
- 模拟交易与持仓地图已按重设计落地：直接读 [模拟交易](paper-trading.md) 与 [持仓地图](position-map.md) 即可上手；想了解设计取舍再看重设计文档。
