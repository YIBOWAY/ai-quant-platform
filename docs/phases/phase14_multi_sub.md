# Phase 14 Prompt Plan - Buy-Side US Options Strategy Assistant

下面这套不是一个 prompt，而是一组分阶段 prompt。建议按顺序喂给 Codex；每一阶段完成、测试、检查 diff 后，再执行下一阶段。这样最稳，不容易一次改爆整个项目。

本版针对当前仓库做了约束增强：明确复用现有卖方期权模块、Futu 只读行情层、VIX regime、Next.js/Tailwind UI 风格、安全红线与测试基线。

> 本套 prompt 面向 Codex (GPT-5.5)，采用 outcome-first 风格：每个 Prompt 都给出 `Goal` + `Done when`（= Success criteria）+ 显式约束 + 显式 stopping 行为；安全红线使用 `MUST NOT` 仅限于真正的 invariant；其余决策点尽量交给模型选择最有效路径。

## Recommended Execution Order

1. Prompt 0 - Repository Reconnaissance / 只读侦察与集成计划
2. Prompt 1 - Futu Data Integration Audit / 先确认现有 Futu 行情层能力
3. Prompt 2 - Data Contract / 扩展买方数据契约
4. Prompt 3 - Quant Metrics Engine / 买方单合约反坑指标
5. Prompt 4 - Strategy Candidate Generator / 生成 Long Call 与 Call Spread 候选
6. Prompt 5 - Scenario Lab / IV crush 与 theta burn 情景 PnL
7. Prompt 6 - Decision Engine + CLI / 观点到结构的决策支持
8. Prompt 7 - UI Page / 新增买方期权策略页面
9. Prompt 8 - Testing, Validation, Risk Controls / 测试、验证、风控文案与文档同步

## Global Rules For Every Prompt

Paste this section before every phase if Codex does not retain previous context.

```text
GLOBAL REPO CONTEXT
- Repository: AI-assisted quant research and paper-trading platform.
- Backend: local FastAPI API under src/quant_system.
- Frontend: Next.js app under src/frontend.
- Current project state: completed through Phase 13.
- Existing option modules already exist and must be reused, not duplicated:
   - src/quant_system/options/models.py
   - src/quant_system/options/screener.py
   - src/quant_system/options/radar.py
   - src/quant_system/options/futu_provider.py
   - src/quant_system/options/market_regime.py
   - src/quant_system/options/iv_history.py
   - src/quant_system/options/vix_data.py
   - src/quant_system/options/earnings.py
   - src/quant_system/api/routes/options.py
   - src/quant_system/cli.py
   - src/quant_system/config/settings.py
- Existing frontend patterns must be reused:
   - src/frontend/components/forms/OptionsScreenerForm.tsx
   - src/frontend/components/forms/OptionsRadarView.tsx
   - src/frontend/app/options-screener/page.tsx
   - existing nav/sidebar/page routing patterns under src/frontend.
- Existing tests and validation commands:
   - conda activate ai-quant
   - python -m pytest -q
   - ruff check src/quant_system tests
   - npm --prefix src/frontend run lint
   - npm --prefix src/frontend run build
- Baseline before Phase 14: pytest 270 pass, ruff clean, frontend lint/build clean.

SAFETY GUARDRAILS - MUST NOT VIOLATE
- No live trading.
- No order placement.
- No signing.
- No wallet connection.
- No Futu account unlock.
- No Futu trading context.
- Do not import or instantiate Futu TradeContext / OpenSecTradeContext / unlock_trade / place_order / modify_order / cancel_order.
- Do not add real broker order APIs.
- Do not weaken dry_run, paper_trading, live_trading_enabled=false, or kill_switch=true.
- Futu is read-only market data only.
- Polymarket remains read-only research/replay only.
- Keep the module as quantitative decision support, not financial advice.

IMPLEMENTATION STYLE
- Reuse existing project structure and naming conventions.
- Prefer small incremental changes.
- Do not introduce heavy new dependencies unless absolutely necessary.
- Do not create a standalone app.
- Do not change unrelated modules.
- Do not duplicate existing OptionContract / OptionQuote / provider abstractions.
- If something is missing, state it explicitly instead of inventing a new architecture.
- Run the relevant focused tests after each phase, then the broader validation commands when appropriate.

PREAMBLE (apply to every multi-step or tool-heavy prompt below)
- Before any tool calls or file edits, send one short user-visible update (1-2 sentences) acknowledging the request and stating the first concrete step.
- Use commentary-style updates for intermediate progress; reserve the final answer for the completed result.

VALIDATION LOOP (apply after every set of edits)
- After modifying code, run the most relevant targeted check before declaring done:
   - new/changed unit tests for the touched module
   - ruff for backend changes
   - npm --prefix src/frontend run lint and run build for frontend changes
   - the full python -m pytest -q only at Prompt 8 or when a phase explicitly requires it
- If a check cannot be run (missing dependency, no env, etc.), say so explicitly and run the next-best check; do not silently skip validation.

STOP RULES
- Stop searching, reading, or iterating once the prompt's Done-when conditions are satisfied with verifiable evidence.
- Do not re-search to refine wording, add nonessential examples, or improve a generic explanation.
- If a required input is missing and would materially change the answer, ask one narrow question instead of guessing; otherwise proceed with stated assumptions.
- Treat the safety guardrails as hard stops: if a step would require live trading, order placement, account unlock, or weakening of safety flags, refuse and explain.
```

---

