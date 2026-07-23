#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.aiquant.agent-v02-connector"
TEMPLATE="$ROOT/scripts/launchd/$LABEL.plist.template"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
TARGET="$LAUNCHD_DIR/$LABEL.plist"
LOG_DIR="$ROOT/data/_runtime/logs"
DOMAIN="gui/$(id -u)"

if [[ "$(uname -s)" != "Darwin" || ! -x /bin/launchctl ]]; then
  echo "macOS launchctl is required" >&2
  exit 69
fi
if [[ ! -f "$TEMPLATE" ]]; then
  echo "missing LaunchAgent template" >&2
  exit 66
fi

install -d -m 700 "$LAUNCHD_DIR" "$ROOT/data/_runtime" "$LOG_DIR"
for LOG in \
  "$LOG_DIR/agent-v02-connector.launchd.out.log" \
  "$LOG_DIR/agent-v02-connector.launchd.err.log"; do
  if [[ ! -e "$LOG" ]]; then
    install -m 600 /dev/null "$LOG"
  else
    chmod 600 "$LOG"
  fi
done

TEMP="$(mktemp "$ROOT/data/_runtime/$LABEL.plist.XXXXXX")"
trap 'rm -f "$TEMP"' EXIT
sed "s#__ROOT__#$ROOT#g" "$TEMPLATE" > "$TEMP"
plutil -lint "$TEMP" >/dev/null
install -m 600 "$TEMP" "$TARGET"

# Replay-safe replacement: an absent old service is an expected first install.
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"

echo "installed=$TARGET"
echo "service=$DOMAIN/$LABEL"
echo "logs=$LOG_DIR"
