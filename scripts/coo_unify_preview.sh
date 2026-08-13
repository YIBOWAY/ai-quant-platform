#!/usr/bin/env bash
# Isolated Step-1 preview. Never binds :3001/:8765 and never uses quantplatform.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAIN_PLATFORM="${QS_MAIN_PLATFORM_ROOT:-/Users/sunyibo/programs/ai-quant-platform}"
DATA_DIR="$ROOT/data/_runtime/coo-unify-preview"
LOG_DIR="$DATA_DIR/logs"
PID_DIR="$DATA_DIR/pids"
BACKEND_PORT="${COO_UNIFY_BACKEND_PORT:-8876}"
FRONTEND_PORT="${COO_UNIFY_FRONTEND_PORT:-3002}"
PYTHON="${QS_QUANT_BACKEND_PYTHON:-$MAIN_PLATFORM/.venv/bin/python}"
NEXT_BIN="$MAIN_PLATFORM/src/frontend/node_modules/.bin/next"

fail() {
  echo "coo_unify_preview_error=$1" >&2
  exit 78
}

database_url() {
  local user pass
  user="$(docker exec quantplatform-db printenv POSTGRES_USER)"
  pass="$(docker exec quantplatform-db printenv POSTGRES_PASSWORD)"
  printf 'postgresql://%s:%s@127.0.0.1:5432/quantplatform_coo' "$user" "$pass"
}

assert_ports_free() {
  local port
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      fail "port_${port}_already_in_use"
    fi
  done
}

start_backend() {
  mkdir -p "$LOG_DIR" "$PID_DIR" "$DATA_DIR"
  (
    cd "$ROOT"
    export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
    export QS_DATA_DIR="$DATA_DIR"
    export QS_DATABASE_ENABLED=true
    export QS_DATABASE_URL
    QS_DATABASE_URL="$(database_url)"
    export QS_DATABASE_AUTO_MIGRATE=false
    export QS_LIVE_TRADING_ENABLED=false
    export QS_PAPER_TRADING=true
    export QS_PAPER_OBSERVATION_ENABLED=true
    export QS_KILL_SWITCH=true
    export QS_DRY_RUN=true
    export QS_API_BIND_ADDRESS=127.0.0.1
    exec "$PYTHON" -m quant_system.cli serve --host 127.0.0.1 --port "$BACKEND_PORT"
  ) >"$LOG_DIR/backend.log" 2>&1 &
  echo $! >"$PID_DIR/backend.pid"
}

start_frontend() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
  [[ -x "$NEXT_BIN" ]] || fail "next_not_found"
  if [[ ! -e "$ROOT/src/frontend/node_modules" ]]; then
    ln -s "$MAIN_PLATFORM/src/frontend/node_modules" "$ROOT/src/frontend/node_modules"
  fi
  (
    cd "$ROOT/src/frontend"
    export NEXT_PUBLIC_QUANT_API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}"
    export QUANT_API_REWRITE_ORIGIN="http://127.0.0.1:${BACKEND_PORT}"
    exec "$NEXT_BIN" dev -H 127.0.0.1 -p "$FRONTEND_PORT"
  ) >"$LOG_DIR/frontend.log" 2>&1 &
  echo $! >"$PID_DIR/frontend.pid"
}

stop_pid() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  local pid
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.4
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
}

cmd="${1:-start}"
case "$cmd" in
  seed)
    mkdir -p "$DATA_DIR"
    PYTHONPATH="$ROOT/src" \
      QS_DATA_DIR="$DATA_DIR" \
      QS_LIVE_TRADING_ENABLED=false \
      QS_PAPER_TRADING=true \
      QS_PAPER_OBSERVATION_ENABLED=true \
      QS_KILL_SWITCH=true \
      QS_DRY_RUN=true \
      "$PYTHON" "$ROOT/scripts/coo_unify_preview_seed.py" "$DATA_DIR"
    ;;
  start)
    assert_ports_free
    mkdir -p "$DATA_DIR"
    PYTHONPATH="$ROOT/src" \
      QS_DATA_DIR="$DATA_DIR" \
      QS_LIVE_TRADING_ENABLED=false \
      QS_PAPER_TRADING=true \
      QS_PAPER_OBSERVATION_ENABLED=true \
      QS_KILL_SWITCH=true \
      QS_DRY_RUN=true \
      "$PYTHON" "$ROOT/scripts/coo_unify_preview_seed.py" "$DATA_DIR"
    start_backend
    start_frontend
    echo "preview_backend=http://127.0.0.1:${BACKEND_PORT}"
    echo "preview_frontend=http://127.0.0.1:${FRONTEND_PORT}/zh/paper-trading"
    echo "live_untouched=http://127.0.0.1:3001"
    echo "logs=$LOG_DIR"
    ;;
  stop)
    stop_pid frontend
    stop_pid backend
    echo "preview_stopped=true"
    ;;
  *)
    fail "usage_start_stop_or_seed"
    ;;
esac
