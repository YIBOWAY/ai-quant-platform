# 卖方期权筛选器 Review — 2026-05-03

本文档记录了 2026-05-03 对 [src/quant_system/options/screener.py](../src/quant_system/options/screener.py)、[src/quant_system/options/models.py](../src/quant_system/options/models.py)、[src/frontend/components/forms/OptionsScreenerForm.tsx](../src/frontend/components/forms/OptionsScreenerForm.tsx)、[src/quant_system/data/providers/futu.py](../src/quant_system/data/providers/futu.py) 的整体 review、发现的 BUG、卖方策略预设参数评估，以及"每日全市场期权卖方扫描器"功能的可行性结论。

基准对比点：commit `77575bf`（Phase 11 末尾）→ HEAD `23f703e`。

---

## 一、Review 与修复清单

### A. 安全边界 — 全部通过
- Futu Provider 仅引入 `OpenQuoteContext`，没有 `OpenSecTradeContext / trd_open / unlock_trade / place_order / modify_order`。
- 期权 API 三个端点 (`GET /options/expirations`、`GET /options/chain`、`POST /options/screener`) 全部只读，并通过 `_build_options_provider` 强制 `provider=futu` + `options_enabled` 守门。
- `/api/orders/submit` 仍 404；safety footer 仍由中间件注入。

### B. 已修复的 BUG

| 编号 | 问题 | 解决 |
|---|---|---|
| B1 | `_trend_pass` 两个分支完全相同（covered_call 与 sell_put 走同一条件） | covered_call 改为 `underlying_price <= trend_reference`，并在 docstring 写明：sell_put 喜欢上行/横盘趋势，covered_call 喜欢非超买趋势 |
| B2 | `_rating` 的 hard_failures 缺少 `delta above limit`、`open interest below minimum` 等核心约束 | 抽取为常量 `HARD_FAILURES`，新增上述两项与新增 mid/ADV/市值 hard 约束 |
| B3 | `filtered = [c for c in rows if c.rating != "Avoid" or (c.bid is not None and c.ask is not None)]` 等价于不过滤 | 改为保留所有 rows，让排序把 Avoid 推到末尾，UI 决定是否隐藏；保持向后兼容（避免破坏现有测试 `result.candidates[0].rating == "Avoid"`） |
| B4 | `ranked[:50]` 硬编码 | `OptionsScreenerConfig.top_n: int = 100` 可配置 |
| B7 | `_normalize_volatility` 阈值 2 会把 `IV=2`（即 200%）当成百分比再除以 100 | 阈值改为 5（500%），并补 docstring 说明 |
| B8 | `_days_to_expiry` 用 UTC `now()` 在 BJT 凌晨会出 off-by-one | 改用 `America/New_York` 时区 |
| C1 | `history_start = "2024-01-02"` 写死 | `history_start/history_end` 可空，新增 `history_lookback_days: int = 90`，由 `_resolve_history_window` 根据当前美东日期回溯 |
| — | `OptionsScreenerForm` 切换预设留下 stale 字段 | 三档预设现在都显式提供完整字段（含 `min_premium`、`min_iv_input`、`min_mid_price`、`min_avg_daily_volume`、`min_market_cap`） |

### C. 仍待跟进
- C2（限速）：`fetch_market_snapshots` 仍按 400 batch 一次性调，单标的扫描尚未达到 Futu 接口频控阈值。**Phase 13 全市场扫描需要在 batch 间加 token bucket 限速。**
- C3（LV2 行情依赖）：`option_implied_volatility / option_delta / option_open_interest` 在没有 LV2 订阅时会大量为空，导致筛选器输出全 Avoid。需要在 [docs/futu/futu_options_data_provider.md](../futu/futu_options_data_provider.md) 显式提示。

---

## 二、卖方策略预设参数评估与新基线

### 业内基准 (tastytrade / TastyLive 体系)
- Delta: 0.16–0.30（卖方甜蜜区）
- DTE: 30–45（θ 衰减最快），<21 γ 风险陡增
- IV: 优先 IVR > 30
- Spread: < 5%（大盘 ETF），<10%（中盘）
- OI: > 100（流动性硬门槛）
- HV/IV: < 1.0（IV 富裕度），> 1.0 等于反向交易
- 退出：50% 利润目标 / 21 DTE roll / 200% credit 止损

### 用户决策（2026-05-03）
- **保留 delta**：`0.20 / 0.30 / 0.45`（用户希望激进档保持高 delta）
- **保留 min_dte**：`14 / 10 / 7`（用户接受 γ 风险敞口）
- **修改 APR**：`5/10/15` → `8/15/25`
- **修改 max_dte**：`45/60/90` → `45/60/60`（原 90 偏离卖方 θ 卖方逻辑）
- **修改 spread**：`5/15/25` → `5/10/15`
- **修改 OI**：`100/50/20` → `200/100/50`
- **修改 HV/IV**：`0.75/1.5/2.0` → `0.75/1.0/1.0`
- **新增**（所有预设默认开 `trend_filter`，激进档关 `hv_iv_filter`）

