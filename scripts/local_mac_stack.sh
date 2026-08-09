#!/usr/bin/env bash
set -euo pipefail

# Stable macOS entrypoint for the local AI Quant stack. This script deliberately
# uses repository-owned runners and user LaunchAgents; it never relies on the
# lifetime or environment of a Codex, Claude Code, or IDE terminal.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/src/frontend"
DOMAIN="gui/$(id -u)"
DATABASE_CONTAINER="${QS_LOCAL_POSTGRES_CONTAINER:-quantplatform-db}"
HERMES_PLIST="$HOME/Library/LaunchAgents/ai.hermes.gateway.plist"

fail() {
  echo "local_stack_error=$1" >&2
  exit 78
}

resolve_executable() {
  local configured="$1"
  shift
  local candidate
  for candidate in "$configured" "$@"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      case "$candidate" in
        *"/.codex/"* | *"/.claude/"* | *"/ChatGPT.app/"*)
          continue
          ;;
      esac
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

DOCKER_BIN="$(resolve_executable "${QS_LOCAL_DOCKER_BIN:-}" \
  /usr/local/bin/docker /opt/homebrew/bin/docker || true)"
NPM_BIN="$(resolve_executable "${QS_LOCAL_NPM_BIN:-}" \
  "$HOME/.local/bin/npm" /opt/homebrew/bin/npm /usr/local/bin/npm || true)"
LAUNCHCTL_BIN="$(resolve_executable "${QS_LOCAL_LAUNCHCTL_BIN:-}" \
  /bin/launchctl || true)"
CURL_BIN="$(resolve_executable "${QS_LOCAL_CURL_BIN:-}" \
  /usr/bin/curl /opt/homebrew/bin/curl /usr/local/bin/curl || true)"

validate_environment() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "macos_required"
  [[ "$DATABASE_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] ||
    fail "invalid_database_container"
  [[ -n "$DOCKER_BIN" ]] || fail "docker_not_found"
  [[ -n "$NPM_BIN" ]] || fail "npm_not_found"
  [[ -n "$LAUNCHCTL_BIN" ]] || fail "launchctl_not_found"
  [[ -n "$CURL_BIN" ]] || fail "curl_not_found"
}

wait_for_docker() {
  local attempt_no
  if "$DOCKER_BIN" info >/dev/null 2>&1; then
    return 0
  fi
  /usr/bin/open -ga Docker
  for attempt_no in {1..30}; do
    if "$DOCKER_BIN" info >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail "docker_desktop_not_ready"
}

start_database() {
  local attempt_no
  wait_for_docker
  "$DOCKER_BIN" inspect "$DATABASE_CONTAINER" >/dev/null 2>&1 ||
    fail "database_container_missing"
  "$DOCKER_BIN" update --restart unless-stopped "$DATABASE_CONTAINER" >/dev/null
  "$DOCKER_BIN" start "$DATABASE_CONTAINER" >/dev/null
  for attempt_no in {1..30}; do
    if "$DOCKER_BIN" exec "$DATABASE_CONTAINER" sh -lc \
      'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
      echo "database_ready=true container=$DATABASE_CONTAINER"
      return 0
    fi
    sleep 1
  done
  fail "postgres_not_ready"
}

build_stack() {
  bash "$ROOT/scripts/run_quant_backend.sh" --check
  "$NPM_BIN" --prefix "$FRONTEND_DIR" run build
  bash "$ROOT/scripts/run_quant_frontend.sh" --check
  bash "$ROOT/scripts/run_agent_v02_connector.sh" --check
  echo "build_ready=true"
}

install_platform_jobs() {
  bash "$ROOT/scripts/install_agent_v02_stack_launchagents.sh"
  bash "$ROOT/scripts/install_agent_v02_connector_launchagent.sh"
}

ensure_hermes_job() {
  local attempt_no bootstrap_output bootstrap_status old_pid
  [[ -f "$HERMES_PLIST" && ! -L "$HERMES_PLIST" ]] ||
    fail "hermes_launchagent_missing"
  old_pid=""
  if "$LAUNCHCTL_BIN" print "$DOMAIN/ai.hermes.gateway" >/dev/null 2>&1; then
    old_pid="$(
      "$LAUNCHCTL_BIN" print "$DOMAIN/ai.hermes.gateway" |
        /usr/bin/awk '/^[[:space:]]*pid = / {print $3; exit}'
    )"
    "$LAUNCHCTL_BIN" bootout "$DOMAIN/ai.hermes.gateway"
  fi
  # kickstart -k can overlap old/new gateway lifetimes and make the new process
  # lose the 8642 bind race. launchctl bootout can return before the previous
  # PID has actually exited, and that process can briefly release/reacquire its
  # socket while shutting down. Require both PID exit and port release before
  # bootstrapping one unambiguous process generation.
  for attempt_no in {1..60}; do
    if [[ -z "$old_pid" ]] || ! /bin/kill -0 "$old_pid" 2>/dev/null; then
      if ! /usr/sbin/lsof -nP -iTCP:8642 -sTCP:LISTEN >/dev/null 2>&1; then
      for bootstrap_attempt in {1..10}; do
        if bootstrap_output="$(
          "$LAUNCHCTL_BIN" bootstrap "$DOMAIN" "$HERMES_PLIST" 2>&1
        )"; then
          [[ -z "$bootstrap_output" ]] || printf '%s\n' "$bootstrap_output"
          return 0
        else
          bootstrap_status=$?
        fi
        if [[ "$bootstrap_output" != *"Input/output error"* \
          && "$bootstrap_output" != *": 5:"* ]]; then
          [[ -z "$bootstrap_output" ]] || printf '%s\n' "$bootstrap_output" >&2
          return "$bootstrap_status"
        fi
        echo "hermes_bootstrap_retry=$bootstrap_attempt" >&2
        sleep 0.5
      done
      fail "hermes_launchagent_bootstrap_failed"
      fi
    fi
    sleep 0.5
  done
  fail "hermes_previous_generation_did_not_exit"
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempt_no
  for attempt_no in {1..30}; do
    if "$CURL_BIN" --fail --silent --max-time 3 "$url" >/dev/null 2>&1; then
      echo "$name=true url=$url"
      return 0
    fi
    sleep 2
  done
  fail "${name}_not_ready"
}

