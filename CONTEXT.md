# AI Quant Research and Paper Trading Context

This context defines the project-specific language for the local AI quant research and paper-trading platform. It is a glossary, not an implementation plan.

## Language

**Persistent Paper Account**:
The single local paper account that aggregates manual paper activity and strategy-sleeve paper activity for combined review.
_Avoid_: Strategy account, separate paper account

**Manual Sleeve**:
The default ownership segment for user-directed paper cash and paper lots inside the persistent paper account.
_Avoid_: Unallocated bucket, default strategy

**Strategy Sleeve**:
A strategy-owned segment inside the persistent paper account with its own cash, lots, lifecycle, and performance attribution.
_Avoid_: Strategy account, rebalance account

**Sleeve Lot**:
A paper holding lot owned by exactly one manual or strategy sleeve; ordinary manual sells do not consume strategy-sleeve lots.
_Avoid_: Shared position, blended holding

**Lot Transfer**:
An explicit ownership change that moves an existing sleeve lot from one sleeve to another; it is outside Paper Strategy Sleeves MVP-1.
_Avoid_: Implicit adoption, inherited holding

**Allocated Sleeve Cash**:
Cash explicitly moved from the manual sleeve into a strategy sleeve; manual orders cannot spend it unless the user first transfers it back.
_Avoid_: Virtual principal, shared account cash

**Signal-Only Sleeve**:
A strategy sleeve that observes and records strategy signals without owning cash or changing paper-account holdings.
_Avoid_: Paper trading strategy, dormant allocation

**Paused Sleeve**:
A strategy sleeve whose execution is blocked while its strategy may still record observation signals.
_Avoid_: Stopped sleeve, archived strategy

**Manual Intervention**:
An explicit user action that changes a strategy sleeve's cash, lots, or lifecycle outside that sleeve's own strategy logic.
_Avoid_: Normal manual order, automatic rebalance

**Remediation Package**:
A bounded bundle of assessment-driven project improvement work with a defined scope, acceptance evidence, and stop condition.
_Avoid_: Phase, open-ended project optimization

**Remediation Goal**:
A long-running agent objective that advances one remediation package at a time and stops only when the package queue is complete or a user decision is required.
_Avoid_: Optimize everything, continuous cleanup

## Agent Workspace (v0.2)

**Plan-V6**:
The official Agent v0.2 slice for durable workspace snapshot/follow and full Web Chat UI on the AgentWorkspace adapter; its exit still keeps public chat write closed.
_Avoid_: V6 done, local mutation ON as V6 complete

**Local Dark Enablement**:
Single-user opening of real Hermes dispatch, supervised worker path, and local mutation/composer flags under the trading kill switch; it is not Plan-V6 acceptance and not public cutover.
_Avoid_: memory-V6 as plan exit, public composer open

**Thin Browser Write Rail**:
The minimum browser path that obtains an owner gate, ensures a managed session, and submits a turn through the composite turn submit entry, then reconciles via action receipt and snapshot.
_Avoid_: Composer draft unlock, gateway status poll, preventDefault-only submit, full Plan-V6 UI, public put-then-act

**L2a-Send**:
The single construction package that delivers the thin browser write rail through M1 (accepted command + snapshot reconcile, store may be faked in tests) and M2 (real HQA Intent Payload Store put/get and worker prompt resolve under local dark). **M1+M2 ACCEPT@2026-07-22** (live assistant `L2a-pong`).
_Avoid_: Plan-V6 complete, FE-only submit, calling M1 “delivered to Hermes”

**L2b-Observe**:
Command-aware workspace snapshot/follow plus post-deliver assistant preview via the existing Hermes messages BFF bound by `hermes_session_id`. M1 = lifecycle objects/poll; M2 = latest assistant text in Composer status. **M1+M2 ACCEPT@2026-07-22**. No SSE; follow carries no message bodies.
_Avoid_: Plan-V6 transcript UI done, assistant bodies in follow ledger, public cutover

