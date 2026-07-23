#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/data/_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="${QS_AGENT_V02_CONNECTOR_ENV_FILE:-$RUNTIME_DIR/agent-v0.2-connector.env}"

install -d -m 700 "$RUNTIME_DIR" "$LOG_DIR"

# launchd does not inherit the operator's interactive shell.  A local env file
# is optional, but when present it must be owned by this user and inaccessible
# to group/other users before it is sourced.
if [[ -f "$ENV_FILE" ]]; then
  OWNER_UID="$(stat -f '%u' "$ENV_FILE")"
  FILE_MODE="$(stat -f '%Lp' "$ENV_FILE")"
  if [[ "$OWNER_UID" != "$(id -u)" || $((8#$FILE_MODE & 077)) -ne 0 ]]; then
    echo '{"error_code":"connector_env_file_permissions_invalid"}' >&2
    exit 78
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PYTHON="${QS_AGENT_V02_CONNECTOR_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  COMMON_GIT_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
  MAIN_ROOT="$(dirname "$COMMON_GIT_DIR")"
  if [[ -x "$MAIN_ROOT/ai-quant/bin/python" ]]; then
    PYTHON="$MAIN_ROOT/ai-quant/bin/python"
  elif [[ -x "$ROOT/ai-quant/bin/python" ]]; then
    PYTHON="$ROOT/ai-quant/bin/python"
  else
    echo '{"error_code":"connector_python_unavailable"}' >&2
    exit 69
  fi
fi

if [[ ! -x "$PYTHON" ]]; then
  echo '{"error_code":"connector_python_unavailable"}' >&2
  exit 69
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

POLL_INTERVAL="${QS_AGENT_V02_CONNECTOR_POLL_INTERVAL_SECONDS:-5}"
WORKER_ID="${QS_AGENT_V02_CONNECTOR_WORKER_ID:-agent-v02-connector-1}"

cd "$ROOT"
exec "$PYTHON" -m quant_system.cli hermes connector-worker \
  --mode supervised_dispatch \
  --poll-interval-seconds "$POLL_INTERVAL" \
  --reconcile-limit 100 \
  --worker-id "$WORKER_ID"
