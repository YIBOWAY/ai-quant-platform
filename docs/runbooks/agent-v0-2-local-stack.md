# Agent v0.2 Local Stack Operations

This is the sole Platform operations authority for Agent v0.2 database
migration, readiness, service restart, candidate E2E, and database restore.
The connector runbook covers connector mechanics only and must not duplicate
this sequence.

The long-running local stack has six independently managed LaunchAgents:

- `ai.hermes.gateway` — official Hermes API on `127.0.0.1:8642`;
- `com.aiquant.backend` — Platform API on `127.0.0.1:8765`;
- `com.aiquant.frontend` — built Web frontend on `127.0.0.1:3001`;
- `com.aiquant.agent-v02-connector` — installed separately and kept in
  explicit `reconcile_only` unless a bounded candidate/release window is ready;
- `com.aiquant.factor-automation` — five-minute, dual-Flag, `paper_only`
  automation and sleeve-maintenance driver;
- `com.aiquant.asia-radar-refresh` — daily, read-only Asia Radar cache/snapshot
  refresh, independent of D-33 qualification and execution.

This stack still does not install the optional legacy manual-sleeve schedulers.
The D-33 driver acts only on `automation_managed` sleeves; its semantic runbook
is `/Users/sunyibo/programs/Hermes-quant-agent/docs/runbooks/full-automation-paper.md`.

## Everyday macOS operation (2026-08-10)

The supported daily entrypoint is repository-owned and independent of Codex,
Claude Code, ChatGPT, or any terminal lifetime:

```bash
cd /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
bash scripts/local_mac_stack.sh start
bash scripts/local_mac_stack.sh status
```

### Source and deployment checkout contract (2026-08-11)

The two local checkouts have different, non-interchangeable roles:

| Role | Path | Allowed Git activity |
|---|---|---|
| Development source | `/Users/sunyibo/programs/ai-quant-platform` | edit, test, commit, and push `main` to GitHub |
| Deployment runtime | `/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform` | fetch and fast-forward only; never develop, commit, rebase, or push |

All agents and interactive development tools must edit the development source.
The runtime checkout contains ignored owner-only environment, logs, caches, and
generated runtime state; never run `git clean`, reset those files, or delete the
checkout as part of source synchronization.

Deploy a reviewed source commit with an exact fast-forward:

```bash
# 1. Develop and verify only in the source checkout.
cd /Users/sunyibo/programs/ai-quant-platform
git status --short --branch

# 2. Promote that exact committed main into the runtime checkout.
cd /Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/ai-quant-platform
git fetch source main
git merge --ff-only FETCH_HEAD
test "$(git rev-parse HEAD)" = "$(git -C /Users/sunyibo/programs/ai-quant-platform rev-parse HEAD)"

# 3. Build/restart the persistent stack from the deployment checkout.
bash scripts/local_mac_stack.sh restart
bash scripts/local_mac_stack.sh status

# 4. After runtime health and safety verification, publish from source only.
cd /Users/sunyibo/programs/ai-quant-platform
git push origin main
```

In the runtime checkout, `origin` is the GitHub fetch remote and `source` is
the local development checkout. Runtime push URLs and local commit/push hooks
are intentionally disabled. If fast-forward is impossible, stop and inspect
the divergence; do not rebase, force-push, create a merge commit, or edit the
runtime copy to make it pass.

Use `restart` after backend or environment changes. `start` and `restart` both
run the production frontend build before installing/reloading the jobs. Use
`build` to compile without restarting, `logs` to tail stable files under
`data/_runtime/logs/`, and `stop` for an intentional full stop.

When invoking the script from a non-interactive runner (AI tool shells, CI),
export `USER` and `HOME` first — the backend env file references `$USER` under
`set -u` and aborts with `USER: unbound variable` otherwise. Note that a
running stack does not pick up new backend routes or frontend pages until
`restart` (or `build` + `restart`) completes; a stale process answers 404 for
routes added after it started. The script:

1. opens Docker Desktop if necessary and starts the existing
   `quantplatform-db` container without recreating its volume;
2. validates the ordinary backend command
   `python -m quant_system.cli serve --host 127.0.0.1 --port 8765`;
3. runs `npm --prefix src/frontend run build` and serves the production build;
4. installs the Hermes, backend, frontend, connector, factor-automation, and
   Asia Radar refresh user LaunchAgents;
