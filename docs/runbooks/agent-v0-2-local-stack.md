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

Keep the Hermes API key in its separate owner-only file. Then validate both
runners without starting them:

```bash
chmod 600 data/_runtime/agent-v0.2-backend.env
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
