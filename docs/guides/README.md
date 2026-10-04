# 界面操作与说明指南

这些文档面向"看着界面理解不了它在干什么"的使用者。每篇都**基于真实代码**编写，诚实说明每个界面**实际**能做什么、怎么操作、字段含义，以及当前"承诺 vs 实现"的落差与改进建议。

## 研究流水线与研究入口

| 指南 | 界面路由 | 一句话 |
|---|---|---|
| [策略保存、组合与研究评价](strategy-library.md) | `/strategy-library`、`/research-evaluation` | 保存明确规则；查看逐期选股、相对基准表现和27项因子记分卡；验证与资金准入分别记录。 |
| [因子实验室 Factor Lab](factor-lab.md) | `/factor-lab` | 因子诊断面板（IC、IC 衰减、分位收益、择时）+ 可保存的因子研究运行；数据源/股票池/择时标的/基准可在侧栏调整，并可把当前上下文发送至回测器预填表单。 |
| [美股风险与市场对照](market-cross-section.md) | `/watch?pane=cross` | 估值、行情与波动的有来源观察评分；Grok解读另列；价格和板块对照可展开。 |
| [亚洲泡沫与区域对照](asia-radar.md) | `/watch?pane=radar` | 亚洲市场ETF的估值、趋势、回撤与来源；AI解读不冒充已校准崩盘概率。 |
| [回测器 Backtester](backtester.md) | `/backtest` | 因子打分、选股、历史成交与绩效计算；不直接给模拟运行资格。 |
| [公司研究](company-research.md) | `/company-research` | 通过Longbridge读取公司财报、估值和事件资料；当前公司资料不冒充历史时点可用财报。 |
| [策略目录 Strategy Catalog](strategy-catalog.md) | `/strategies` | 注册表驱动的策略启动器，按 schema 自动生成参数表单。 |
| [实验管理 Experiments](experiments.md) | `/experiments` | 在 sample/futu/tiingo 数据源上做参数网格扫描，可显式开启滚动验证折，按 Sharpe 选最佳，并保持发送至回测的数据源一致。 |
| [模拟交易 Paper Trading](paper-trading.md) | `/paper-trading` | 持久 100 万模拟账户：手动下单 + 策略一键再平衡；另含历史回放（研究）。 |
| [持仓地图 Position Map](position-map.md) | `/paper-trading?view=map` | 模拟账户实时持仓地图；旧 `/position-map` 为 301 alias。 |
| [期权推荐](options-recommendations.md) | `/options-radar` | 22:00 自动任务、立即更新、六态、物理 EV、IVR warming 与故障边界。 |
| [AI 新闻研究流 AI News](ai-news.md) | `/ai-news` | AI HOT 只读新闻入口：精选/全部动态、分类/关键词/时间窗筛选、日报、原文链接；不触发策略、回测或模拟账户。 |
| [Hermes 助手与会话](hermes-sessions.md) | `/hermes` | managed local-trust composer、saved-session 深链、server-side key、034 与 public-off 边界；旧 `/hermes/sessions` 为 301 alias。 |

## 重设计

- [模拟交易 + 持仓地图 重设计](../design/paper_trading_position_map_redesign.md) — 单一 100 万模拟账户、策略「一键再平衡」+ 可选定时、手动美股下单（优先 Futu 实时快照，离线时只回退到真实最近收盘价，绝不使用演示价格）、统一持仓地图。**阶段 1-5 已实现**；该文档记录目标形态、API 设计与分阶段实现，落地后的操作说明见上面两份指南。
- [Paper Strategy Sleeves](../design/paper_strategy_sleeves_plan.md) — 策略资金段 / signal-only / allocated 分账设计。MVP-2 已完成手动 pending execution 与 next-open paper execution processor；自动运维路线见 [MVP-3 Operations & Automation](../design/paper_strategy_sleeves_mvp3_operations_plan.md)，执行状态见 [Paper Strategy Sleeves 执行说明](../execution/paper_strategy_sleeves.md)。

## 阅读建议

- 先读 [回测器](backtester.md) 建立"因子→策略→下单→绩效"的整体直觉，其余界面都是围绕这条链路的不同切面。
- 模拟交易与持仓地图已按重设计落地：直接读 [模拟交易](paper-trading.md) 与 [持仓地图](position-map.md) 即可上手；想了解设计取舍再看重设计文档。
- 调试本地 Hermes 连接前先读 [Hermes 会话读取](hermes-sessions.md)；不要把 upstream Bearer key 放进浏览器，也不要把 session read 误写成 chat 已接通。
