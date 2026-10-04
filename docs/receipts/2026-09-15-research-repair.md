# 研究域修复 · 本地源码与隔离验证

范围为 9 月 13 日 E2E 的研究域缺陷；本记录不是整站最终验收，也不声明已部署。

## 已修

1. 新 `strategy_definition` 候选不再把 JSON 当 Python 解析。目录读取它实际绑定的名称、公式、因子参数、持仓与调仓规则；候选的 source SHA → definition digest → 指定 validation SHA → 两引擎文件形成精确关联。单独的只读历史读取器不修改严格激活验证器，不从 `entry.latest` 或同名策略借指标。
2. `GET /api/research-evaluation?key=research:strategy-…` 返回该策略已保存证据，不再 422。新定义不送进旧单因子参考组合；直接旧链接显示历史证据与对应“我的策略”入口，旧通用刷新请求返回解释清楚的 409，不运行错误协议。
3. 模板默认均为 Futu；样例源只保留显式开发选择。没有执行器的草稿同时取消可运行徽标、参数和提交能力；后端原有拒绝保持。
4. 因子体检中的回撤、胜率、覆盖率、换手和分位收益差按百分比显示；交易次数/样本数按整数显示，原始数值未改。
5. “我的策略”加载后按 URL 指定的精确策略定位，历史分组需要时展开；不触发验证或启用。
6. 模拟 AI 复盘的后续失败会区分模型设置、文字结构、证据引用、无依据推断等固定原因。旧 `ValueError` 原因没有被保存，读取时解释这一限制但保持失败、事实与原文件不变；没有重新调用 Grok。

## 实际历史文件复核

只读正式 book 及其指向的文件，使用修改后的源码读取，零 provider/model/账户写。

- 5 个新版定义的名称与 Platform 原始指标恢复。包括 24 股月度动量：`total_return=8.063788394693573`、`sharpe=1.001362349140119`，历史区间 `2018-01-02` 至 `2026-09-08`。这不是本轮新计算，也没有改动历史结果。
- 这些 Qlib 原回放文件没有保存 `metrics.sharpe/total_return` 汇总字段；表格仍空白并解释，绝不复制 Platform 指标。
- 2 个更早定义缺 `history_start` 且无专属验证摘要绑定。原文件标题可展示，但不能补字段把它们变成当前可运行版本，也不能随便选一个验证结果。

## 检查

- 重要复现先红：定义误解析、422、默认 sample 等 8 项失败；修后通过。模拟校验原因 3 项先红后绿。
- 六组后端聚焦测试合计 80 项通过；之后新增旧 schema 测试并重跑定义组，10 项通过（当前合计 81 项，后一个不是整批重跑）。文件为 `test_definition_collection`、`test_collection_catalog`、`test_api_strategy_universe_catalog`、`test_research_evaluation_service`、`test_paper_evaluation`、`test_strategy_library`。
- 七组前端测试 37 项通过：DataPreviewTable、StrategyCatalogWorkbench、CollectionWorkbench、ResearchEvaluationView、StrategyLibraryPanel、catalogPresentationUsage、strategyPayload。
- 本域 Ruff、ESLint、`git diff --check` 通过。
- 全局 type-check 初次通过；并发的统一 Results 新增 `data_mode` 尚待根代理生成 API 类型时再次检查报两个对应类型错误。没有修改他人文件以掩盖它。
- 浏览器整批验收由根代理统一完成；这里不把组件测试当作浏览器通过。

本分工未 commit/deploy、未调用 provider/model、未重做历史回测、未启用候选、未手工运行模拟周期。

## 追加：路由与周/月报可读性

- 整批 E2E 发现 server page 尚保留旧 key 正则，已修 `app/research-evaluation/page.tsx`；直接执行该页面的 6 项测试覆盖 strategy、artifact、非法及数组参数。不是只修后端。
- 对现有 W36 数据库快照进行只读复核，发现标题中的收益百分数、现金金额与 `pnl_pct` 小数比例使用了不同单位。公开版省略账户金额和收益明细；单位混用这一原始问题及只读复核结论保留。
- 周/月报展示仅格式化能与其自身快照字段对应且带明确单位/字段标签的数字，提供“查看原始生成文字”。原始数据库、来源标题、新闻数字、日期及模型版本不改；模糊散文中的单位不猜。
- 后续起草与复核提示共同约束两位小数、金额分隔、比例单位与中文标签，不再要求逐字复制原始字段名或浮点长串。没有调用模型验证生成质量。
- 新周/月报的事实包识别缺价标记和旧 `avg_cost_fallback` 持仓。缺价端点的市值、盈亏和投资比例保持未知，现金不变；成本参考额单独保留，不参与期间变化计算。已发布旧周报不重算或改库。
- 追加前端三文件 34 项通过（两个周报测试共 28 项，加页面参数 6 项）；三个后端文件 59 项通过（`test_brief_rollup`、`test_brief_rollup_llm`、`test_api_brief_rollups`），Ruff/ESLint 通过。全局类型检查仍由根代理在完成其并发字段与 fixture 更新后复核。

