#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/scripts/launchd/com.aiquant.futu-quota-probe.plist.template"
TARGET="$HOME/Library/LaunchAgents/com.aiquant.futu-quota-probe.plist"
LOG_DIR="$ROOT/data/_runtime/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "missing template: $TEMPLATE" >&2
  exit 66
fi
sed "s#__ROOT__#$ROOT#g" "$TEMPLATE" > "$TARGET"
chmod 644 "$TARGET"
launchctl bootout "gui/$(id -u)" "$TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
echo "installed=$TARGET"
