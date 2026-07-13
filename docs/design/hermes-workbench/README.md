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
| F0 visual polish (A) | **landed 2026-07-13** | Premium dark Linear/Raycast craft on `shared.css` + `direction-a.html`. Commit message: `docs(frontend): polish Hermes F0 direction-a to premium dark COO craft`. |
| F0 independent review | **completed 2026-07-13** | UX pass/fail recorded below (pre-polish). Package was Ready for user selection; user chose A for craft pass. |
| F1 clickable prototype | not started | Next after polish acceptance. |
| F2 production shell | not started | Blocked on F1 approval + candidate-integrity Task 5 types. |

### F0 decision

- status: `approved`
- selected stem: `direction-a`
- approver: `user`
- date: `2026-07-13`
- adjustments (explicit user intent):
  1. Keep direction-a COO desk layout hierarchy (action and status first).
  2. Visual craft was unacceptable; require substantial premium redesign.
  3. Study excellent systems from VoltAgent/awesome-design-md (Linear, Raycast, Superhuman, Vercel, Resend, VoltAgent dark product UIs).
  4. Professional frontend agent owns visual craft; not a minor CSS tweak.
  5. Polish landed in commit series after approval: premium dark COO craft for `direction-a`.


---

## Directions (F0)

Shared tokens and breakpoints: [`f0/shared.css`](./f0/shared.css)

| Stem | File | Theme | Hierarchy emphasis |
| --- | --- | --- | --- |
| `direction-a` | [`f0/direction-a.html`](./f0/direction-a.html) | **COO desk** | Action and status first (KPI strip, attention card, values rail) |
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

- ~1440 desktop with secondary panel  
- ~1280 laptop (secondary panel collapses at `max-width: 1279px`)  
- ~768 tablet stack  
- ~390 phone stack  

---

## How to open locally

```bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
```

Then open:

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
