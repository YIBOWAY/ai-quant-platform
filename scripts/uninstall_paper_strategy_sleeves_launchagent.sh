#!/usr/bin/env bash
set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
  com.aiquant.paper-sleeves.ops-status
  com.aiquant.paper-sleeves.signals
  com.aiquant.paper-sleeves.execute-due
)

for LABEL in "${LABELS[@]}"; do
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  if [[ -f "$TARGET" ]]; then
    launchctl bootout gui/$(id -u) "$TARGET" >/dev/null 2>&1 || true
    rm -f "$TARGET"
    echo "removed=$TARGET"
  else
    echo "missing=$TARGET"
  fi
done
