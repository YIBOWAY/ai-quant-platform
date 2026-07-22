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

**Observe Spine**:
Durable workspace cursor plus snapshot and follow that project sessions, commands, tasks, attempts, runs, results, approvals, and authority health without inventing missing facts. L2b-M1 covers commands lifecycle; richer Task/Attempt/Run projections remain Plan-V6 remainder.
_Avoid_: empty follow poll, sessions-and-commands-only snapshot sold as complete observe UI

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