5. requires the prior Hermes PID and port to remain quiescent before replacement,
   then waits for PostgreSQL and all three HTTP ports to become ready.

The local trust mode bypasses identity ceremony only. A trust session is bound
to the `local_trust` session kind and stops working when trust mode is disabled.
Live readiness reports `admission_mode=local_trust` with no candidate ID or
digest; it must never masquerade as a digest-bound candidate admission.
It does not enable real trading: `live_trading_enabled=false` and
`kill_switch=true` remain independent hard boundaries. Startup never applies a
database migration. Migration 029 was applied once on 2026-08-10 after backup
and isolated restore rehearsal. It is the append-only automatic
promote/demote/daily-quota authority and must not be replayed. D-33 source flags
default off; the inspected owner runtime enabled all four on 2026-08-10 after
full acceptance. They grant only machine-reviewed `paper_only` land and never
authorize a candidate/release or live trading.

## Historical source and live boundary (2026-07-31)

The snapshot below is retained as dated evidence and is superseded operationally
by the 2026-08-10 everyday-operation and migration statements above.

Read-only inspection on 2026-07-31 established this narrow snapshot:

- the repository change set contains ordered migration source 016–028;
- live `quantplatform` has the inspected 016–027 markers;
- live `quantplatform` does not have
  `agent_v02_candidate_paper_fence_meta`, the migration 028 marker;
- the running backend predates this source and returns `404` for the new
  provider-free `GET /api/safety/effective` route.

Migration 028 is a source/change set. This runbook does not prove whether it is
committed, installed, isolated-replayed, live-applied, loaded by the running
process, or authorized. Recheck every fact in the actual operator window; do
not copy this dated observation forward.
Nothing in this runbook sets `release_authorized=true` or opens public write.

### Completed operator-window and AlphaZeroBeta retest (2026-08-01)

The retained 2026-07-31 text above is the pre-apply snapshot. In the exact
authorized follow-up window, Platform commit `2eb714d1ef4ece96a664a816b1f3392d1640809e`
was installed for the one-time migration apply. The later formal AlphaZeroBeta
retest bound Platform `53f7280dbd66ecb79add9fc377db2de8a3d22edd`, HQA
`669c247f8b0d33c8a90e6381c3f0828519304816`, and Hermes
`199a251d20ec62be3845681f40d220a40fabd7d8`; do not collapse those identities
into the earlier apply snapshot. The live database was observed with:

- one `agent_v02_candidate_paper_fence_meta` row at schema version 1, schema
  fingerprint
  `e3f713ac05a1a990cfa9be45157e880e06709c425a4883736544d8f2b626f33a`,
  and exactly `trg_hermes_session_candidate_binding` and
  `trg_hermes_command_candidate_binding` in `ENABLE ALWAYS` state;
- a passing normal backend/frontend restart, live readiness, and live
  provider-free `GET /api/safety/effective`;
- `dry_run=true`, `paper_trading=true`, `live_trading_enabled=false`, and
  `kill_switch=true` throughout;
- public release/write fields still OFF.

The subsequent AlphaZeroBeta retest has two separate verdicts. Do not collapse
them into one “E2E passed” claim:

| Layer | Verdict | Observed evidence |
|---|---|---|
| Mechanical lifecycle | **PASS** | Web UI, managed Session, dispatch, real provider, command approval, durable Run, direct PDF/full-text reads, and database persistence completed. The actual 13 tool calls were `web_search=0`, `web_extract=1` (failed), `terminal=5`, `read_file=5`, and `skill_view=2`. |
| Paper-intake research contract | **UNVERIFIED / NOT ACCEPTED** | The successful lifecycle did not produce or verify a runtime-enforced, digest-bound `hqa.paper_intake/v1` receipt. Skill-only hardening did not constrain the research verdict and is not an accepted mitigation. |
| Factor/backtest/Gate/result continuation | **NOT EVALUATED** | Because the upstream paper-intake verdict was not accepted, zero downstream rows cannot be relabeled `EXPECTED_NOT_REACHED` or used as evidence of a correct non-actionable branch. |
| Trading safety | **PASS** | The canonical order state did not change and the retest placed zero orders. |

The exact lifecycle identity was:

