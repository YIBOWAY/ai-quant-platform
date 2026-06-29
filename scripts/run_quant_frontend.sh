#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/src/frontend"
LOG_DIR="$ROOT/data/_runtime/logs"
LOG_PATH="$LOG_DIR/frontend-next.launchd.log"

mkdir -p "$LOG_DIR"

if [[ ! -d "$FRONTEND_DIR/.next" ]]; then
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] frontend build missing"
    echo "Stop any dev server, then run: npm --prefix src/frontend run build"
  } | tee -a "$LOG_PATH"
  exit 78
fi

cd "$FRONTEND_DIR"
export NEXT_PUBLIC_QUANT_API_BASE_URL="${NEXT_PUBLIC_QUANT_API_BASE_URL:-http://127.0.0.1:8765}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting frontend-next" | tee -a "$LOG_PATH"
npm run start -- -H 127.0.0.1 -p 3001 2>&1 |
  tee -a "$LOG_PATH"
