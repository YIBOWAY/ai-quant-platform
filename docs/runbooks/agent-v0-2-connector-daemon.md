# Agent v0.2 Connector Daemon

This user-level macOS LaunchAgent runs the production Agent v0.2 connector from
the checkout that contains this runbook. The owner-only environment selects one
of exactly two modes:

- `reconcile_only` performs `LISTEN/NOTIFY` wakeups, periodic timeout scans, and
  expired-lease reconciliation. It never claims or dispatches a command and
  every cycle reports zero provider calls and zero Hermes mutations;
- `supervised_dispatch` enables the production dispatch and Run-observation
  seam through HQA's subprocess CLI and Hermes' durable `/v1/runs` contract;
- before publishing liveness, the daemon invokes the real HQA `capabilities`
  subprocess in `supervised_dispatch` and verifies its exact
  six-operation/write/fork contract plus the grounded Hermes capability receipt
  against the shared Platform manifest;
- the same short-bounded compatibility probe repeats before every work cycle;
  one permanent contract drift, or three consecutive transient CLI/probe
  failures, requests cooperative shutdown without claiming or provisioning;
- in `supervised_dispatch`, one pending managed Session is provisioned before
  each command-claim cycle, and the daemon holds the single-active PostgreSQL
  liveness lease for its complete process lifetime;
- every new or recovery dispatch re-evaluates the effective durable release
  gate immediately before network use;
- there is no default or configured fixed prompt;
- it has no trading/order path and does not change the trading kill switch.

The installed v0.2.2 hardening posture must set
`QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` explicitly. The legacy absent-env fallback remains `supervised_dispatch`
solely for the frozen compatibility contract; it is a residual default, not the
installed safety posture. Never remove the explicit mode from the live
owner-only environment. Reconcile-only intentionally does not acquire the
supervised liveness generation, so it can never make Web chat ready.

## Prerequisites

The following additional prerequisites apply before selecting
`supervised_dispatch`. Do not run that mode until migrations through
`026_agent_v02_paper_research_claim_lineage.sql` are live and the restricted runtime
database login is configured. The Platform, HQA and Hermes runtime checkouts
must be clean commits because the daemon binds its generation to the exact
Platform Git runtime digest. Hermes must expose the managed Session and durable
Run capability contract on loopback. Migration 023 binds each Run to the stable
conversation root and its immutable resolved compression tip; migration 024
persists approval/stop external outcomes before an exact replay may be treated
as terminal. Migration 025 binds every new managed Session/Command to the
current paper-authority epoch plus the active candidate or exact accepted
release, so a paper-authority mutation cannot leave a stale release writable.
Migration 026 persists only the sealed research claim/start/continue digests:
Gate 1/2 carry claim+start, Gate 3 adds continue, historical claim-less
completions remain v1, and claimed completions must use exact-lineage v2.

The corresponding HQA source keeps the paper title and ordered universe only
inside its encrypted Intent Payload Store. It may bind the sealed claim only to
Attempt 1, must verify the exact pre-terminal Attempt lineage before terminal
completion, and must accept only the closed 42-key Platform completion
response. Source and isolated review are APPROVE; this statement does not prove
that 025/026 are live or that any candidate, stamp, cutover or connector
generation is active. Inspect those facts in the current operator window.

The final live upgrade sequence is:

```text
backup -> migration 025 -> migration 026 -> service restart -> live E2E
```

If inspection finds an earlier 016–024 migration missing, apply the missing
ordered prerequisites before 025. Never install or restart the connector
between 025 and 026.

The release gate distinguishes durable operator/drift facts from uncertainty.
An operator-closed stamp/cutover, runtime identity mismatch, schema fingerprint
mismatch, or release-evidence mismatch may terminally reject a newly claimed
turn. A timeout, unavailable release/DB/Hermes probe, stale capability read, or
temporary registry outage returns the exact turn to the delayed queue with
bounded backoff and performs zero Hermes mutations. Never drain or delete those
retryable queued turns to make readiness appear green.

The wrapper requires this trusted shell dotenv:

```text
data/_runtime/agent-v0.2-connector.env
```

