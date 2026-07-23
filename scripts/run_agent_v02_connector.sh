#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/data/_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
ENV_FILE="${QS_AGENT_V02_CONNECTOR_ENV_FILE:-$RUNTIME_DIR/agent-v0.2-connector.env}"

fail() {
  echo "connector_config_error=$1" >&2
  exit 78
}

file_owner_and_mode() {
  local path="$1"
  if stat -f "%u %Lp" "$path" >/dev/null 2>&1; then
    stat -f "%u %Lp" "$path"
  else
    stat -c "%u %a" "$path"
  fi
}

load_connector_env() {
  local metadata owner mode
  [[ -e "$ENV_FILE" || -L "$ENV_FILE" ]] || fail "connector_env_missing"
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "connector_env_not_regular"
  metadata="$(file_owner_and_mode "$ENV_FILE")" ||
    fail "connector_env_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "connector_env_wrong_owner"
  [[ "$mode" =~ ^0?600$ ]] || fail "connector_env_mode_must_be_600"

  set -a
  # This is deliberately a trusted shell dotenv so an owner may resolve a
  # password from Keychain with command substitution.  Suppress all output
  # while evaluating it: a secret helper must never reach launchd logs.
  # shellcheck disable=SC1090
  if ! source "$ENV_FILE" >/dev/null 2>&1; then
    set +a
    fail "connector_env_load_failed"
  fi
  set +a
}

resolve_python() {
  local common_git_dir main_root
  if [[ -n "${QS_AGENT_V02_CONNECTOR_PYTHON:-}" ]]; then
    printf '%s\n' "$QS_AGENT_V02_CONNECTOR_PYTHON"
    return
  fi
  common_git_dir="$(
    git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null
  )" || fail "main_repo_not_discoverable"
  if [[ "$(basename "$common_git_dir")" == ".git" ]]; then
    main_root="$(dirname "$common_git_dir")"
  else
    main_root="$ROOT"
  fi
  if [[ -x "$ROOT/ai-quant/bin/python" ]]; then
    printf '%s\n' "$ROOT/ai-quant/bin/python"
  elif [[ -x "$main_root/ai-quant/bin/python" ]]; then
    printf '%s\n' "$main_root/ai-quant/bin/python"
  else
    fail "connector_python_unavailable"
  fi
}

validate_release_runtime() {
  "$PYTHON" - "$ROOT/src" "$POLL_INTERVAL" "$WORKER_ID" >/dev/null 2>&1 <<'PY'
import math
import sys
from pathlib import Path

source_root = Path(sys.argv[1]).resolve()
poll_interval = float(sys.argv[2])
worker_id = sys.argv[3]
if not math.isfinite(poll_interval) or not 0.05 <= poll_interval <= 3600.0:
    raise SystemExit(1)
if not worker_id.strip() or len(worker_id.encode("utf-8")) > 256:
    raise SystemExit(1)

import quant_system
import quant_system.cli
from quant_system.config import load_settings

Path(quant_system.__file__).resolve().relative_to(source_root)
if load_settings().database.auto_migrate:
    raise SystemExit(1)
PY
}

load_connector_env
[[ -d "$ROOT/src/quant_system" ]] || fail "release_source_missing"

case "${QS_DATABASE_AUTO_MIGRATE:-false}" in
  false | FALSE | 0 | no | NO | off | OFF)
    export QS_DATABASE_AUTO_MIGRATE=false
    ;;
  *)
    fail "database_auto_migrate_forbidden"
    ;;
esac

PYTHON="$(resolve_python)"
[[ -x "$PYTHON" ]] || fail "connector_python_unavailable"
POLL_INTERVAL="${QS_AGENT_V02_CONNECTOR_POLL_INTERVAL_SECONDS:-5}"
WORKER_ID="${QS_AGENT_V02_CONNECTOR_WORKER_ID:-agent-v02-connector-1}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

validate_release_runtime || fail "release_runtime_config_invalid"

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    printf 'connector_ready=true release_root=%s python=%s\n' "$ROOT" "$PYTHON"
    exit 0
    ;;
  "")
    [[ "$#" -eq 0 ]] || fail "unexpected_arguments"
    ;;
  *)
    fail "unexpected_arguments"
    ;;
esac

install -d -m 700 "$RUNTIME_DIR" "$LOG_DIR"
cd "$ROOT"
exec "$PYTHON" -m quant_system.cli hermes connector-worker \
  --mode supervised_dispatch \
  --poll-interval-seconds "$POLL_INTERVAL" \
  --reconcile-limit 100 \
  --worker-id "$WORKER_ID"
