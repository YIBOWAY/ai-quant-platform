#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.aiquant.d34-worker"
DOMAIN="gui/$(id -u)"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$ROOT/scripts/launchd/$LABEL.plist.template"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-/bin/launchctl}"
PLUTIL="${QS_PLUTIL_BIN:-/usr/bin/plutil}"

[[ -x "$LAUNCHCTL" && -x "$PLUTIL" && -f "$TEMPLATE" ]] || exit 78

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

bash "$ROOT/scripts/run_d34_worker.sh" --check >/dev/null
umask 077
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/_runtime/logs"
for log in d34-worker.launchd.out.log d34-worker.launchd.err.log; do
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
bootout_if_loaded "$DOMAIN/$LABEL"
"$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET"
echo "installed=$TARGET"