## Prompt 0: Repository Reconnaissance / 先理解现有平台，不改代码

```text
You are Codex-GPT5.5 acting as a senior quant engineering + full-stack trading platform engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Your first task is NOT to build from scratch and NOT to modify files. Inspect the current repository and produce an integration plan for adding a new module:

"Buy-side US Options Strategy Assistant"

This module helps traders compare more suitable bullish long-option structures using quantitative metrics:
- Long Call
- Bull Call Spread
- LEAPS Call
- LEAPS Call Spread

Out of scope for Phase 14 MVP:
- Diagonal / Calendar Spread
- Probability of profit model
- Black-Scholes repricing unless already available and trivial to reuse
- Any live trading, broker order, signing, wallet, or account unlock path

Important existing platform facts you must verify and reuse:
- There is already a sell-side single-ticker options screener.
- There is already a cross-ticker options radar.
- There are existing Pydantic option models.
- There is an existing Futu read-only market data provider.
- There is an existing VIX regime module from Phase 13.
- There is an existing Next.js/Tailwind frontend style and routing pattern.

Read these first, then inspect only what is necessary:
- AGENTS.md
- README.md
- docs/OVERVIEW.md
- docs/INDEX.md
- docs/delivery/phase_13_delivery.md
- src/quant_system/options/models.py
- src/quant_system/options/screener.py
- src/quant_system/options/radar.py
- src/quant_system/options/futu_provider.py
- src/quant_system/options/market_regime.py
- src/quant_system/options/iv_history.py
- src/quant_system/options/vix_data.py
- src/quant_system/options/earnings.py
- src/quant_system/api/routes/options.py
- src/quant_system/cli.py
- src/frontend/components/forms/OptionsScreenerForm.tsx
- src/frontend/components/forms/OptionsRadarView.tsx
- src/frontend/app/options-screener/page.tsx

Your tasks:
1. Summarize the current architecture.
2. Identify where existing option chain, quote, Greeks, IV, earnings, and VIX regime logic live.
3. Identify what can be reused directly for the buy-side assistant.
4. Identify exact files to create or modify.
5. Identify whether OptionContract / OptionQuote need extension or only helper functions.
6. Identify frontend page/nav/component locations.
7. Identify tests to add and validation commands to run.
8. Identify risks, missing information, and assumptions.

Output format:
- Current architecture summary
- Existing option stack discovered
- Proposed module location
- Proposed backend/service changes
- Proposed frontend/UI changes
- Proposed data model/interface changes
- Testing plan
- Safety review
- Risks/assumptions
- Step-by-step implementation phases

Constraints:
- Do not modify any files in this phase.
- Do not invent APIs that do not exist.
- Prefer extending/reusing existing option modules over adding parallel abstractions.

Done when:
- You have produced a concrete integration plan with exact file paths.
- You have clearly stated assumptions and missing information.
```

---

## Prompt 1: Futu Data Integration Audit / 先确认现有 Futu 美股期权数据层

先把数据来源摸清楚，再建模型和策略。这个阶段大概率不需要大改代码；目标是确认 src/quant_system/options/futu_provider.py 已经能提供买方模块需要的字段，并把缺失映射补齐。

```text
You are Codex-GPT5.5 acting as a senior market data integration engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Audit and, only if necessary, minimally extend the existing Futu read-only US stock/options data provider so the Buy-side US Options Strategy Assistant can consume normalized option data.

Important:
- Do not reinstall Futu OpenAPI.
- Do not create a new provider architecture.
- Do not import any Futu trading context or account unlock API.
- Reuse src/quant_system/options/futu_provider.py and the existing src/quant_system/options/rate_limiter.py wrapper.
- Respect Futu option-chain rate limits; avoid live calls in tests.

Tasks:
1. Inspect src/quant_system/options/futu_provider.py, src/quant_system/options/rate_limiter.py, and related tests.
2. Identify available methods for:
    - underlying stock snapshot / spot
    - option expiration dates
    - option chain
    - option quote snapshot
    - Greeks: delta, gamma, theta, vega, rho
    - IV, volume, open interest, timestamp
    - historical K-line / realized volatility if available
3. Confirm provider field conventions:
    - theta unit: daily vs annual
    - vega unit: per 1 vol point (1 percentage point) vs per 1.00 volatility decimal
    - IV unit: percent vs decimal
    - option contract size
4. If mapping helpers are missing, add small adapter helpers in the existing options package, for example:
    - map Futu option records to existing OptionContract / OptionQuote models
    - normalize Futu symbols to platform-standard option symbols
    - attach data-quality warnings for missing Greeks, missing IV, stale quote, invalid bid/ask, zero OI/volume
5. Add mocked unit tests only; do not call live Futu APIs in tests.

Constraints:
- Preserve existing provider behavior.
- Do not hard-code credentials.
- Do not expose account/trading functions.
- Do not create a second provider layer if the existing one can be extended.

Output requirements:
- Summary of provider capabilities discovered.
- Any fields or units that remain uncertain.
- Changed files and tests run.

Done when:
- The buy-side module can consume normalized read-only option data from the existing Futu provider or the missing fields are clearly documented.
- Mocked integration tests pass.
```

---

## Prompt 2: Data Contract / 扩展买方期权数据输入输出结构

这一阶段先别急着做 UI。先把数据结构做稳，但不要重复 OptionContract 和 OptionQuote。

