# Hermes Workbench — Design Artifacts

Professional frontend design records for the Hermes unified research workbench
(F0 high-fidelity directions → F1 clickable state prototype → F2 production shell).

These files live under `docs/design/hermes-workbench/` only. They are **not**
imported from `app/`, `components/`, `lib/`, or `public/`.

---

## Status

| Gate | Status | Notes |
| --- | --- | --- |
| F0 visual directions | **direction-a approved for polish path** | Hierarchy A (COO desk) selected for visual redesign. B/C remain comparison artifacts. |
| F0 visual polish (A) | **superseded by v3** | 2026-07-13 Linear/Raycast craft was user-rejected (AI 味 + skinny mid column). |
| F0 v3 finance redesign (A) | **landed 2026-07-13** | **v3 finance/crypto redesign after user craft rejection.** Binance/Revolut/xAI desk DNA; full-width stage; horizontal top nav; amber CTAs; no purple haze / no permanent 288px right rail. |
| F0 independent review | **completed 2026-07-13** | UX pass/fail recorded below (pre-polish). Package was Ready for user selection; user chose A for craft pass. |
| F1 clickable prototype | **draft ready — awaiting user gate** | Full-state catalogs + walkthrough under `f1/`. Aligned to v3 finance desk shell. **Not approved.** |
| F2 production shell | not started | Blocked on F1 written approval + candidate-integrity Task 5 types. |

### F0 decision

- status: `approved` (stem) · craft **v3 redesign after user rejection**
- selected stem: `direction-a`
- approver: `user`
- date: `2026-07-13`
- adjustments (explicit user intent):
  1. Keep direction-a COO hierarchy (safety → attention/action → status → work → result → disabled composer).
  2. Linear-purple “AI product” craft rejected; too much AI 味; middle column felt thin/uncomfortable.
  3. Re-reference finance/crypto DNA (Binance, Coinbase, Revolut, Kraken) + non-purple AI restraint (xAI, Claude coral, Ollama mono).
  4. Kill permanent right rail + fat side-nav combo; full-width main stage (≥1100px content at 1440).
  5. Amber/yellow for attention/money CTAs; blue only for secondary links; Hermes purple only as flat brand mark.

### F1 decision

- status: `draft` — **not approved**
- package: [`f1/prototype.html`](./f1/prototype.html) + [`f1/prototype.css`](./f1/prototype.css) + [`f1/states/`](./f1/states/)
- visual base: F0 `direction-a` **v3 finance/crypto trading desk** (Binance canvas `#0b0e11` / surface `#1e2329`, amber CTAs)
- stop: written user approval required before any `src/frontend/app` / production shell work from this package

---

## Directions (F0)

Shared tokens and breakpoints: [`f0/shared.css`](./f0/shared.css)

| Stem | File | Theme | Hierarchy emphasis |
| --- | --- | --- | --- |
| `direction-a` | [`f0/direction-a.html`](./f0/direction-a.html) | **COO trading desk (v3)** | Full-width stage · horizontal top nav · attention full width · 值守 bottom strip |
| `direction-b` | [`f0/direction-b.html`](./f0/direction-b.html) | **Research timeline** | Change and progress first (pipeline steps + chronological stream) |
| `direction-c` | [`f0/direction-c.html`](./f0/direction-c.html) | **Quiet split canvas** | Conversation and result first; idle still answers safety / action / current work / recent result in five seconds |

Each HTML file includes local state toggles (no CDN):

1. **今日 idle** — Today overview  
2. **对话/执行** — conversation / execution composition  
3. **审批** — approval / Gate 2 CAS read-only presentation  
4. **结果** — factor / backtest / experiment result composition  

Identical fixed content (comparison is hierarchy, not copy):

- Safety strip only at top: `仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK`
- Candidate: `factor-momentum_20d_reversal-323b045e4b`
- Automation: `3/4` with `weekly_review` stale + collapsed technical detail
- Recent result: `AAPL 风险与新因子计划 · completed_degraded`
- Disabled composer: `真实 Hermes 写入能力尚未通过` + disabled 发送

Responsive behavior uses **real CSS breakpoints** (not whole-UI `transform: scale`):

- ~1440 desktop full-width stage (main content ≥1100px; no permanent 288px right rail)  
- ~1280 laptop one strong main column  
- ~768 tablet stack · horizontal nav → mobile tabs  
- ~390 phone stack  

---

## F1 full-state prototype (draft)

Local-only clickable package (no production imports, no network beyond the static server):

