#!/usr/bin/env bash
# =============================================================================
# FlowCore — Verify Full Stack
#
# Checks health of ALL containers and HTTP endpoints for the full FlowCore stack.
# Exits 0 if everything is healthy, 1 if any check fails.
#
# Usage:
#   ./scripts/verify-all.sh          # check all + print report
#   ./scripts/verify-all.sh --quiet  # only print failures
#
# Run from the flowcore/ root directory.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOWCORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$FLOWCORE_DIR/docker"
ENV_FILE="$DOCKER_DIR/.env"

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  C='\033[0;36m'; W='\033[1m'; B='\033[0;34m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; B=''; N=''
fi

QUIET=false
for arg in "$@"; do [[ "$arg" == "--quiet" ]] && QUIET=true; done

PASS=0; FAIL=0; WARN=0
FAILED_CHECKS=()

log()  { [[ "$QUIET" == "false" ]] && echo -e "${C}[$(date '+%H:%M:%S')]${N} $*" || true; }
hdr()  { echo -e "\n${W}${B}======================================================"
         echo -e "  $*"
         echo -e "======================================================${N}\n"; }

pass() { PASS=$((PASS+1)); echo -e "  ${G}[PASS]${N} $*"; }
fail() { FAIL=$((FAIL+1)); FAILED_CHECKS+=("$*"); echo -e "  ${R}[FAIL]${N} $*"; }
skip() { WARN=$((WARN+1)); echo -e "  ${Y}[SKIP]${N} $*"; }

# Load port config from .env (with defaults)
load_port() { grep -E "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "${2}"; }

API_PORT=$(load_port "API_GATEWAY_PORT" "8888")
KC_PORT=$(load_port "KEYCLOAK_PORT" "8080")
KAFKA_UI_PORT=$(load_port "REDPANDA_UI_PORT" "8090")
MLFLOW_PORT=$(load_port "MLFLOW_PORT" "5000")
REPLAY_PORT=$(load_port "REPLAY_PORT" "8050")

# ── Helper: check container health ───────────────────────────────────────────
check_container() {
  local name="$1" label="${2:-$1}"
  local status health
  status=$(docker inspect --format='{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
  health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$name" 2>/dev/null || echo "missing")

  if [[ "$status" == "missing" ]]; then
    fail "$label — container not found"
    return
  fi
  if [[ "$status" != "running" ]]; then
    fail "$label — status: $status (expected: running)"
    return
  fi
  if [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then
    pass "$label — running ($health)"
  elif [[ "$health" == "starting" ]]; then
    skip "$label — still starting (health: starting)"
  else
    fail "$label — unhealthy (status: $status, health: $health)"
  fi
}

# ── Helper: check HTTP endpoint ───────────────────────────────────────────────
check_http() {
  local url="$1" label="${2:-$1}" pattern="${3:-}"
  local resp
  resp=$(curl -sf --max-time 5 "$url" 2>/dev/null || echo "__CURL_FAILED__")
  if [[ "$resp" == "__CURL_FAILED__" ]]; then
    fail "$label — HTTP request failed ($url)"
  elif [[ -n "$pattern" && ! "$resp" =~ $pattern ]]; then
    fail "$label — unexpected response (expected pattern: $pattern)"
  else
    pass "$label — HTTP OK ($url)"
  fi
}

# ── Helper: check Docker exec command ─────────────────────────────────────────
check_exec() {
  local container="$1" label="$2"; shift 2
  if docker exec "$container" "$@" >/dev/null 2>&1; then
    pass "$label — command succeeded"
  else
    fail "$label — command failed"
  fi
}

hdr "FlowCore Full Stack Verification"
log "Checking all containers and service endpoints..."
echo ""

# ── Infrastructure containers ─────────────────────────────────────────────────
echo -e "${W}─── Infrastructure Containers ───────────────────────────────${N}"
check_container "flowcore-postgres"    "PostgreSQL"
check_container "flowcore-timescaledb" "TimescaleDB"
check_container "flowcore-neo4j"       "Neo4j"
check_container "flowcore-kafka"       "Kafka (Redpanda)"
check_container "flowcore-kafka-ui"    "Kafka UI"

# ── Application containers ────────────────────────────────────────────────────
echo ""
echo -e "${W}─── Application Containers ─────────────────────────────────${N}"
check_container "flowcore-platform"  "Platform (Keycloak + services)"
check_container "flowcore-agents"    "Agents (MLflow + topology + classification)"
check_container "flowcore-api-ui"    "API + UI (nginx + GraphQL + insights)"
check_container "flowcore-replay"    "Synthetic Replay"

# ── Database connectivity ─────────────────────────────────────────────────────
echo ""
echo -e "${W}─── Database Connectivity ──────────────────────────────────${N}"
check_exec "flowcore-postgres" "PostgreSQL query" \
  psql -U flowcore -d flowcore --no-align --tuples-only -c "SELECT 1;"

check_exec "flowcore-timescaledb" "TimescaleDB query" \
  psql -U flowcore -d flowcore_ts --no-align --tuples-only -c "SELECT 1;"

check_exec "flowcore-neo4j" "Neo4j Bolt" \
  cypher-shell -u neo4j -p flowcore_secret "RETURN 1;"

check_exec "flowcore-kafka" "Kafka health" \
  rpk cluster health

# ── HTTP endpoint checks ───────────────────────────────────────────────────────
echo ""
echo -e "${W}─── HTTP Endpoint Checks ────────────────────────────────────${N}"
check_http "http://localhost:${API_PORT}/health"            "NOC Gateway /health"    "ok"
check_http "http://localhost:${API_PORT}/api/insights/"     "Insights API"
check_http "http://localhost:${KC_PORT}"                    "Keycloak"
check_http "http://localhost:${KAFKA_UI_PORT}"              "Kafka UI"
check_http "http://localhost:${MLFLOW_PORT}"                "MLflow UI"
check_http "http://localhost:${REPLAY_PORT}/health"         "Replay /health"         "ok"

# ── Summary ───────────────────────────────────────────────────────────────────
hdr "Verification Summary"
echo -e "  ${G}PASS: $PASS${N}   ${R}FAIL: $FAIL${N}   ${Y}SKIP: $WARN${N}"
echo ""

if [[ ${#FAILED_CHECKS[@]} -gt 0 ]]; then
  echo -e "${R}Failed checks:${N}"
  for c in "${FAILED_CHECKS[@]}"; do echo "  ✘ $c"; done
  echo ""
  exit 1
else
  echo -e "${G}All checks passed — FlowCore stack is healthy!${N}"
  echo ""
fi
