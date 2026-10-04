# 期权筛选器学习指南

## 筛选器是什么

期权筛选器是一个研究工具，利用富途只读期权数据对期权候选合约进行排序。

它目前支持：

- Sell Put（卖出看跌）
- Covered Call / Sell Call（备兑看涨 / 卖出看涨）

它不是一个投顾引擎，也不会进行交易。

## 输入项

| 输入项 | 含义 |
|---|---|
| Ticker | 美股代码，例如 `AAPL` |
| Strategy | `Sell Put` 或 `Covered Call` |
| Min premium | 可接受的最小中间价权利金 |
| Min APR | 最小的简化年化权利金估算值 |
| Min / Max DTE | 以天为单位的到期窗口。后端会自动扫描该区间内所有富途到期日。 |
| Min IV | 可选的 IV 下限 |
| Max delta | 可选的绝对 delta 上限 |
| Max spread percentage | 剔除买卖价差过宽、流动性差的合约 |
| Min open interest | 剔除未平仓量过低的稀薄合约 |
| Max HV/IV | 剔除已实现波动率相对 IV 过高的情形 |
| Trend filter | 可选项，基于近期股价历史的 EMA21 + SMA50 趋势检查 |
| HV/IV filter | 可选项，对隐含波动率与计算得到的历史波动率进行比较 |

## 预设方案

前端包含三种预设方案：

- `Conservative`：更低的 delta、更紧的价差、更高的未平仓量，HV/IV filter 开启，Max HV/IV = `0.75`。
- `Balanced`：用于常规卖方风格筛选的中间设置，Max HV/IV = `1.2`。
- `Aggressive`：更宽松的限制和更少的过滤器，用于更广泛地发现候选合约。

预设方案仅改变表单参数，不会创建任何交易。

## Sell Put 指标

对于一个看跌候选合约，筛选器计算：

- 标的价格
- 行权价
- bid / ask / mid
- 基于中间价的权利金估算
- 下行距离
- 距到期天数
- 年化收益率估算
- 价差百分比
- 可用时提供 IV 与 HV 上下文
- 趋势过滤结果
- 保守评级

## Covered Call 指标

对于一个看涨候选合约，筛选器计算：

- 标的价格
- 行权价
- bid / ask / mid
- 基于中间价的权利金估算
- 上行距离
- 距到期天数
- 年化收益率估算
- 价差百分比
- 可用时提供 IV 与 HV 上下文
- 趋势过滤结果
- 保守评级

## 评级逻辑

评级刻意偏保守：

- `Strong`：数据齐全、价差可接受、过滤器全部通过，且权利金/收益率有意义。
- `Watch`：存在可用数据，但有一项或多项条件仅为中等。
- `Avoid`：数据缺失、价差过宽、过滤器硬性未通过，或权利金过低。

评级是一个筛选标签，而非推荐建议。

前端的保守 / 平衡 / 激进预设会同时调整收益率、delta、DTE、价差、未平仓量、最低权利金、最低 IV、最低中间价、标的平均成交量和市值过滤。
`min_market_cap=0` 表示不启用市值硬过滤；这避免了在 Futu 快照没有返回市值字段时，把原本可研究的合约全部挡掉。

默认情况下，UI 与 API 会在推荐表中隐藏 `Avoid` 行。
这样可以防止深度实值的卖方合约、零未平仓量合约，
或硬性未通过过滤器的行被当作可用候选合约展示出来。
对于审计/调试工作，可在请求体中设置 `include_rejected=true` 以检视
这些行被剔除的原因。

前端标签 `Filtered out` / `已过滤` 是这些被隐藏的 `Avoid` 行的计数。
它通常意味着该合约对卖方策略而言深度实值、未平仓量为零、
价差过宽，或未通过 HV-IV 过滤。它不是一种单独的交易状态，
也绝不会创建任何订单。

趋势过滤器现在会检查标的价格是否处于或高于 EMA21 与 SMA50 两者。
弱趋势信号本身不再构成硬性剔除：
其他方面可用的候选合约会被降级为 `Watch`，并通过备注标明
价格是低于 EMA21、SMA50，还是两者皆低。诸如价差过宽、
delta 过大、未平仓量过低、卖方实值行权价以及
HV/IV 未通过等硬性风险过滤器，仍可将候选合约隐藏为 `Avoid`。

### 市场状态调整（VIX/VIX3M）