```text
You are Codex-GPT5.5 acting as a senior quant data engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Implement the data contract layer for the Buy-side US Options Strategy Assistant using the existing options package and Pydantic style.

Existing models:
- src/quant_system/options/models.py already contains option-related Pydantic models.
- Do not duplicate existing OptionContract / OptionQuote if they already exist.
- Extend existing models only when needed, or add buy-side-specific models in the existing options package with clear imports.

Preferred model additions:
- BuySideStrategyType = Literal["long_call", "bull_call_spread", "leaps_call", "leaps_call_spread"]
- BuySideViewType = Literal["long_term_aggressive_bullish", "long_term_conservative_bullish", "short_term_speculative_bullish", "short_term_conservative_bullish", "event_driven_bullish"]
- BuySideVolatilityView = Literal["auto", "prefer_low_iv", "expect_iv_crush", "expect_iv_expansion"]
- BuySideRiskPreference = Literal["aggressive", "balanced", "conservative"]
- BuySideEventRisk = Literal["none", "earnings", "fomc", "cpi", "product_event", "user_defined"]
- BuySideRiskWarning as typed Literal values, not free-form strings
- BuySideThesisInput, must include volatility_view: BuySideVolatilityView (default "auto")
- BuySideStrategyLeg
- BuySideStrategyScore, extended with optional product-grade composite scores defined in Prompt 3:
   - buyer_friendliness_score: float | None
   - iv_crash_risk_score: float | None
   - breakeven_difficulty_score: float | None
   - theta_pain_score: float | None
   - leverage_efficiency: float | None
   - cost_of_convexity: float | None
- BuySideStrategyCandidate, extended with:
   - expected_move_pct: float | None
   - target_vs_expected_move_ratio: float | None
   - risk_attribution: dict with keys direction / time / volatility / liquidity, each 0-100
- BuySideScenarioInput, extended with optional user_scenarios: list of (label, probability, spot_change_pct, iv_change_vol_points)
- BuySideScenarioResult
- BuySideScenarioMatrixCell
- BuySideScenarioEV: expected_value, contributions per scenario
- BuySideAssistantResult

Derived fields and helper definitions:
- mid_price = (bid + ask) / 2 when both bid and ask are valid
- spread_abs = ask - bid
- spread_pct = spread_abs / mid_price
- call_moneyness = spot / strike, define once and use consistently
- dte = calendar days to expiration
- contract_size defaults to 100 unless provider data says otherwise

Validation rules:
- bid >= 0
- ask >= bid
- mid_price > 0 when the quote is tradable
- expiration must be valid
- option_type must be call/put according to existing repo convention
- invalid/stale/missing quotes should be flagged through warnings where possible instead of crashing strategy generation

Implementation requirements:
1. Use existing Pydantic conventions from src/quant_system/options/models.py.
2. Keep data contracts independent from UI rendering.
3. Do not hard-code Futu-specific assumptions into strategy logic; isolate provider-specific mapping.
4. Add small unit tests for mid price, spread percentage, DTE, and invalid quote handling.

Constraints:
- Do not implement metrics engine yet.
- Do not implement strategy generation yet.
- Do not implement UI yet.
- Do not break existing data-provider APIs or existing tests.

Output requirements:
- Changed files.
- Tests added.
- Test command and results.

Done when:
- Buy-side data contracts exist and reuse existing option models.
- Derived fields and validation helpers work.
- Tests pass.
```

---

## Prompt 3: Quant Metrics Engine / 买方期权反坑指标计算

这一阶段做核心反坑指标：先评估单个合约是否贵、窄、耗时、抗 IV crush，不直接推荐策略。

