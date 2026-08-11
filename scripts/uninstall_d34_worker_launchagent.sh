#!/usr/bin/env bash
set -euo pipefail

LABEL="com.aiquant.d34-worker"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-/bin/launchctl}"

[[ -x "$LAUNCHCTL" ]] || exit 78

bootout_if_loaded() {
  local service="$1"
  local output status
  if output="$("$LAUNCHCTL" bootout "$service" 2>&1)"; then
    [[ -z "$output" ]] || printf '%s\n' "$output"
    return 0
  else
    status=$?
  fi
  if [[ "$status" -eq 3 && "$output" == "Boot-out failed: 3: No such process" ]] ||
    [[ "$status" -eq 113 && "$output" == "Boot-out failed: 113: Could not find specified service" ]]; then
    echo "already_unloaded=$service"
    return 0
  fi
  [[ -z "$output" ]] || printf '%s\n' "$output" >&2
  return "$status"
}

bootout_if_loaded "$DOMAIN/$LABEL"
rm -f "$TARGET"
echo "removed=$TARGET"
