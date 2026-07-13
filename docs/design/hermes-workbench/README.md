# Hermes Workbench — Design Artifacts

Professional frontend design records for the Hermes unified research workbench
(F0 high-fidelity directions → F1 clickable state prototype → F2 production shell).

These files live under `docs/design/hermes-workbench/` only. They are **not**
imported from `app/`, `components/`, `lib/`, or `public/`.

---

## Status

| Gate | Status | Notes |
| --- | --- | --- |
| F0 visual directions | **draft — awaiting user selection** | Three full-size directions A/B/C delivered. **Not approved.** |
| F0 independent review | **placeholder — not completed** | Review table below is empty pending independent frontend/UX reviewer. |
| F1 clickable prototype | not started | Blocked on written F0 approval. |
| F2 production shell | not started | Blocked on F1 approval + candidate-integrity Task 5 types. |

### F0 decision

**No F0 decision has been recorded.**

Do not treat any direction as selected until this section contains all of:

- status: `approved`
- exact selected filename stem under `f0/` (e.g. `direction-a`)
- approver: `user`
- date from `date +%F`
- only adjustments explicitly requested by the user

Until then, F1 must not start from a presumed winner.

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

## Independent review (placeholder)

Reviewer: _TBD_  
Date: _TBD_  
Method: full-size browser at four viewports + state toggles; checklist reference may include HQA `.superpowers/sdd/frontend-task-1-ux-checklist.md` if present.

| Criterion | A | B | C | Notes |
| --- | --- | --- | --- | --- |
| Hierarchy (action / exception / work / result) | | | | |
| Five-second scan (idle Today) | | | | |
| Safety uniqueness (strip only) | | | | |
| Long Chinese + long IDs | | | | |
| Reduced motion | | | | |
| Contrast | | | | |
| Viewport 1440 | | | | |
| Viewport 1280 | | | | |
| Viewport 768 | | | | |
| Viewport 390 | | | | |
| 44px targets + focus order | | | | |
| Automation compression | | | | |
| Direction identity (A/B/C distinct) | | | | |

**Outcome:** _pending_ — pass/fail per direction not yet recorded.

---

## Constraints carried into design

- Only the global SafetyStrip shows paper / live / kill / API.  
- Normal automation is one row; technical cron/run/path details are collapsed.  
- Platform candidate label: 研究审批项 / Research approval item.  
- Composer is non-submitting; no Hermes / tasks / provider / live calls.  
- No fake “approved” gate before written user selection.
