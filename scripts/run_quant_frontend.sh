#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/src/frontend"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/frontend-next.launchd.log"

fail() {
  echo "frontend_config_error=$1" >&2
  exit 78
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

MAIN_ROOT="$(discover_main_root)"
[[ -d "$MAIN_ROOT" ]] || fail "main_repo_missing"
[[ -f "$FRONTEND_DIR/.next/BUILD_ID" ]] || fail "release_build_missing"
NEXT_BIN="$(resolve_next)"
MAIN_NODE_MODULES="$MAIN_ROOT/src/frontend/node_modules"
if [[ -d "$MAIN_NODE_MODULES" ]]; then
  export NODE_PATH="$MAIN_NODE_MODULES${NODE_PATH:+:$NODE_PATH}"
fi
export NEXT_PUBLIC_QUANT_API_BASE_URL="${NEXT_PUBLIC_QUANT_API_BASE_URL:-http://127.0.0.1:8765}"

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    "$NEXT_BIN" --version >/dev/null || fail "next_runtime_check_failed"
    printf 'frontend_ready=true release_root=%s next=%s\n' "$ROOT" "$NEXT_BIN"
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

exec > >(tee -a "$LOG_PATH") 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting frontend-next"
exec "$NEXT_BIN" start -H 127.0.0.1 -p 3001