```text
You are Codex-GPT5.5 acting as a senior options quant engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Implement a pure quantitative metrics engine for buy-side US options. It must be independent from UI and must not call external APIs.

Suggested location:
- src/quant_system/options/buy_side_metrics.py
- tests/test_options_buy_side_metrics.py

Before coding:
- Confirm theta and vega unit conventions discovered in Prompt 1.
- If still uncertain, encode assumptions explicitly and add warnings in outputs.

Core metrics:
1. Basic pricing metrics
    - mid_price
    - bid_ask_spread_abs
    - bid_ask_spread_pct
    - intrinsic_value for calls: max(spot - strike, 0)
    - extrinsic_value = max(mid_price - intrinsic_value, 0)
    - break_even_price for long call = strike + premium
    - required_move_pct = break_even / spot - 1

2. Liquidity metrics
    - spread_pct
    - volume
    - open_interest
    - quote_staleness if timestamp is available
    - liquidity_score from 0 to 100

3. Theta/time decay metrics
    - daily_theta_cost = abs(theta)
    - theta_pct_of_premium = abs(theta) / mid_price
    - theta_burn_7d = abs(theta) * 7
    - theta_burn_7d_pct = theta_burn_7d / mid_price
    - days_to_lose_30pct = mid_price * 0.3 / abs(theta), safe for theta = 0

4. Vega/IV crush metrics
    - vega_pct_of_premium = abs(vega) / mid_price
    - estimated_iv_crush_loss for user-specified vol drop, e.g. -5 or -10 vol points
    - estimated_iv_crush_loss_pct = loss / mid_price
    - Treat vega according to the verified provider convention; add a unit test that locks this convention.

5. Greek efficiency metrics
    - delta_per_dollar = delta * spot / mid_price
    - gamma_per_dollar = gamma * spot / mid_price
    - gamma_theta_ratio = gamma / abs(theta), safe for theta = 0
    - vega_risk_score

6. Volatility valuation metrics
    - IV rank if 1Y IV low/high are available
    - IV percentile if historical IV series is available
    - IV/HV ratio if historical realized volatility is available
    - If unavailable, return None and include a missing-data warning.

7. Expected move and target comparison
    - expected_move_pct = (atm_call_mid + atm_put_mid) / spot, computed when an ATM straddle is available
    - target_vs_expected_move_ratio = user_target_move_pct / expected_move_pct
    - flag TARGET_BELOW_IMPLIED_MOVE when ratio < 1 (typical for naked-call mismatch)
    - degrade gracefully to None if ATM put/call quotes are missing

8. Product-grade composite scores (all 0-100, all optional with graceful None)
    - buyer_friendliness_score: weighted blend of cheap IV, manageable break-even, low theta burn, good liquidity
    - iv_crash_risk_score: increases with vega_pct_of_premium, IV rank, and proximity to known event
      base formula sketch: min(100, (vega_pct_of_premium * 100) * (0.5 + 0.5 * iv_rank/100) * event_multiplier)
    - breakeven_difficulty_score: combines required_move_pct and historical-probability of reaching break-even within DTE if HV/forward-return data is available; otherwise falls back to required_move_pct vs expected_move_pct
    - theta_pain_score: bucketed from theta_pct_of_premium (<1% low, 1-3% medium, 3-5% high, >5% extreme)
    - leverage_efficiency = delta * spot / mid_price
    - cost_of_convexity = extrinsic_value / max(gamma, eps)

9. Historical probability (optional, only if forward-return distribution is available)
    - historical_probability_of_breakeven for the given DTE bucket
    - explicitly distinct from any future risk-neutral probability model; do not conflate them
    - return None plus warning when underlying historical series is unavailable

Risk warning flags:
- WIDE_SPREAD
- LOW_OPEN_INTEREST
- LOW_VOLUME
- HIGH_THETA_BURN
- HIGH_IV_RANK
- HIGH_IV_CRUSH_RISK
- BREAK_EVEN_TOO_FAR
- LOW_DELTA_LOTTERY_CALL
- STALE_QUOTE
- MISSING_GREEKS
- TARGET_BELOW_IMPLIED_MOVE

Default thresholds:
- spread_pct excellent < 5%
- spread_pct acceptable < 10%
- spread_pct warning > 15%
- theta_burn_7d_pct warning > 15%
- IV rank warning > 70
- OI warning < 100
- volume warning < 20

Scoring components:
- liquidity_score: 0-100
- theta_safety_score: 0-100
- volatility_valuation_score: 0-100
- greek_efficiency_score: 0-100
- break_even_quality_score: 0-100
- contract_quality_score weighted aggregate:
   - liquidity 25%
   - theta safety 25%
   - volatility valuation 25%
   - greek efficiency 15%
   - break-even quality 10%

Constraints:
- No external API calls.
- No strategy recommendation yet.
- No heavy new quantitative libraries.
- Missing historical IV/HV data must degrade gracefully.

Tests:
- normal contract
- missing Greeks
- zero theta
- invalid/wide spread
- stale quote
- missing IV/HV
- high IV rank warning
- vega unit convention

Output requirements:
- Formula summary.
- Changed files.
- Test command and results.

Done when:
- A single option contract can be scored and diagnosed.
- Missing data is handled gracefully.
- Tests pass.
```

---

## Prompt 4: Strategy Candidate Generator / 生成 Long Call 与 Call Spread 候选策略

这里从单合约评分变成策略组合。继续保持纯计算，不拉 live 数据，不做 UI。

