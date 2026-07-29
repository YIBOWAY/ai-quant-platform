#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT/scripts/launchd"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/data/_runtime/logs"
if [[ -n "${QS_LAUNCHCTL_BIN:-}" ]]; then
  LAUNCHCTL="$QS_LAUNCHCTL_BIN"
elif command -v launchctl >/dev/null 2>&1; then
  LAUNCHCTL="$(command -v launchctl)"
else
  LAUNCHCTL=""
fi
if [[ -n "${QS_PLUTIL_BIN:-}" ]]; then
  PLUTIL="$QS_PLUTIL_BIN"
elif command -v plutil >/dev/null 2>&1; then
  PLUTIL="$(command -v plutil)"
else
  PLUTIL=""
fi
LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS=5
LAUNCHCTL_BOOTSTRAP_RETRY_DELAY_SECONDS=0.2

fail() {
  echo "stack_install_error=$1" >&2
  exit 78
}

[[ -n "$LAUNCHCTL" && -x "$LAUNCHCTL" ]] || fail "launchctl_not_found"
[[ -n "$PLUTIL" && -x "$PLUTIL" ]] || fail "plutil_not_found"
[[ "$ROOT" != *"#"* ]] || fail "unsupported_root_character"

bootout_if_loaded() {
  local service="$1"
  local output
  local status

  if output="$("$LAUNCHCTL" bootout "$service" 2>&1)"; then
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  else
    status=$?
  fi
  if [[ "$status" -eq 3 \
    && "$output" == "Boot-out failed: 3: No such process" ]]; then
    echo "already_unloaded=$service"
    return 0
  fi
  if [[ "$status" -eq 113 \
    && "$output" == "Boot-out failed: 113: Could not find specified service" ]]; then
    echo "already_unloaded=$service"
    return 0
  fi
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" >&2
  fi
  return "$status"
}

bootstrap_launchagent() {
  local label="$1"
  local target="$2"
  local attempt=1
  local output
  local status

  while (( attempt <= LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS )); do
    if output="$("$LAUNCHCTL" bootstrap "$DOMAIN" "$target" 2>&1)"; then
      [[ -z "$output" ]] || printf '%s\n' "$output"
      return 0
    else
      status=$?
    fi

    if [[ "$output" != *"Input/output error"* \
      && "$output" != *"input/output error"* \
      && "$output" != *"EIO"* \
      && "$output" != *": 5:"* ]]; then
      [[ -z "$output" ]] || printf '%s\n' "$output" >&2
      return "$status"
    fi

    if (( attempt == LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS )); then
      [[ -z "$output" ]] || printf '%s\n' "$output" >&2
      echo \
        "stack_install_error=launchctl_bootstrap_eio_exhausted label=$label attempts=$attempt" \
        >&2
      return "$status"
    fi

    echo \
      "stack_install_retry=launchctl_bootstrap_eio label=$label attempt=$attempt" \
      >&2
    sleep "$LAUNCHCTL_BOOTSTRAP_RETRY_DELAY_SECONDS"
    attempt=$((attempt + 1))
  done
}

# Fail before changing launchd state when the exact release cannot start.
"$ROOT/scripts/run_quant_backend.sh" --check
"$ROOT/scripts/run_quant_frontend.sh" --check

umask 077
mkdir -p "$LAUNCHD_DIR"
[[ ! -L "$LOG_DIR" ]] || fail "unsafe_log_directory"
install -d -m 700 "$LOG_DIR"

for LOG_NAME in \
  backend-api.launchd.log \
  backend-api.launchd.out.log \
  backend-api.launchd.err.log \
  frontend-next.launchd.log \
  frontend-next.launchd.out.log \
  frontend-next.launchd.err.log; do
  LOG_PATH="$LOG_DIR/$LOG_NAME"
  if [[ ! -e "$LOG_PATH" ]]; then
    touch "$LOG_PATH"
  fi
  [[ -f "$LOG_PATH" && ! -L "$LOG_PATH" ]] || fail "unsafe_log_path"
  chmod 600 "$LOG_PATH"
done

LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
)

ESCAPED_ROOT="${ROOT//\\/\\\\}"
ESCAPED_ROOT="${ESCAPED_ROOT//&/\\&}"
DOMAIN="gui/$(id -u)"

for LABEL in "${LABELS[@]}"; do
  TEMPLATE="$TEMPLATE_DIR/$LABEL.plist.template"
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  [[ -f "$TEMPLATE" ]] || fail "missing_template"

  TEMP="$(mktemp "$LAUNCHD_DIR/.${LABEL}.plist.XXXXXX")"
  trap 'rm -f "$TEMP"' EXIT
  sed "s#__ROOT__#$ESCAPED_ROOT#g" "$TEMPLATE" >"$TEMP"
  "$PLUTIL" -lint "$TEMP" >/dev/null
  chmod 600 "$TEMP"
  mv -f "$TEMP" "$TARGET"
  trap - EXIT

  bootout_if_loaded "$DOMAIN/$LABEL"
  bootstrap_launchagent "$LABEL" "$TARGET"
  echo "installed=$TARGET"
done

echo "launchagents_dir=$LAUNCHD_DIR"
echo "logs=$LOG_DIR"
