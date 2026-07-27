#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "agent_v02_ops_error=python_not_executable" >&2
  exit 78
fi

export PYTHONPATH="$ROOT/src"
exec "$PYTHON" -m quant_system.ops.release_ops backup-restore \
  "$@" \
  --repository-root "$ROOT"