```text
You are Codex-GPT5.5 acting as a senior options strategy engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Generate and evaluate bullish buy-side option strategy candidates from normalized option chain data:
- Long Call
- Bull Call Spread
- LEAPS Call
- LEAPS Call Spread

Suggested location:
- src/quant_system/options/buy_side_strategy.py
- tests/test_options_buy_side_strategy.py

User trade thesis inputs:
- ticker
- spot price
- view_type:
   - long_term_aggressive_bullish
   - long_term_conservative_bullish
   - short_term_speculative_bullish
   - short_term_conservative_bullish
   - event_driven_bullish
- target_price
- target_date
- max_loss_budget
- risk_preference: aggressive / balanced / conservative
- allow_capped_upside: true/false
- avoid_high_iv: true/false
- volatility_view: auto / prefer_low_iv / expect_iv_crush / expect_iv_expansion
- event_risk: none / earnings / fomc / cpi / product_event / user_defined
- expected_iv_change_vol_points, optional
- preferred_dte_range, optional

Volatility view interaction:
- prefer_low_iv: penalize naked Long Call / LEAPS Call when IV rank is high; reward Spreads.
- expect_iv_crush: heavily penalize naked long premium and reward spreads with short-leg vega offset; raise HIGH_IV_CRUSH_RISK readiness.
- expect_iv_expansion: do not penalize high IV rank for buyers; allow naked long structures even when IV rank is elevated.
- auto: derive behavior from view_type, event_risk, and current VIX regime.

Strategy construction rules:

A. Long Call
- Use call options only.
- Candidate DTE depends on view type:
   - short_term_speculative_bullish: 7-45 DTE
   - short_term_conservative_bullish: 21-90 DTE
   - long_term views: 180+ DTE, preferably 360+ when available
- Suggested delta range:
   - speculative: 0.30-0.60
   - conservative: 0.45-0.70
   - LEAPS stock replacement: 0.65-0.85
- Exclude or penalize very wide spreads, low OI, missing Greeks, or stale quotes.

B. Bull Call Spread
- Buy lower-strike call and sell higher-strike call with same expiration.
- Net debit = long_call_mid - short_call_mid.
- Max loss = net debit * contract_size.
- Max profit = (short_strike - long_strike - net_debit) * contract_size.
- Break-even = long_strike + net_debit.
- Reward/risk = max_profit / max_loss.
- Suggested long delta: 0.45-0.70.
- Suggested short delta: 0.20-0.40.
- Exclude invalid spreads where net debit <= 0 or max profit <= 0.
- Prefer spreads where net debit is not too close to spread width.

C. LEAPS Call
- Same as Long Call but DTE >= 360 when available.
- Prefer delta 0.65-0.85 for stock-replacement style.
- Penalize wide spreads heavily.

D. LEAPS Call Spread
- Same as Bull Call Spread but DTE >= 360 when available.
- Suitable for long-term conservative bullish view.
- Prefer lower theta burden and lower vega exposure versus naked LEAPS call.

Market regime integration:
- Reuse src/quant_system/options/market_regime.py and VixRegimeSnapshot.
- Do not change seller_regime_penalty behavior.
- Add buyer_regime_penalty(strategy_type, regime) if it does not already exist.
- Suggested defaults:
   - Panic: long_call -40, leaps_call -20, bull_call_spread -15, leaps_call_spread -10
   - Elevated: long_call -20, leaps_call -10, bull_call_spread -5, leaps_call_spread -5
   - Normal/Unknown: 0
- Rationale: high IV makes long premium expensive and IV crush risk larger; spreads partially hedge vega through the short leg.

Scoring:
- StrategyScore 0-100 components:
   - direction_fit_score: 25%
   - volatility_valuation_score: 20%
   - theta_safety_score: 20%
   - greek_efficiency_score: 15%
   - liquidity_score: 10%
   - risk_reward_score: 10%
- Apply market regime penalty after component aggregate and record it separately.

Direction fit:
- Calculate required move to break-even.
- Compare break-even with target price.
- Penalize if break-even is above target price.
- Reward if target price gives attractive estimated payoff.

Risk warnings:
- HIGH_IV_CRUSH_RISK
- HIGH_THETA_BURN
- POOR_LIQUIDITY
- BREAK_EVEN_ABOVE_TARGET
- LOW_REWARD_RISK
- CAPPED_UPSIDE
- LOTTERY_OPTION
- EVENT_RISK
- MISSING_DATA
- MARKET_REGIME_ELEVATED
- MARKET_REGIME_PANIC

Constraints:
- Do not fetch live data inside this module.
- Do not assume all option chains have complete Greeks.
- Do not recommend trades as financial advice; label outputs as quantitative decision support.
- Diagonal/calendar spreads remain out of scope.

Tests:
- long call candidate creation
- bull call spread candidate creation
- LEAPS filtering
- invalid spread filtering
- scoring behavior
- missing data handling
- view_type-specific filtering
- market regime penalty behavior

Output requirements:
- Example output structure for one Long Call and one Bull Call Spread candidate.
- Changed files and test results.

Done when:
- Given an option chain and trade thesis, the engine returns ranked strategy candidates with scores, metrics, payoff fields, market regime fields, and warnings.
- Tests pass.
```

---

## Prompt 5: Scenario Lab / 情景 PnL 分析与 IV Crash 模拟

这个模块是 killer feature：方向看对以后，IV 和时间变化是否仍然让你亏钱。

```text
You are Codex-GPT5.5 acting as a senior options quant engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Implement a pure Scenario Lab engine for approximate strategy PnL under spot price, IV change, and time-passed scenarios.

Supported MVP strategies:
- Long Call
- Bull Call Spread
- LEAPS Call
- LEAPS Call Spread

Suggested location:
- src/quant_system/options/buy_side_scenarios.py
- tests/test_options_buy_side_scenarios.py

Scenario inputs:
- current_spot
- current_date
- strategy legs
- spot_change_pct list, e.g. [-20, -10, -5, 0, 5, 10, 20, 30]
- iv_change_vol_points list, e.g. [-20, -10, -5, 0, 5, 10]
- days_passed list or single value, e.g. 0, 7, 14, 30
- pricing_method = "greek_approximation"

MVP pricing approach:
new_option_value ~= current_mid
                         + delta * spot_change_abs
                         + 0.5 * gamma * spot_change_abs^2
                         + vega * iv_change_unit
                         + theta * days_passed

Unit requirements:
- Use the theta/vega conventions verified in Prompt 1.
- If Futu vega is per 1 vol point, then iv_change_vol_points = -5 means vega * -5.
- If provider uses decimal vega, convert explicitly and document it.
- Add tests that lock the chosen convention so it cannot silently drift.

PnL rules:
- Floor option value at 0.
- For long leg: PnL = new_value - entry_value.
- For short leg: PnL = entry_value - new_value.
- Multiply leg PnL by contract_size.
- For spreads, calculate leg by leg and aggregate.
- Return warnings if Greeks are missing or approximation is unreliable.

Outputs:
- ScenarioResult table
- PnL matrix for heatmap/table:
   - x-axis: spot_change_pct
   - y-axis: iv_change_vol_points
   - value: estimated PnL
- Summary metrics:
   - best_case_pnl
   - worst_case_pnl
   - flat_spot_iv_crush_pnl
   - spot_up_iv_down_pnl
   - theta_only_pnl
   - probability_not_calculated = true

User-defined scenario EV (optional):
- Accept user_scenarios as a list of (label, probability, spot_change_pct, iv_change_vol_points, days_passed).
- Validate that probabilities sum to 1.0 within tolerance; otherwise return a warning and skip EV.
- For each scenario, compute strategy PnL using the same Greek approximation pipeline.
- Output BuySideScenarioEV:
   - expected_value = sum(prob_i * pnl_i)
   - contributions = list of (label, probability, pnl, prob * pnl)
- Label this as user-input subjective EV, not a market-implied probability.
- Add a unit test for a 3-scenario weighted EV case (bull / base / bear).

Constraints:
- No external API calls.
- No exact pricing claims.
- Do not add complex pricing libraries unless already present.
- Do not calculate probability of profit in Phase 14 MVP.
- Do not implement UI yet.

Tests:
- long call positive spot move
- long call IV crush
- spread capped upside approximation
- theta decay with no spot move
- missing Greeks
- option value floor at zero
- vega unit convention

Done when:
- A strategy candidate can be passed into Scenario Lab and produce scenario PnL tables/matrices.
- Tests pass.
```

