# 期权推荐（界面路由：`/options-radar`）

期权推荐页每天从真实 Futu 期权报价中筛选卖方研究机会。它只生成本地研究快照，
不会解锁账户、下单、修改模拟账户或进入实盘。

## 怎么使用

1. 确认 Futu OpenD 已启动并登录。
2. 打开 `/options-radar` 或 `/zh/options-radar`。
3. 需要最新结果时点击「立即更新今日推荐」。请求会很快返回，扫描在后台继续；
   页面会显示目标交易日、当前步骤、进度和耗时，可以离开页面。
4. 完成后页面自动读取同一个目标交易日的新快照。最多显示 20 条通过全部硬条件的
   推荐，每个标的最多两条；零条也是一种有效结果，缺口不补虚构合约。
5. 「高级数据源」只单独刷新公开财报日历或 VIX。页面不会改写正式的 34 标的
   策展名单。

## 自动更新

HQA 拥有调度，Platform 拥有扫描合同、快照和页面：

- 周一至周六北京时间 22:00，现役 LaunchAgent
  `com.aiquant.business.hqa-options-collect` 经 `hqa.business_schedule` 调用
  安装后的 `hqa-options-collect.sh`。旧 Hermes cron 已于 2026-09-21 暂停，
  原因为 `migrated_to_platform_launchd`，不能为恢复扫描再启用它。
- 周一至周五先刷新财报、除息事件和 VIX，再扫描跟踪的 34 个策展标的。
- 周六先写同一份 34 标的正式快照，再把公开宽池的前 100 个标的写到独立的
  `data/options_scans/wide`；宽池不进入正式推荐页。
- sample 输入只能写隔离目录，不能进入正式 universe、earnings、dividend、VIX、
  IV history 或推荐快照。
- API 启动不会补扫；机器在 22:00 未在线时不会靠启动服务偷偷补写当天结果。
- 旧 `com.aiquant.options-collect` 模板不属于现役调度，不得与
  `com.aiquant.business.hqa-options-collect` 同时加载，否则会形成双调度。

安装、日志和只读验收以
[HQA 期权推荐运维 runbook](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/runbooks/options-recommendations.md)
为准。2026-10-04 只读核验发现新调度 10-01、10-02、10-03 的 22:00 执行账均为
`ok / exit 0`；10-03 日志绑定到本轮 20 条正式 generation，覆盖仍为 33/34。
任务退出成功不表示每个标的都扫描成功，也不表示页面读取已通过全部校验。

## 页面六种状态

| 状态 | 页面含义 | 应该怎么做 |
|---|---|---|
| 需要更新 | 没有快照、只有旧版快照，或报价已过期；旧行不会冒充当前推荐。 | 点击「立即更新今日推荐」，或等待 22:00 自动任务。 |
| 已排队 / 正在更新 | 后台正在刷新财报、除息、VIX 或逐标的扫描。 | 等待即可；离开页面不会取消任务。 |
| 有推荐 | 真实 Futu 快照可用，且至少一条合约通过全部硬条件。 | 查看主表和单行展开详情；仍只作研究。 |
| 暂无推荐 | 扫描有效完成，但没有合约通过全部硬条件。 | 查看排除原因；不要把 0 条解释成数据源故障。 |
| 部分完成 | 至少一个标的成功，但另有标的失败。成功标的的结果保留。 | 查看覆盖率和失败标的；结果不代表完整 34 标的覆盖。 |
| 失败 / 数据不可用 | 任务失败，或没有可用的真实报价证据。 | 修复 OpenD、权限或输入后重试；页面不会用 sample 补位。 |

任务状态来自 `GET /api/options/daily-scan/status`。结果来自
`GET /api/options/daily-scan`，两者不能混为一谈：任务完成可以得到 0 条有效推荐，
任务失败也不会删除上一份已经写成的有效快照。

## 立即更新接口

```text
POST /api/options/daily-scan/run
```

- `202`：已获得扫描锁并写入 `queued` 状态。响应不是“已经扫完”。
- `409 options_scan_already_running`：定时任务或另一次手动更新持有同一把锁；不会
  再启动一份重复扫描。
- 手动和自动路径都固定使用真实 Futu、34 个策展标的、同一正式输出目录和相同输入
  刷新顺序。
- 单标的失败只进入 `failed_tickers`；其余成功标的继续产生结果。

## 推荐是怎么计算的

每个合约先经过报价和事件硬条件，包括：中间价、买卖价差、未平仓量、Delta、
5–60 天剩余期限、有效 IV、目标美股交易日报价和无风险利率。非 ETF 还必须有财报
证据；备兑看涨必须有除息证据。若除息日在到期日前，备兑看涨的外在价值还必须高于
每股股息。过去的除息日不证明下一次除息时间；缺未来日期时明确排除，来源明确不分红的记录可放行。
单标的筛选遇到缺失/过期财报或除息资料时查询该标的的公开事件源，在内存使用，不改正式扫描池。

通过这些检查后，卖方 EV 使用物理测度的对数正态预期赔付：

```text
physical_sigma = min(IV, HV)  # HV 有效时；否则使用 IV
physical_drift = risk_free_rate + equity_risk_premium
expected_value = extrinsic_premium - physical_expected_payout
recommendation_score = annualized_expected_value * liquidity_factor
```

`QS_OPTIONS_RADAR_EQUITY_RISK_PREMIUM` 可配置，当前默认值为 `0.04`。预期价值必须
为正；最终按 `recommendation_score` 排序。这个模型是研究筛选假设，不是风险中性定价、
成交概率保证或收益承诺。