**L3a-Transcript**:
Workbench Conversation panel above Today when local chat is open; binds usable Hermes API `hermes_session_id` on deliver (and snapshot bootstrap with only-if-empty), then loads full user/assistant bubbles via same-origin messages BFF. **M1 ACCEPT@2026-07-22** (live `L3a-pong` + FE marker). No SSE; not Task drawer/approval/a11y.
_Avoid_: Plan-V6 complete, SSE done, public cutover, registry `web_`/`wm_` as messages id

**L3b-Transcript-Polish**:
FE polish on the L3a canvas only: keep-last-ready no-flicker refresh, soft stick-to-bottom when near bottom, optimistic user bubble on submit accept, `aria-live` on canvas, copyable session chip, sessions detail reuses shared `TranscriptCanvas`. **M1 ACCEPT@2026-07-22**. Still no SSE / public write.
_Avoid_: Plan-V6 complete, SSE done, inventing assistant text, binding on accept instead of deliver

**L4a-Task-Drawer (Command Activity)**:
Read-only workbench **Activity** panel from workspace `commands[]` (conversation_turn lifecycle). Task/Attempt authority rows still empty tuples — M1 does **not** invent HQA Task UI. Collapsible; markers `data-hermes-command-activity` + `data-hermes-task-drawer=l4a-m1`. Mounted in `HermesLocalChatBoundary` when chat open. **≠** `/hermes/tasks` artifacts page. **M1 ACCEPT@2026-07-22**. As of L4b, Activity consumes the shared follow spine (no private 8s snapshot loop). No mutation / approvals / public write.
_Avoid_: filled Task/Attempt authority, stop/gate actions, conflating with research Tasks page, public write

**L4b-SSE-Follow**:
Shared durable workspace follow spine for command lifecycle only. BFF `GET …/follow/stream` SSE over the same follow projector (`ready`/`command`/`cursor`/`resync`/`heartbeat`/`reconnect`/`error`); FE `createWorkspaceFollowSpine` prefers EventSource, falls back to GET follow poll after soft SSE failures, bootstrap + periodic snapshot reconcile, resync → snapshot + restart. `WorkspaceFollowProvider` mounts under chat boundary (`data-hermes-workspace-follow=l4b-m1`); Activity + delivered-bind/bump consume one spine. **No assistant bodies** on follow/SSE. Test knobs: `max_ticks` / `poll_seconds` query. **M1 ACCEPT@2026-07-22**. As of L5a, Composer also waits on this spine (no private follow poll).
_Avoid_: assistant token stream, message bodies in follow, inventing Task authority, public write, dual private poll loops

**L5a-Hermes-Approval-Observe**:
Honest empty Hermes **command-approval** observe slot + Composer dual-poll hygiene. Originally emitted `approvals=[]` with observe-only panel (`data-hermes-approval-observe=l5a-m1`). FE spine carries `approvals`; Composer waits on spine. As of **V7a**, health is `command_approval="ready"` when the hermetic authority is mounted (empty list still honest); decide controls are a separate term. **M1 ACCEPT@2026-07-22**.
_Avoid_: inventing approval rows, Gate mutation, conflating with candidate approvals page, assistant bodies on follow, public write

**L5b-Authority-Projection**:
Honest empty **Task / Attempt / Run / result-ref** slots on snapshot + shared spine, plus `authority_health.task|attempt|run|result="unavailable"`. FE spine carries `tasks/attempts/runs/results` + `authorityHealth`. Read-only `WorkbenchAuthorityProjectionPanel` (`data-hermes-authority-observe=l5b-m1`). Ordinary `conversation_turn` never invents Attempt. **≠** `/hermes/tasks`. **No stop/gate/mutation**. **M1 ACCEPT@2026-07-22**.
_Avoid_: inventing HQA Task/Attempt from commands, stop writes as Task authority, stuffing Domain Gates into Task/Attempt rows, research Task creation UI, public write