---

## Prompt 6: Decision Engine + CLI / 根据用户观点推荐策略结构

这一阶段把指标、候选策略、情景分析串起来，输出 decision support，不输出买入建议。

```text
You are Codex-GPT5.5 acting as a senior quant product engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Given user trade thesis + normalized option chain + optional historical IV/HV/VIX data, generate ranked strategy recommendations and explain why each strategy fits or does not fit.

Suggested locations:
- src/quant_system/options/buy_side_decision.py
- tests/test_options_buy_side_decision.py
- src/quant_system/api/routes/options.py for API route
- src/quant_system/cli.py for CLI command

Supported MVP strategies:
- Long Call
- Bull Call Spread
- LEAPS Call
- LEAPS Call Spread

Decision logic:

A. long_term_aggressive_bullish
- Prefer LEAPS Call if IV is not extremely high and liquidity is acceptable.
- Prefer high-delta LEAPS Call for stock-replacement style.
- If IV is high or user wants lower premium, consider LEAPS Call Spread.

B. long_term_conservative_bullish
- Prefer LEAPS Call Spread.
- Prefer lower break-even, lower theta burden, and lower net vega exposure.
- Penalize naked LEAPS if IV rank is high or spread is wide.

C. short_term_speculative_bullish
- Prefer Long Call only when expected move is fast and large.
- Require acceptable gamma/theta tradeoff.
- Warn strongly if theta burn is high or IV crush risk is high.

D. short_term_conservative_bullish
- Prefer Bull Call Spread.
- Reward reasonable break-even and defined risk.
- Penalize capped upside only if user does not allow capped upside.

E. event_driven_bullish
- If event risk is high and IV rank is high, prefer Call Spread over naked Long Call.
- Warn about IV crush.
- If no strong quantitative edge exists, phrase as "waiting for post-event IV normalization may be more prudent under current assumptions"; do not say what the user should do.

Decision tree (reference pseudocode, must be implemented as deterministic rules, not free-form heuristics):
```
if dte < 14:
    if iv_rank > 60 or volatility_view == "expect_iv_crush":
        prefer bull_call_spread; demote naked long_call
    else:
        if risk_preference == "aggressive":
            prefer ATM / slightly OTM long_call
        else:
            prefer ITM long_call or bull_call_spread
elif 14 <= dte <= 60:
    if iv_rank < 40 and volatility_view in ("auto", "prefer_low_iv", "expect_iv_expansion"):
        if view_type == "short_term_speculative_bullish":
            prefer ATM / slightly OTM long_call
        else:
            prefer bull_call_spread
    else:
        prefer bull_call_spread; demote naked long_call when iv_rank > 70
elif dte > 180:
    if view_type == "long_term_aggressive_bullish" and iv_rank < 40:
        prefer leaps_call (delta 0.65-0.85)
    elif view_type == "long_term_conservative_bullish" or iv_rank > 60:
        prefer leaps_call_spread
    else:
        rank both leaps_call and leaps_call_spread by composite score
apply buyer_regime_penalty
apply event_risk adjustments
```

Four-axis risk attribution (required output per recommendation):
- direction_risk_score: derived from required_move_pct vs target_move_pct and vs expected_move_pct
- time_risk_score: derived from theta_pct_of_premium and dte
- volatility_risk_score: derived from iv_rank, vega_pct_of_premium, and event proximity
- liquidity_risk_score: derived from spread_pct, OI, volume, quote_staleness
- All on 0-100 (higher = more risky); the recommendation should also expose primary_risk_source = argmax of the four.

Output for each recommendation:
- strategy_type
- score
- rank
- one_line_summary
- key_reasons
- key_risks
- max_loss
- max_profit if defined
- break_even
- required_move_pct
- theta_burn_7d_pct
- estimated_iv_crush_loss_pct
- liquidity_score
- risk_reward
- expected_move_pct
- target_vs_expected_move_ratio
- buyer_friendliness_score
- iv_crash_risk_score
- risk_attribution: { direction, time, volatility, liquidity }
- primary_risk_source
- market_regime
- market_regime_penalty
- warnings
- scenario_summary
- scenario_ev (optional, only when user_scenarios is provided)

Explanation style:
- Clear and trader-friendly.
- Avoid direct advice language.
- Prefer: "this structure is more suitable for the stated thesis".
- Avoid: "buy this", "best trade", "safe", "guaranteed", "risk-free".
- Explain hidden costs: IV premium, IV crush, theta decay, bid-ask spread, break-even distance, low-delta lottery risk, wrong DTE risk, event timing risk.

API/CLI:
- Add a POST route under existing options API namespace, for example /api/options/buy-side/assistant or the route name chosen in Prompt 0.
- Add a CLI command for debug/dev use, for example:
   quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
- CLI should output JSON or a compact table and must not place orders.

Constraints:
- No UI yet.
- No live data fetch inside the pure decision engine; API/CLI may call the existing read-only provider and pass normalized data in.
- No hard-coded ticker.
- No probability-of-profit model in Phase 14 MVP.

Tests:
- each view_type
- high IV / event risk behavior
- conservative vs aggressive risk preference
- market regime behavior
- safe wording in explanations
- deterministic ranking
- mocked provider route/CLI behavior if route/CLI is added

Done when:
- Mock option chain + thesis returns ranked recommendations with explanations, warnings, scenario summary, and market regime fields.
- API/CLI integration is covered or explicitly deferred with rationale.
- Tests pass.
```