筛选器现在会读取离线 VIX 缓存（`data/options_universe/vix_history.csv`），并计算与每日雷达相同的 `Normal / Elevated / Panic` 状态。密度计算使用近三个月的 VIX/VIX3M 窗口，因此短暂的一个月尖峰不会主导整个市场状态标签。Options Radar 在每日扫描中会将同一份状态快照传入逐个标的的筛选器。当状态为非 Normal 时，卖方候选合约（`sell_put`、`covered_call`）会被降级：

- `Elevated`：任何 `Strong` 评级都被降级为 `Watch`。
- `Panic`：`sell_put` 被强制为 `Avoid`；`covered_call` 从 `Strong` 降级为 `Watch`。
- `Unknown`（缓存缺失/为空）：不施加惩罚；通过 `quant-system options refresh-vix` 刷新。

结果载荷会暴露 `market_regime`、`market_regime_penalty`、`market_regime_w_vix`、`market_regime_vix_density` 以及 `market_regime_term_ratio`；`/options-screener` 页面会在指标网格上方渲染一个带颜色的状态横幅。在 `Elevated` 或 `Panic` 状态下，页面还会提示卖方权利金保证金与回撤压力可能上升，因此应控制仓位规模。

结果载荷还会为筛选器页面暴露以下顶层状态字段：

- `ema_21`
- `sma_50`
- `hv_iv_threshold`
- `hv_iv_pass_count`
- `hv_iv_contract_count`
- `hv_iv_min`
- `hv_iv_max`

前端使用这些字段在候选表上方显示标的价格、EMA21、SMA50、HV 以及 HV/IV 状态。

## 重要假设

- 权利金使用中间价，而非保证成交的成交价。
- 需要时，HV 由历史股价收益率计算得出。
- 缺失的 IV 或希腊字母会被标记为缺失；不会凭空捏造。
- 行权指派、提前行权、税费、保证金以及账户约束均未建模。
- 不会创建任何实盘订单。

## 快速上手

1. 启动 OpenD 并确认其已登录。
2. 启动后端：

```powershell
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

3. 启动前端：

```powershell
cd src/frontend
npm run dev -- --port 3001
```

4. 打开：

```text
http://127.0.0.1:3001/options-screener
```

5. 尝试 `AAPL`、`Sell Put`、provider 选 `futu`。
6. 选择一个预设方案，或手动编辑 DTE / delta / 价差 / 未平仓量过滤器。
7. 运行筛选器。后端会扫描 DTE 窗口内每一个可用的富途到期日，并返回排序后的候选合约。

## 常见错误

- 把评级当作投资建议。
- 假设中间价总能成交。
- 忽略买卖价差。
- 在不检查数据时效性的情况下比较 IV 与 HV。
- 忘记 OpenD 必须处于运行状态。

## 没有合约时，先看是哪一层没有通过

筛选结果现在显示整条期权链的三类数字：基础质量未通过、个人条件或市场状态不符、全部符合。
三类互不重叠。下方原因明细可能重复计算同一合约，不要把原因数量相加。

- 基础质量没过，例如报价陈旧、价差过宽、未平仓量不足、财报资料缺失或物理期望值不为正。
  先补事件资料、等待新报价，或者改查另一个自己愿意持有的标的；不为增加数量降低这些底线。
- 基础质量已过，但自己的收益、波动率或趋势要求不符，单独列入「仅供观察」。
  系统会在仅差收益目标时显示这些合约实际最高的权利金年化。用户可以手动改目标后重查，
  也可以等待；系统不会自动修改默认 15% 或用户输入。
- 全部符合的合约才进入主表。按中间价估算的权利金年化是收益筛选条件；买一价口径单独列出。
  用户不填开平仓费用时，扣费后数字保持未知。即使填写，也没有计算买回期权和持股价格变化，
  不能把它当作实际年化收益。

本轮冻结的 2026-10-02 SPY、10–21 天样本里，原先显示的 50 个候选全部低于 15%。
修正后 1042 条中 980 条未过共同质量检查、62 条个人条件不符、0 条全部符合。
只差收益目标的合约最高中间价权利金年化约 11.83%。这是同一输入的优化前后对照，
不是随机 A/B 测试，也没有证明策略盈利。收益目标过高时，零结果是应当保留的结论。

卖出看跌以有足够现金接股为前提；备兑看涨以已持有足够股票为前提。
美式期权可能提前指派，尤其要关注除息前后的变化。这些研究指标没有验证用户账户的担保资金，
没有期权交易账本，也没有完成包含历史合约链与提前指派的策略回测。
参考 [OIC 现金担保看跌](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put)、
[OIC 指派说明](https://www.optionseducation.org/referencelibrary/faq/options-assignment)、
[OIC 备兑看涨](https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write)。
