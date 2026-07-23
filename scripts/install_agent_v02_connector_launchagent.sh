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
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-$(command -v launchctl || true)}"
PLUTIL="${QS_PLUTIL_BIN:-$(command -v plutil || true)}"

fail() {
  echo "connector_install_error=$1" >&2
  exit 78
}

[[ -n "$LAUNCHCTL" && -x "$LAUNCHCTL" ]] || fail "launchctl_not_found"
[[ -n "$PLUTIL" && -x "$PLUTIL" ]] || fail "plutil_not_found"
[[ -f "$TEMPLATE" && ! -L "$TEMPLATE" ]] || fail "missing_template"
[[ "$ROOT" != *"#"* ]] || fail "unsupported_root_character"

# Do not create a LaunchAgents directory, log, plist, or launchd generation
# until the exact release checkout and owner-only runtime configuration pass
# the provider/network/database-free connector check.
"$ROOT/scripts/run_agent_v02_connector.sh" --check

install -d -m 700 "$LAUNCHD_DIR" "$ROOT/data/_runtime" "$LOG_DIR"
for LOG in \
  "$LOG_DIR/agent-v02-connector.launchd.out.log" \
  "$LOG_DIR/agent-v02-connector.launchd.err.log"; do
  if [[ -e "$LOG" || -L "$LOG" ]]; then
    [[ -f "$LOG" && ! -L "$LOG" ]] || fail "unsafe_log_path"
  else
    install -m 600 /dev/null "$LOG"
  fi
  chmod 600 "$LOG"
done

ESCAPED_ROOT="${ROOT//\\/\\\\}"
ESCAPED_ROOT="${ESCAPED_ROOT//&/\\&}"
TEMP="$(mktemp "$LAUNCHD_DIR/.${LABEL}.plist.XXXXXX")"
trap 'rm -f "$TEMP"' EXIT
sed "s#__ROOT__#$ESCAPED_ROOT#g" "$TEMPLATE" >"$TEMP"
"$PLUTIL" -lint "$TEMP" >/dev/null
chmod 600 "$TEMP"
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  [[ -f "$TARGET" && ! -L "$TARGET" ]] || fail "unsafe_launchagent_target"
fi
mv -f "$TEMP" "$TARGET"
trap - EXIT

# Replay-safe replacement: an absent old service is an expected first install.
"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
"$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET"

echo "installed=$TARGET"
echo "service=$DOMAIN/$LABEL"
echo "logs=$LOG_DIR"