| Path | Role |
| --- | --- |
| [`f1/prototype.html`](./f1/prototype.html) | COO desk shell + walkthrough + state matrix |
| [`f1/prototype.css`](./f1/prototype.css) | v3 finance-desk tokens / full-width shell / mobile order |
| [`f1/states/home.json`](./f1/states/home.json) | `empty/loading/normal/degraded/hermes_offline` |
| [`f1/states/conversation.json`](./f1/states/conversation.json) | `sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback` |
| [`f1/states/tasks.json`](./f1/states/tasks.json) | `queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped` |
| [`f1/states/approvals.json`](./f1/states/approvals.json) | `available/approved/rejected/expired/stale/digest_mismatch` |
| [`f1/states/results.json`](./f1/states/results.json) | `loading/partial/no_data/audit_warning/source_missing` |

Walkthrough (review chrome):  
`提出目标 → 结构化计划 → Gate 1 → streaming → completed_degraded → Gate 2 → Gate 3`

Visible **prototype data** badge sits outside product chrome. Composer never submits. Catalogs load only via `fetch("./states/*.json")`.

### F1 review (implementer self-check — independent reviewer TBD)

```markdown
## F1 review

- Full lifecycle: pass (implementer)
- State catalog: pass (exact IDs)
- 1440/1280/768/390: pass (implementer; overflow none)
- Keyboard-only: pass (aria-pressed, modal focus restore, Escape)
- Reduced motion: pass (CSS kill-switch)
- Horizontal overflow: none
- Console errors/warnings: 0 product errors (browser favicon 404 only)
```

**Not approved.** Do not start F2 from this draft until written user approval is recorded here.

---

## How to open locally

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
```

Then open:

- http://localhost:4173/f1/prototype.html  
- http://localhost:4173/f0/direction-a.html  
- http://localhost:4173/f0/direction-b.html  
- http://localhost:4173/f0/direction-c.html  

Inspect at 1440×900, 1280×800, 768×1024, and 390×844. At each width check:

```text
document.documentElement.scrollWidth <= window.innerWidth
interactive targets >= 44 CSS pixels
focus order follows visible reading order
safety message not duplicated in content
normal automation not expanded into four equal cards
```

---

## Independent review (completed)

Reviewer: frontend/UX (independent of design author)  
Date: 2026-07-13  
Method: full-size headless Chrome at 1440×900, 1280×800, 768×1024, 390×844; idle + state toggles; overflow / 44px / safety probes.  
Full write-up: Hermes-quant-agent `.superpowers/sdd/frontend-task-1-ux-review.md` (checklist-aligned).

| Criterion | A | B | C | Notes |
| --- | --- | --- | --- | --- |
| Hierarchy (action / exception / work / result) | Pass | Pass | Pass | Distinct A desk / B timeline / C split; automation one-row |
| Five-second scan (idle Today) | Pass | Fail@390 S5 | Pass | B: `completed_degraded` below fold on phone |
| Safety uniqueness (strip only) | Pass | Pass | Pass | Single top `role="status"`; no body paper/live/kill/API |
| Long Chinese + long IDs | Pass | Pass | Pass | wrap/break-all; no horizontal overflow |
| Reduced motion | Pass | Pass | Pass | shared kill-switch; B spark neutralized |
| Contrast | Pass* | Pass* | Pass* | *disabled composer copy ~3.95:1 (medium) |
| Viewport 1440 | Pass | Pass | Pass | no overflow |
| Viewport 1280 | Pass | Pass | Pass | secondary collapses; primary content kept |
| Viewport 768 | Pass | Pass | Pass | honest stack |
| Viewport 390 | Pass | Fail S5 | Pass | no overflow; B progress chrome tall |
| 44px targets + focus order | Pass | Pass | Pass | 0 sub-44 interactive targets measured |
| Automation compression | Pass | Pass | Pass | never four equal healthy cards |
| Direction identity (A/B/C distinct) | Pass | Pass | Pass | action-status / change-progress / conversation-result |

**Outcome:** **Ready for user selection** — A Pass · B Pass with mobile S5 caveat · C Pass.  
**Not approved.** No direction selected. F0 decision section stays empty until written user choice.

---

## Constraints carried into design

- Only the global SafetyStrip shows paper / live / kill / API.  
- Normal automation is one row; technical cron/run/path details are collapsed.  
- Platform candidate label: 研究审批项 / Research approval item.  
- Composer is non-submitting; no Hermes / tasks / provider / live calls.  
- No fake “approved” gate before written user selection.