```text
Platform Session: wm_39f4577b534c9a9bca8eb5c634339408
Hermes Session:   web_39f4577b534c9a9bca8eb5c634339408cd82dd74
Command:          850d34cd-6286-4fdb-9151-4c6b333ef895
Hermes Run:       run_7cf82203191743ff85cb373285579ab6
Candidate:        candidate_087abe73ffb54fb9914fac6817862c01 (revoked)
```

The PostgreSQL retest counts were `primary=1`, `approval_control=2`,
`hermes_run=1`, `workflow_binding=0`, `gate_challenge=0`, `gate_action=0`,
`gate_completion=0`, `run_link=0`, `typed_result=0`, `platform_run=0`, and
`platform_backtest=0`. Those zeros describe **not evaluated** downstream work;
they do not validate the research verdict.

The canonical order snapshot SHA-256 was
`c4d6979ffddeed35fad34ca6daef30907c7bc8036297ce0b6332b6bfa1ad295d`:
one account, 12 ledger facts, zero pending orders, and three positions. All four
order-table delta counts were zero and paper-authority epoch `197` was unchanged.
Cleanup revoked the exact candidate, restored the connector to `reconcile_only`,
and left `chat_write_ready=false` with blocker `candidate_admission_missing`,
`public_chat_write_ready=false`, `public_write_authorized=false`,
`release_authorized=false`, `kill_switch=true`, `paper_trading=true`, and
`live_trading_enabled=false`.

The formal retest preflight manifest is
`/Users/sunyibo/programs/Hermes-quant-agent/artifacts/alphazerobeta-websearch-retest-20260801.pEDa3x/preflight/agent-v0.2-candidate-evidence.json`
(SHA-256
`eba8099bf3801927f3d93b40d1e133546d7cbcc4eece4c58b416bf52bd29a136`);
its candidate suite recorded `5632 passed / 272 skipped / 0 failed`.
The cross-repo trace and database/browser evidence are recorded in the exact
HQA runtime repository as
`/Users/sunyibo/programs/Hermes-quant-agent/data/_runtime/agent-v02-work/Hermes-quant-agent/docs/audits/2026-07-31-alphazerobeta-paper-research-web-e2e.md`;
do not duplicate them here. This is a dated observation, not authority to
reapply 028, reuse the revoked candidate, or open public write. Re-run all
status and readiness checks before any future candidate or release window.

## Non-negotiable safety state

Keep all of the following true throughout preparation, migration, candidate
E2E, and rollback:

```text
paper_trading=true
live_trading_enabled=false
kill_switch=true
public_chat_write_ready=false
public_write_authorized=false
release_authorized=false
```

`chat_write_ready` is local readiness and may open only inside an exact private
candidate or accepted-release window. It is not a synonym for any public field.

Backend startup is never migration authority. The runtime env must contain
`QS_DATABASE_AUTO_MIGRATE=false`; the launch scripts reject a truthy value.
Only `quant-system migrate --apply --allow <exact-file>` may apply a future
migration, after fresh human authorization for that exact database and source
identity. For current live `quantplatform`, first observe the 028 marker: because
it exists, every 028 plan/apply must stop even if a generic migration approval is
later granted. The retained 028 command below is permitted only against a newly
created isolated pre-028 restore for rehearsal, never current live.

## Release identity and runtime files

Use a clean, reviewed, committed release checkout. Source, HQA, and Hermes
runtime digests must match the preflight/evidence that the candidate will bind.
A dirty worktree, a green isolated suite, or a backup receipt is not a release
identity.

Create these ignored owner-only files in the release checkout:

```text
data/_runtime/agent-v0.2-backend.env
data/_runtime/agent-v0.2-frontend.env
data/_runtime/agent-v0.2-connector.env
```

Every file must be a regular non-symlink owned by the current user with exact
mode `600`. Keep credentials in an owner-only key file or Keychain; never put
them in this runbook, Git, argv, browser storage, or evidence logs.

The backend env may contain the following non-secret shape:

```dotenv
QS_DATABASE_ENABLED=true
QS_DATABASE_URL=REDACTED
QS_DATABASE_AUTO_MIGRATE=false
QS_PAPER_ACCOUNT_DB_MODE=canonical
QS_HERMES_GATEWAY_ENABLED=true
QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642
QS_HERMES_GATEWAY_API_KEY_FILE=/absolute/owner-only/hermes-api.key
QS_HERMES_GATEWAY_RUNTIME_ROOT=/absolute/path/to/hermes-runtime
QS_INTENT_PAYLOAD_HQA_ROOT=/absolute/path/to/Hermes-quant-agent-release
QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE=/absolute/path/to/hqa-python
QS_LOCAL_MUTATION_ENABLED=true
QS_LOCAL_MUTATION_COMPOSER_OPEN=true
```

