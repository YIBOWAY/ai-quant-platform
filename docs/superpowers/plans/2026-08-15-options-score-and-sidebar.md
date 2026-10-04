# Options Hands + Detailed Seller Scores + Honest Composer

> **历史冻结（2026-08-26）：**这是 2026-08-15 的期权/UI 实施计划，不能覆盖
> 当前 options v3 推荐合同、22:00 HQA cron 或现行 Hermes composer。正文复选框
> 不是 NEXT。统一边界见 [`../README.md`](../README.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put 期权筛选器 / 期权雷达 / 买方期权 / AI 新闻 back on the site sidebar; replace the screener’s three-word 评级 with a documented per-contract score breakdown; keep radar/buy-side scoring honest and comparable; stop telling the owner Hermes is ready to talk while send is hard-disabled.

**Architecture:** Sidebar visibility stays in `sectionsForSurface` (never render an empty group). Seller scoring becomes a pure function `score_seller_contract(...)` used by the screener and radar. The 评估 column shows a 0–100 composite plus five named legs. Buy-side already has component scores — Task 5 only surfaces them and documents weights, no second scoring language. Composer: when `hermesChatAdmission.chatOpen` is true, wire the existing `ComposerSubmitController`; when false, show blocked copy. Do not flip public `chat_write_ready` / public composer settings.

**Tech Stack:** Python 3.12 + pytest (platform venv), Next.js 15 / Vitest (frontend `npx vitest run`), existing FastAPI options routes. HQA tests use `./.venv/bin/python -m pytest` only if an HQA file is touched (this plan does not touch HQA code).

## Diagnosis (read before coding)

### 期权筛选器 (`quant_system/options/screener.py`)
- It is a **filter + three buckets**, not a score. Notes from `_candidate_notes` become `Avoid` if they hit `HARD_FAILURES`, else `Watch` if any note remains, else `Strong`.
- `Strong` requires a completely clean note list. Real names almost always pick up a soft note (min APR, missing OI, IV missing) and collapse to `观察`.
- Ranking among the same bucket is `annualized_yield` then tighter spread. Yield is `(mid / strike_or_spot) * (365 / dte)` — no assignment, POP, or fees (already disclosed in assumptions).
- `iv_rank` is always `None` in the screener (comment: filled later by radar).
- Frontend 评级 column maps Strong/Watch/Avoid → 强烈/观察/避开. That is the “评估” the owner sees. There is no numeric breakdown.

### 期权雷达 (`quant_system/options/radar.py`)
- Reuses the screener per ticker, then `compute_global_score`:
  - rating weight Strong=100, Watch=30, Avoid=0
  - `min(APR*100, 60)`
  - `0.4 * IVR` (0 if unknown)
  - −50 if earnings in window, −100 if spread > 10%, plus VIX regime penalty
- Rating dominates. Two Strong rows that differ a lot in liquidity look the same until APR/IVR move.
- IVR is a 252-day percentile in `iv_history.compute_iv_rank` (not the tastytrade range formula). Keep that definition; document it. Do not invent IVR in the screener when history is missing.

### 买方期权 (`buy_side_metrics.py` + `buy_side_strategy.py`)
- Already has the detailed scores the screener lacks: liquidity, theta safety, volatility valuation (`100 - IVR` for buyers), greek efficiency, breakeven quality, buyer_friendliness (30/30/20/20), contract_quality (25/25/25/15/10), plus strategy `total_score` (direction 25 / vol 20 / theta 20 / greek 15 / liq 10 / R:R 10).
- Task 5 does **not** invent a second language. It makes those numbers visible and labeled as decision support.

### External references (do not copy vendor products)
- tastytrade: sell premium when IV is rich vs its own history (IV Rank). We already store a 252-day percentile; use it as one **seller** leg, weight 0 if unknown.
- Counter-evidence (SJ Options SPX study): high IVR is not a free lunch. So IVR is a component, not a veto, and the UI must say “相对自身历史，不是胜率”.
- Liquidity literature: bid-ask width is the practical tax. Keep spread in the liquidity leg; do not add a second cliff besides the existing Avoid gate.
- Buy-side: high IV is expensive (crush risk). Existing `100 - IVR` direction is correct for buyers; opposite of the seller IVR leg.

### Hermes 不能回复
- Screenshot: “Hermes 对话已就绪” + 输入框禁用 + “发送（已禁用）”.
- Cause: `HermesWorkbenchShell` hardcodes `<ComposerDock allowSubmit={false} disabled />`. Layout already computes `hermesChatAdmission(flags, gateway.chat_write_ready)`. When that is open, the dock still cannot submit.
- Public composer / public cutover stay closed (`AGENTS.md`). Local owner path already has `ComposerSubmitController` + `sendComposerTurn`. Wire that when `chatOpen`; otherwise show blocked copy and never claim 已就绪.

## Global Constraints

- `live_trading_enabled=false`. Options pages stay read-only research. Scores are not trade tickets and must say so.
- Sidebar: show 期权筛选器, 期权雷达, 买方期权, AI 新闻. Do **not** restore 期权工具 or Polymarket unless a later owner order says so. Never render a group heading with zero items.
- Site sidebar stays; do not hide it on `/hermes`.
- Seller composite weights (verbatim): yield 0.30, liquidity 0.25, delta_safety 0.20, iv_edge 0.15, iv_rank 0.10. Missing iv_rank drops that weight and renormalizes. Then add `market_regime_penalty` (already −15/−40 etc.) and clip to [0, 100].
- Avoid-rated rows keep composite but stay sorted after Watch/Strong. Default list still hides Avoid unless `include_rejected`.
- Do not invent IV, Greeks, or IVR. Missing inputs lower or omit that leg.
- Do not set public `chat_write_ready` or open public composer. Only honor existing local admission.
- Work only in this worktree/checkout. Do not edit `data/_runtime/agent-v02-work/` (deploy-mirror).
- Tests: platform pytest via `$HOME/programs/ai-quant-platform/.venv/bin/python -m pytest` if that venv exists, else `python -m pytest` from the platform root. Frontend: `cd src/frontend && npx vitest run <files>`.
- TDD on every task. Commit after each task.

---

## File map

- Modify: `src/frontend/lib/navConfig.ts`, `src/frontend/lib/navConfig.test.ts`
- Create: `src/quant_system/options/seller_score.py`
- Modify: `src/quant_system/options/models.py`, `src/quant_system/options/screener.py`, `src/quant_system/options/radar.py`
- Create: `tests/test_options_seller_score.py`
- Modify: `tests/test_options_screener.py`, `tests/test_options_radar.py`
- Modify: `src/frontend/lib/api.ts`, `src/frontend/components/forms/OptionsScreenerForm.tsx`
- Modify: options radar frontend table if it shows `global_score` only
- Modify: buy-side frontend to print existing component scores
- Modify: `src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx` + its tests

### Task 1: Restore four sidebar hands

**Files:**
- Modify: `src/frontend/lib/navConfig.ts`
- Modify: `src/frontend/lib/navConfig.test.ts`

**Interfaces:**
- Consumes: `sectionsForSurface`, `isVisibleOnSurface`
- Produces: default sidebar hrefs include `/options-screener`, `/options-radar`, `/options-buyside`, `/ai-news`; still exclude `/options-tools`, `/polymarket`, `/data-explorer` as siblings of `/watch`

- [ ] **Step 1: Write the failing test**

In `navConfig.test.ts` `computes full route lists by navigation surface`, change the default sidebar expectation to:

```ts
expect(sidebarRoutes).toEqual([
  "/hermes",
  "/brief",
  "/watch",
  "/paper-trading",
  "/position-map",
  "/options-screener",
  "/options-radar",
  "/options-buyside",
  "/ai-news",
  "/settings",
]);
expect(sidebarRoutes).not.toContain("/options-tools");
expect(sidebarRoutes).not.toContain("/polymarket");
expect(sectionsForSurface(buildNavSections({ shellEnabled: true }), "sidebar").map((s) => s.id)).toEqual([
  "research",
  "paper",
  "options",
  "markets",
  "system",
]);
```

Remove those four hrefs from the “must not contain” loop if present.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/frontend && npx vitest run lib/navConfig.test.ts`
Expected: FAIL because those hrefs are still `surfaces: []`

- [ ] **Step 3: Write minimal implementation**

In `navConfig.ts` delete `surfaces: []` only on `optionsScreener`, `optionsRadar`, `buySide`, `aiNews`. Leave `optionsTools`, `orderBook`, `agentStudio`, `asiaRadar`, `marketCrossSection` hidden.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/frontend && npx vitest run lib/navConfig.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/frontend/lib/navConfig.ts src/frontend/lib/navConfig.test.ts
git commit -m "Show screener, radar, buy-side, and AI news on the sidebar."
```

### Task 2: Seller detailed score (backend)

**Files:**
- Create: `src/quant_system/options/seller_score.py`
- Modify: `src/quant_system/options/models.py` (`OptionsScreenerCandidate`)
- Modify: `src/quant_system/options/screener.py` (`_build_candidate`)
- Create: `tests/test_options_seller_score.py`
- Modify: `tests/test_options_screener.py` (assert new fields on the Strong fixture)

**Interfaces:**
- Consumes: existing candidate fields (`annualized_yield`, `spread_pct`, `open_interest`, `volume`, `delta`, `hv_iv_ratio`, `iv_rank`, `market_regime_penalty`, `rating`)
- Produces:

```python
class SellerScoreBreakdown(BaseModel):
    yield_score: float | None = Field(default=None, ge=0, le=100)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    delta_safety_score: float | None = Field(default=None, ge=0, le=100)
    iv_edge_score: float | None = Field(default=None, ge=0, le=100)
    iv_rank_score: float | None = Field(default=None, ge=0, le=100)
    composite: float = Field(ge=0, le=100)
    weights_used: dict[str, float]
```

`score_seller_contract(...)` is a pure function. Screener attaches `seller_score` on every candidate.

Scoring rules (verbatim):
- `yield_score`: `clip((annualized_yield / 0.60) * 100, 0, 100)` i.e. 60% APR → 100. None if yield missing.
- `liquidity_score`: average of spread leg and OI leg. Spread: `0` if spread_pct is None; `100` if spread_pct ≤ 0.03; `40` if ≤ 0.08; else `10`. OI: `0` if None; `100` if ≥ 500; `70` if ≥ 100; `30` if ≥ 50; else `10`.
- `delta_safety_score`: seller wants smaller |delta|. `clip((1 - min(abs(delta), 1)) * 100, 0, 100)`. None if delta missing.
- `iv_edge_score`: seller wants rich IV vs HV. `hv_iv = hv/iv`. `clip((1.2 - hv_iv) / 1.2 * 100, 0, 100)` if hv_iv present; None otherwise.
- `iv_rank_score`: `clip(iv_rank, 0, 100)` if present else omit (do not treat missing as 0 in the average).
- Composite: weighted average of available legs with weights yield 0.30, liquidity 0.25, delta_safety 0.20, iv_edge 0.15, iv_rank 0.10, renormalize over present legs. Then `clip(composite + market_regime_penalty, 0, 100)`.
- Rank visible rows by rating bucket then `-composite` then `-annualized_yield`.

- [ ] **Step 1: Write the failing test**

`tests/test_options_seller_score.py`:

```python
from quant_system.options.seller_score import score_seller_contract

def test_seller_score_uses_five_legs_and_renormalizes_without_iv_rank():
    breakdown = score_seller_contract(
        annualized_yield=0.30,  # 30% APR → 50 yield score
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.25,
        hv_iv_ratio=0.60,
        iv_rank=None,
        market_regime_penalty=0.0,
    )
    assert breakdown.iv_rank_score is None
    assert "iv_rank" not in breakdown.weights_used
    assert breakdown.yield_score == 50.0
    assert breakdown.liquidity_score == 100.0
    assert abs(breakdown.composite - (
        50.0 * 0.30 + 100.0 * 0.25 + 75.0 * 0.20 + 50.0 * 0.15
    ) / 0.90) < 1e-6

def test_seller_score_applies_regime_penalty():
    raw = score_seller_contract(
        annualized_yield=0.60,
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.20,
        hv_iv_ratio=0.50,
        iv_rank=80,
        market_regime_penalty=0.0,
    )
    penalized = score_seller_contract(
        annualized_yield=0.60,
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.20,
        hv_iv_ratio=0.50,
        iv_rank=80,
        market_regime_penalty=-15.0,
    )
    assert penalized.composite == max(0.0, raw.composite - 15.0)
```

Also extend `test_options_screener_scores_sell_put_candidate` with `assert candidate.seller_score is not None` and `assert candidate.seller_score.composite >= 0`.

- [ ] **Step 2: Run test to verify it fails**

Run: `$HOME/programs/ai-quant-platform/.venv/bin/python -m pytest tests/test_options_seller_score.py tests/test_options_screener.py::test_options_screener_scores_sell_put_candidate -q`
Expected: FAIL import or attribute error

- [ ] **Step 3: Write minimal implementation**

Implement `seller_score.py` exactly as specified. Add `seller_score: SellerScoreBreakdown | None = None` on `OptionsScreenerCandidate`. In `_build_candidate`, after rating, call `score_seller_contract` with the row fields. Change `run_options_screener` sort key to rating then `-composite` then `-yield`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$HOME/programs/ai-quant-platform/.venv/bin/python -m pytest tests/test_options_seller_score.py tests/test_options_screener.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quant_system/options/seller_score.py src/quant_system/options/models.py src/quant_system/options/screener.py tests/test_options_seller_score.py tests/test_options_screener.py
git commit -m "Score each short-premium contract with a five-leg breakdown."
```

### Task 3: Screener table shows the breakdown

**Files:**
- Modify: `src/frontend/lib/api.ts` (`OptionsScreenerCandidate`)
- Modify: `src/frontend/components/forms/OptionsScreenerForm.tsx`

**Interfaces:**
- Consumes: `candidate.seller_score` from Task 2
- Produces: 评级 column becomes 评估: `72 观察` plus a second line `收益 50 · 流动性 100 · Δ安全 75 · IV估值 50 · IVR --`

- [ ] **Step 1: Write the failing test**

Add `src/frontend/lib/sellerScoreDisplay.test.ts`:

```ts
import { formatSellerScoreLine } from "@/lib/sellerScoreDisplay";

it("prints composite and five legs in Chinese", () => {
  expect(
    formatSellerScoreLine(
      {
        yield_score: 50,
        liquidity_score: 100,
        delta_safety_score: 75,
        iv_edge_score: 50,
        iv_rank_score: null,
        composite: 72.2,
        weights_used: { yield: 0.3, liquidity: 0.25, delta_safety: 0.2, iv_edge: 0.15 },
      },
      "zh",
    ),
  ).toContain("72");
  expect(formatSellerScoreLine(...)).toContain("IVR --");
});
```

Create `src/frontend/lib/sellerScoreDisplay.ts` only after the test fails.

- [ ] **Step 2: Run test to verify it fails**

`cd src/frontend && npx vitest run lib/sellerScoreDisplay.test.ts`
Expected: FAIL cannot find module

- [ ] **Step 3: Implement formatter + table cell**

Replace the 评级 cell with:

```tsx
<td>
  <div>{Math.round(candidate.seller_score?.composite ?? 0)} {ratingLabel(candidate.rating, locale)}</div>
  <div className="font-body-sm text-text-secondary">
    {formatSellerScoreLine(candidate.seller_score, locale)}
  </div>
</td>
```

Change zh heading `评级` → `评估`, en `Rating` → `Score`. Keep Notes.

Extend `OptionsScreenerCandidate` in `api.ts` with optional `seller_score`.

- [ ] **Step 4: Run tests**

`cd src/frontend && npx vitest run lib/sellerScoreDisplay.test.ts lib/navConfig.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/frontend/lib/api.ts src/frontend/lib/sellerScoreDisplay.ts src/frontend/lib/sellerScoreDisplay.test.ts src/frontend/components/forms/OptionsScreenerForm.tsx
git commit -m "Show a per-contract seller score breakdown in the screener."
```

### Task 4: Radar ranks with the seller composite

**Files:**
- Modify: `src/quant_system/options/radar.py` (`compute_global_score`)
- Modify: `tests/test_options_radar.py`

**Interfaces:**
- Consumes: `candidate.seller_score.composite` from Task 2
- Produces: `global_score = clip(seller_composite + earnings_penalty + extra_spread_penalty, 0, 100)` where earnings_penalty is −15 if earnings in window (not −50), extra_spread_penalty is 0 (spread already in liquidity). Keep rating only as a gate (Avoid stays last). Sort by `-global_score`.

Do **not** keep the old Strong=100 cliff. Document the new formula in a module docstring.

- [ ] **Step 1: Failing test** rewriting the existing global_score assertions in `tests/test_options_radar.py` to the new formula using a fixture candidate with `seller_score.composite = 80` and earnings true → 65.

- [ ] **Step 2: Run to see FAIL**

- [ ] **Step 3: Implement**

- [ ] **Step 4: `pytest tests/test_options_radar.py -q` PASS**

- [ ] **Step 5: Commit** `Rank options radar rows with the seller composite, not a rating cliff.`

### Task 5: Buy-side shows the scores it already computes

**Files:**
- Modify the buy-side results UI (`src/frontend/components/forms/BuySideOptionsAssistant.tsx` or the file that renders `total_score`)
- Add `src/frontend/lib/buySideScoreDisplay.ts` + test if no formatter exists

**Interfaces:**
- Consumes: existing `BuySideStrategyScore` fields
- Produces: each candidate card/row shows `总分` plus `方向/波动/时间/希腊/流动性/盈亏比` when present. No new backend formula.

If a field is null, print `--`. Do not invent numbers.

- [ ] Steps: failing formatter test → implement → render → commit `Surface existing buy-side component scores on each candidate.`

### Task 6: Owner composer submits when admission is open

**Files:**
- Modify: `src/frontend/components/hermes/shell/HermesWorkbenchShell.tsx`
- Modify: workbench/capability tests that assert a permanently disabled dock

**Interfaces:**
- Consumes: `hermesChatAdmission(flags, chatWriteReady)` already computed in `app/hermes/layout.tsx`
- Produces: if `chatOpen`, render visible `ComposerSubmitController` with `allowSubmit` and `networkSubmit` true (not inside `sr-only`). If not `chatOpen`, render disabled dock + blocked capability copy. Never show “对话已就绪” while send is disabled.

Pass `chatWriteReady` into the shell (layout already has it). Do not change backend public cutover flags.

- [ ] **Step 1:** Add/adjust a shell test: when `deliveryState === "local_mutation_authorized"` and `chatWriteReady`, markup includes an enabled send control or `allowSubmit` path; when blocked, includes the blocked title and no enabled send.

- [ ] **Step 2:** FAIL because dock is hardcoded disabled

- [ ] **Step 3:** Wire `ComposerSubmitController` when open; keep disabled dock when closed; take composer out of `sr-only` so the owner can see it.

- [ ] **Step 4:** Focused vitest on hermes shell / capability / composer presentation PASS

- [ ] **Step 5:** Commit `Let the owner composer submit when local chat admission is open.`

---

## Self-review

1. Sidebar four hrefs → Task 1. Detailed screener 评估 → Tasks 2–3. Radar formula → Task 4. Buy-side visibility → Task 5. Composer contradiction → Task 6.
2. No TBD placeholders.
3. `SellerScoreBreakdown` / `score_seller_contract` names are consistent across Tasks 2–4.
