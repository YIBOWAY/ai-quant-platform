#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "python_static_error=$1" >&2
  exit 78
}

seen_describe=0
seen_gate2_receipt=0
seen_output_dir=0
seen_expected_commit=0
for argument in "$@"; do
  case "$argument" in
    --bootstrap-python | --bootstrap-python=* | --public-argv | --public-argv=* | \
      --public-entrypoint | --public-entrypoint=* | --repository-root | \
      --repository-root=*)
      fail "public_argument_forbidden"
      ;;
    --describe)
      seen_describe=$((seen_describe + 1))
      [[ "$seen_describe" -eq 1 ]] || fail "public_argument_duplicate"
      ;;
    --gate2-receipt | --gate2-receipt=*)
      seen_gate2_receipt=$((seen_gate2_receipt + 1))
      [[ "$seen_gate2_receipt" -eq 1 ]] || fail "public_argument_duplicate"
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
HELPER="$SCRIPT_DIR/python_static_gate.py"

[[ -f "$HELPER" && ! -L "$HELPER" ]] || fail "helper_not_found"
if BOOTSTRAP_PYTHON="$(command -v python3.11)"; then
  :
else
  fail "python3_11_not_found"
fi
[[ -n "$BOOTSTRAP_PYTHON" && -x "$BOOTSTRAP_PYTHON" ]] || fail "python3_11_not_found"

exec /usr/bin/env -i \
  HOME="/tmp" \
  LANG="C" \
  LC_ALL="C" \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE="1" \
  TMPDIR="/tmp" \
  "$BOOTSTRAP_PYTHON" -I -B "$HELPER" \
  --repository-root "$ROOT" \
  --bootstrap-python "$BOOTSTRAP_PYTHON" \
  --public-entrypoint "$0" \
  --public-argv "$@"