The frontend env requires an explicit local-only chat build:

```dotenv
QS_HERMES_CHAT_ENABLED=true
NEXT_PUBLIC_QUANT_API_BASE_URL=http://127.0.0.1:8765
```

These flags are necessary but never sufficient: database readiness, effective
paper safety, Keychain readiness, candidate/release authority, owner/CSRF
checks, and connector liveness still gate every write.

## Historical migration 016–028 operator window — do not replay live

This section preserves the exact pre-apply sequence used by the completed
2026-08-01 window. It is not a current live execution queue. If
`quant_system.agent_v02_candidate_paper_fence_meta` exists in the target, stop:
do not plan or apply 028 there. The example apply command in this section may be
used only on a new isolated database restored from the retained pre-028 dump.

The ordered additive ladder is:

```text
016 -> 017 -> 018 -> 019 -> 020 -> 021 -> 022
    -> 023 -> 024 -> 025 -> 026 -> 027 -> 028
```

Never skip an absent prerequisite or use a later migration as a patch. In a new
isolated pre-028 restore only, if inspection finds any missing 016–024 entry,
apply the missing entries in order before 025. Do not start backend, frontend,
or connector between partially applied ladder entries.

The completed window used this sequence:

```text
freeze writers
  -> capture live pre-028 backup
  -> restore that backup into an isolated destination
  -> replay the exact missing migrations there
  -> pass exact readiness
  -> obtain one-time live-apply authorization
  -> apply the exact allowlist to live once
  -> pass live readiness
  -> seal absolute-runner release preflight
  -> restart backend/frontend
  -> non-creating Keychain probe
  -> open private candidate
  -> start supervised connector
  -> real E2E
  -> revoke/accept candidate
  -> retain and re-verify the isolated pre-028 restore rehearsal
```

The final rehearsal check never overwrites, replaces, or switches the live
database.

### 1. Freeze and capture pre-028 authority

Keep the connector in `reconcile_only`, close any candidate, stamp, or cutover,
and stop mutation traffic before the backup. Record clean three-repository
identity, live schema fingerprint, current service identity, and provider-free
paper safety facts without printing connection strings or credentials.

Create a new owner-only backup directory and capture the live database with
operator-vetted PostgreSQL tools. The live dump and its digest are the rollback
authority; the repository helper below is additional disposable-cluster proof,
not a backup of live `quantplatform`:

```bash
umask 077
set -a
source data/_runtime/agent-v0.2-backend.env >/dev/null 2>&1
set +a
mkdir -m 700 /absolute/owner-only/pre-028-backup
pg_dump --dbname="$QS_DATABASE_URL" --format=custom \
  --file=/absolute/owner-only/pre-028-backup/quantplatform.dump
pg_restore --list \
  /absolute/owner-only/pre-028-backup/quantplatform.dump >/dev/null
shasum -a 256 \
  /absolute/owner-only/pre-028-backup/quantplatform.dump

bash scripts/verify_agent_v02_backup_restore.sh \
  --output-dir /absolute/new/owner-only/disposable-backup-proof
```

Do not continue until the live dump has been restored into a new isolated
database and its pre-028 schema/data/ownership facts match the source. Preserve
that untouched restore as the rollback rehearsal. Never test restore by
overwriting the live database.

### 2. Replay the exact source in isolation

Point a temporary owner-only env at a newly created isolated restored database.
First run a dry plan, then apply only the exact missing files. For the dated
016–027 pre-apply baseline, the isolated-only final command was:

```bash
quant-system migrate --allow 028_agent_v02_candidate_paper_epoch_fence.sql

quant-system migrate --apply \
  --allow 028_agent_v02_candidate_paper_epoch_fence.sql \
  --yes
```

This example is prohibited against current live. On an older isolated restore,
repeat `--allow` in lexical order for every genuinely missing prerequisite. Run
the PostgreSQL and focused safety suites against isolated infrastructure and
retain their receipts:

```bash
bash scripts/verify_agent_v02_postgres_suite.sh \
  --output-dir /absolute/new/owner-only/postgres-suite
bash scripts/verify_agent_v02_focused_safety.sh \
  --python /absolute/path/to/release/.venv/bin/python \
  --basetemp /absolute/new/owner-only/focused-safety
```

