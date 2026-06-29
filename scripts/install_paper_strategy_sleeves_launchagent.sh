#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT/scripts/launchd"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/data/_runtime/logs"

mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"

LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
  com.aiquant.paper-sleeves.ops-status
  com.aiquant.paper-sleeves.signals
  com.aiquant.paper-sleeves.execute-due
)

for LABEL in "${LABELS[@]}"; do
  TEMPLATE="$TEMPLATE_DIR/$LABEL.plist.template"
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  if [[ ! -f "$TEMPLATE" ]]; then
    echo "missing template: $TEMPLATE" >&2
    exit 66
  fi
  sed "s#__ROOT__#$ROOT#g" "$TEMPLATE" > "$TARGET"
  chmod 644 "$TARGET"
  launchctl bootout gui/$(id -u) "$TARGET" >/dev/null 2>&1 || true
  launchctl bootstrap gui/$(id -u) "$TARGET"
  echo "installed=$TARGET"
done

echo "launchagents_dir=$LAUNCHD_DIR"
echo "logs=$LOG_DIR"
