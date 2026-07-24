#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/paper-strategy-sleeves.log"
PYTHON="${QS_PAPER_STRATEGY_PYTHON:-$ROOT/ai-quant/bin/python}"
COMMAND="${1:-ops-status}"

if [[ $# -gt 0 ]]; then
  shift
fi

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi

cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

case "$COMMAND" in
  generate-due-signals)
    CMD_ARGS=(paper strategies generate-due-signals)
    ;;
  execute-due)
    CMD_ARGS=(paper strategies execute-due)
    ;;
  ops-status)
    CMD_ARGS=(paper strategies ops-status --format json)
    ;;
  *)
    echo "unknown paper strategy sleeves command: $COMMAND" | tee -a "$LOG_PATH"
    exit 64
    ;;
esac

{
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] command=$COMMAND args=$*"
  "$PYTHON" -m quant_system.cli "${CMD_ARGS[@]}" "$@"
} 2>&1 | tee -a "$LOG_PATH"
