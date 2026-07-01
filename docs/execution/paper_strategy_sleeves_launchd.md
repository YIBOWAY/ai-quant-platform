# Paper Strategy Sleeves macOS LaunchAgent Runbook

This runbook is for a local Mac setup where the app should start with the user
session and stop when the Mac shuts down. Use LaunchAgent, not LaunchDaemon.
The files live under `~/Library/LaunchAgents`, run as the current user, and
require no sudo.

Safety boundary: this remains paper-only. The LaunchAgent files do not enable
live trading, do not import Futu trade contexts, and do not place broker orders.
UI availability does not mean auto-execution is enabled.

## What Gets Installed

The installer renders templates from `scripts/launchd/` into
`~/Library/LaunchAgents/`:

| Label | Role | KeepAlive |
| --- | --- | --- |
| `com.aiquant.backend` | Runs the local FastAPI backend on `127.0.0.1:8765`. | `true` |
| `com.aiquant.frontend` | Runs the built Next.js frontend on `127.0.0.1:3001`. | `true` |
| `com.aiquant.paper-sleeves.ops-status` | Writes a JSON paper-sleeves status snapshot. | `false` |
| `com.aiquant.paper-sleeves.signals` | Runs one due-signal generation command. | `false` |
| `com.aiquant.paper-sleeves.execute-due` | Runs one due execution-processing command. | `false` |

The backend/frontend service jobs use `KeepAlive=true` because they are local
services. The strategy jobs use `KeepAlive=false` because failed one-shot
commands must not retry in a loop.

## Prepare Frontend Build

Stop any frontend dev server before building. The dev server and build share
`src/frontend/.next`.

```bash
npm --prefix src/frontend run build
```

The frontend LaunchAgent uses production start, not `npm run dev`.

## Install

```bash
chmod +x scripts/run_quant_backend.sh \
  scripts/run_quant_frontend.sh \
  scripts/run_paper_strategy_sleeves.sh \
  scripts/install_paper_strategy_sleeves_launchagent.sh \
  scripts/uninstall_paper_strategy_sleeves_launchagent.sh

./scripts/install_paper_strategy_sleeves_launchagent.sh
```

The installer uses:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist
```

It does not use sudo and should not be run as root.

## Uninstall

```bash
./scripts/uninstall_paper_strategy_sleeves_launchagent.sh
```

This calls `launchctl bootout gui/$(id -u)` for each installed label and removes
the rendered plist files.

## Logs

Wrapper logs are appended under:

```text
data/_runtime/logs/
```

Important files:

- `backend-api.launchd.log`
- `frontend-next.launchd.log`
- `paper-strategy-sleeves.log`

launchd stdout/stderr files are also under the same directory with
`.launchd.out.log` and `.launchd.err.log` suffixes.

## Manual Commands

The same commands can be run without launchd:

```bash
scripts/run_paper_strategy_sleeves.sh ops-status
scripts/run_paper_strategy_sleeves.sh generate-due-signals --target-date 2024-03-20
scripts/run_paper_strategy_sleeves.sh execute-due --target-date 2026-06-29
```

These are one-shot paper commands. File locks and execution journals protect
the account and sleeve files if the API or another CLI command is running.

## Time Windows

The template defaults are conservative local-time placeholders:

- signal generation: weekday `06:10`
- next-open processing: weekday `21:35`

They are not a full market-calendar engine and are not DST-aware. Adjust the
rendered plist times if your Mac timezone or US market open window requires a
different trigger.
