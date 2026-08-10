#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.aiquant.factor-automation"
DOMAIN="gui/$(id -u)"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$ROOT/scripts/launchd/$LABEL.plist.template"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-/bin/launchctl}"
PLUTIL="${QS_PLUTIL_BIN:-/usr/bin/plutil}"

[[ -x "$LAUNCHCTL" && -x "$PLUTIL" && -f "$TEMPLATE" ]] || exit 78
bash "$ROOT/scripts/run_factor_automation_driver.sh" >/dev/null
umask 077
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/_runtime/logs"
for log in factor-automation.launchd.out.log factor-automation.launchd.err.log; do
  touch "$ROOT/data/_runtime/logs/$log"
  chmod 600 "$ROOT/data/_runtime/logs/$log"
done
temporary="$(mktemp "$HOME/Library/LaunchAgents/.${LABEL}.plist.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
escaped_root="${ROOT//\/\\}"
escaped_root="${escaped_root//&/\&}"
sed "s#__ROOT__#$escaped_root#g" "$TEMPLATE" >"$temporary"
"$PLUTIL" -lint "$temporary" >/dev/null
chmod 600 "$temporary"
mv -f "$temporary" "$TARGET"
trap - EXIT
"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
"$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET"
echo "installed=$TARGET"
