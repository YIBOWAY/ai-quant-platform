#!/usr/bin/env bash
set -euo pipefail

LABEL="com.aiquant.agent-v02-connector"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$TARGET"
echo "removed=$TARGET"
