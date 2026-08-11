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
if [[ -n "${QS_LAUNCHCTL_BIN:-}" ]]; then
  LAUNCHCTL="$QS_LAUNCHCTL_BIN"
elif command -v launchctl >/dev/null 2>&1; then
  LAUNCHCTL="$(command -v launchctl)"
else
  LAUNCHCTL=""
fi
if [[ -n "${QS_PLUTIL_BIN:-}" ]]; then
  PLUTIL="$QS_PLUTIL_BIN"
elif command -v plutil >/dev/null 2>&1; then
  PLUTIL="$(command -v plutil)"
else
  PLUTIL=""
fi
LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS=5
LAUNCHCTL_BOOTSTRAP_RETRY_DELAY_SECONDS=0.2

fail() {
  echo "connector_install_error=$1" >&2
  exit 78
}

[[ -n "$LAUNCHCTL" && -x "$LAUNCHCTL" ]] || fail "launchctl_not_found"
[[ -n "$PLUTIL" && -x "$PLUTIL" ]] || fail "plutil_not_found"
[[ -f "$TEMPLATE" && ! -L "$TEMPLATE" ]] || fail "missing_template"
[[ "$ROOT" != *"#"* ]] || fail "unsupported_root_character"

bootout_if_loaded() {
  local service="$1"
  local output
  local status

  if output="$("$LAUNCHCTL" bootout "$service" 2>&1)"; then
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return 0
  else
    status=$?
  fi
  if [[ "$status" -eq 3 \
    && "$output" == "Boot-out failed: 3: No such process" ]]; then
    echo "already_unloaded=$service"
    return 0
  fi
  if [[ "$status" -eq 113 \
    && "$output" == "Boot-out failed: 113: Could not find specified service" ]]; then
    echo "already_unloaded=$service"
    return 0
  fi
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output" >&2
  fi
  return "$status"
}

bootstrap_launchagent() {
  local attempt=1
  local output
  local status

  while (( attempt <= LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS )); do
    if output="$("$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET" 2>&1)"; then
      [[ -z "$output" ]] || printf '%s\n' "$output"
      return 0
    else
      status=$?
    fi

    # launchctl may return EIO after it has already registered this exact job.
    # A second bootstrap then conflicts with the loaded generation and can make
    # the enclosing stack startup stop before later scheduled jobs are installed.
    if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      return 0
    fi

    if [[ "$output" != *"Input/output error"* \
      && "$output" != *"input/output error"* \
      && "$output" != *"EIO"* \
      && "$output" != *": 5:"* ]]; then
      [[ -z "$output" ]] || printf '%s\n' "$output" >&2
      return "$status"
    fi

    if (( attempt == LAUNCHCTL_BOOTSTRAP_MAX_ATTEMPTS )); then
      [[ -z "$output" ]] || printf '%s\n' "$output" >&2
      echo \
        "connector_install_error=launchctl_bootstrap_eio_exhausted label=$LABEL attempts=$attempt" \
        >&2
      return "$status"
    fi

    echo \
      "connector_install_retry=launchctl_bootstrap_eio label=$LABEL attempt=$attempt" \
      >&2
    sleep "$LAUNCHCTL_BOOTSTRAP_RETRY_DELAY_SECONDS"
    attempt=$((attempt + 1))
  done
}

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
bootout_if_loaded "$DOMAIN/$LABEL"
bootstrap_launchagent

echo "installed=$TARGET"
echo "service=$DOMAIN/$LABEL"
echo "logs=$LOG_DIR"
