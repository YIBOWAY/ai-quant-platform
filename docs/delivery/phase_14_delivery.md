# Phase 14 交付说明

Phase 14 交付了买方美股期权策略助手，作为只读的量化决策支持工具。涵盖后端评分、
API / CLI 接线以及位于 `/options-buyside` 的前端页面。

## 已交付

- 富途期权记录规范化助手：
  - `src/quant_system/options/option_data.py`
- 买方数据合约：
  - `src/quant_system/options/models.py`
- 单合约指标引擎：
  - `src/quant_system/options/buy_side_metrics.py`
- 策略候选引擎：
  - `src/quant_system/options/buy_side_strategy.py`
- 情景实验室引擎：
  - `src/quant_system/options/buy_side_scenarios.py`
- 确定性决策引擎：
  - `src/quant_system/options/buy_side_decision.py`
- API 路由：
  - `POST /api/options/buy-side/assistant`
  - 请求 schema：`BuySideAssistantRequest`
  - 响应 schema：`BuySideAssistantResponse`
  - 已记录的错误码：400 / 403 / 404 / 422 / 503
- CLI 命令：
  - `quant-system options buyside-screen`
- 前端页面：
  - `/options-buyside`
  - 论点表单
  - 市场快照面板
  - 推荐卡片
  - 对比表格
  - 防坑清单
  - 情景实验室摘要
  - 必需的风险披露文本
- 市场状态买方惩罚：
  - `src/quant_system/options/market_regime.py`
- 测试：
  - `tests/test_options_option_data.py`
  - `tests/test_options_buy_side_models.py`
  - `tests/test_options_buy_side_metrics.py`
  - `tests/test_options_buy_side_strategy.py`
  - `tests/test_options_buy_side_scenarios.py`
  - `tests/test_options_buy_side_decision.py`
  - `tests/test_api_options_buy_side.py`
  - `tests/test_options_buy_side_cli.py`
  - `src/frontend/tests/e2e/phase14-buyside-smoke.spec.ts`

## Phase 14 后续扩展

在初始买方助手交付之后，本地期权研究界面扩展了以下功能：

- 本地 AlphaGBM 风格工具，页面 `/options-tools`。
- 期权雷达当日扫描及公开/样本缓存刷新控件，页面 `/options-radar`。
- 单标的雷达下钻，页面 `/options-radar/[symbol]`。
- 回测、因子及模拟交易的运行详情页。
- 使用最新保存的研究输出填充的 `/position-map` 页面。
- 增强的 `/experiments` 审阅：支持扫描、分折、对比及发送至回测视图。
- 本地 DuckDB 支持的富途期权报价缓存，期权页面共享使用。
- Data Explorer 默认数据源处理，清晰标注样本回退。

Phase 14 的原始范围仍为仅供研究使用，未增加任何交易能力。

## 安全状态

Phase 14 仍为仅供研究使用：

- 无实盘交易。
- 无下单。
- 无富途账户解锁。
- 无富途交易上下文。
- 无钱包或签名路径。
- 测试使用模拟/本地数据，不调用真实富途 API。

前端包含以下必需的风险披露：

```text
本工具仅提供量化决策支持，不构成投资建议。期权交易涉及风险，可能因时间衰退、
波动率变化、流动性及标的价格不利变动而迅速贬值。在实际交易前，请查阅官方期权
风险披露文件。
```

用户在交易期权前应阅读 OCC 的《标准化期权的特征与风险》。

## 验证记录

在 `ai-quant` 环境中的最新验证结果：

```powershell
conda activate ai-quant
python -m pytest -q
```

结果：最近一次验证中完整后端测试套件全部通过。

```powershell
ruff check src/quant_system tests
```

结果：全部检查通过。

```powershell
npm --prefix src/frontend run lint
```

结果：通过。

```powershell
npm --prefix src/frontend run build
```

结果：通过。

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1 tests/e2e/phase14-buyside-smoke.spec.ts
```

结果：浏览器冒烟测试通过。

## 已知限制

- 情景盈亏为近似值，基于希腊字母计算。
- 标的大幅波动和较长持有期会降低可靠性。
- 精确定价、盈利概率及事件驱动重定价超出 Phase 14 范围。
- 富途数据需要本地 OpenD 运行才能使用真实数据。
- 该助手在用户假设下比较不同结构；它不了解用户的账户、税务、执行质量或
  实际成交价格。

## 后续 QA 修复

在实际 UI 测试后，针对若干可用性和数据质量问题进行了收紧修复：

- 卖方筛选器推荐表现在默认隐藏 `Avoid` 合约。这使深度实值 put、
  零未平仓量合约以及过滤失败的条目不会显示在候选列表中。被拒绝的条目仍可通过
  `include_rejected=true` 进行审计查看。
- VIX 市场状态分类现在使用近三个月的 VIX/VIX3M 缓存窗口，与预期的状态横幅
  行为一致。
- 富途期权区间查询使用短期进程内缓存和本地 DuckDB 支持的期权报价缓存，以减少
  对相同标的和 DTE 窗口的重复请求。
- 期权雷达详情现在在存储的快照候选没有备注时显示回退说明，并且当快照仅由极小
  股票池生成时页面会给出警告。
- 买方页面的中文选择器现在渲染本地化标签，视图类型切换会应用合理的表单预设，
  max-loss 预算已从输入表单中移除，情景实验室使用 horizon 日期加上更清晰的
  主观 EV 文案。
- 来自 OpenD 的富途限频响应现被类型化为 `rate_limited`，数据源在重试只读请求
  前等待一次。这减少了在交互式期权页面切换 AAPL / SPY / QQQ / NVDA 时的重复
  失败。
- 期权雷达现在将已加载的同一 VIX 市场状态传递给逐标的筛选器，使雷达和单标的
  筛选器在同一次扫描日期中共用同一市场状态分类来源。
- 买方推荐卡片现在每张卡片上直接显示具体选中的合约，且多张卡片可同时保持详情
  展开。
- 可选 PostgreSQL 运行索引现已在后台初始化，使用短连接超时，短暂记住失败，
  并在数据库不可用时保持列表端点回退到文件系统。
- 回测页面不再暴露含义模糊的行业上限输入框。行业上限仅在提供 `sector_map`
  时对 API/脚本调用者可用；无映射的请求会被拒绝。
- 语言前缀导航现在在最新的回测和模拟运行链接、position-map 快捷方式、详情页
  返回链接及预测市场筛选提交中正确保留 `/zh/...` / `/en/...` 前缀。
- 一次 `quant-system options daily-scan --top 100` 的实盘尝试于 2026-05-05
  启动，但因富途限速在 30 分钟保护超时内未完成。一次较小范围的实盘刷新成功
  完成：

```powershell
conda activate ai-quant
quant-system options daily-scan --top 10
```

结果：

```text
run_date=2026-05-05 universe_size=10 scanned_tickers=10 failed_tickers=0 candidates=50
data=data\options_scans\2026-05-05.jsonl meta=data\options_scans\2026-05-05_meta.json
```

## 完成定义状态

- 后端测试：完整套件通过。
- 后端 lint：通过。
- 前端 lint/build：通过。
- 浏览器冒烟测试：通过。
- 风险披露：已包含。
- 投资建议用语审查：后端和浏览器测试已覆盖。
- 交易安全边界：未更改。
