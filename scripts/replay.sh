#!/usr/bin/env bash
# =============================================================================
# FlowCore — Synthetic Replay Controller (Linux/Mac)
#
# Controls the synthetic-replay service that publishes to Kafka topics:
#   metrics.timeseries.raw  (60%)
#   dcim.config.normalized  (20%)
#   discovery.snmp.results   (5%)
#   discovery.bmc.results    (5%)
#   alerts.raw              (~0.5%)
#
# Usage:
#   ./scripts/replay.sh start [--mode live|historical] [--rate N] [--local]
#   ./scripts/replay.sh stop
#   ./scripts/replay.sh status
#   ./scripts/replay.sh pause
#   ./scripts/replay.sh resume
#   ./scripts/replay.sh rate <events_per_sec>
#   ./scripts/replay.sh reset
#   ./scripts/replay.sh logs [-f]
#
# Modes:
#   --local   Run natively with uvicorn (databases must be on localhost)
#   (default) Run as Docker container (requires built image)
#
# Examples:
#   ./scripts/replay.sh start                      # Docker, live mode, 1000/s
#   ./scripts/replay.sh start --rate 500           # Docker, 500 events/s
#   ./scripts/replay.sh start --mode historical    # Replay 30-day seed data
#   ./scripts/replay.sh start --local              # Native uvicorn (dev mode)
#   ./scripts/replay.sh rate 2000                  # Change rate while running
#   ./scripts/replay.sh status                     # Show full state
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$PROJECT_ROOT/docker"
SERVICE_DIR="$PROJECT_ROOT/services/synthetic-replay"
ENV_FILE="$DOCKER_DIR/.env"
REPLAY_COMPOSE="$DOCKER_DIR/docker-compose.replay.yml"
DB_COMPOSE="$DOCKER_DIR/docker-compose.databases.yml"
REPLAY_PORT="${REPLAY_PORT:-8050}"
REPLAY_API="http://localhost:${REPLAY_PORT}"
PID_FILE="/tmp/flowcore-replay.pid"

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  C='\033[0;36m'; W='\033[1m'; B='\033[0;34m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; B=''; N=''
fi

log()  { echo -e "${C}[replay]${N} $*"; }
ok()   { echo -e "${G}[replay] ✔ $*${N}"; }
warn() { echo -e "${Y}[replay] ! $*${N}"; }
err()  { echo -e "${R}[replay] ✘ $*${N}"; exit 1; }
hdr()  { echo -e "\n${W}${B}======================================================${N}"
         echo -e "${W}${B}  $*${N}"
         echo -e "${W}${B}======================================================${N}\n"; }

# ── Load port from .env if present ───────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  _port=$(grep -E "^REPLAY_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || true)
  [ -n "$_port" ] && REPLAY_PORT="$_port" && REPLAY_API="http://localhost:${REPLAY_PORT}"
fi

# ── Helper: check if API is reachable ────────────────────────────────────────
api_up() {
  curl -sf --max-time 3 "${REPLAY_API}/health" >/dev/null 2>&1
}

# ── Helper: wait for API to come up ──────────────────────────────────────────
wait_for_api() {
  local max=30 i=0
  log "Waiting for replay API on :${REPLAY_PORT}..."
  while ! api_up; do
    i=$((i+1))
    [ "$i" -ge "$max" ] && err "Replay API did not come up after ${max}s"
    sleep 1
  done
  ok "Replay API is up"
}

# ── Helper: detect compose binary ────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else DC=""; fi

# ─────────────────────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_start() {
  local mode="live" rate="" local_mode=false

  # Parse start-specific flags
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --mode)       mode="$2"; shift 2 ;;
      --mode=*)     mode="${1#--mode=}"; shift ;;
      --rate)       rate="$2"; shift 2 ;;
      --rate=*)     rate="${1#--rate=}"; shift ;;
      --local)      local_mode=true; shift ;;
      *) warn "Unknown start flag: $1"; shift ;;
    esac
  done

  [[ "$mode" != "live" && "$mode" != "historical" ]] && err "Mode must be 'live' or 'historical'"

  if api_up; then
    warn "Replay service is already running at ${REPLAY_API}"
    cmd_status
    return 0
  fi

  if $local_mode; then
    _start_local "$mode" "$rate"
  else
    _start_docker "$mode" "$rate"
  fi
}

