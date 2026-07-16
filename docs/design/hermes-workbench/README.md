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
| F2 production shell | **code-delivered 2026-07-14** | Read-only Hermes shell, Today hierarchy, Tasks/Approvals/Results and reversible root→Hermes cutover. Chat/execution/approval mutation/unifiedResults/legacyRedirects remain hard-off; Tasks/Results distinguish unavailable/degraded/corrupt from a genuine empty feed. |
| F2.1 official session read | **code-delivered 2026-07-15** | `sessionRead=true`: platform GET-only BFF reads official Hermes API Server persisted sessions and exposes list/detail views. Browser never receives the Hermes key. `approvalMutations=false`; composer remains disabled. |
| F2.2 / D-31 3E-A Unified Results | **delivered + live accepted 2026-07-15** | Read-only catalog/detail over platform runs, experiments, candidates, HQA artifacts and exact run links. Preview is visible; `unifiedResultsCutoverAccepted=false`, exact Hermes Run links may legitimately be empty, and no write capability is implied. |
| D-31 3C.1 backend foundation | **code accepted; live 006 pending** | HQA Task/Attempt/payload authority, exact workflow binding/inventory and reverse audit passed code/isolated-PostgreSQL acceptance. Migration 006 is not live applied; browser POST, worker claim and Hermes/provider mutation remain off. |
| D-31 3F Agent Studio gate | **mechanism delivered, default-off** | Page-scoped, reversible redirect exists behind `QS_HERMES_AGENT_STUDIO_REDIRECT_ENABLED=true`; default remains the read-only legacy page. Audit parity and user cutover approval are still missing. |

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
- hard-off at delivery: `chat` / `execution` / `unifiedResults` / `legacyRedirects` are literal `false` (env=true ineffective)
- capability notice at delivery: static `blocked_in_this_slice`; the later F2.1 increment adds a read-only gateway status route without enabling chat
- old four research pages retained pending later parity; no mutation path under Hermes F2 surfaces
- Tasks/Results never translate an unavailable, degraded, corrupt, or API-error artifact feed into a healthy empty state; they expose the source reason and reserve empty copy for a verified empty feed

### F2.1 official Hermes session read (2026-07-15)

- status: `code-delivered` (persisted-session observation only)
- feature contract: `sessionRead=true`; `chat=false`, `execution=false`,
  `approvalMutations=false`, `unifiedResults=false`, `legacyRedirects=false`
- platform BFF: `GET /api/hermes/gateway`, `GET /api/hermes/sessions`,
  `GET /api/hermes/sessions/{session_id}` and
  `GET /api/hermes/sessions/{session_id}/messages`
- production views: `/hermes/sessions` list + `/hermes/sessions/{session_id}` detail;
  composer remains disabled on the transcript view
- upstream: official Hermes API Server on explicit HTTP loopback (default
  `127.0.0.1:8642`); the older TUI gateway contract drifted and is no longer the
  platform's primary connection
- credential boundary: full-authority Hermes Bearer key is read server-side from
  an owner-only regular file and never serialized into frontend props/responses
- data/quota boundary: health, capabilities and persisted-session GETs submit no
  prompt, call no provider and consume no Hermes provider quota; no PostgreSQL
  migration was added and sessions are not copied into the platform database
- deployment boundary: loopback is a network boundary, not OS-user authentication;
  the unauthenticated local platform must itself bind `127.0.0.1`/`::1`
- operations and threat model: [`../../guides/hermes-sessions.md`](../../guides/hermes-sessions.md)

### D-31 Wave 3 current state (2026-07-16)

- migration 005 delivers schema metadata plus durable commands, events, outbox and
  exact run links; live PostgreSQL readiness validates the complete schema signature
- the ledger implements tested claim/lease/heartbeat primitives; the runnable
  connector-worker currently implements only deterministic wake/scan and expired-lease
  reconciliation. It does not claim queued commands, has no dispatch/provider/SSE adapter,
  and performs zero Hermes mutations
- 3C.1 has code-accepted HQA Task/Attempt/immutable-payload authority plus platform exact
  workflow binding/inventory and reverse audit; migration 006 is not live applied, so no
  browser or worker runtime consumes this foundation
- 3E-A exposes `/hermes/results` plus bounded dynamic detail routes; malformed,
  missing, corrupt, degraded and unknown-total sources stay explicit
- the read-only preview is visible while `unifiedResultsCutoverAccepted=false`
- Agent Studio has a page-scoped default-off redirect mechanism; the other legacy
  pages remain intact and no retirement is authorized

The approved write-side design is not “enable the composer against `/v1/runs`”.
The durable ledger and reconcile-only worker base now exist, but chat remains blocked
until authenticated mutation BFF/CSRF/retention/live-applied workflow-binding readiness
plus upstream idempotency,
request recovery, event replay, provider lock/evidence, approval exact binding and
stop reconciliation are independently proven. `LISTEN/NOTIFY` is only a wakeup;
periodic scan recovers missed notifications, and neither path invokes an LLM when no
queued command exists.

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

## F1 full-state prototype (approved reference)

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

### F1 review (implementer self-check; independent review recorded below)

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

**Historical pre-selection outcome:** **Ready for user selection** — A Pass · B
Pass with mobile S5 caveat · C Pass. The later written decision selected
direction A and approved F1 after the platform-token rebind; see the Status,
F0 decision, and F1 decision sections above. This table remains the independent
review evidence, not the current approval state.

---

## Constraints carried into design

- Only the global SafetyStrip shows paper / live / kill / API.  
- Normal automation is one row; technical cron/run/path details are collapsed.  
- Platform candidate label: 研究审批项 / Research approval item.  
- Composer is non-submitting; no Hermes / tasks / provider / live calls.  
- No fake “approved” gate before written user selection.
