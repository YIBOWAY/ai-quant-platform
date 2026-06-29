#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/backend-api.launchd.log"
PYTHON="${QS_QUANT_BACKEND_PYTHON:-$ROOT/ai-quant/bin/python}"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || command -v python)"
fi

cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export QS_API_BIND_ADDRESS=127.0.0.1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting backend-api" | tee -a "$LOG_PATH"
# Equivalent to: quant-system serve --host 127.0.0.1 --port 8765
"$PYTHON" -m quant_system.cli serve --host 127.0.0.1 --port 8765 2>&1 |
  tee -a "$LOG_PATH"