---

## Prompt 7: UI Page / 在现有平台中添加买方期权策略界面

现在才开始 UI。底层稳定后，再接页面，避免 UI 绑死错误模型。

```text
You are Codex-GPT5.5 acting as a senior full-stack trading platform engineer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Add the Buy-side US Options Strategy Assistant UI inside the existing Next.js frontend.

Must reuse existing frontend style:
- Tailwind/design tokens from existing files, such as:
   - border-border-subtle
   - bg-bg-surface
   - text-text-primary / text-text-secondary
   - font-data-mono
   - font-label-caps
   - border-accent-success/40
   - bg-accent-success/10
   - text-accent-danger / text-warning
- Component patterns from:
   - src/frontend/components/forms/OptionsScreenerForm.tsx
   - src/frontend/components/forms/OptionsRadarView.tsx
- Bilingual copy pattern with copy.en / copy.zh where existing options pages use it.
- Existing navigation/sidebar/page routing.

Do not introduce:
- shadcn
- Mantine
- MUI
- Recharts or any charting library unless it already exists in the app
- A new design system

Suggested page:
- src/frontend/app/options-buyside/page.tsx
- src/frontend/components/forms/BuySideOptionsAssistant.tsx
- Add nav entry wherever existing options pages are registered.

UI sections:

A. Trade Thesis Panel
- ticker
- view_type:
   - Long-term aggressive bullish
   - Long-term conservative bullish
   - Short-term speculative bullish
   - Short-term conservative bullish
   - Event-driven bullish
- target_price
- target_date
- max_loss_budget
- risk_preference: aggressive / balanced / conservative
- allow_capped_upside
- avoid_high_iv
- volatility_view selector: auto / prefer_low_iv / expect_iv_crush / expect_iv_expansion
- event_risk
- expected_iv_change_vol_points
- optional user scenarios (3 rows: bull / base / bear, each with probability, spot_change_pct, iv_change_vol_points)

B. Market Snapshot Panel
- spot price
- timestamp
- nearest earnings/event date if available, otherwise "not available"
- current IV summary if available
- IV rank/percentile if available
- market regime banner, reused from OptionsRadarView/OptionsScreenerForm style
- data quality warnings

C. Strategy Recommendation Cards
- rank
- strategy name
- total score
- buyer_friendliness_score badge (large, prominent)
- best-use label
- net debit
- max loss
- max profit if capped
- break-even
- required move and expected_move_pct comparison (e.g. target +5% vs implied move +8%)
- reward/risk
- theta burn 7D
- estimated IV crush loss
- liquidity score
- four-axis risk attribution bar (direction / time / volatility / liquidity), with primary_risk_source highlighted
- one-line summary of the form "Primary risk: <volatility|time|direction|liquidity>"
- warnings
- explanation

D. Strategy Comparison Table
- strategy type
- expiration
- strikes
- net debit
- max loss
- max profit
- break-even
- required move
- total score
- theta safety
- IV crush risk
- liquidity
- reward/risk
- key warning

E. Anti-Pitfall Checklist
- IV Rank too high?
- Crossing earnings/event?
- 7-day theta burn too high?
- Bid-ask spread too wide?
- Break-even too far?
- Low-delta lottery call?
- DTE too short for thesis?
- Max loss exceeds budget?
- Strategy depends too much on IV staying high?
- If direction is right but IV falls, can it still profit?

F. Scenario Lab
- Inputs: spot change range, IV change range, days passed
- Display: table fallback first; heatmap only if existing charting support is already available
- Highlight:
   - spot flat + IV crush
   - spot up + IV down
   - theta-only case
   - best case / worst case
- Optional user-scenario EV widget: 3 rows (bull / base / bear) with probability, spot %, IV vol points; show weighted EV and per-scenario contribution. Label clearly as user-input subjective EV, not market-implied probability.

Required disclaimer:
"This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading."

Implementation requirements:
1. Reuse existing fetch/error/loading patterns.
2. Add loading, error, empty-state, and missing-data states.
3. Keep layout dense and work-focused, like the existing options tools.
4. Make responsive behavior consistent with existing frontend.
5. Avoid marketing/landing-page style.
6. Add frontend tests according to existing test framework if available.

Constraints:
- Do not redesign the platform.
- Do not change unrelated pages.
- Do not duplicate components if reusable local patterns exist.
- Do not use advice language like "Buy this option now".

Done when:
- The new module/page is accessible from existing navigation.
- User can input thesis and see ranked strategy recommendations.
- Strategy comparison, anti-pitfall checklist, risk disclaimer, market regime, and Scenario Lab render correctly.
- Frontend lint/build pass.
```

