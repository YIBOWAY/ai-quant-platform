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
| F0 v3 finance redesign (A) | **landed 2026-07-13** | Full-width trading desk after craft rejection; no purple haze / no permanent 288px right rail. |
| F0/F1 platform token rebind | **landed 2026-07-13** | F0/F1 CSS tokens aligned to QUANTUM_CORE (`globals.css`): warm terminal surfaces, info-blue primary CTAs, warning yellow for safety/warn only, Hermes purple brand/focus only. |
| F0 independent review | **completed 2026-07-13** | UX pass/fail recorded below (pre-polish). Package was Ready for user selection; user chose A for craft pass. |
| F1 clickable prototype | **approved 2026-07-13** | Craft accepted with platform token rebind. Full-state catalogs + walkthrough under `f1/`. Density + full-width desk retained. |
| F2 production shell | **code-delivered 2026-07-14** | Read-only Hermes shell, Today hierarchy, Tasks/Approvals/Results, reversible root→Hermes cutover, hard-off chat/execution/unifiedResults/legacyRedirects, static `blocked_in_this_slice`. Chat/approve UI still closed. |

### F0 decision

- status: `approved` (stem) · craft **accepted with platform token rebind**
- selected stem: `direction-a`
- approver: `user`
- date: `2026-07-13`
- adjustments (explicit user intent):
  1. Keep direction-a COO hierarchy (safety → attention/action → status → work → result → disabled composer).
  2. Linear-purple “AI product” craft rejected; too much AI 味; middle column felt thin/uncomfortable.
  3. Full-width trading desk density retained (no skinny mid column).
  4. Kill permanent right rail + fat side-nav combo; full-width main stage (≥1100px content at 1440).
  5. **Platform token alignment (2026-07-13):** rebind F0/F1 CSS to QUANTUM_CORE SSOT in `src/frontend/app/globals.css` — see below.

### Platform token alignment (2026-07-13)

Prototype CSS variables now mirror QUANTUM_CORE (not Binance exchange yellow CTAs):

| Role | Token | Hex |
| --- | --- | --- |
| Page / cards / muted | `--bg` / `--surface` / `--surface-2` | `#12110E` / `#181714` / `#23211C` |
| Borders | `--line` | `#302C25` |
| Text | `--text` / `--muted` / mono secondary | `#E7E0D3` / `#9B9488` / `#D8D1C4` |
| Primary CTA + secondary outline | `--accent` / `--link` (info) | `#5EA2FF` |
| Success / health | `--success` | `#089981` |
| Warning (safety strip + warn pills only) | `--warning` | `#F0B90B` |
| Danger | `--danger` | `#F23645` |
| Hermes (brand mark + focus ring only) | `--hermes` | `#9085E9` |

No purple atmosphere. Warning yellow is not used as Submit/primary fill.

### F1 decision

- status: `approved` — craft accepted with platform token rebind
- approver: `user`
- date: `2026-07-13`
- package: [`f1/prototype.html`](./f1/prototype.html) + [`f1/prototype.css`](./f1/prototype.css) + [`f1/states/`](./f1/states/)
- visual base: F0 `direction-a` full-width trading desk + QUANTUM_CORE palette
- next: F2 production shell proceeded on craft; candidate-integrity types gate real candidate wiring

### F2 decision / delivery (2026-07-14)

- status: `code-delivered` (read-only shell; not chat/execution)
- production base: F0 `direction-a` full-width trading desk + QUANTUM_CORE tokens
- enabled root/navigation: Hermes; `QS_HERMES_SHELL_ENABLED=false` returns root/home nav to Dashboard while direct `/hermes` stays read-only
- hard-off: `chat` / `execution` / `unifiedResults` / `legacyRedirects` are literal `false` (env=true ineffective)
- capability notice: static `blocked_in_this_slice` (no platform capability-contract getter/route in this wave)
- old four research pages retained pending later parity; no mutation path under Hermes F2 surfaces

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
| [`f1/prototype.css`](./f1/prototype.css) | QUANTUM_CORE tokens / full-width shell / mobile order |
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

**Approved 2026-07-13** (craft + platform token rebind). F2 production shell craft may start; keep integrity/type gates for real wiring.

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