It must be a regular, non-symlink file owned by the current user with exact
mode `600`. Group-readable files, permissive files, symlinks, directories, and
missing files all fail closed. A typical local file sets paths and loopback
coordinates, not raw prompts:

```dotenv
QS_DATABASE_ENABLED=true
QS_DATABASE_URL=postgresql://quant_app_runtime:REDACTED@127.0.0.1:5432/quantplatform
QS_DATABASE_AUTO_MIGRATE=false
QS_AGENT_V02_CONNECTOR_MODE=reconcile_only
QS_HERMES_GATEWAY_ENABLED=true
QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642
QS_HERMES_GATEWAY_API_KEY_FILE=/Users/you/.hermes/api-server.key
QS_HERMES_GATEWAY_RUNTIME_ROOT=/absolute/path/to/hermes-runtime
QS_INTENT_PAYLOAD_HQA_ROOT=/absolute/path/to/Hermes-quant-agent-release
QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE=/absolute/path/to/hqa-python
QS_LOCAL_MUTATION_ENABLED=true
QS_LOCAL_MUTATION_COMPOSER_OPEN=true
```

Because this is an owner-only trusted shell dotenv, a local operator may keep
the database password in macOS Keychain instead of writing it into the file:

```dotenv
QS_DATABASE_URL="postgresql://quant_app_runtime:$(security find-generic-password -w -s ai-quant-platform-agent-v02-db -a "${USER}")@127.0.0.1:5432/quantplatform"
QS_DATABASE_AUTO_MIGRATE=false
```

The wrapper suppresses dotenv evaluation output, so neither the password nor a
secret-helper diagnostic is copied into launchd logs. Startup always exports
`QS_DATABASE_AUTO_MIGRATE=false`; any truthy request is rejected before Python
starts.

The Hermes API key stays in its separate mode-`600` file. Never put prompt
content in the daemon configuration. The production connector has no
`--fixed-input` option; it resolves only the exact encrypted intent payload.

Validate the exact checkout before installing:

```bash
chmod 600 data/_runtime/agent-v0.2-connector.env
bash scripts/run_agent_v02_connector.sh --check
```

This check sources the protected dotenv, accepts only exact
`reconcile_only|supervised_dispatch`, rejects startup migration, verifies the
configured Python can import `quant_system` and connector configuration from
this release checkout, and validates the poll/worker settings. It does not open
PostgreSQL, contact Hermes or a provider, acquire connector liveness, or claim
work.

## Install or replace

The installer is replay-safe. It runs the same network-free check, including
the exact mode validation, before creating or replacing any LaunchAgent state,
validates the plist, boots out an older generation when present, then
bootstraps this exact template.

```bash
chmod 600 data/_runtime/agent-v0.2-connector.env
bash scripts/install_agent_v02_connector_launchagent.sh
```

The installer pre-creates its directory as mode `700` and both launchd logs as
mode `600`:

```text
data/_runtime/logs/agent-v02-connector.launchd.out.log
data/_runtime/logs/agent-v02-connector.launchd.err.log
```

Cycle output is bounded NDJSON. It reports command counts, the managed Session
provisioning outcome, and liveness generation state; it never logs a prompt or
API key. In `reconcile_only`, `claimed_count`, `provider_call_count`, and
`hermes_mutation_count` must remain zero.

## Inspect and stop

```bash
launchctl print gui/$(id -u)/com.aiquant.agent-v02-connector
tail -f data/_runtime/logs/agent-v02-connector.launchd.out.log
bash scripts/uninstall_agent_v02_connector_launchagent.sh
```

SIGTERM/SIGINT requests cooperative shutdown. A normal supervised shutdown
records a durable `stopped` generation receipt and releases the advisory lock.
Reconcile-only has no supervised liveness generation to stop and exits cleanly
without claiming work. If a supervised database session or heartbeat is lost,
the process stops claiming new work; the missing advisory lock makes readiness
fail closed even if the last durable row still said `active`.

Do not use `--once --fixed-input` as a daemon substitute. The CLI rejects that
prompt-bearing option; supervised dispatch uses only the durable intent-payload
port and the option is absent from the wrapper and plist.