start_stack() {
  start_database
  build_stack
  ensure_hermes_job
  install_platform_jobs
  wait_for_url "hermes_ready" "http://127.0.0.1:8642/health"
  wait_for_url "backend_ready" "http://127.0.0.1:8765/api/health"
  wait_for_url "frontend_ready" "http://127.0.0.1:3001/zh/hermes"
}

bootout_job() {
  local label="$1"
  if "$LAUNCHCTL_BIN" print "$DOMAIN/$label" >/dev/null 2>&1; then
    "$LAUNCHCTL_BIN" bootout "$DOMAIN/$label"
  fi
}

stop_stack() {
  bootout_job com.aiquant.agent-v02-connector
  bootout_job com.aiquant.frontend
  bootout_job com.aiquant.backend
  bootout_job ai.hermes.gateway
  if "$DOCKER_BIN" info >/dev/null 2>&1 && \
    "$DOCKER_BIN" inspect "$DATABASE_CONTAINER" >/dev/null 2>&1; then
    "$DOCKER_BIN" stop "$DATABASE_CONTAINER" >/dev/null
  fi
  echo "stack_stopped=true"
}

print_job_status() {
  local label="$1"
  if "$LAUNCHCTL_BIN" print "$DOMAIN/$label" >/dev/null 2>&1; then
    local pid state
    pid="$($LAUNCHCTL_BIN print "$DOMAIN/$label" | \
      /usr/bin/awk '/^[[:space:]]*pid = / {print $3; exit}')"
    state="$($LAUNCHCTL_BIN print "$DOMAIN/$label" | \
      /usr/bin/awk '/^[[:space:]]*state = / {print $3; exit}')"
    echo "service=$label loaded=true state=${state:-unknown} pid=${pid:-none}"
  else
    echo "service=$label loaded=false state=stopped pid=none"
  fi
}

status_stack() {
  if "$DOCKER_BIN" info >/dev/null 2>&1; then
    echo "docker_ready=true"
    "$DOCKER_BIN" ps --filter "name=^/${DATABASE_CONTAINER}$" \
      --format 'database={{.Names}} status={{.Status}} ports={{.Ports}}'
  else
    echo "docker_ready=false"
  fi
  print_job_status ai.hermes.gateway
  print_job_status com.aiquant.backend
  print_job_status com.aiquant.frontend
  print_job_status com.aiquant.agent-v02-connector
  for endpoint in \
    "hermes=http://127.0.0.1:8642/health" \
    "backend=http://127.0.0.1:8765/api/health" \
    "frontend=http://127.0.0.1:3001/zh/hermes"; do
    local name="${endpoint%%=*}"
    local url="${endpoint#*=}"
    if "$CURL_BIN" --fail --silent --max-time 2 "$url" >/dev/null; then
      echo "endpoint=$name ready=true url=$url"
    else
      echo "endpoint=$name ready=false url=$url"
    fi
  done
}

show_logs() {
  echo "hermes_log=$HOME/.hermes/logs/gateway.log"
  echo "hermes_error_log=$HOME/.hermes/logs/gateway.error.log"
  echo "backend_log=$ROOT/data/_runtime/logs/backend-api.launchd.log"
  echo "frontend_log=$ROOT/data/_runtime/logs/frontend-next.launchd.log"
  echo "connector_log=$ROOT/data/_runtime/logs/agent-v02-connector.launchd.out.log"
}

usage() {
  cat <<'EOF'
Usage: bash scripts/local_mac_stack.sh <command>

Commands:
  start    Start Docker/PostgreSQL, run the production build, install/restart LaunchAgents, and wait for readiness.
  restart  Same as start; all long-running services are replaced by launchd.
  build    Validate the Python backend and run the Next.js production build.
  stop     Unload all four LaunchAgents and stop the project PostgreSQL container.
  status   Show Docker, launchd, and HTTP readiness without changing state.
  logs     Print the stable log paths.
EOF
}

validate_environment
case "${1:-}" in
  start | restart)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    start_stack
    ;;
  build)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    build_stack
    ;;
  stop)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    stop_stack
    ;;
  status)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    status_stack
    ;;
  logs)
    [[ "$#" -eq 1 ]] || fail "unexpected_arguments"
    show_logs
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
