#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"

fail() {
  echo "factor_automation_driver_error=$1" >&2
  exit 78
}

COMMAND=(run-once)
if [[ "$#" -eq 0 ]]; then
  :
elif [[ "$#" -eq 3 && "$1" == "enqueue" && "$2" == "--request-file" && -n "$3" ]]; then
  COMMAND=("$@")
else
  fail "operation_invalid"
fi

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "backend_env_not_regular"
metadata="$(stat -f '%u %Lp' "$ENV_FILE" 2>/dev/null || stat -c '%u %a' "$ENV_FILE")" ||
  fail "backend_env_stat_failed"
read -r owner mode <<<"$metadata"
[[ "$owner" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
[[ "$mode" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

HQA_ROOT="${QS_INTENT_PAYLOAD_HQA_ROOT:-}"
HQA_PYTHON="${QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE:-}"
[[ -d "$HQA_ROOT/hqa" ]] || fail "hqa_root_missing"
[[ -x "$HQA_PYTHON" ]] || fail "hqa_python_missing"
case "$HQA_ROOT:$HQA_PYTHON" in
  *"/.codex/"* | *"/.claude/"* | *"/ChatGPT.app/"*)
    fail "transient_ai_tool_runtime_forbidden"
    ;;
esac

export HQA_AIQP_DIR="$ROOT"
export HQA_QUANT_SYSTEM_BIN="$ROOT/ai-quant/bin/quant-system"
cd "$HQA_ROOT"
exec "$HQA_PYTHON" -m hqa.factor_automation_cli "${COMMAND[@]}"
