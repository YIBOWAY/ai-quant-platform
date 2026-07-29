#!/usr/bin/env bash
set -euo pipefail

LABEL="com.aiquant.agent-v02-connector"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ -n "${QS_LAUNCHCTL_BIN:-}" ]]; then
  LAUNCHCTL="$QS_LAUNCHCTL_BIN"
elif command -v launchctl >/dev/null 2>&1; then
  LAUNCHCTL="$(command -v launchctl)"
else
  echo "connector_uninstall_error=launchctl_not_found" >&2
  exit 78
fi
if [[ ! -x "$LAUNCHCTL" ]]; then
  echo "connector_uninstall_error=launchctl_not_found" >&2
  exit 78
fi

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

bootout_if_loaded "$DOMAIN/$LABEL"
rm -f "$TARGET"
echo "removed=$TARGET"
