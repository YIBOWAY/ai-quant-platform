#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${PYTHON_BIN:-python}"

run_step() {
  local name="$1"
  shift
  echo "==> ${name}"
  "$@"
}

run_step "Python version" "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required; run: conda activate ai-quant")'
run_step "Ruff" ruff check src/quant_system tests
run_step "Pytest" "$PYTHON_BIN" -m pytest -q
run_step "Frontend lint" npm --prefix src/frontend run lint
run_step "Frontend type-check" npm --prefix src/frontend run type-check
run_step "Frontend tests" npm --prefix src/frontend run test

if [[ "${RUN_BUILD:-0}" == "1" ]]; then
  run_step "Frontend build" npm --prefix src/frontend run build
else
  echo "==> Frontend build skipped (set RUN_BUILD=1 when no frontend dev server is running)"
fi
