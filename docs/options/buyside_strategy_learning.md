# 买方美股期权策略助手

Phase 14 新增了面向看涨多头权利金 (long premium) 结构的买方美股期权策略助手。
它仅用于决策支持，不会下单、解锁账户，也不会调用任何交易 API。

## 范围

已实现的部分：

- 针对只读富途期权数据的标准化期权记录。
- 用于论点、腿 (leg)、评分、候选方案和情景的买方数据契约。
- 单合约质量指标。
- 候选方案生成，支持：
  - Long Call（买入看涨）
  - Bull Call Spread（牛市看涨价差）
  - LEAPS Call（长期看涨）
- LEAPS Call Spread（长期看涨价差）
- 使用希腊字母 (Greek) 近似的情景实验室 (Scenario Lab)。
- 对推荐进行排序并给出解释的确定性决策规则。
- 面向只读富途数据的本地 API 与 CLI 接线。
- 位于 `/options-buyside` 的前端页面。
- 必需的风险披露与反建议语言检查。

未实现的部分：

- 精确的期权定价模型。
- 盈利概率 (probability of profit)。
- 对角价差或日历价差。
- 实盘交易或下单。

## 主要文件

| 文件 | 用途 |
|---|---|
| `src/quant_system/options/option_data.py` | 将数据提供方的期权行标准化为平台记录。 |
| `src/quant_system/options/models.py` | 新增买方论点、腿、评分、候选方案和情景模型。 |
| `src/quant_system/options/buy_side_metrics.py` | 对单个期权合约评分并生成告警。 |
| `src/quant_system/options/buy_side_strategy.py` | 从期权链构建并排序买方策略候选方案。 |
| `src/quant_system/options/buy_side_scenarios.py` | 使用希腊字母近似估算情景损益。 |
| `src/quant_system/options/buy_side_decision.py` | 应用确定性决策规则与解释。 |
| `src/quant_system/api/routes/options.py` | 暴露 `POST /api/options/buy-side/assistant`。 |
| `src/quant_system/cli.py` | 暴露 `quant-system options buyside-screen`。 |
| `src/frontend/app/options-buyside/page.tsx` | 前端路由。 |
| `src/frontend/components/forms/BuySideOptionsAssistant.tsx` | 论点表单、推荐、检查清单与情景实验室。 |

## 数据流

```text
Futu read-only option data
  -> option_data.normalize_option_records
  -> BuySideStrategyLeg
  -> buy_side_metrics score
  -> buy_side_strategy candidate ranking
  -> buy_side_decision explanation and demotion labels
  -> buy_side_scenarios scenario matrix
  -> API / CLI / frontend read-only display
```

每一步都是纯粹的研究输出。这些文件均无法提交、修改或取消订单。

## 重要假设

当前的富途映射采用以下约定：

- `theta` 被视为每张合约每天的期权价格变化。
- `vega` 被视为每 1 个波动率点的期权价格变化。
- 合约乘数默认为 100，除非数据提供方另有说明。
- 缺失的希腊字母、IV、未平仓量、成交量、过期报价以及无效的买卖价，在可能的情况下
  作为告警处理，而非自动崩溃。

这些假设由测试锁定。如果数据提供方的约定发生变化，请同步更新测试与文档。

## 策略逻辑

多头权利金结构通过以下维度进行比较：

- 相对于目标价的方向契合度。
- IV 与波动率观点。
- Theta 负担。
- 流动性。
- 希腊字母效率。
- 可定义情况下的回报/风险。
- 来自现有 VIX 体制 (regime) 模块的市场体制惩罚。

高 VIX 体制对多头权利金的惩罚大于价差，因为隐含波动率挤压 (IV crush) 会损害裸买
看涨。价差受到的惩罚较小，因为空头腿抵消了部分 vega 暴露。

## 情景实验室的局限

情景实验室使用一阶/二阶希腊字母近似：

```text
new value ~= mid + delta * spot move
                 + 0.5 * gamma * spot move^2
                 + vega * IV change
                 + theta * days passed
```

它有意保持近似性：

- 当标的价格变动超过约 +/-15% 时，精度下降。
- 当经过时间超过 30 天时，精度下降。
- 临近到期的 Theta 加速未被建模。
- Vanna、charm、vomma 及其他交叉希腊字母被忽略。

每一行情景都包含一个 `approximation_reliability` 值：

- `high`
- `medium`
- `low`

## 安全用语

输出是定量研究辅助工具，而非投资建议。该模块并不了解用户的账户、风险承受能力、税务
状况、执行质量或真实成交价格。它不得被描述为交易推荐引擎。

前端必须显示以下必需的披露：

```text
This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading.
```