## 追加：交叉复核后授权的对冲数量与费用修复

独立复核没有改自己已作者的研究逻辑；发现了请求来源被当实际来源、归档补回显式未知市值、对冲数量与费用三个 P2。前两项交由根代理处理，本分工获授权修第三项。

- 本工具仅支持正整数股数；前端与 API 都不再把 1.5 截断为 1。0、负数、布尔值和非整数拒绝。
- 仅支持标准 100 股期权；显式非标准或无效的 `contract_size/multiplier` 拒绝，未提供规格沿用标准合约假设并在结果说明。
- 看跌保护张数向上取整；卖出看涨张数向下取整，不得超过实际持股。少于 100 股不生成 collar。
- 250 股例子，PUT 中价 1.10、CALL 中价 0.60：买 3 张 put，卖 2 张 call；额外 put 保护 50 股，看涨覆盖 200 股，整套净支出 `3 × 110 − 2 × 60 = 210`。单组净支出 50 另列，不能代替合计。
- 原 `contracts_needed` 对 collar 表示成对组数，额外 put 单列；`estimated_debit/estimated_net_debit` 明确为整套总额。每腿数量与费用另有字段，网页在原 JSON 上方用中文显示数量、额外保护与整套费用。
- 有效红测试为后端 14 个失败、前端整数输入校验 1 个失败，修后相关后端两文件 45 项通过、前端三文件 34 项通过；Ruff、ESLint、全局 type-check 和 diff 检查通过。全部使用离线隔离输入，无真实交易、行情调用或正式账户写入。

## 追加：全量后端发现的五处试验账入口遗漏

`test_every_backtest_engine_callsite_is_enumerated_or_exempted` 发现的五处，不能直接全部豁免。

- `strategy_runtime._run` 已由 `strategy_library.validate_strategy` 在 Qlib 和 DSR 之前记录该定义的净收益试验；本轮补登记准确的 owner，不再给毛收益、基准和同池对照重复计数。
- `profile_backtests._run` 之前只在未来验证时通过 `_record_study_family` 补记成功方案。现在 `run_studies` 当次完成后立即记账；已有 `recorded-study` 身份规则不变，后续补记和重复相同研究不会翻倍。
- `_discover` 现在保留训练期结果。被训练筛选拒绝但确实计算出有效净值的假说也记试验；通过筛选的训练分段仅作审计记录，完整净组合只记一次。失败无净值时保留明确跳过原因，不制造收益或样本数。
- `reference_backtests` 的三个纯计算入口保持无副作用。外层 `refresh_evaluation` 将实际净组合写入试验账；月频毛收益、草稿缺结果、rolling 基线对照仅作跳过记录，不混入每日净收益的 DSR 分组。Qlib 每折与 QQQ 基准不单独充当新的搜索试验。
- 新评价试验身份绑定实际行情/特征摘要、研究配置、代码摘要和所评价方案，排除刷新时间、新运行目录和 `captured_at`。同冻结输入与配置的重复结果复用；同身份返回不同收益会报冲突，不默默计成一个新试验。所有新调用都先完成记账再继续；写账异常不被记账 helper 吞掉。
- 未更改 DSR 计算、0.95 门槛、原定义验证身份、旧历史结论；未启动正式研究或对旧任务执行补账。新增产品逻辑约 190 行，仍为现有账本的 owner 接线，无新假设注册系统。
- 两条关键 owner 复现先红（研究结果已完成但账本 0 行），修后五个相关文件共 **79 项通过**，含纯函数无写、净/毛/对照区分、同冻结输入重复、以后补记不翻倍、收益冲突拒绝及训练拒绝结果落账。两个 owner 文件 Ruff 和 diff 检查通过；`trials.py` 的旧类型/zip/长行告警与旧 OP0k 测试 SIM300 已用 HEAD 基线对照确认属于原有内容，没有借此改动统计代码。
