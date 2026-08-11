#!/usr/bin/env bash
set -euo pipefail

HERMES_BIN="${QS_HERMES_OAUTH_PROXY_BIN:-/Users/sunyibo/.local/bin/hermes}"

fail() {
  echo "hermes_oauth_proxy_error=$1" >&2
  exit 78
}

[[ -x "$HERMES_BIN" ]] || fail "hermes_not_found"
case "$HERMES_BIN" in
  *"/.codex/"* | *"/.claude/"* | *"/ChatGPT.app/"*)
    fail "transient_ai_tool_runtime_forbidden"
    ;;
esac

case "${1:-}" in
  --check)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    proxy_status="$("$HERMES_BIN" proxy status)" || fail "provider_status_failed"
    printf '%s\n' "$proxy_status" |
      /usr/bin/grep -Eq '^[[:space:]]*\[xai[[:space:]]+\].*[[:space:]]ready$' ||
      fail "xai_oauth_not_ready"
    printf 'hermes_oauth_proxy_ready=true provider=xai binary=%s\n' "$HERMES_BIN"
    exit 0
    ;;
  "")
    ;;
  *)
    fail "unexpected_arguments"
    ;;
esac

exec "$HERMES_BIN" proxy start --provider xai --host 127.0.0.1 --port 8645