_start_docker() {
  local mode="$1" rate="$2"
  [ -z "$DC" ] && err "docker compose not found"

  hdr "Starting Synthetic Replay (Docker)"
  log "Mode: ${mode} | Rate: ${rate:-default} events/s"

  # Check Kafka and databases are up
  if ! docker ps --format "{{.Names}}" 2>/dev/null | grep -q "flowcore-kafka"; then
    err "Kafka is not running. Start it first: ./scripts/start-databases.sh"
  fi

  local env_overrides=()
  env_overrides+=("-e" "REPLAY_MODE=${mode}")
  [ -n "$rate" ] && env_overrides+=("-e" "REPLAY_EVENTS_PER_SEC=${rate}")

  # Build env overrides: pass as DOCKER_* env vars for compose
  export REPLAY_MODE="$mode"
  [ -n "$rate" ] && export REPLAY_EVENTS_PER_SEC="$rate"

  $DC -f "$DB_COMPOSE" -f "$REPLAY_COMPOSE" \
    --env-file "$ENV_FILE" \
    up -d synthetic-replay

  wait_for_api
  echo ""
  cmd_status
}

_start_local() {
  local mode="$1" rate="$2"

  hdr "Starting Synthetic Replay (Local / uvicorn)"
  log "Mode: ${mode}"

  # Find Python
  local py=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then py="$candidate"; break; fi
  done
  [ -z "$py" ] && err "Python not found"

  # Check for venv
  local venv_py=""
  for venv_path in "$PROJECT_ROOT/venv/bin/python" "$SERVICE_DIR/venv/bin/python" "$PROJECT_ROOT/.venv/bin/python"; do
    if [ -f "$venv_path" ]; then venv_py="$venv_path"; break; fi
  done
  [ -n "$venv_py" ] && py="$venv_py" && log "Using venv: $venv_py"

  # Set env to point at localhost
  export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:19092}"
  export PG_HOST="${PG_HOST:-localhost}"
  export PG_PORT="${PG_PORT:-5432}"
  export TS_HOST="${TS_HOST:-localhost}"
  export TS_PORT="${TS_PORT:-5433}"
  export REPLAY_MODE="$mode"
  export REPLAY_PORT="$REPLAY_PORT"
  [ -n "$rate" ] && export REPLAY_EVENTS_PER_SEC="$rate"

  # Source .env for passwords/credentials (but don't override host settings)
  if [ -f "$ENV_FILE" ]; then
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | \
      grep -v -E '^(KAFKA_BOOTSTRAP_SERVERS|PG_HOST|PG_PORT|TS_HOST|TS_PORT)=')
    set +o allexport
  fi

  log "Starting uvicorn on :${REPLAY_PORT}..."
  cd "$SERVICE_DIR"
  nohup "$py" -m uvicorn main:app --host 0.0.0.0 --port "$REPLAY_PORT" \
    > "/tmp/flowcore-replay.log" 2>&1 &
  echo $! > "$PID_FILE"
  ok "Replay started (PID: $!). Logs: /tmp/flowcore-replay.log"

  wait_for_api
  echo ""
  cmd_status
}

cmd_stop() {
  hdr "Stopping Synthetic Replay"

  # Stop Docker container if running
  if [ -n "$DC" ] && docker ps --format "{{.Names}}" 2>/dev/null | grep -q "flowcore-replay"; then
    log "Stopping Docker container..."
    $DC -f "$DB_COMPOSE" -f "$REPLAY_COMPOSE" \
      --env-file "$ENV_FILE" stop synthetic-replay 2>/dev/null || true
    $DC -f "$DB_COMPOSE" -f "$REPLAY_COMPOSE" \
      --env-file "$ENV_FILE" rm -f synthetic-replay 2>/dev/null || true
    ok "Docker container stopped"
  fi

  # Kill local process if PID file exists
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      log "Stopping local uvicorn (PID: $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      ok "Local process stopped"
    fi
    rm -f "$PID_FILE"
  fi

  if ! docker ps --format "{{.Names}}" 2>/dev/null | grep -q "flowcore-replay" && \
     [ ! -f "$PID_FILE" ]; then
    ok "Replay service is stopped"
  else
    warn "Service may still be running — check manually"
  fi
}

