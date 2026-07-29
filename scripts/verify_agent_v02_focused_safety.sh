#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "agent_v02_ops_error=$1" >&2
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

path_has_symlink_component() {
  local candidate="$1"
  local component
  local current=""
  local remainder="${candidate#/}"

  while [[ -n "$remainder" ]]; do
    if [[ "$remainder" == */* ]]; then
      component="${remainder%%/*}"
      remainder="${remainder#*/}"
    else
      component="$remainder"
      remainder=""
    fi
    [[ -z "$component" ]] && continue
    current="$current/$component"
    [[ -L "$current" ]] && return 0
  done
  return 1
}

path_is_canonical_absolute() {
  local candidate="$1"
  [[ "$candidate" == /* && "$candidate" != "/" && "$candidate" != */ ]] ||
    return 1
  case "$candidate" in
    *//* | */./* | */../* | */. | */..)
      return 1
      ;;
  esac
  return 0
}

require_safe_owned_mode() {
  local path="$1"
  local label="$2"
  local metadata
  local mode
  local owner
  local permissions

  metadata="$(file_owner_and_mode "$path")" || fail "${label}_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(id -u)" ]] || fail "${label}_wrong_owner"
  [[ "$mode" =~ ^0?[0-7]{3}$ ]] || fail "${label}_mode_invalid"
  permissions="${mode#0}"
  case "${permissions:1:1}" in
    2 | 3 | 6 | 7)
      fail "${label}_unsafe_mode"
      ;;
  esac
  case "${permissions:2:1}" in
    2 | 3 | 6 | 7)
      fail "${label}_unsafe_mode"
      ;;
  esac
}

require_safe_regular_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" && ! -L "$path" ]] || fail "${label}_unsafe"
  require_safe_owned_mode "$path" "$label"
}

require_safe_directory() {
  local path="$1"
  local label="$2"
  [[ -d "$path" && ! -L "$path" ]] || fail "${label}_unsafe"
  require_safe_owned_mode "$path" "$label"
}

require_empty_output_path() {
  local path="$1"
  local label="$2"
  local parent

  path_is_canonical_absolute "$path" || fail "focused_safety_path_not_canonical"
  path_has_symlink_component "$path" && fail "${label}_unsafe"
  parent="$(dirname "$path")"
  require_safe_directory "$parent" "${label}_parent"
  if [[ -e "$path" || -L "$path" ]]; then
    require_safe_directory "$path" "$label"
    [[ -z "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
      fail "${label}_must_be_empty"
  fi
}

export PATH="/usr/bin:/bin"

[[ "$#" -eq 4 ]] || fail "focused_safety_arguments_invalid"
[[ "$1" == "--python" && "$3" == "--basetemp" ]] ||
  fail "focused_safety_arguments_invalid"

PYTHON="$2"
BASETEMP="$4"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ ! -L "$SCRIPT_SOURCE" ]] || fail "focused_safety_script_unsafe"
if [[ "$SCRIPT_SOURCE" == /* ]]; then
  SCRIPT_SOURCE_ABSOLUTE="$SCRIPT_SOURCE"
else
  SCRIPT_SOURCE_ABSOLUTE="$(pwd -L)/$SCRIPT_SOURCE"
fi
path_has_symlink_component "$SCRIPT_SOURCE_ABSOLUTE" &&
  fail "focused_safety_script_unsafe"
SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SCRIPT_SOURCE")"
[[ "$SCRIPT_PATH" == "$ROOT/scripts/verify_agent_v02_focused_safety.sh" ]] ||
  fail "focused_safety_script_not_authoritative"
require_safe_regular_file "$SCRIPT_PATH" "focused_safety_script"
[[ -x "$SCRIPT_PATH" ]] || fail "focused_safety_script_not_executable"
require_safe_directory "$ROOT" "focused_safety_release_root"
require_safe_directory "$SCRIPT_DIR" "focused_safety_scripts_directory"
require_safe_directory "$ROOT/tests" "focused_safety_tests_directory"

SELECTORS=(
  tests/test_api_safety.py
  tests/test_frontend_paper_replay_safety.py
  tests/test_hermes_effective_release_gate.py
  tests/test_hermes_release_authority.py
  tests/test_release_authority_hardening.py
  tests/test_release_authority_projection.py
  tests/test_command_approval_decide.py
  tests/test_approval_release_v7b.py
  tests/test_approval_observe_v7d.py
  tests/test_production_run_control_saga.py
  tests/test_agent_v02_zero_effect_hardening.py
  tests/test_agent_v02_restart_live_settings.py
  tests/test_agent_v02_restart_release_authority.py
  tests/test_gate_surfaces_v7e.py
  tests/test_paper_gate_authority.py
  tests/test_paper_run_attestation.py
  tests/test_api_paper.py
  tests/test_hermes_run_control_client.py
  tests/test_zero_effect_switch_scope.py
  tests/test_zero_effect_switch_independence.py
)

path_is_canonical_absolute "$PYTHON" ||
  fail "focused_safety_path_not_canonical"
path_is_canonical_absolute "$BASETEMP" ||
  fail "focused_safety_path_not_canonical"
[[ "$PYTHON" == "$ROOT/.venv/"* ]] || fail "python_must_be_release_local"
path_has_symlink_component "$PYTHON" && fail "python_unsafe"
require_safe_regular_file "$PYTHON" "python"
[[ -x "$PYTHON" ]] || fail "python_not_executable"
PYTHON_DIRECTORY="$(dirname "$PYTHON")"
while [[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ||
  "$PYTHON_DIRECTORY" == "$ROOT/.venv/"* ]]; do
  require_safe_directory "$PYTHON_DIRECTORY" "python_directory"
  [[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ]] && break
  PYTHON_DIRECTORY="$(dirname "$PYTHON_DIRECTORY")"
done
[[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ]] ||
  fail "python_must_be_release_local"

case "$BASETEMP" in
  "$ROOT" | "$ROOT"/*)
    fail "basetemp_must_be_outside_release_checkout"
    ;;
esac
require_empty_output_path "$BASETEMP" "basetemp"
PYCACHE_ROOT="${BASETEMP}.pycache"
require_empty_output_path "$PYCACHE_ROOT" "pycache"

for selector in "${SELECTORS[@]}"; do
  path_has_symlink_component "$ROOT/$selector" &&
    fail "focused_safety_selector_unsafe"
  require_safe_regular_file "$ROOT/$selector" "focused_safety_selector"
done

cd "$ROOT"
umask 077
export PATH="$(dirname "$PYTHON"):/usr/bin:/bin"
unset \
  COVERAGE_PROCESS_START \
  LLM_API_KEY \
  LLM_MODEL \
  OPENAI_API_KEY \
  PYTEST_ADDOPTS \
  PYTEST_PLUGINS \
  PYTHONHOME \
  PYTHONPATH \
  PYTHONSTARTUP \
  PYTHONWARNINGS \
  QS_LLM_PROVIDER
export PYTHONNOUSERSITE=1
export PYTHONPYCACHEPREFIX="$PYCACHE_ROOT"
export QS_DATABASE_AUTO_MIGRATE=false
export QS_DATABASE_ENABLED=false
export QS_DEFAULT_DATA_PROVIDER=sample
export QS_FUTU_ENABLED=false
export QS_KILL_SWITCH=true
export QS_LIVE_TRADING_ENABLED=false

exec "$PYTHON" -m pytest -q "--basetemp=$BASETEMP" "${SELECTORS[@]}"
