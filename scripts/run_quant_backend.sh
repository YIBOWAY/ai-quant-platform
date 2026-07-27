#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/backend-api.launchd.log"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"

fail() {
  echo "backend_config_error=$1" >&2
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

discover_main_root() {
  local common_dir
  if [[ -n "${QS_MAIN_REPO_ROOT:-}" ]]; then
    printf '%s\n' "$QS_MAIN_REPO_ROOT"
    return
  fi
  common_dir="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ||
    fail "main_repo_not_discoverable"
  if [[ "$(basename "$common_dir")" == ".git" ]]; then
    dirname "$common_dir"
  else
    printf '%s\n' "$ROOT"
  fi
}

resolve_python() {
  local candidate
  for candidate in \
    "${QS_QUANT_BACKEND_PYTHON:-}" \
    "$ROOT/ai-quant/bin/python" \
    "$MAIN_ROOT/ai-quant/bin/python" \
    "$MAIN_ROOT/.venv/bin/python"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  if candidate="$(command -v python3 2>/dev/null)"; then
    :
  elif candidate="$(command -v python 2>/dev/null)"; then
    :
  else
    fail "python_not_found"
  fi
  printf '%s\n' "$candidate"
}

load_backend_env
MAIN_ROOT="$(discover_main_root)"
[[ -d "$MAIN_ROOT" ]] || fail "main_repo_missing"
PYTHON="$(resolve_python)"
[[ -d "$ROOT/src/quant_system" ]] || fail "release_source_missing"

case "${QS_DATABASE_AUTO_MIGRATE:-false}" in
  false | FALSE | 0 | no | NO | off | OFF)
    export QS_DATABASE_AUTO_MIGRATE=false
    ;;
  *)
    fail "database_auto_migrate_forbidden"
    ;;
esac

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export QS_API_BIND_ADDRESS=127.0.0.1

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    "$PYTHON" -c "import quant_system.cli" >/dev/null ||
      fail "release_runtime_import_failed"
    printf 'backend_ready=true release_root=%s python=%s\n' "$ROOT" "$PYTHON"
    exit 0
    ;;
  "")
    ;;
  *)
    fail "unexpected_arguments"
    ;;
esac

umask 077
install -d -m 700 "$LOG_DIR"
if [[ -e "$LOG_PATH" || -L "$LOG_PATH" ]]; then
  [[ -f "$LOG_PATH" && ! -L "$LOG_PATH" ]] || fail "unsafe_log_path"
else
  touch "$LOG_PATH"
fi
chmod 600 "$LOG_PATH"
cd "$ROOT"

exec >>"$LOG_PATH" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting backend-api"
# Equivalent to: quant-system serve --host 127.0.0.1 --port 8765
exec "$PYTHON" -m quant_system.cli serve --host 127.0.0.1 --port 8765