The migration runner holds the exclusive
`quant_system:hermes_schema_runtime_gate` for the complete allowlisted file
batch. Candidate open takes the matching transaction-scoped shared gate before
reading the schema fingerprint, checking readiness, or writing authority rows;
the production fingerprint is read on that same guarded connection. Thus
migration and candidate admission serialize instead of admitting a
check-then-write schema race. A gate wait timeout is not candidate success and
must not be retried by bypassing the gate.

### 3. Verify the 028 contract

Migration 028 readiness is exact, not “table exists.” It must verify:

- the fence marker's version, owner, and ACL;
- the canonical `default` paper-account raw-consistency constraint;
- exact helper function identity/source/ACL;
- exact candidate and paper-epoch trigger signatures, including the required
  `ENABLE ALWAYS` state;
- restricted runtime-role access;
- candidate TTL and all 016–027 prerequisites.

The effective paper authority must also be true:

- `QS_PAPER_ACCOUNT_DB_MODE=canonical`;
- exactly one root-owner paper account exists;
- its materialized `account_id` is `default`;
- its materialized `kill_switch` is true;
- raw JSON contains the same `account_id` and a JSON boolean `kill_switch=true`;
- the global kill switch is true and the current paper-authority epoch is
  available.

Use the source readiness functions before restart. The script emits booleans
only and exits closed:

```bash
set -a
source data/_runtime/agent-v0.2-backend.env >/dev/null 2>&1
set +a

PYTHONPATH=src .venv/bin/python - <<'PY'
from quant_system.config.settings import load_settings
from quant_system.hermes.candidate_admission_authority import (
    candidate_admission_runtime_security_is_ready,
    candidate_admission_schema_ready,
)

settings = load_settings()
schema = candidate_admission_schema_ready(settings)
runtime = candidate_admission_runtime_security_is_ready(settings)
print({"candidate_schema_ready": schema, "runtime_security_ready": runtime})
raise SystemExit(0 if schema and runtime else 78)
PY
```

The completed 2026-08-01 window performed the live apply once after isolated
review and exact human authorization. That authorization is spent. Current live
already has the 028 marker, so do not run the dry plan or apply there again. A
timeout or unavailable fingerprint in any future migration is an unknown
outcome: stop, inspect, and recover; never rerun blindly.

### 4. Seal frontend runner identity in release evidence

Before building candidate or release preflight evidence, run the frontend suite
only with an argv whose first two entries are:

```text
/absolute/trusted/node
/absolute/platform/src/frontend/node_modules/vitest/vitest.mjs
```

The first entry is the reviewed Node executable; the second is the Vitest
JavaScript entry. Both arguments must be absolute and resolve to trusted,
owner-controlled regular files. In test-execution receipt contract v2,
`runner_kind` must be `node_vitest`; the required `executable` and
`suite_entry` identity documents seal canonical realpath, trusted root plus
relative path, uid/mode/link facts, and SHA-256. Receipt validation must recheck
the same paths and bytes before the evidence can open a candidate or release
gate.

Never resolve Node from ambient `PATH`, invoke bare `node`, use
`/usr/bin/env node`, or substitute `npm`, `pnpm`, a shell wrapper, or
`node_modules/.bin/vitest`. A clean repository digest does not substitute for
these two runner identities. If either file, path, owner/mode/link identity, or
digest changes, discard the receipt and rerun the suite from the reviewed
release identity.

### 5. Restart and observe

Build and validate the release-bound frontend/backend:

```bash
npm --prefix src/frontend run build
chmod 600 data/_runtime/agent-v0.2-backend.env
chmod 600 data/_runtime/agent-v0.2-frontend.env
bash scripts/run_quant_backend.sh --check
bash scripts/run_quant_frontend.sh --check

bash scripts/restart_agent_v02_stack.sh \
  --output-dir /absolute/new/owner-only/restart-evidence
```

Then verify provider-free runtime state:

```bash
curl --fail http://127.0.0.1:8765/api/health
curl --fail http://127.0.0.1:8765/api/settings
curl --fail http://127.0.0.1:8765/api/hermes/gateway
curl --fail http://127.0.0.1:8765/api/safety/effective
curl --fail http://127.0.0.1:3001/zh/hermes
quant-system hermes release status
quant-system hermes candidate status
```