## IV Rank 为什么显示“积累中”

IVR 使用同执行价附近、约 30 天到期的 Call + Put 双腿 ATM30 straddle IV 历史。
正式历史不足 30 个美股交易 session 时，页面显示「积累中 n/30」，但这不会阻断
推荐。已有的真实 IV、HV、报价、事件、物理 EV 和流动性仍参与筛选；达到 30 个正式
session 后页面显示 IVR 诊断值，但当前推荐硬门和排序不依赖其高低。非法 IVR 仍会
被拒绝，旧的单腿 IV 历史不会冒充 ATM30 双腿历史。

## 快照合同

正式快照使用 `options_recommendations/v3`，当前评分模型名为
`seller_ev_liquidity_v1`：

- 候选写入带随机 generation 的 `{date}.{generation}.jsonl`；
- `{date}_meta.json` 是原子替换的当前指针，并携带 generation、文件哈希、行数、
  universe 身份、覆盖率、报价水位、risk-free rate 和 equity risk premium；
- 页面最多读取 20 条通过硬条件的 Futu 候选；
- raw meta 的 `empty` 只表示该 generation 没有候选行；它可能来自完整扫描，也可能
  来自 `completed_with_warnings` 的部分扫描。页面必须结合覆盖率、freshness 与 API
  投影判断“完整有效的零条”；`unavailable` 表示快照当前不能作为推荐。

读取器会按当前物理 EV、股息与评分合同重新验证每一行。因此，较早的 v3 generation
即使版本字符串相同，只要缺少当前必填字段或仍是旧公式，也会读成 `unavailable`；
不能把“同为 v3”写成向后兼容承诺。

## 当前已知边界

同一目标交易日再次更新会生成新 generation，并把当天 meta 指针切到新结果。
当前只阻止报价时间 `as_of` 回退，**还不会阻止覆盖率回退**。因此，同一 session
较晚运行的一次 1/34 部分扫描，可能替换较早的 34/34 快照。这是当前已知的
same-session 边界，查看推荐时必须同时看「已扫描 / 失败」而不能只看日期。

2026-08-26 的现场快照正好体现了这个区别：正式目录的 2026-08-25 generation 为
1 个标的成功、33 个失败、0 条候选；隔离目录 `/private/tmp/options-verify` 的同日
验证为 34/34、0 失败、Top 20。隔离结果证明代码路径能够形成完整候选，但不会被
冒充为正式页面数据；正式 raw meta 是 partial `empty`，GET/API 因快照陈旧投影为
`unavailable`，页面如实显示不可用。

## 相关文档

### 实时期权详情与本地研究工具（2026-09-15 修正）

- 详情页的平值 IV 与所选期权链使用同一个到期日。`/api/options/snapshot/{ticker}`
  接受 `expiration`，响应的 `iv_expiry` 记录实际期限；`nearest_expiry` 仍记录最近到期日。
- Futu 原始期权链的 IV 是百分数，例如 `214.227` 表示 `214.227%`。
  `/api/options/chain` 显式返回 `implied_volatility_unit=percent`；本地计算器采用
  小数比例，例如 `0.25` 表示 `25%`。只在数据进入计算器时转换一次，不按数值大小猜单位。
- 实时详情没有读取同口径的期权 IV 历史，因此 IV Rank 留空。股票历史波动率不再充当
  期权 IV 历史；推荐页已有的正式 ATM30 IV 历史与积累规则保持不变。
- 恐慌与情绪工具显示已取得/应取得的输入数量及缺项。数据不全时，完整评分与市场判断
  保留未知；`partial_score` 仅说明已知部分，不能触发完整恐慌规则的价差入场信号。
- 「研究档案完整度」只读取已保存的本地研究自选档案。没有档案、更新日期缺失或无效时
  不给分；它只检查资料完整度，不评价公司或策略质量，不临时填日期或研究说明。
- 财报 IV 回落需要历次财报前/后的配对观测。本地普通 ATM30 日历史没有这样的事件绑定，
  不能替代。未提供配对历史时明确显示不可估算，不生成预期财报后 IV。
- 买方目标价不高于现价时提示修改输入；合约报价过期时提示等待新报价，两种问题分开说明。

- [Phase 13 架构](../architecture/phase_13_architecture.md)
- [Phase 13 执行指南](../execution/phase_13_execution.md)
- [Futu 期权数据提供方](../futu/futu_options_data_provider.md)
- [期权筛选器学习指南](../options/options_screener_learning.md)

### 2026-10-04 读取校验与筛选诊断修复

评分改用 `math.fsum`，使 Python 3.11/3.12 的浮点求和一致；快照读取允许评分字段
`rel_tol=1e-14, abs_tol=1e-12` 的计算末位误差，仍逐项校验字段、权重、身份、报价、事件和 EV。
正式 2026-10-02 原件有 20 条候选，原读取器因 7 条评分仅约 `1e-14` 差异而拒绝整份快照。
修后原件无需改写即可读取，覆盖仍为 33/34，XLY 失败没有隐藏。
这是源码回读结果，发布与浏览器采用状态看本轮 HQA 收据。

同一天反复扫描不会增加 IVR 样本数：当前 `IvHistoryStore` 已按 ticker、
`atm30_straddle_iv_v1` 与美股交易日去重，252 指去重后的交易日观测数。
旧单腿 `.jsonl` 不会充当现行 ATM30 历史，无需为了旧审计再修改历史原件。
单标的筛选的新计数、观察列表、买一价与费用口径见
[API 合同](../options/options_screener_api.md#2026-10-04-筛选与年化口径)。
