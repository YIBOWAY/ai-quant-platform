#!/usr/bin/env bash
# Observation-day-only driver: the digest-gated paper cycle for hung sleeves.
#
# This script deliberately does NOT honor QS_D34_WORKER_ENABLED and never runs
# the research factory (no jobs, mandates, canary activation, docker, or LLM).
# Load its LaunchAgent only when the owner has hung a digest-bound candidate
# on live; `launchctl unload` stops observation without touching research.
#
# Accountability: the CLI prints its own hqa.d34_paper_cycle/v1 receipt for
# expected outcomes; this wrapper appends a hqa.d34_paper_cycle_failure/v1
# receipt for crashes, config errors, and signals so a dead run is never
# silent in the launchd log (2026-08-20: a DatabaseUnavailable crash was).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${QS_AGENT_V02_BACKEND_ENV_FILE:-$ROOT/data/_runtime/agent-v0.2-backend.env}"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\r'/}"
  printf '%s' "$s"
}

emit_failure_receipt() {
  local outcome="$1" code="$2" detail="$3"
  # Keys are printed in sorted order so the line is canonical JSON.
  printf '{"contract":"hqa.d34_paper_cycle_failure/v1","detail":"%s","exit_code":%d,"finished_at":"%s","outcome":"%s","pid":%d,"started_at":"%s"}\n' \
    "$(json_escape "$detail")" \
    "$code" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$outcome" \
    "$$" \
    "$STARTED_AT"
}

child=""
run_log=""
on_signal() {
  local code="$1" name="$2"
  if [[ -n "$child" ]]; then
    kill "$child" 2>/dev/null || true
  fi
  if [[ -n "$run_log" ]]; then
    cat "$run_log"
    rm -f "$run_log"
  fi
  emit_failure_receipt signal "$code" "$name"
  exit "$code"
}
trap 'on_signal 143 SIGTERM' TERM
trap 'on_signal 130 SIGINT' INT

fail() {
  echo "d34_paper_cycle_config_error=$1" >&2
  emit_failure_receipt config_error 78 "$1"
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

if [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]]; then
  metadata="$(file_owner_and_mode "$ENV_FILE")" || fail "backend_env_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "backend_env_wrong_owner"
  [[ "$mode" =~ ^0?600$ ]] || fail "backend_env_mode_must_be_600"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

resolve_python() {
  local candidate
  for candidate in \
    "${QS_D34_WORKER_PYTHON:-}" \
    "${QS_QUANT_BACKEND_PYTHON:-}" \
    "$ROOT/.venv/bin/python" \
    "$ROOT/ai-quant/bin/python"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  fail "python_not_found"
}

PYTHON="$(resolve_python)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Run in the background and wait: bash defers signal traps while a foreground
# child runs, but wait is interruptible, so SIGTERM/SIGINT still get receipts.
run_log="$(mktemp "${TMPDIR:-/tmp}/d34-paper-cycle.XXXXXX")"
"$PYTHON" -m quant_system.cli d34 paper-cycle "$@" >"$run_log" 2>&1 &
child=$!
status=0
wait "$child" || status=$?
child=""
cat "$run_log"
detail="$(tail -n 20 "$run_log")"
rm -f "$run_log"
run_log=""
if [[ $status -ne 0 ]]; then
  # The CLI prints no receipt on an unexpected crash; append the wrapper's.
  emit_failure_receipt crash "$status" "$detail"
fi
exit "$status"