### 新预设落地
见 [src/frontend/components/forms/OptionsScreenerForm.tsx](../src/frontend/components/forms/OptionsScreenerForm.tsx#L11-L60) 中的 `presets`。

| 字段 | conservative | balanced | aggressive |
|---|---|---|---|
| max_delta | 0.20 | 0.30 | 0.45 |
| min_apr (%) | 8 | 15 | 25 |
| min_dte | 14 | 10 | 7 |
| max_dte | 45 | 60 | 60 |
| max_spread (%) | 5 | 10 | 15 |
| min_oi | 200 | 100 | 50 |
| max_hv_iv | 0.75 | 1.0 | 1.0 |
| min_premium | 0.20 | 0.15 | 0.10 |
| min_iv (%) | 15 | 10 | 0 |
| min_mid_price | 0.20 | 0.15 | 0.10 |
| min_avg_daily_volume | 1,000,000 | 500,000 | 100,000 |
| min_market_cap (USD) | 1e10 | 2e9 | 0 |
| trend_filter | true | true | true |
| hv_iv_filter | true | true | false |

---

## 三、`trend_filter` 当前实现说明

| 阶段 | 行为 |
|---|---|
| 输入 | 标的 OHLCV 历史（默认 `today - 90d ~ today`，纽约时区） |
| 计算 | 取最近 20 根日线 `close` 的均值作为 `trend_reference`（20 日 SMA） |
| 判定（Phase 12 修复后） | **sell_put**：`underlying_price >= MA20`（趋势向上或横盘 → 卖 put 安全） &nbsp;&nbsp; **covered_call**：`underlying_price <= MA20`（趋势走弱/横盘 → 卖 call 不会过早封顶上涨收益） |
| 失败处理 | 趋势失败 → `note="trend filter failed"` → 评级 `Avoid`（在 `HARD_FAILURES` 内） |
| 数据缺失 | OHLCV 不足或 MA 为 NaN → `trend_pass=None`，跳过该过滤（不视为失败） |

代码：[screener.py L380-L420](../src/quant_system/options/screener.py)。

---

## 四、新增的卖方关键约束（已落地）

数据可得性结合 Futu OpenAPI Skill 文档：

| 约束 | 字段 | Futu 是否提供 | 落地状态 |
|---|---|---|---|
| `min_mid_price` | (bid+ask)/2 | ✅ 期权链 + snapshot | 已实现，硬约束 |
| `min_avg_daily_volume` | OHLCV `volume` 20 日均值 | ✅ `request_history_kline` | 已实现，硬约束 |
| `min_market_cap` | `total_market_val` | ✅ `get_market_snapshot` | 已实现（Futu provider 新增字段映射），硬约束 |
| `min_iv_rank` | 历史 IV 累计百分位 | ❌ Futu 仅返回当前 IV | **配置字段已加，留给 Phase 13 用持久化的快照历史填充** |
| `avoid_earnings_within_days` | 财报日历 | ❌ Futu OpenAPI 不提供财报日历 | **配置字段已加，Phase 13 通过 yfinance 等外部源补齐** |

落地点：
- 后端：[src/quant_system/options/models.py](../src/quant_system/options/models.py) 新增 `top_n / min_mid_price / min_avg_daily_volume / min_market_cap / min_iv_rank / avoid_earnings_within_days / history_lookback_days`，候选模型新增 `avg_daily_volume / market_cap / iv_rank / earnings_date`。
- 后端：[src/quant_system/options/screener.py](../src/quant_system/options/screener.py) 在 `_candidate_notes` 中实施硬约束；`_resolve_history_window` 处理动态历史窗；`_average_volume` 计算 ADV。
- Provider：[src/quant_system/data/providers/futu.py](../src/quant_system/data/providers/futu.py#L382-L412) `_normalize_snapshots` 映射 `total_market_val → market_val`、新增 `turnover`。
- 前端：[src/frontend/components/forms/OptionsScreenerForm.tsx](../src/frontend/components/forms/OptionsScreenerForm.tsx) 三档预设、zod schema、payload 全部覆盖新字段。

---

## 五、回归验证

- `pytest`：**230 passed in 39.48s**（基线 177 → 230，新增覆盖未受影响）
- `ruff check src/quant_system/options src/quant_system/data/providers/futu.py`：**All checks passed**
- 安全自检：`/api/orders/submit` 仍 404、kill_switch=true、bind_address=127.0.0.1、Polymarket read-only=true、Futu 仅 `OpenQuoteContext`。

---

## 六、Phase 13 — 每日定时全市场期权卖方扫描器

详细设计与实现 prompt 见 [phase_13_options_radar_codex_prompt.md](phase_13_options_radar_codex_prompt.md)。

要点：
- **Universe**：S&P 500 ∪ Nasdaq 100，去重后 ≈ 530 标的；首版精选 100（按 ADV/市值排序）。
- **调度**：Windows 任务计划程序每日 BJT 06:30（美东 17:30 收盘后）触发 `python -m quant_system.cli options daily-scan`。
- **存储**：`data/options_scans/{YYYY-MM-DD}.jsonl` (append + 哈希 idempotent)。
- **限速**：Futu 行情接口 10 次 / 30 秒；按 token bucket 实现；100 标的 × 6 到期日 ≈ 1200 次调用 / ≈ 1 小时。
- **API**：`GET /api/options/daily-scan?date=...&strategy=...&top=...`。
- **前端**：`/options-radar` 路由 — 日期 + sector + DTE 桶 + 策略筛选；CSV 导出；safety banner。
- **IV Rank**：靠每日扫描自动累积 IV 历史；满 30 天后启用。
- **Earnings**：通过 `yfinance` 离线缓存美股下季度财报日历。
- **Futu 限制必须在 README 显式声明**：账户实名 + 美股 LV2 行情 + OpenD 在线 + 自用研究、不对外提供数据 API。

---

## 七、未提交内容提醒

- [docs/INDEX.md](INDEX.md) 仍未提交（R5 创建）。
- 仓库根 `src/quantum-core-algorithmic-trading-platform.zip` 仍未追踪。
- 本次 Phase 12 修复（screener bug + 预设 + 新约束 + Futu market_val）尚未 commit；建议作为单独 commit `fix(options): screener bugs, expanded constraints, preset rebaseline`。