cmd_status() {
  hdr "Replay Service Status"

  # Container status
  if docker ps --format "{{.Names}}\t{{.Status}}" 2>/dev/null | grep -q "flowcore-replay"; then
    local ctr_status
    ctr_status=$(docker ps --format "{{.Names}}\t{{.Status}}" | grep "flowcore-replay" || true)
    echo -e "  ${G}Container:${N} ${ctr_status}"
  elif [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo -e "  ${G}Process:${N}   PID $(cat "$PID_FILE") (local uvicorn)"
  else
    echo -e "  ${Y}Status:${N}    Not running"
    return 0
  fi

  # API status
  if api_up; then
    local resp
    resp=$(curl -sf --max-time 5 "${REPLAY_API}/status" 2>/dev/null || echo "{}")
    echo ""
    echo -e "  ${W}API Response from ${REPLAY_API}/status:${N}"
    echo "$resp" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "  $resp"
  else
    warn "API not reachable at ${REPLAY_API}"
  fi

  echo ""
  echo -e "  ${B}Controls:${N}"
  echo "    ./scripts/replay.sh pause          # pause publishing"
  echo "    ./scripts/replay.sh resume         # resume publishing"
  echo "    ./scripts/replay.sh rate <N>       # change events/sec"
  echo "    ./scripts/replay.sh reset          # reload seed data + restart"
  echo "    ./scripts/replay.sh logs -f        # follow logs"
}

cmd_pause() {
  api_up || err "Replay API not reachable at ${REPLAY_API}. Is the service running?"
  curl -sf -X POST "${REPLAY_API}/control/pause" | python3 -m json.tool 2>/dev/null || true
  ok "Paused"
}

cmd_resume() {
  api_up || err "Replay API not reachable at ${REPLAY_API}. Is the service running?"
  curl -sf -X POST "${REPLAY_API}/control/resume" | python3 -m json.tool 2>/dev/null || true
  ok "Resumed"
}

cmd_rate() {
  local rate="${1:-}"
  [ -z "$rate" ] && err "Usage: ./scripts/replay.sh rate <events_per_sec>"
  [[ "$rate" =~ ^[0-9]+$ ]] || err "Rate must be a positive integer"
  api_up || err "Replay API not reachable at ${REPLAY_API}. Is the service running?"
  curl -sf -X POST "${REPLAY_API}/control/rate" \
    -H "Content-Type: application/json" \
    -d "{\"events_per_sec\": ${rate}}" | python3 -m json.tool 2>/dev/null || true
  ok "Rate set to ${rate} events/sec"
}

cmd_reset() {
  api_up || err "Replay API not reachable at ${REPLAY_API}. Is the service running?"
  log "Reloading seed data and restarting replay..."
  curl -sf -X POST "${REPLAY_API}/control/reset" | python3 -m json.tool 2>/dev/null || true
  ok "Reset complete — replay restarted with fresh seed data"
}

cmd_logs() {
  local follow=""
  [ "${1:-}" == "-f" ] && follow="-f"

  if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "flowcore-replay"; then
    docker logs $follow flowcore-replay
  elif [ -f "/tmp/flowcore-replay.log" ]; then
    if [ -n "$follow" ]; then tail -f /tmp/flowcore-replay.log
    else cat /tmp/flowcore-replay.log; fi
  else
    err "No running replay service or log file found"
  fi
}

cmd_help() {
  echo ""
  echo -e "${W}FlowCore Synthetic Replay Controller${N}"
  echo ""
  echo -e "${B}Usage:${N}"
  echo "  ./scripts/replay.sh <command> [options]"
  echo ""
  echo -e "${B}Commands:${N}"
  echo "  start   [--mode live|historical] [--rate N] [--local]"
  echo "            Start replay (Docker by default, --local for native uvicorn)"
  echo "  stop      Stop the replay service"
  echo "  status    Show container status + live API state"
  echo "  pause     Pause message publishing (keeps service running)"
  echo "  resume    Resume message publishing"
  echo "  rate <N>  Change publishing rate to N events/sec"
  echo "  reset     Reload seed data from DB and restart replay"
  echo "  logs [-f] Show service logs (-f to follow)"
  echo ""
  echo -e "${B}Examples:${N}"
  echo "  ./scripts/replay.sh start                      # live mode, default rate"
  echo "  ./scripts/replay.sh start --rate 500           # 500 events/sec"
  echo "  ./scripts/replay.sh start --mode historical    # replay 30-day seed data"
  echo "  ./scripts/replay.sh start --local              # run natively (dev mode)"
  echo "  ./scripts/replay.sh rate 2000                  # update rate live"
  echo "  ./scripts/replay.sh pause && sleep 60 && ./scripts/replay.sh resume"
  echo ""
  echo -e "${B}Topics published:${N}"
  echo "  metrics.timeseries.raw   (60%)   dcim.config.normalized (20%)"
  echo "  discovery.snmp.results    (5%)   discovery.bmc.results   (5%)"
  echo "  alerts.raw               (~0.5%)"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────────────────────────────────────
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
  start)   cmd_start "$@" ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  pause)   cmd_pause ;;
  resume)  cmd_resume ;;
  rate)    cmd_rate "$@" ;;
  reset)   cmd_reset ;;
  logs)    cmd_logs "${1:-}" ;;
  help|--help|-h) cmd_help ;;
  *) err "Unknown command: '$COMMAND'. Run './scripts/replay.sh help'" ;;
esac
