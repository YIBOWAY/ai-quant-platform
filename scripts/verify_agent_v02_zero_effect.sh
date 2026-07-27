#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
HQA_ROOT="$(cd "$ROOT/../Hermes-quant-agent" && pwd)"
ENV_FILE="$ROOT/data/_runtime/agent-v0.2-backend.env"

fail() {
  echo "agent_v02_ops_error=$1" >&2
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

if [[ ! -x "$PYTHON" ]]; then
  fail "python_not_executable"
fi
if [[ ! -d "$HQA_ROOT/hqa" ]]; then
  fail "hqa_release_root_required"
fi
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "backend_env_not_private_regular"
read -r ENV_OWNER ENV_MODE <<<"$(file_owner_and_mode "$ENV_FILE")"
[[ "$ENV_OWNER" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
[[ "$ENV_MODE" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"

set -a
# The owner-only environment is evaluated without allowing helper output into evidence.
# shellcheck disable=SC1090
if ! source "$ENV_FILE" >/dev/null 2>&1; then
  set +a
  fail "backend_env_load_failed"
fi
set +a

case "${QS_DATABASE_AUTO_MIGRATE:-false}" in
  false | FALSE | 0 | no | NO | off | OFF)
    export QS_DATABASE_AUTO_MIGRATE=false
    ;;
  *)
    fail "database_auto_migrate_forbidden"
    ;;
esac

export QS_AGENT_V02_RELEASE_PLATFORM_RUNTIME_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src"
exec "$PYTHON" -m quant_system.ops.release_ops zero-effect \
  "$@" \
  --repository-root "$ROOT" \
  --hqa-root "$HQA_ROOT"