---

## Prompt 8: Testing, Validation, Risk Controls / 测试、边界情况、风控文案与文档同步

OCC 的标准化期权风险披露文件强调，投资者在买卖期权前应阅读 Characteristics and Risks of Standardized Options。界面里的风险提示是必须项，不是装饰。

```text
You are Codex-GPT5.5 acting as a senior QA engineer and quant risk reviewer.

Follow the GLOBAL REPO CONTEXT and SAFETY GUARDRAILS above.

Goal:
Perform a full testing, validation, safety, and documentation pass for the Buy-side US Options Strategy Assistant.

Baseline:
- Before Phase 14, python -m pytest -q had 270 passing tests.
- ruff check was clean.
- npm --prefix src/frontend run lint was clean.
- npm --prefix src/frontend run build was clean.
- After Phase 14, test count should be >= 270 + new tests and there should be no regressions.

Test categories:

A. Unit tests
- data contract validation
- mid price calculation
- bid-ask spread calculation
- DTE calculation
- intrinsic/extrinsic value
- break-even calculation
- required move calculation
- theta burn calculation
- IV crush estimate
- liquidity score
- risk warning generation
- vega/theta unit convention

B. Strategy tests
- Long Call generation
- Bull Call Spread generation
- LEAPS Call generation
- LEAPS Call Spread generation
- invalid spread filtering
- missing Greeks handling
- low liquidity filtering
- high IV event-risk warning
- conservative vs aggressive view behavior
- buyer market-regime penalty behavior

C. Scenario Lab tests
- spot up / IV unchanged
- spot up / IV down
- spot flat / IV crush
- time decay only
- spread capped upside approximation
- missing Greeks
- option value floored at zero

D. UI tests
- page renders
- thesis form validation
- loading state
- error state
- empty option chain state
- missing data warning state
- recommendation cards render
- comparison table renders
- scenario table renders
- risk disclaimer renders
- forbidden advice language is absent

E. Integration tests
- mocked Futu option chain response
- mocked option quotes
- normalized data passed to decision engine
- decision engine output rendered by UI
- API route returns safe structured payload
- CLI returns safe JSON/table output if implemented

F. Risk and language review
Ensure UI/API explanation text does NOT say:
- buy this
- guaranteed profit
- safe strategy
- best trade
- risk-free

Safer language:
- more suitable for the stated thesis
- quantitatively preferred under current assumptions
- defined-risk structure
- estimated scenario PnL
- decision support only, not financial advice

Required disclaimer:
"This tool provides quantitative decision support only and is not financial advice. Options involve risk and may lose value rapidly due to time decay, volatility changes, liquidity, and adverse underlying price movement. Review official options risk disclosures before trading."

Validation commands:
- conda activate ai-quant
- python -m pytest -q
- ruff check src/quant_system tests
- npm --prefix src/frontend run lint
- npm --prefix src/frontend run build

Documentation sync:
- Update docs/options/buyside_strategy_learning.md, or create it only if no appropriate existing doc exists.
- Update docs/delivery/phase_14_delivery.md.
- Update docs/execution/phase_14_execution.md.
- Update docs/INDEX.md and README.md only if they already list phase/module entry points.
- Keep docs concise and consistent with Phase 13 style.

Tasks:
1. Run existing and new tests.
2. Add missing tests where coverage is thin.
3. Fix failing tests related to the new module.
4. Run lint/build.
5. Check git diff for unrelated modifications.
6. Produce final validation report.

Constraints:
- Do not rewrite the module from scratch.
- Do not change unrelated platform behavior.
- Do not hide known limitations.
- If a command cannot be run because dependencies are missing, state that clearly and explain what was verified instead.

Done when:
- Tests/build pass, or failures are clearly documented and unrelated.
- Unit, strategy, scenario, integration, and UI coverage is sufficient.
- Risk language is safe and professional.
- Docs are synchronized.
- Final changed-files summary is provided.
```

---

## Phase 15+ Future Scope (Not In Phase 14)

These are intentionally deferred. Do not pull them into Phase 14 even if time remains.

1. Calendar Spread (long-dated long call + short near-dated call, same strike).
2. Diagonal Call Spread, including Poor Man's Covered Call (PMCC) workflow with rolling cadence.
3. Earnings Event Strategy module: pre-earnings IV crush historical statistics, expected-move backtest, post-earnings drift analysis.
4. Buy-side Backtest engine:
   - Fixed-rule backtest (e.g. "IV rank < 30 + 50DMA breakout buys 45 DTE delta-0.5 call").
   - Strategy comparison backtest (ATM call vs OTM call vs spread vs LEAPS vs stock under same regime filter).
   - Event backtest (per-ticker earnings, FOMC, CPI windows).
   - PnL attribution to delta / gamma / theta / vega buckets.
5. Risk-neutral Probability of Profit (Black-Scholes / binomial) reconciled against historical probability.
6. Multi-leg ratio / butterfly / condor structures for advanced users.

Guardrail: any future phase that picks these up must still respect the SAFETY GUARDRAILS block (no live trading, no order placement, no account unlock, read-only Futu data only).