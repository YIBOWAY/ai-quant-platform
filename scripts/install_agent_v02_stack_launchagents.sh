#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT/scripts/launchd"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/data/_runtime/logs"
LAUNCHCTL="${QS_LAUNCHCTL_BIN:-$(command -v launchctl || true)}"
PLUTIL="${QS_PLUTIL_BIN:-$(command -v plutil || true)}"

fail() {
  echo "stack_install_error=$1" >&2
  exit 78
}

[[ -n "$LAUNCHCTL" && -x "$LAUNCHCTL" ]] || fail "launchctl_not_found"
[[ -n "$PLUTIL" && -x "$PLUTIL" ]] || fail "plutil_not_found"
[[ "$ROOT" != *"#"* ]] || fail "unsupported_root_character"

# Fail before changing launchd state when the exact release cannot start.
"$ROOT/scripts/run_quant_backend.sh" --check
"$ROOT/scripts/run_quant_frontend.sh" --check

umask 077
mkdir -p "$LAUNCHD_DIR"
[[ ! -L "$LOG_DIR" ]] || fail "unsafe_log_directory"
install -d -m 700 "$LOG_DIR"

for LOG_NAME in \
  backend-api.launchd.log \
  backend-api.launchd.out.log \
  backend-api.launchd.err.log \
  frontend-next.launchd.log \
  frontend-next.launchd.out.log \
  frontend-next.launchd.err.log; do
  LOG_PATH="$LOG_DIR/$LOG_NAME"
  if [[ ! -e "$LOG_PATH" ]]; then
    touch "$LOG_PATH"
  fi
  [[ -f "$LOG_PATH" && ! -L "$LOG_PATH" ]] || fail "unsafe_log_path"
  chmod 600 "$LOG_PATH"
done

LABELS=(
  com.aiquant.backend
  com.aiquant.frontend
)

ESCAPED_ROOT="${ROOT//\\/\\\\}"
ESCAPED_ROOT="${ESCAPED_ROOT//&/\\&}"
DOMAIN="gui/$(id -u)"

for LABEL in "${LABELS[@]}"; do
  TEMPLATE="$TEMPLATE_DIR/$LABEL.plist.template"
  TARGET="$LAUNCHD_DIR/$LABEL.plist"
  [[ -f "$TEMPLATE" ]] || fail "missing_template"

  TEMP="$(mktemp "$LAUNCHD_DIR/.${LABEL}.plist.XXXXXX")"
  trap 'rm -f "$TEMP"' EXIT
  sed "s#__ROOT__#$ESCAPED_ROOT#g" "$TEMPLATE" >"$TEMP"
  "$PLUTIL" -lint "$TEMP" >/dev/null
  chmod 600 "$TEMP"
  mv -f "$TEMP" "$TARGET"
  trap - EXIT

  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  "$LAUNCHCTL" bootstrap "$DOMAIN" "$TARGET"
  echo "installed=$TARGET"
done

echo "launchagents_dir=$LAUNCHD_DIR"
echo "logs=$LOG_DIR"
