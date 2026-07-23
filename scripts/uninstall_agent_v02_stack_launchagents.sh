#!/usr/bin/env bash
set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-$(command -v launchctl || true)}"

if [[ -z "$LAUNCHCTL" || ! -x "$LAUNCHCTL" ]]; then
  echo "stack_uninstall_error=launchctl_not_found" >&2
  exit 78
fi

LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
)
DOMAIN="gui/$(id -u)"

for LABEL in "${LABELS[@]}"; do
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  if [[ -e "$TARGET" || -L "$TARGET" ]]; then
    rm -f "$TARGET"
    echo "removed=$TARGET"
  else
    echo "missing=$TARGET"
  fi
done