在交易期权之前应阅读 OCC 的 `Characteristics and Risks of Standardized Options`。
该披露是一项必需的风险控制，而非装饰性文字。

## API 契约

端点：

```text
POST /api/options/buy-side/assistant
```

请求体 schema：`BuySideAssistantRequest`。

关键字段：

| 字段 | 是否必需 | 说明 |
|---|---:|---|
| `ticker` | 是 | 美股标的代码，例如 `AAPL`。 |
| `view_type` | 是 | 受支持的看涨论点观点之一。 |
| `target_price` | 是 | 用户论点的目标价。 |
| `target_date` | 是 | ISO 日期，例如 `2026-12-31`。 |
| `provider` | 否 | 默认为 `futu`；其他数据提供方返回 400。 |
| `spot_price` | 否 | 可选覆盖值；缺省时 API 读取富途报价快照。 |
| `iv_rank` | 否 | 可选的 0-100 IV 排名。 |
| `user_scenarios` | 否 | 可选的主观情景 EV 输入。 |
| `scenario_spot_changes` | 否 | 可选的情景实验室标的变动网格。 |
| `scenario_iv_changes` | 否 | 可选的情景实验室 IV 变动网格。 |
| `scenario_days_passed` | 否 | 可选的情景实验室经过时间网格。 |
| `max_recommendations` | 否 | 默认为 10，最大 50。 |

响应体 schema：`BuySideAssistantResponse`。

顶层字段：

| 字段 | 说明 |
|---|---|
| `ticker` | 标准化后的标的代码。 |
| `thesis` | 已验证决策输入的回显。 |
| `recommendations` | 排序后的策略结果，含理由、风险、评分、情景摘要、降级徽章与告警。 |
| `recommendations[].legs` | 前端比较表所使用的腿。 |
| `recommendations[].net_debit` | 已定义情况下的净权利金支出。 |
| `assumptions` | 只读的研究与近似假设。 |

API 安全中间件还会向 JSON 响应追加惯常的 `safety` 页脚。

错误响应：

| 状态码 | 含义 |
|---:|---|
| 400 | 不受支持的数据提供方或无效的参数组合。 |
| 403 | 富途报价权限不足。 |
| 404 | 未找到标的、无可用的标的价格，或无可用的期权链。 |
| 422 | 无效的论点输入。 |
| 503 | 富途 OpenD/数据提供方不可用或超时。 |

请求示例：

```json
{
  "ticker": "AAPL",
  "view_type": "long_term_aggressive_bullish",
  "target_price": 220,
  "target_date": "2026-12-31",
  "provider": "futu",
  "iv_rank": 35,
  "max_recommendations": 5
}
```

响应结构示例：

```json
{
  "ticker": "AAPL",
  "recommendations": [
    {
      "strategy_type": "leaps_call",
      "rank": 1,
      "score": 78.2,
      "one_line_summary": "LEAPS Call is more suitable for the stated thesis under the current assumptions.",
      "primary_risk_source": "volatility",
      "warnings": []
    }
  ],
  "assumptions": ["Quantitative decision support only; no order placement is available."]
}
```

## 前端

打开：

```text
http://127.0.0.1:3001/options-buyside
```

该页面包含：

- 交易论点表单。
- 市场快照面板。
- 策略推荐卡片。
- 策略比较表。
- 反踩坑检查清单。
- 情景实验室摘要与用户输入的主观 EV。
- 必需的风险披露。
- 每张推荐卡片直接展示具体选定的期权腿。
- 推荐详情面板可独立展开，因此可以并排查看多个结构。

### Phase 14 后续 UI 调整

论点表单现在会在用户更改看涨观点时应用观点类型预设。这些预设会更新风险偏好、封顶上行
设置、IV 观点、事件风险设置、目标日期、情景实验室区间以及 IV 变动假设。它们仅是表单
默认值；用户在运行助手前仍可编辑这些字段。

UI 从论点面板移除了最大亏损预算字段，因为买方助手已经按结构报告最大亏损，且本阶段不
管理账户规模。情景实验室现在询问的是一个时间范围日期，而非原始的天数字符串。前端会在
调用 API 之前将该日期转换为 0 / 中点 / 时间范围日的检查。

主观 EV 面板是一个用户输入的期望值计算。它不是市场隐含概率模型，也不应被解读为预测。

富途限流响应被作为临时的数据提供方故障处理。后端会等待一次并重试该只读请求。如果 OpenD
仍然拒绝该请求，前端会显示明确的数据提供方错误，用户应等待后再重新运行同一标的。

## 快速验证

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system/options/buy_side_decision.py src/quant_system/api/routes/options.py src/quant_system/cli.py tests/test_options_buy_side_decision.py tests/test_api_options_buy_side.py tests/test_options_buy_side_cli.py
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```
