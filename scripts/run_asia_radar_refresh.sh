#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "asia_radar_refresh_error=missing_venv_python" >&2
  exit 78
fi

cd "$ROOT"
exec "$VENV_PY" -m quant_system.cli data asia-radar-refresh