**L5c-Workbench-A11y**:
FE-only workbench shell a11y contracts. Marker `data-hermes-workbench-a11y=l5c-m1`; `data-hermes-workbench-main` region landmark (not nested main; root layout owns document main); responsive content pad (p-3/sm:p-4/lg:p-6); shared `COLLAPSE_TOGGLE_CLASS` (44px + focus-visible) + `LONG_ID_CLASS`/`displayId` on Activity/Approvals/Authority + transcript session chip; Composer focus-visible + aria-busy/invalid; breakpoints 1440/1280/768/390; globals keep reduced-motion + focus ring. **No mutation routes**. **M1 ACCEPT@2026-07-22**.
_Avoid_: inventing Task/Attempt, assistant bodies on follow, public write, selling visual e2e as full screen-reader certification

**V7a-Hermes-Approval-Decide**:
Exact single-use Hermes **command-approval** decision: `allow_once` | `deny` only. CAS binds `approval_ref` + `run_ref` + `command_digest` + `expected_status=pending` + `expected_expires_at`. Platform hermetic `CommandApprovalAuthority` + typed `hermes.command_approval.decide` on `POST …/act` (owner cookie + CSRF); mutation OFF → unavailable; fail-closed on stale/expired/wrong digest/run/replay; same `client_action_id`+digest is idempotent. Snapshot projects pending rows and `authority_health.command_approval="ready"` (empty still honest). FE panel marker `data-hermes-approval-decide=v7a-m1` shows controls only when `mutation_enabled` and CAS-complete pending. **No always-allow**. **≠** Gate 1/2/3, **≠** `/hermes/approvals` candidate page, **≠** live Hermes durable projector (later). **M1 ACCEPT@2026-07-22**.
_Avoid_: always-allow, Gate mutation, inventing challenges, stop/token stream, public write

**V7b-Hermes-Approval-Release**:
Post-CAS hermetic **release/signal** for decided command approvals. Platform `FakeHermesApprovalReleaseAdapter` mirrors HQA `respond_approval` without `import hqa`: choice map `allow_once→once` / `deny→deny`; first commit emits `approval.responded` + `approval.release_committed` + `approval.signalled`; exact same choice+digest is idempotent replay (no double signal); stale/expired/mismatch fail closed without consuming. Saga calls release after authority CAS; release failure → receipt `reconciling` and **does not** resurrect pending. `project_pending_challenge` dual-seeds authority + release port for hermetic/local-dark tests. **No** always-allow, Gate, stop, live HTTP Hermes, or public write. **M1 ACCEPT@2026-07-22**.
_Avoid_: always-allow, rolling back CAS on release fail, inventing live projector, public write

**V7c-Hermes-Stop**:
Hermetic Run-scoped **stop intent** with plan §5.5 layered receipt. Platform typed `run.stop.request` (`RequestStop`: required `run_ref`; optional `task_ref`/`attempt_ref`/`platform_job_ref`) + `FakeHermesRunStopAdapter` mirrors HQA `stop` without `import hqa`: terminal-honest already_terminal (no coerce→stopped); first stop emits `run.cancelled` then status stopped; exact client_action_id+digest is idempotent; `partial_stop` → receipt `reconciling` then replay heals. Receipt carries `stop_layers` (`hermes_run` / `hqa_attempt` / `platform_job` / `overall`); overall `stopped` only when every artifact-producing target is known terminal — unknown Attempt keeps overall `reconciling` even if the run is confirmed. **No** Task invention, Gate, live HTTP, FE stop control, or public write. **M1 ACCEPT@2026-07-22**.
_Avoid_: inventing Task stopped from run alone, coerce succeeded→stopped, public write, live HTTP stop


