#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"
VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "brief_auto_archive_error=missing_venv_python" >&2
  exit 78
fi

fail() {
  echo "brief_auto_archive_error=$1" >&2
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

load_backend_env() {
  local metadata owner mode
  [[ -e "$ENV_FILE" || -L "$ENV_FILE" ]] || fail "backend_env_missing"
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "backend_env_not_regular"
  metadata="$(file_owner_and_mode "$ENV_FILE")" || fail "backend_env_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
  [[ "$mode" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"
  set -a
  # The file is deliberately a trusted shell dotenv: ownership and mode are
  # checked before evaluation, and no value is ever printed.
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

# The archive write goes to the same PostgreSQL the backend uses, so load the
# backend's trusted dotenv (QS_DATABASE_*) exactly like run_quant_backend.sh.
load_backend_env

case "${QS_DATABASE_AUTO_MIGRATE:-false}" in
  false | FALSE | 0 | no | NO | off | OFF)
    export QS_DATABASE_AUTO_MIGRATE=false
    ;;
  *)
    fail "database_auto_migrate_forbidden"
    ;;
esac

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"
exec "$VENV_PY" -m quant_system.cli brief auto-archive
