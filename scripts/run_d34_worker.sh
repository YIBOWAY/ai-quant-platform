#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"

fail() {
  echo "d34_worker_config_error=$1" >&2
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
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "backend_env_not_regular"
  metadata="$(file_owner_and_mode "$ENV_FILE")" || fail "backend_env_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
  [[ "$mode" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"
  set -a
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
    "${QS_D34_WORKER_PYTHON:-}" \
    "${QS_QUANT_BACKEND_PYTHON:-}" \
    "$ROOT/ai-quant/bin/python" \
    "$MAIN_ROOT/ai-quant/bin/python" \
    "$MAIN_ROOT/.venv/bin/python"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  fail "python_not_found"
}

load_backend_env
MAIN_ROOT="$(discover_main_root)"
PYTHON="$(resolve_python)"
HQA_ROOT="${QS_D34_HQA_ROOT:-${QS_INTENT_PAYLOAD_HQA_ROOT:-/Users/sunyibo/programs/Hermes-quant-agent}}"
D34_WORKER_ENABLED="${QS_D34_WORKER_ENABLED:-false}"

[[ -d "$ROOT/src/quant_system" ]] || fail "release_source_missing"
[[ -d "$HQA_ROOT/hqa" ]] || fail "hqa_source_missing"
case "$ROOT:$PYTHON:$HQA_ROOT" in
  *"/.codex/"* | *"/.claude/"* | *"/ChatGPT.app/"*)
    fail "transient_ai_tool_runtime_forbidden"
    ;;
esac
case "${QS_DATABASE_AUTO_MIGRATE:-false}" in
  false | FALSE | 0 | no | NO | off | OFF)
    export QS_DATABASE_AUTO_MIGRATE=false
    ;;
  *)
    fail "database_auto_migrate_forbidden"
    ;;
esac

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    "$PYTHON" -c "from quant_system.d34.cli import build_local_worker" >/dev/null ||
      fail "release_runtime_import_failed"
    printf 'd34_worker_ready=true enabled=%s release_root=%s python=%s hqa_root=%s\n' \
      "$D34_WORKER_ENABLED" "$ROOT" "$PYTHON" "$HQA_ROOT"
    exit 0
    ;;
  "")
    ;;
  *)
    fail "unexpected_arguments"
    ;;
esac

case "$D34_WORKER_ENABLED" in
  true)
    ;;
  false)
    printf 'state=disabled code=d34_worker_disabled\n'
    exit 0
    ;;
  *)
    fail "d34_worker_enabled_must_be_true_or_false"
    ;;
esac

umask 077
install -d -m 700 "$ROOT/data/_runtime/d34" "$ROOT/data/_runtime/d34/cache"
cd "$ROOT"
exec "$PYTHON" -m quant_system.cli d34 worker-once \
  --platform-root "$ROOT" \
  --hqa-root "$HQA_ROOT" \
  --workspace-root "$ROOT/data/_runtime/d34" \
  --cache-root "$ROOT/data/_runtime/d34/cache"
