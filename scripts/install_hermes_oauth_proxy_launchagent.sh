#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.aiquant.hermes-oauth-proxy"
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

bash "$ROOT/scripts/run_hermes_oauth_proxy.sh" --check >/dev/null
umask 077
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/_runtime/logs"
for log in hermes-oauth-proxy.launchd.out.log hermes-oauth-proxy.launchd.err.log; do
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
bootstrap_launchagent() {
  local attempt output status
  for attempt in 1 2 3 4 5; do
    if output="$("$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET" 2>&1)"; then
      [[ -z "$output" ]] || printf '%s\n' "$output"
      return 0
    else
      status=$?
    fi
    # launchctl can return EIO after it has already registered this exact job.
    if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      return 0
    fi
    if [[ "$output" != *"Input/output error"* && "$output" != *": 5:"* ]]; then
      [[ -z "$output" ]] || printf '%s\n' "$output" >&2
      return "$status"
    fi
    echo "oauth_proxy_install_retry=launchctl_bootstrap_eio attempt=$attempt" >&2
    sleep 1
  done
  return "$status"
}

bootout_if_loaded "$DOMAIN/$LABEL"
# launchctl bootout can return before the old generation has fully
# deregistered; a bootstrap issued in that window races the pending removal.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 0.5
done
bootstrap_launchagent
echo "installed=$TARGET"
