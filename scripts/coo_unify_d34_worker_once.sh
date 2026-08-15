#!/usr/bin/env bash
# One isolation D-34 cycle against quantplatform_coo. Never uses live LaunchAgent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAIN_PLATFORM="${QS_MAIN_PLATFORM_ROOT:-/Users/sunyibo/programs/ai-quant-platform}"
DATA_DIR="$ROOT/data/_runtime/coo-unify-preview"
LOG_DIR="$DATA_DIR/logs"
PYTHON="${QS_QUANT_BACKEND_PYTHON:-$MAIN_PLATFORM/.venv/bin/python}"
HQA_ROOT="${QS_D34_HQA_ROOT:-/Users/sunyibo/programs/Hermes-quant-agent}"
ENV_FILE="${QS_D34_ENV_FILE:-/Users/sunyibo/.config/hqa/d34.env}"

fail() {
  echo "coo_unify_d34_worker_error=$1" >&2
  exit 78
}

[[ -x "$PYTHON" ]] || fail "python_not_found"
[[ -d "$HQA_ROOT/hqa" ]] || fail "hqa_source_missing"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "d34_env_file_required"

user="$(docker exec quantplatform-db printenv POSTGRES_USER)"
pass="$(docker exec quantplatform-db printenv POSTGRES_PASSWORD)"
db_url="postgresql://${user}:${pass}@127.0.0.1:5432/quantplatform_coo"

mkdir -p "$LOG_DIR" "$DATA_DIR/d34/cache"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export QS_DATA_DIR="$DATA_DIR"
export QS_DATABASE_ENABLED=true
export QS_DATABASE_URL="$db_url"
export QS_DATABASE_AUTO_MIGRATE=false
export QS_LIVE_TRADING_ENABLED=false
export QS_PAPER_TRADING=true
export QS_PAPER_OBSERVATION_ENABLED=true
export QS_PAPER_ACCOUNT_DB_MODE=canonical
export QS_KILL_SWITCH=true
export QS_DRY_RUN=true
export QS_FUTU_ENABLED=true
export QS_D34_ENV_FILE="$ENV_FILE"

"$PYTHON" "$ROOT/scripts/coo_unify_seed_paper_authority.py"

if [[ "${1:-}" == "--wait-window" ]]; then
  "$PYTHON" - <<'PY'
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import time as pytime
tz = ZoneInfo("Asia/Shanghai")
now = datetime.now(tz)
open_at = datetime.combine(now.date(), time(6, 0), tzinfo=tz)
if now < open_at:
    delay = (open_at - now).total_seconds()
else:
    delay = 0
print(f"window_wait_seconds={int(delay)} now={now.isoformat()}", flush=True)
if delay > 0:
    pytime.sleep(delay)
PY
fi

cd "$ROOT"
exec "$PYTHON" -m quant_system.cli d34 worker-once \
  --platform-root "$ROOT" \
  --hqa-root "$HQA_ROOT" \
  --workspace-root "$DATA_DIR/d34" \
  --cache-root "$DATA_DIR/d34/cache" \
  --worker-id hqa-d34-coo-unify
