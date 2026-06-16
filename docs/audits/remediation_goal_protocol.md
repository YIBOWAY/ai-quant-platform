# Remediation Goal Protocol

This protocol defines how long-running Codex `/goal` work should execute the
2026-06-11 project assessment remediation without becoming open-ended project
cleanup. It is an agent execution protocol, not a product feature spec.

## Why The Previous Goal Failed

The previous goal asked the agent to optimize and iterate the whole project,
including frontend and backend work, using the assessment report as guidance.
That was directionally useful but operationally weak:

- It had no bounded completion definition.
- It did not define which assessment findings should be handled first.
- It did not pair scope boundaries with verification evidence.
- It allowed unrelated improvement work to look aligned.
- It did not define when the agent should continue, stop, or downgrade.

For `/goal`, the total direction may be broad, but execution must happen through
bounded remediation packages.

## Language

- **Remediation Goal**: a long-running agent objective that advances one
  remediation package at a time and stops only when the package queue is
  complete or a user decision is required.
- **Remediation Package**: a bounded bundle of assessment-driven work with a
  defined scope, acceptance evidence, and stop condition.

Do not call these packages "Phase 1", "Phase 2", etc. The project already has
historical phases, so remediation work uses package names such as
`Remediation Package A` or Chinese names such as `整改包 A`.

## Goal Layers

### L0: Total Goal

Advance the assessment-driven remediation route for the current project. The
agent may continue automatically, but only by activating one remediation package
at a time.

### L1: Package Queue

Select the next package by this priority order:

1. Result credibility.
2. Safety boundaries.
3. Contract drift.
4. High-frequency workflows.
5. Low-frequency refactors and visual polish.

The agent must not simply follow the report order or choose whatever is easiest.

### L2: Active Remediation Package

Before implementation, each package must define:

- In-scope items.
- Out-of-scope items.
- Machine-verifiable acceptance standards.
- Boundary conditions paired with those standards.
- Failure downgrade rules.
- Commit frequency.
- Documentation sync requirements.

### L3: Task Slices

Each task slice must be small enough to verify independently. A slice may be
committed on its own only when it is a coherent theme; otherwise it should be
batched into the package commit.

## Package Size

A remediation package should have:

- One primary problem domain.
- One to three closely related deliverables, usually code, tests, and docs.
- A local verification gate that is usually practical to run within 10 to 20
  minutes.

Do not size packages by hours worked or by desired commit count. Size them by a
verifiable problem domain.

## Initial Package Queue

The first active package is:

### Remediation Package A: Result Credibility Baseline

Purpose: turn the assessment report's highest-priority result-credibility
concerns into machine-verifiable evidence and regression guards.

Initial scope:

- Re-check the Tiingo adjusted-price path.
- Add or confirm tests proving Tiingo daily data prefers adjusted OHLCV and
  volume when available, with raw fallback only when adjusted fields are absent.
- Confirm key research paths do not silently treat raw data as adjusted data.
- Update audit documentation so the Tiingo adjusted-price concern no longer
  remains an unresolved critical candidate if the evidence proves it is guarded.

Out of scope:

- ArtifactStore unification.
- Job runner, cancellation, progress, or recovery.
- Broad frontend redesign.
- Futu market-data path changes.
- Full API contract convergence.
- Historical raw-cache migration, unless it blocks the package acceptance gate.

Machine-verifiable acceptance:

- A Tiingo fixture with both raw and adjusted fields proves output OHLCV and
  volume prefer adjusted fields and marks `price_adjustment` as `adjusted`.
- A Tiingo fixture without adjusted fields proves output falls back to raw fields
  and marks `price_adjustment` as `raw`.
- A Tiingo fixture with partial adjusted fields proves `price_adjustment` is
  `mixed`; mixed data may exist, but it must be visible and must not be presented
  as fully adjusted.
- At least one provider/schema/storage-path test proves `price_adjustment` is
  not dropped by normalization or local cache persistence.
- Audit docs state the current status of the Tiingo adjusted-price concern as
  guarded, partially guarded, or still open with exact missing evidence.
- Relevant pytest, ruff, and `git diff --check` gates pass.

Boundaries:

- Do not require a real Tiingo token; use mocks or fixtures.
- Do not migrate historical cache data in this package.
- Do not change return calculation logic unless a test proves raw/adjusted
  confusion still affects current result calculation.
- Do not expand into Futu, options pricing, ArtifactStore, or job-runner work.

Historical-cache downgrade:

- If historical Tiingo cache data may contain raw prices, this package records
  the risk and proposes a follow-up cache credibility package.
