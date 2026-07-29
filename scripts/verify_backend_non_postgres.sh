#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "backend_non_postgres_error=$1" >&2
  exit 78
}

seen_describe=0
seen_self_test=0
seen_output_dir=0
seen_expected_commit=0
for argument in "$@"; do
  case "$argument" in
    --node | --node=* | --repository-root | --repository-root=* | --uv | --uv=*)
      fail "public_argument_forbidden"
      ;;
    --describe)
      seen_describe=$((seen_describe + 1))
      [[ "$seen_describe" -eq 1 ]] || fail "public_argument_duplicate"
      ;;
    --self-test)
      seen_self_test=$((seen_self_test + 1))
      [[ "$seen_self_test" -eq 1 ]] || fail "public_argument_duplicate"
      ;;
    --output-dir | --output-dir=*)
      seen_output_dir=$((seen_output_dir + 1))
      [[ "$seen_output_dir" -eq 1 ]] || fail "public_argument_duplicate"
      ;;
    --expected-commit | --expected-commit=*)
      seen_expected_commit=$((seen_expected_commit + 1))
      [[ "$seen_expected_commit" -eq 1 ]] || fail "public_argument_duplicate"
      ;;
  esac
done

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
HELPER="$SCRIPT_DIR/backend_non_postgres_gate.py"

[[ -f "$HELPER" && ! -L "$HELPER" ]] || fail "helper_not_found"
if PYTHON311="$(command -v python3.11)"; then
  :
else
  fail "python3_11_not_found"
fi
[[ -n "$PYTHON311" && -x "$PYTHON311" ]] || fail "python3_11_not_found"
if UV_BIN="$(command -v uv)"; then
  :
else
  fail "uv_not_found"
fi
[[ -n "$UV_BIN" && -x "$UV_BIN" ]] || fail "uv_not_found"
if NODE_BIN="$(command -v node)"; then
  :
else
  fail "node_not_found"
fi
[[ -n "$NODE_BIN" && -x "$NODE_BIN" ]] || fail "node_not_found"

exec /usr/bin/env -i \
  HOME="/tmp" \
  LANG="C" \
  LC_ALL="C" \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE="1" \
  TMPDIR="/tmp" \
  "$PYTHON311" -I -B "$HELPER" \
  --repository-root "$ROOT" \
  --uv "$UV_BIN" \
  --node "$NODE_BIN" \
  --public-entrypoint "$0" \
  --public-argv "$@"
