#!/usr/bin/env bash
set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
if [[ -n "${QS_LAUNCHCTL_BIN:-}" ]]; then
  LAUNCHCTL="$QS_LAUNCHCTL_BIN"
elif command -v launchctl >/dev/null 2>&1; then
  LAUNCHCTL="$(command -v launchctl)"
else
  LAUNCHCTL=""
fi

if [[ -z "$LAUNCHCTL" || ! -x "$LAUNCHCTL" ]]; then
  echo "stack_uninstall_error=launchctl_not_found" >&2
  exit 78
fi

LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
)
DOMAIN="gui/$(id -u)"

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

for LABEL in "${LABELS[@]}"; do
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  bootout_if_loaded "$DOMAIN/$LABEL"
  if [[ -e "$TARGET" || -L "$TARGET" ]]; then
    rm -f "$TARGET"
    echo "removed=$TARGET"
  else
    echo "missing=$TARGET"
  fi
done
