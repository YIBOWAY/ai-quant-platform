#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
elif [[ -x "$ROOT/ai-quant/bin/python" ]]; then
  PYTHON_BIN="$ROOT/ai-quant/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "No usable Python interpreter found. Create ai-quant or .venv, or set PYTHON_BIN." >&2
  exit 1
fi

run_step() {
  local name="$1"
  shift
  echo "==> ${name}"
  "$@"
}

run_step "Python version" "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required; run: uv venv ai-quant --python 3.11 && source ai-quant/bin/activate")'
run_step "Ruff" "$PYTHON_BIN" -m ruff check src/quant_system tests
run_step "Pytest" "$PYTHON_BIN" -m pytest -q
run_step "Frontend lint" npm --prefix src/frontend run lint
run_step "Frontend type-check" npm --prefix src/frontend run type-check
run_step "Frontend tests" npm --prefix src/frontend run test

if [[ "${RUN_BUILD:-0}" == "1" ]]; then
  run_step "Frontend build" npm --prefix src/frontend run build
else
  echo "==> Frontend build skipped (set RUN_BUILD=1 when no frontend dev server is running)"
fi
