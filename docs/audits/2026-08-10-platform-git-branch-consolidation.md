# Platform Git branch consolidation — 2026-08-10

Status: **COMPLETE** for D-33 Slice 1. This record is about repository topology and the installed local runtime. It does not authorize live trading, candidate promotion, or migration 029.

## Approved source

- HQA plan: `docs/plans/2026-08-10-full-automation-paper-path.md`
- HQA plan commit: `db926e3097a0198120e48057f599403359f6d949`
- Strategy: release wins shared Hermes infrastructure; preserve only genuinely new behavior; publish Platform by fast-forward; archive before deletion.

## Frozen starting point

| Surface | Frozen identity |
|---|---|
| Platform normal checkout | `codex/agent-v0-2-platform-v1@854a65fb9e291d1ee72d6bf5666fb70ff916ff81` |
| Platform runtime checkout | `codex/agent-v0-2-release@f3b346babddd0956f3c4a8dbdb6b2a56b26791d0` plus a 52-entry dirty tree |
| GitHub `main` | `197bc173a93bca1b922e05d4549cba64e1d2c27d` |

Recovery material is owner-only at `/Users/sunyibo/programs/.git-backups/ai-quant-platform-pre-consolidation-20260810`. It contains two all-ref bundles, two dirty tracked bundles, binary patches, untracked archives, an exact 52-entry porcelain manifest, and `SHA256SUMS`. The final dirty state was reconstructed independently from bundle + patch + archive; its manifest SHA-256 is `b54298fcc2ce566eb13ca31ad4af86dd436eba15b0d15cde5513ce71cf5dbd2b`.

Twenty-one annotated `archive/pre-consolidation-20260810/*` tags were pushed before any branch deletion. Annotated tags produce 42 `ls-remote` rows because both tag objects and peeled commits are advertised.

## Reconciliation decisions

| v1-only commit | Decision |
|---|---|
| `174287a` | Ported as `68cbf83`; Horizon corrupt-run isolation and CLI failure behavior were genuinely absent. |
| `e400553` | Not replayed wholesale. A trial three-way apply produced 20 conflicts in later release infrastructure. Its durable lifecycle/retry/idempotency behavior is already represented by release adaptation `28ce796` and subsequent hardening; the expanded recovery matrix below is the acceptance anchor. |
| `4d3fd59` | Not replayed. Its test stub targets an older session contract; the release fixture additionally enforces canonical session admission. |
| `21568cf` | Not replayed. Brief performance behavior is present through release `d018765` and later fixes, including the consolidated live-runtime reliability changes. |
| `d64bd8e` | Not replayed. Position Map modularization is present through release `d018765` and later evolution. |
| `0081248` | Preserved as `2c6503b`; the missing design records were additive. |
| `854a65f` | Ported as `9ddefa6`; release won the conflict for the newer earnings calendar, while refresh hardening and tests were retained. |

The frozen live worktree was preserved in `44f2065`; a concurrent Asia Radar heading-contrast follow-up was separately verified and preserved in `43ac66d`.

## Automated acceptance

- Platform full suite: `3052 tests collected`, exit 0.
- Expanded `e400553` recovery gate: run lifecycle, connector dispatch/HTTP/CLI/daemon, composite submit, command ledger, release runtime, PostgreSQL recovery seams, Horizon, and options refresh; exit 0. Environment-dependent PostgreSQL cases remained explicit skips.
- Frontend recovery slice: 5 files / 118 tests, all passed.
- Frontend full suite: 77 files / 464 tests, all passed.
- Frontend `type-check`, ESLint, and Next 15.5.15 production build: passed; 27 static pages generated.

## Published topology and runtime

- GitHub `main`: `9ddefa685ad1ccdb80bd504fc3ff16a294c40133`, published by fast-forward from `197bc17`.
- GitHub default branch: `main`.
- GitHub branch protection matches HQA: required linear history; force-push disabled; branch deletion disabled.
- All thirteen non-main remote branches were deleted only after their exact tips matched archive tags.
- Both local Platform checkouts now contain only `main` and point to `9ddefa6`.
- HQA installed wrappers/skill and Platform backend/frontend/connector LaunchAgents all bind `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform`.
- Persistent stack startup completed through `scripts/local_mac_stack.sh start`; Docker/PostgreSQL and all four LaunchAgents were running afterward.
- Runtime safety remained `dry_run=true`, `paper_trading=true`, `live_trading_enabled=false`, `kill_switch=true`; `release_authorized=false`.
- Post-restart `/zh/brief` warm verification returned six consecutive HTTP 200 responses in 0.049–0.143 seconds. One immediate 5-second probe during startup timed out before the successful warm series; no corresponding frontend 500 or `ECONNRESET` was logged.

## Recovery boundary

The archive tags and bundles are recovery evidence, not active branches. Restoring one must be a deliberate operator action into a new branch; do not move `main` backward or force-push it.