`GET /api/safety/effective` is provider-free observation. Its `effective=true`
does not open local chat or public release.

## Keychain preflight and private candidate

After restart, use the exact configured HQA release and interpreter. The first
probe must not create a key:

```bash
(
  cd "$QS_INTENT_PAYLOAD_HQA_ROOT"
  printf '{}\n' |
    "$QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE" -m hqa.intent_payload_cli probe
)
```

If the result is key missing, stop. Only a human operator may separately decide
to initialize this exact committed/installed runtime:

```bash
(
  cd "$QS_INTENT_PAYLOAD_HQA_ROOT"
  printf '{}\n' |
    "$QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE" \
    -m hqa.intent_payload_cli initialize-key
  printf '{}\n' |
    "$QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE" -m hqa.intent_payload_cli probe
)
```

`initialize-key` is the only key-creating operation. Do not substitute a normal
encrypt/put, expose it to the BFF/worker/skill, or automate it.

Inspect, open, and if necessary revoke the bounded candidate:

```bash
quant-system hermes candidate status
quant-system hermes candidate open \
  --note "<operator reason>" \
  --client-action-id "<stable exact action id>"

quant-system hermes candidate revoke \
  --admission-id "<exact id>" \
  --expected-admission-digest "<exact digest>" \
  --reason "<failure, drift, or abandonment reason>" \
  --client-action-id "<stable exact revoke id>"
```

Open only after all preflight facts match. It remains local-private and
short-lived. Start `supervised_dispatch` only after the candidate status and
connector liveness bind the same runtime/schema; see
[the connector runbook](agent-v0-2-connector-daemon.md).

Real E2E must cover managed multi-turn chat, refresh/restart recovery,
historical/external session read-only behavior plus explicit exact fork,
approval/stop/result evidence, both vertical flows, and zero orders. External
or historical sessions never become writable in place. Any uncertainty closes
the candidate and keeps public standing OFF.

### Paper-intake acceptance gate (P1 open)

For a paper-research task, lifecycle success is necessary but not sufficient.
Do not accept a research verdict from a succeeded Command/Run, provider usage,
tool counts, direct PDF/full-text reads, or skill instructions alone. A future
candidate must provide a runtime-enforced, digest-bound `hqa.paper_intake/v1`
receipt and pass its verifier before the verdict can authorize a downstream
classification or a deliberate no-op branch.

Until that receipt/verifier exists and passes, record the paper-intake verdict
as `unverified/not accepted` and factor, backtest, Gate, Run-link, and typed-
result work as `not evaluated`. Keep candidate acceptance, release, and public
write closed. This P1 is an application/runtime contract gap; changing a skill
prompt alone does not close it.

## Pre-028 restore

After a successful E2E, retain and re-verify the already isolated rehearsal by
its dump digest and pre-028 schema/data/owner facts only. Do not run an
environment switch as a normal completion step.

Migration 028 has no supported down-migration. Only if an explicitly authorized
emergency rollback is required, use the untouched pre-028 backup:

1. revoke the candidate and keep public/local mutation closed;
2. return the connector to `reconcile_only`, then stop connector and Web stack;
3. restore the pre-028 dump into a new database, never over the failed live
   database;
4. verify the dump digest and the rehearsed pre-028 schema/data/owner facts;
5. change the owner-only runtime env to the restored database;
6. restart backend/frontend and verify provider-free health/readiness;
7. keep 028-dependent candidate/release paths closed.

Do not delete the failed database or the backup while the outcome is uncertain.
Do not merge post-028 candidate/E2E rows back into the restored authority.
Database replacement and env switching require explicit operator approval.

## Install or remove LaunchAgents

For a prepared release:

```bash
bash scripts/install_agent_v02_stack_launchagents.sh
launchctl print gui/$(id -u)/com.aiquant.backend
launchctl print gui/$(id -u)/com.aiquant.frontend
```

Install the connector separately only after the private candidate prerequisites
above are honest:

```bash
bash scripts/install_agent_v02_connector_launchagent.sh
```

Remove only the Web stack:

```bash
bash scripts/uninstall_agent_v02_stack_launchagents.sh
```

The uninstaller removes only backend/frontend LaunchAgents. It does not alter
the connector, Paper Strategy Sleeves jobs, runtime evidence, backups, or logs.