**V7d-Durable-Approval-Projector**:
Hermetic projector of real Hermes command-approval challenges (pending + recent decided facts) into durable workspace `snapshot`/`follow`/`authority_health` from V7a/V7b authorities. `list_observed` + `EventPage.approvals` on L4b spine/SSE (`event: approvals`); empty remains honest; no Gate; no always-allow; no dual private FE poll; no Task/Attempt invention; no live HTTP product path. **M1 ACCEPT@2026-07-22**.

**V7e-Gate-Surfaces**:
Hermetic Domain Gate 1/2/3 **observe + typed act** surfaces on the shared spine, fully separate from Hermes command-approval. Snapshot/follow carry `gates[]` + `authority_health.gate_1|gate_2|gate_3`; SSE emits fingerprint-gated `event: gates` (never stuffs into `event: approvals`). Typed acts via `/act`: `gate1.formula_source.confirm` (task_ref + reviewed_source_sha256 + nonempty human note), `gate2.candidate.review` (candidate + digest + pending + note, no-refetch), `gate3.promotion_review.prepare` (prepare-only; note stamps `human_git_commit_required`; web never Git-commits). FE `WorkbenchGateSurfacesPanel` markers `data-hermes-gate-*=v7e-m1`; Gate1/2 Confirm disabled until note typed; post-CAS ledger conflict still returns accepted. Mutation OFF fail-closed. Empty honest. Hermetic stand-in ≠ live HQA/domain final authority; no `promotion_id` yet (V7g). **No** always-allow, public write, dual private poll, Task invention, `import hqa`, live Hermes HTTP. **M1 ACCEPT@2026-07-23**.
_Avoid_: stuffing gates into approvals, Gate-as-command-approval, silent default notes, web Git commit, public write, claiming production Gate authority

**V7f-Typed-Results**:
Hermetic typed result surface on the shared spine. `results[]` promoted from L5b bare id strings to typed public objects; `authority_health.result=ready` when projector mounted (empty list still honest); SSE fingerprint-gated `event: results` (never stuffs into gates/approvals). sample/real fail-closed (only exact `real` is REAL); Mapping `read_status` fail-closed (invalid/missing → unavailable, never invent available). Vertical A options fields (ticker/expiry/strike/bid/ask/delta/iv/apr) + filters/exclusions/limitations/provider_evidence/freshness. Exact Task/Attempt/Run/artifact/command links only when known — never invent Task rows. FE `WorkbenchTypedResultsPanel` markers `data-hermes-typed-results-*=v7f-m1`; Authority panel stays ids-only via `resultIdsFromProjection`. Separate from page-level HermesResultsCatalog (`/hermes/results`). Hermetic ≠ live Futu. **No** public write, catalog-on-spine, live provider quotes, Task invention, `import hqa`. **M1 ACCEPT@2026-07-23**.
_Avoid_: wiring HermesResultsCatalog onto spine as V7f substitute, fail-open REAL badge, inventing read_status=available, stuffing results into gates/approvals, live Futu, public write, Task invention

**V7g-A-M1 hermetic Vertical A binding**:
Hermetic options research vertical bind on the shared spine. Typed act `vertical.options_a.bind` / `BindOptionsVerticalA` → durable receipt with `task_id`/`attempt_id`/`run_id`/`result_id`/`terminal_status` → in-process Task/Attempt/Run authority + V7f typed `options_vertical_a` result (always `sample_or_real=sample`, limitations include `not_live_futu_quote`/`not_tradeable`/`zero_orders`). Terminal honesty: `completed` when fixture `provider_evidence` present; `completed_degraded` when intentionally omitted. Snapshot projects real task/attempt/run **ids** + linked typed result; `authority_health.task|attempt|run=ready` (empty still honest). Idempotent on `client_action_id`+digest; digest mismatch → conflict. Mutation OFF fail-closed. **Not** `StartResearch` (still dark). **Not** Gate. **Not** live Futu / orders / public write. FE: Authority panel shows ids when present; Typed results panel shows V7f shape; `bindOptionsVerticalA` client helper. **M1 ACCEPT@2026-07-23**.
_Avoid_: unlocking StartResearch as substitute, inventing Task from conversation.turn, claiming REAL live quote, live Futu in M1, public write, always-allow, catalog-on-spine, `import hqa`

