# Agent v0.2 Connector Daemon

This user-level macOS LaunchAgent runs the production Agent v0.2 connector from
the checkout that contains this runbook. It is deliberately different from the
old dark worker:

- mode is always `supervised_dispatch`;
- the production dispatch and Run-observation seam is HQA's subprocess CLI and
  Hermes' durable `/v1/runs` contract;
- before publishing liveness, the daemon invokes the real HQA `capabilities`
  subprocess and verifies its exact six-operation/write/fork contract plus the
  grounded Hermes capability receipt against the shared Platform manifest;
- the same short-bounded compatibility probe repeats before every work cycle;
  one permanent contract drift, or three consecutive transient CLI/probe
  failures, requests cooperative shutdown without claiming or provisioning;
- one pending managed Session is provisioned before each command-claim cycle;
- the daemon holds the single-active PostgreSQL liveness lease for its complete
  process lifetime and heartbeats independently of a slow Hermes call;
- every new or recovery dispatch re-evaluates the effective durable release
  gate immediately before network use;
- there is no default or configured fixed prompt;
- it has no trading/order path and does not change the trading kill switch.

`reconcile_only` remains a manual repair mode. It intentionally does not acquire
the supervised liveness generation, so it can never make Web chat ready.

## Prerequisites

Do not install the LaunchAgent until migrations through
`014_agent_v02_connector_liveness.sql` are live and the restricted runtime
database login is configured. The Platform, HQA and Hermes runtime checkouts
must be clean commits because the daemon binds its generation to the exact
Platform Git runtime digest. Hermes must expose the managed Session and durable
Run capability contract on loopback.

The release gate distinguishes durable operator/drift facts from uncertainty.
An operator-closed stamp/cutover, runtime identity mismatch, schema fingerprint
mismatch, or release-evidence mismatch may terminally reject a newly claimed
turn. A timeout, unavailable release/DB/Hermes probe, stale capability read, or
temporary registry outage returns the exact turn to the delayed queue with
bounded backoff and performs zero Hermes mutations. Never drain or delete those
retryable queued turns to make readiness appear green.

The wrapper reads inherited variables and, when present, this optional
owner-only file:

```text
data/_runtime/agent-v0.2-connector.env
```

Keep the file owned by the current user and mode `600`. A typical local file
sets paths and loopback coordinates, not raw prompts:

```dotenv
QS_DATABASE_ENABLED=true
QS_DATABASE_URL=postgresql://quant_app_runtime:REDACTED@127.0.0.1:5432/quantplatform
QS_HERMES_GATEWAY_ENABLED=true
QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642
QS_HERMES_GATEWAY_API_KEY_FILE=/Users/you/.hermes/api-server.key
QS_HERMES_GATEWAY_RUNTIME_ROOT=/absolute/path/to/hermes-runtime
QS_INTENT_PAYLOAD_HQA_ROOT=/absolute/path/to/Hermes-quant-agent-release
QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE=/absolute/path/to/hqa-python
QS_LOCAL_MUTATION_ENABLED=true
QS_LOCAL_MUTATION_COMPOSER_OPEN=true
```

The Hermes API key stays in its separate mode-`600` file. Never put prompt
content or `--fixed-input` in the daemon configuration.

## Install or replace

The installer is replay-safe: it validates the plist, boots out an older
generation when present, then bootstraps this exact template.

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
API key.

## Inspect and stop

```bash
launchctl print gui/$(id -u)/com.aiquant.agent-v02-connector
tail -f data/_runtime/logs/agent-v02-connector.launchd.out.log
bash scripts/uninstall_agent_v02_connector_launchagent.sh
```

SIGTERM/SIGINT requests cooperative shutdown. A normal shutdown records a
durable `stopped` generation receipt and releases the advisory lock. If the
database session or heartbeat is lost, the process stops claiming new work;
the missing advisory lock makes readiness fail closed even if the last durable
row still said `active`.

Do not use `--once --fixed-input` as a daemon substitute. That option is only an
explicit operator smoke tool and is never present in the wrapper or plist.
