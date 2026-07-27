#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/src/frontend"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/frontend-next.launchd.log"
ENV_FILE="${QS_AGENT_V02_FRONTEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-frontend.env}"

fail() {
  echo "frontend_config_error=$1" >&2
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

load_frontend_env() {
  local metadata owner mode
  [[ -e "$ENV_FILE" || -L "$ENV_FILE" ]] || fail "frontend_env_missing"
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "frontend_env_not_regular"
  metadata="$(file_owner_and_mode "$ENV_FILE")" || fail "frontend_env_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "frontend_env_wrong_owner"
  [[ "$mode" =~ ^0?600$ ]] || fail "frontend_env_mode_must_be_600"
  set -a
  # The file is a trusted shell dotenv after its owner/type/mode checks.
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

resolve_next() {
  local candidate
  for candidate in \
    "${QS_QUANT_FRONTEND_NEXT_BIN:-}" \
    "$FRONTEND_DIR/node_modules/.bin/next" \
    "$MAIN_ROOT/src/frontend/node_modules/.bin/next"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  fail "next_executable_not_found"
}

resolve_node() {
  local candidate path_node=""
  if path_node="$(command -v node 2>/dev/null)"; then
    :
  fi
  for candidate in \
    "${QS_QUANT_FRONTEND_NODE_BIN:-}" \
    "$path_node" \
    "$HOME/.local/bin/node" \
    "/opt/homebrew/bin/node" \
    "/usr/local/bin/node" \
    "/usr/bin/node"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  fail "node_executable_not_found"
}

load_frontend_env
MAIN_ROOT="$(discover_main_root)"
[[ -d "$MAIN_ROOT" ]] || fail "main_repo_missing"
[[ -f "$FRONTEND_DIR/.next/BUILD_ID" ]] || fail "release_build_missing"
NEXT_BIN="$(resolve_next)"
NODE_BIN="$(resolve_node)"
MAIN_NODE_MODULES="$MAIN_ROOT/src/frontend/node_modules"
if [[ -d "$MAIN_NODE_MODULES" ]]; then
  export NODE_PATH="$MAIN_NODE_MODULES${NODE_PATH:+:$NODE_PATH}"
fi
export NEXT_PUBLIC_QUANT_API_BASE_URL="${NEXT_PUBLIC_QUANT_API_BASE_URL:-http://127.0.0.1:8765}"

case "${QS_HERMES_CHAT_ENABLED:-false}" in
  true | TRUE | 1 | yes | YES | on | ON)
    export QS_HERMES_CHAT_ENABLED=true
    ;;
  *)
    fail "hermes_chat_must_be_explicitly_enabled"
    ;;
esac

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    "$NODE_BIN" "$NEXT_BIN" --version >/dev/null ||
      fail "next_runtime_check_failed"
    printf 'frontend_ready=true release_root=%s node=%s next=%s\n' \
      "$ROOT" "$NODE_BIN" "$NEXT_BIN"
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
cd "$FRONTEND_DIR"

exec >>"$LOG_PATH" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting frontend-next"
exec "$NODE_BIN" "$NEXT_BIN" start -H 127.0.0.1 -p 3001
