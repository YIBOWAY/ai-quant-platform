#!/usr/bin/env bash
# Owner-run, opt-in installer for the D34 research worker LaunchAgent.
# Not referenced by local_mac_stack.sh: the owner installs this explicitly.
# Also retires the removed com.aiquant.d34-worker label — its entrypoint
# scripts/run_d34_worker.sh no longer exists in this release, so the plist is
# booted out and archived under data/_runtime/launchd-retired/ as a receipt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.aiquant.d34-research-worker"
RETIRED_LABELS=("com.aiquant.d34-worker" "com.aiquant.factor-automation")
DOMAIN="gui/$(id -u)"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$ROOT/scripts/launchd/$LABEL.plist.template"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-/bin/launchctl}"
PLUTIL="${QS_PLUTIL_BIN:-/usr/bin/plutil}"

[[ -x "$LAUNCHCTL" && -x "$PLUTIL" && -f "$TEMPLATE" ]] || exit 78

service_missing() {
  [[ "$1" == *"Could not find service"* || "$1" == *"No such process"* ]]
}

bootout_and_confirm_absent() {
  local label="$1" output code
  set +e
  output="$("$LAUNCHCTL" bootout "$DOMAIN/$label" 2>&1)"
  code=$?
  set -e
  if [[ "$code" -ne 0 ]] && ! service_missing "$output"; then
    printf 'launchctl_bootout_failed=%s\n' "$label" >&2
    return "$code"
  fi
  set +e
  output="$("$LAUNCHCTL" print "$DOMAIN/$label" 2>&1)"
  code=$?
  set -e
  if [[ "$code" -eq 0 ]] || ! service_missing "$output"; then
    printf 'launchctl_service_still_present=%s\n' "$label" >&2
    return 78
  fi
}
umask 077
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/_runtime/logs"
for log in d34-research-worker.launchd.out.log d34-research-worker.launchd.err.log; do
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
for retired_label in "${RETIRED_LABELS[@]}"; do
  bootout_and_confirm_absent "$retired_label"
  retired_target="$HOME/Library/LaunchAgents/$retired_label.plist"
  if [[ -f "$retired_target" ]]; then
    mkdir -p "$ROOT/data/_runtime/launchd-retired"
    mv -f "$retired_target" "$ROOT/data/_runtime/launchd-retired/$retired_label.plist"
  fi
done
bootout_and_confirm_absent "$LABEL"
"$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET"
echo "installed=$TARGET retired=${RETIRED_LABELS[*]}"