**Observe Spine**:
Durable workspace cursor plus snapshot and follow that project sessions, commands, tasks, attempts, runs, results, approvals, gates, and authority health without inventing missing facts. L2b-M1 covers commands lifecycle; L4a-M1 surfaces those commands in UI; L4b-M1 is the shared SSE/poll transport; L5a-M1 adds empty-honest approvals + Composer on spine; L5b-M1 carries Task/Attempt/Run slots on spine (empty honest; V7g mounts health ready); L5c-M1 hardens shell a11y around that spine; V7a/V7b may project and release real pending command-approval challenges from the hermetic authority (empty remains honest); V7c may attach layered stop receipts on act (does not invent Task/Attempt from stop alone); V7d projects pending+decided approvals on spine; V7e projects Domain gates on a separate namespace; V7f projects typed results on a separate namespace (`results[]` objects + `event:results`); V7g-A-M1 hermetic vertical bind fills Task/Attempt/Run ids + linked typed options result (`completed|completed_degraded`).
_Avoid_: empty follow poll, commands-only Activity sold as complete Task/Attempt observe spine, private dual poll after L4b/L5a, stuffing gates/results into approvals, catalog-on-spine

**Action Receipt**:
The durable acknowledgment of one user action, carrying status, digests, recovery guidance, and optional command or session identities.
_Avoid_: chat message, run result, toast-only success

**Payload Binding**:
The exact pair of store-issued payload digest and matching payload ref on a turn action; the digest is the content address of the HQA intent envelope, not a bare hash of textarea bytes.
_Avoid_: raw textarea as the action, prompt stored in the command row, frontend sha256(text) as the ledger key

**Composite Turn Submit**:
One browser write to the platform BFF that, server-side only, puts the intent payload into the HQA Intent Payload Store and then records conversation.turn on the command ledger.
_Avoid_: public put-then-act as the product API, prompt on POST /act, browser-coordinated dual calls

**Intent Payload Store**:
The HQA owner-only content-addressed encrypted store that is the sole authority for chat and research input bodies and their digests.
_Avoid_: platform Postgres prompt column, second blob table, fixed-input as the normal path

**Owner Gate**:
The single-machine browser write latch (signed owner cookie plus CSRF) that proves loopback UI mutations are same-site and owner-bound; it is not a multi-user accounts product.
_Avoid_: login, user module, signup, account switcher

**Public Chat Write Ready**:
The release gate that allows non-dark browser chat mutation only after adversarial acceptance and explicit owner authorization.
_Avoid_: local chat_write_ready, QS_LOCAL_MUTATION flags, draft UI flag

**Local Chat Write Ready**:
The single-user readiness surface that may be true under local mutation and composer flags while public chat write remains closed.
_Avoid_: public cutover, Plan-V6 or V8 completion

**Dark Identity Profile**:
The shared BFF/worker constant map that turns platform workspace/session/owner fields into Intent Payload Store scope (`owner-local-root`, `workspace:ws-local-main`, `session:…`) plus the fixed chat `provider_policy` and its store-canonical digest; create session and composite put must use the same digest.
_Avoid_: FE-supplied store owner/policy, UUID-as-owner_id, bare workspace id without `workspace:` prefix

**Intent Payload CLI Port**:
The platform subprocess boundary to HQA (`put` and `bind_resolve` over stdin/stdout JSON) so the BFF can store intents and the worker can bind a `command:<id>` consumer and resolve plaintext without importing `hqa` or placing secrets on argv.
_Avoid_: platform `import hqa`, public resolve CLI, tempfile prompt paths, fixed-input as the chat resolve path
