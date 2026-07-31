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

The installed posture must set
`QS_AGENT_V02_CONNECTOR_MODE=reconcile_only` explicitly. Never rely on a code
default or remove the explicit mode from the live owner-only environment.
For frozen compatibility, the wrapper's absent-env fallback remains `supervised_dispatch`;
that legacy behavior is not the installed safety posture and must never be
treated as a safe default.
Reconcile-only intentionally does not acquire the supervised liveness
generation, so it can never make local Web chat ready.

## Prerequisites

[`agent-v0-2-local-stack.md`](agent-v0-2-local-stack.md) is the sole authority
for migration 016–028 ordering, live/source distinction, backup, isolated
replay, readiness, restart, candidate E2E, and pre-028 restore. This connector
runbook does not declare any migration live.

Do not select `supervised_dispatch` until that runbook has established all of
the following for one exact operator window:

- clean committed Platform, HQA, and Hermes runtime identities;
- migration 028 exact schema/runtime readiness, including canonical
  `default` paper-account raw consistency and current paper-authority epoch;
- provider-free `GET /api/safety/effective` reports effective paper safety;
- HQA Keychain `probe` succeeds without creating a key;
- one short-lived private candidate, or an exact accepted release, is active;
- Hermes exposes the managed Session and durable Run contract on loopback;
- the restricted runtime login and all local mutation/owner/CSRF gates pass.

An active local candidate may make local `chat_write_ready` true. It never makes
`public_chat_write_ready`, `public_write_authorized`, or
`release_authorized` true. Standing public posture remains OFF.

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
Any Keychain check performed by connector `--check` or normal startup must use
the non-creating HQA `probe`. `initialize-key` is an operator-only HQA command
documented in the local-stack runbook; the daemon, BFF, and automatic retry
paths must never call it.

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
work, and it must not initialize the HQA Keychain.

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
