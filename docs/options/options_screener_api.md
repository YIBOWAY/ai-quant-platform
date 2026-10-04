# 期权筛选器 API

## 概述

期权筛选器 API 提供基于 Futu OpenD 的只读期权研究端点。

任何端点都无法提交、修改、签名或下达真实订单。

## 端点

### GET `/api/options/expirations`

查询参数：

| 名称 | 是否必填 | 示例 |
|---|---|---|
| `ticker` | 是 | `AAPL` |
| `provider` | 否 | `futu` |

示例：

```powershell
curl "http://127.0.0.1:8765/api/options/expirations?ticker=AAPL&provider=futu"
```

响应结构：

```json
{
  "ticker": "AAPL",
  "provider": "futu",
  "expirations": ["2026-05-04"],
  "safety": {
    "dry_run": true,
    "paper_trading": true,
    "live_trading_enabled": false,
    "kill_switch": true,
    "bind_address": "127.0.0.1"
  }
}
```

### GET `/api/options/chain`

查询参数：

| 名称 | 是否必填 | 示例 |
|---|---|---|
| `ticker` | 是 | `AAPL` |
| `expiration` | 是 | `2026-05-04` |
| `provider` | 否 | `futu` |

示例：

```powershell
curl "http://127.0.0.1:8765/api/options/chain?ticker=AAPL&expiration=2026-05-04&provider=futu"
```

### POST `/api/options/screener`

请求体示例：

```json
{
  "ticker": "AAPL",
  "strategy_type": "sell_put",
  "provider": "futu",
  "min_premium": 0.1,
  "min_apr": 10,
  "min_dte": 10,
  "max_dte": 60,
  "max_spread_pct": 0.15,
  "min_open_interest": 50,
  "max_hv_iv": 1.5,
  "trend_filter": true,
  "hv_iv_filter": true
}
```

示例：

```powershell
curl -X POST "http://127.0.0.1:8765/api/options/screener" `
  -H "Content-Type: application/json" `
  -d "{\"ticker\":\"AAPL\",\"strategy_type\":\"sell_put\",\"provider\":\"futu\",\"min_apr\":10,\"min_dte\":10,\"max_dte\":60,\"max_spread_pct\":0.15,\"min_open_interest\":50}"
```

响应包含：

- 标的价格
- 已扫描的到期日数量及已扫描的到期日列表
- 候选数量
- 被剔除的数量
- 候选表格
- DTE / 价差 / 未平仓合约 / APR 筛选效果
- 假设条件
- 安全性页脚

如果省略 `expiration`，后端会扫描 `min_dte` 与 `max_dte` 区间内的每个 Futu 到期日，然后对合并后的候选列表进行排序。出于 API 兼容性考虑仍可传入 `expiration`，但前端并不要求提供。

筛选请求支持最低期权中间价、标的平均日成交量、市值、IV rank、财报窗口和历史回看天数等质量过滤器。
前端的三档预设会显式填入这些字段；`min_market_cap=0` 表示不启用市值硬过滤。

默认情况下 `Avoid` 行会被隐藏，以免主表格把不可用的卖方候选当作可供研究的项展示出来。将 `include_rejected` 设为 `true` 可返回这些行，用于审计 / 调试查看。对于备兑看涨 (covered call)，行权价低于当前股价属于硬性剔除；而趋势检查未通过仅会把一个本来可用的候选降级为 `Watch`。

## 错误映射

| 错误 | 常见原因 |
|---|---|
| `400` | ticker 无效、不支持的 provider、参数错误 |
| `403` | 权限被拒绝 |
| `404` | 无期权链或无市场数据 |
| `503` | OpenD 不可用或超时 |

不会返回原始的堆栈跟踪 (traceback)。

## 安全性

该 API 仅读取市场数据。它不暴露下单、券商、钱包、签名或实盘执行端点。

## 2026-10-04 筛选与年化口径

`min_apr` 使用整数百分数，例如 15 表示 15%，按中间价毛权利金年化计算。
未达到该值、最低 IV、最低权利金或用户已启用的趋势条件时，不进入合格候选。
`hard_gate_passed` 仍只表示报价、事件、流动性与物理 EV 等共同质量检查；
`screen_passed` 表示本次个人筛选条件。合格需要两者均通过，且评级不为 `Avoid`。
现有默认值与预设不会因零结果而自动放宽。

新增字段均为兼容性扩展：

| 字段 | 含义 |
|---|---|
| `scanned_contract_count` | 返回的整条期权链行数，尚未做 `top_n` 截断 |
| `identity_rejected_count` | 合约身份不一致、直接排除的行数 |
| `hard_gate_rejected_count` | 共同质量检查失败数，包含身份失败 |
| `preference_rejected_count` | 已过共同质量检查，但个人条件或市场状态不符 |
| `eligible_count` | 同时满足全部条件的总数，可能大于表格展示数 |
| `watch_candidates` | 最多 10 条仅供观察的个人条件不符合约，不计入合格候选；硬条件失败不会进入这里 |
| `apr_alternative_max_percent` | 只差 APR 条件时，这些合约中最高中间价权利金年化；只供用户判断，不修改配置 |
| `bid_annualized_yield` | 按买一价计算的毛权利金年化，小数比例 |
| `estimated_round_trip_fee_per_contract` | 用户估计的每张开仓与平仓总费用，美元；请求不填或 null 表示未知 |
| `fee_adjusted_bid_annualized_yield` | 扣上述估计费用后的买一价权利金年化；费用未知则 null |

互斥计数满足 `scanned_contract_count = hard_gate_rejected_count + preference_rejected_count + eligible_count`。
`rejection_summary` 是可重叠的原因计数，不能相加。旧 `candidates` 与
`include_rejected` 审计语义保留，前端必须按两个通过字段与评级区分合格行。
权利金按标准每张 100 股计算。买一价不保证成交，扣费权利金也未计入买回价格、指派及持股盈亏，
不能称为净策略收益。原有物理 EV 排序模型没有改成风险中性模型，也没有因新增费用字段而变成完整成本回测。
