# Agent v0.2 Local Stack LaunchAgents

This runbook installs only the long-running Platform backend and built Web
frontend for the local Agent v0.2 stack:

- `com.aiquant.backend` — release checkout source on `127.0.0.1:8765`;
- `com.aiquant.frontend` — release checkout `.next` build on
  `127.0.0.1:3001`.

It never installs or starts Paper Strategy Sleeves schedulers. The supervised
Hermes connector has its own installer and runbook.

## Prepare the exact release

Apply database migrations only through the explicit operator migration
command. Backend startup rejects `QS_DATABASE_AUTO_MIGRATE=true`; startup is
never a migration authority.

For the final hardening window, first inspect the live migration metadata and
prepare a restore-tested backup. Apply any missing 016–024 prerequisites in
order, then preserve this operator sequence:

```text
backup -> migration 025 -> migration 026 -> service restart -> live E2E
```

Migration 025 fences managed Session/Command writes to the current
paper-authority epoch and exact candidate/release generation. Migration 026
seals the HQA research claim/start/continue digests and enforces claim-less v1
versus exact-lineage v2 completion. Do not infer either migration's live state
from this runbook, and do not start the backend, frontend or connector between
025 and 026. After 026, restart the Platform stack and connector before any
candidate-bound live browser flow so no old process reports a stale schema or
release decision.

Build the frontend in the release checkout:

```bash
npm --prefix src/frontend run build
```

The runners discover the main repository through Git's common directory. This
lets a clean worktree reuse the main checkout's Python environment and frontend
`node_modules`, while `PYTHONPATH` and `.next` remain bound to the release
worktree. Operators may override discovery with `QS_MAIN_REPO_ROOT`.

Create the ignored runtime file at:

```text
data/_runtime/agent-v0.2-backend.env
```

It is a trusted shell dotenv and must be a regular file owned by the current
user with exact mode `600`. Do not commit it. A local example is:

```dotenv
QS_DATABASE_ENABLED=true
QS_DATABASE_URL=postgresql://quant_app_runtime:REDACTED@127.0.0.1:5432/quantplatform
QS_DATABASE_AUTO_MIGRATE=false
QS_HERMES_GATEWAY_ENABLED=true
QS_HERMES_GATEWAY_BASE_URL=http://127.0.0.1:8642
QS_HERMES_GATEWAY_API_KEY_FILE=/absolute/path/to/hermes-api.key
QS_HERMES_GATEWAY_RUNTIME_ROOT=/absolute/path/to/hermes-runtime
QS_INTENT_PAYLOAD_HQA_ROOT=/absolute/path/to/Hermes-quant-agent-release
QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE=/absolute/path/to/hqa-python
QS_LOCAL_MUTATION_ENABLED=true
QS_LOCAL_MUTATION_COMPOSER_OPEN=true
```

Create a second ignored, owner-only frontend runtime file:

```text
data/_runtime/agent-v0.2-frontend.env
```

The frontend runner requires an explicit local chat enablement instead of
silently serving a disabled build:

```dotenv
QS_HERMES_CHAT_ENABLED=true
NEXT_PUBLIC_QUANT_API_BASE_URL=http://127.0.0.1:8765
```

Keep the Hermes API key in its separate owner-only file. Then validate both
runners without starting them:

```bash
chmod 600 data/_runtime/agent-v0.2-backend.env
chmod 600 data/_runtime/agent-v0.2-frontend.env
bash scripts/run_quant_backend.sh --check
bash scripts/run_quant_frontend.sh --check
```

## Install or replace

The dedicated installer repeats both checks before changing launchd state,
renders valid plists for this exact checkout, boots out an older generation,
and bootstraps the replacement:

```bash
bash scripts/install_agent_v02_stack_launchagents.sh
```

It is replay-safe and preserves existing logs. The log directory is mode `700`
and all six backend/frontend combined, stdout, and stderr logs are mode `600`.

Inspect the two services:

```bash
launchctl print gui/$(id -u)/com.aiquant.backend
launchctl print gui/$(id -u)/com.aiquant.frontend
curl --fail http://127.0.0.1:8765/api/health
curl --fail http://127.0.0.1:3001/zh/hermes
```

Install the supervised connector separately only after the durable release
prerequisites are honest:

```bash
bash scripts/install_agent_v02_connector_launchagent.sh
```

## Remove only the Web stack

```bash
bash scripts/uninstall_agent_v02_stack_launchagents.sh
```

The uninstaller boots out and removes only `com.aiquant.backend` and
`com.aiquant.frontend`. It does not alter connector or Paper Strategy Sleeves
jobs and does not delete runtime evidence or logs.