- If current cache reads would treat legacy raw cache as adjusted, this package
  may add the smallest guard or failing evidence needed to make that risk
  visible, but it must not perform a broad data migration.
- If the fix requires storage redesign, stop expansion and move it into a
  separate package.

Continue gate for Package A:

- Continue automatically only if all Package A verification, documentation, and
  commit gates pass, the worktree has no Package A leftovers, and the next
  package can be selected without a product or safety decision.
- Stop and report if historical cache credibility affects current research
  conclusions, return calculation still mixes raw and adjusted assumptions, or
  the next highest-priority package requires user judgment.

## Machine-Verifiable Completion

Every package must define evidence that can be checked by tools, such as:

- Unit or integration tests.
- Frontend type-check and lint.
- Backend lint.
- OpenAPI schema checks.
- Browser or Playwright checks for UI work.
- Command output from local services.
- Git status and commit evidence.
- Documentation links or index checks.

If a claim cannot be machine-verified, it must be labelled as an artificial or
manual review item. It cannot be used as the only completion gate.

## Boundary Conditions

The package definition must say what is not allowed. Typical boundaries:

- Do not touch live trading, broker order placement, account unlocking, signing,
  wallets, or Futu trade contexts.
- Do not broaden a package into another problem domain just because adjacent
  code is visible.
- Do not perform large frontend redesigns without first using the relevant
  frontend web skills and defining browser verification.
- Do not include unrelated dirty files in commits.
- Do not push to GitHub unless the user explicitly asks for it.

## Failure Downgrade Rules

### Test Failure

Find the smallest failing scope. If the fix belongs to the active package, fix
it and rerun the gate. If it exposes another problem domain, stop expansion and
record it as a future package candidate.

### External Dependency Unavailable

When Futu OpenD, Docker PostgreSQL, GitHub, network access, or another external
dependency is unavailable, prefer mocks, fixtures, local real caches, or gates
that do not depend on that service. Report exactly which verification was
skipped and what user action would unblock it.

### Scope Expansion

If a fix pulls in a second primary problem domain, handle only the minimum needed
to satisfy the active package. Move the rest into the package queue.

### Frontend Redesign Risk

If UI or interaction design changes are broad, use the relevant frontend web
skills first and define screenshot/browser checks before implementation. Without
that, only small state, copy, data-flow, or type fixes are allowed.

### Safety Uncertainty

Any work that may affect live trading, real broker orders, Futu trade contexts,
account unlock, signing, wallets, or safety switches must stop for user
decision or be redesigned as paper-only/read-only work.

### No Machine Verification

Do not claim completion. Add a verifier, downgrade to a manual review item, or
stop at the continue gate.

## Continue Gate

The agent may automatically enter the next remediation package only when all of
these are true:

1. The active package's machine verification passed.
2. Documentation sync is complete.
3. The package has been committed by coherent theme.
4. The worktree has no active-package leftovers.
5. The next package can be chosen by the priority rule.
6. The next package does not require a new product or safety decision.
7. The next package will not trigger broad UI redesign without a frontend skill
   plan and browser verification.

If any condition fails, the agent must stop and report status.

## Commit Frequency

- Default to one commit per remediation package.
- Large packages may use at most two to three coherent theme commits.
- Do not commit half-finished work.
- Do not push unless explicitly requested.
- Do not include unrelated dirty files.

## Documentation Sync

After each major package, run a scoped documentation sync:

- Update docs that describe changed public routes, commands, settings, safety
  boundaries, or workflows.
- Keep `CONTEXT.md` as glossary only.
- Update index or audit documents when a new remediation protocol or status
  record is added.
- Do not add implementation plans to `CONTEXT.md`.

## Copyable `/goal` Template

```text
Use docs/audits/remediation_goal_protocol.md as the execution protocol.

Advance the 2026-06-11 assessment remediation route for this local AI quant
research and paper-trading platform. Activate one remediation package at a time,
choosing the next package by: result credibility, safety boundaries, contract
drift, high-frequency workflows, then low-frequency refactors or visual polish.

For each remediation package, first define its L2 contract: in-scope items,
out-of-scope items, machine-verifiable completion standards, boundary
conditions, downgrade rules, commit frequency, and documentation sync. Then
execute small L3 task slices. Use codegraph before code reads or edits. Use
frontend web skills for broad frontend UI or interaction redesign. Preserve the
paper-only, no-live-trading safety model.

After each package, run the relevant verification gates, sync docs, commit by
coherent theme without pushing, and pass the continue gate before selecting the
next package. Stop and report when the continue gate fails, a user/product/safety
decision is required, or all eligible packages are complete.
```
