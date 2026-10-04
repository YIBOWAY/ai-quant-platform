#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"

fail() {
  echo "d34_research_worker_config_error=$1" >&2
  exit 78
}

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "backend_env_not_regular"
metadata="$(stat -f "%u %Lp" "$ENV_FILE")" || fail "backend_env_stat_failed"
read -r owner mode <<<"$metadata"
[[ "$owner" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
[[ "$mode" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export QS_DATABASE_AUTO_MIGRATE=false

PYTHON="${QS_D34_WORKER_PYTHON:-${QS_QUANT_BACKEND_PYTHON:-$ROOT/.venv/bin/python}}"
HQA_ROOT="${QS_D34_HQA_ROOT:-${QS_INTENT_PAYLOAD_HQA_ROOT:-/Users/sunyibo/programs/Hermes-quant-agent}}"
[[ -x "$PYTHON" ]] || fail "python_not_found"
"$PYTHON" -I -B -c \
  'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' \
  >/dev/null 2>&1 || fail "python_must_be_3_11"
[[ -d "$ROOT/src/quant_system" ]] || fail "release_source_missing"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    [[ -d "$HQA_ROOT/hqa" ]] || fail "hqa_source_missing"
    "$PYTHON" -c \
      "from quant_system.d34.research_cli import build_local_research_worker" \
      >/dev/null || fail "release_runtime_import_failed"
    printf 'd34_research_worker_ready=true release_root=%s python=%s hqa_root=%s\n' \
      "$ROOT" "$PYTHON" "$HQA_ROOT"
    exit 0
    ;;
  "")
    ;;
  *)
    fail "unexpected_arguments"
    ;;
esac

umask 077
cd "$ROOT"
exec "$PYTHON" -m quant_system.d34.research_cli \
  --platform-root "$ROOT" \
  --hqa-root "$HQA_ROOT"
