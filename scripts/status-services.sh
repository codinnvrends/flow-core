#!/bin/bash
# =============================================================================
# FlowCore — Check Status of Application Services (Linux/Mac)
#
# Shows the status of all locally-running FlowCore services started by
# start-services.sh. Reads the PID file; falls back to port scan if missing.
#
# Usage:
#   ./scripts/status-services.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/docker/.env"
PID_FILE="/tmp/flowcore-services.pids"
LOG_DIR="/tmp/flowcore-logs"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore Application Services Status${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# ── Load port overrides from .env ─────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep -E '_PORT=') 2>/dev/null || true
fi

DCIM_INGESTION_PORT="${DCIM_INGESTION_PORT:-8001}"
TELEMETRY_GATEWAY_HTTP_PORT="${TELEMETRY_GATEWAY_HTTP_PORT:-8002}"
ACTIVE_DISCOVERY_PORT="${ACTIVE_DISCOVERY_PORT:-8003}"
GRAPH_UPDATER_PORT="${GRAPH_UPDATER_PORT:-8010}"
TIMESERIES_WRITER_PORT="${TIMESERIES_WRITER_PORT:-8011}"
EVENT_ARCHIVE_PORT="${EVENT_ARCHIVE_PORT:-8012}"
GRAPH_API_INTERNAL_PORT="${GRAPH_API_INTERNAL_PORT:-4000}"
INSIGHTS_API_INTERNAL_PORT="${INSIGHTS_API_INTERNAL_PORT:-4001}"
EVENTING_API_INTERNAL_PORT="${EVENTING_API_INTERNAL_PORT:-4002}"
TOPO_AGENT_PORT="${TOPO_AGENT_PORT:-8020}"
CLASS_AGENT_PORT="${CLASS_AGENT_PORT:-8021}"
REPLAY_PORT="${REPLAY_PORT:-8050}"

declare -A SERVICE_PORTS=(
    ["dcim-ingestion"]="$DCIM_INGESTION_PORT"
    ["telemetry-gateway"]="$TELEMETRY_GATEWAY_HTTP_PORT"
    ["active-discovery"]="$ACTIVE_DISCOVERY_PORT"
    ["graph-updater"]="$GRAPH_UPDATER_PORT"
    ["timeseries-writer"]="$TIMESERIES_WRITER_PORT"
    ["event-archive"]="$EVENT_ARCHIVE_PORT"
    ["graph-api"]="$GRAPH_API_INTERNAL_PORT"
    ["insights-api"]="$INSIGHTS_API_INTERNAL_PORT"
    ["eventing-integration"]="$EVENTING_API_INTERNAL_PORT"
    ["topology-agent"]="$TOPO_AGENT_PORT"
    ["classification-agent"]="$CLASS_AGENT_PORT"
    ["synthetic-replay"]="$REPLAY_PORT"
)

RUNNING=0
STOPPED=0

if [ -f "$PID_FILE" ]; then
    echo -e "${BLUE}Service Processes (from PID file):${NC}"
    echo ""
    while IFS=: read -r name pid port; do
        [ -z "$pid" ] && continue
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${GREEN}[UP]${NC}    ${name} — PID ${pid}, :${port}"
            RUNNING=$((RUNNING + 1))
        else
            echo -e "  ${RED}[DOWN]${NC}  ${name} — PID ${pid} (exited), :${port}"
            STOPPED=$((STOPPED + 1))
        fi
    done < "$PID_FILE"
else
    echo -e "${YELLOW}No PID file found (${PID_FILE}).${NC}"
    echo -e "Falling back to port scan...\n"
    echo -e "${BLUE}Port Scan:${NC}"
    echo ""
    for name in dcim-ingestion telemetry-gateway active-discovery graph-updater \
                timeseries-writer event-archive graph-api insights-api \
                eventing-integration topology-agent classification-agent; do
        port="${SERVICE_PORTS[$name]}"
        if (echo >/dev/tcp/localhost/"$port") 2>/dev/null; then
            echo -e "  ${GREEN}[UP]${NC}    ${name} — :${port}"
            RUNNING=$((RUNNING + 1))
        else
            echo -e "  ${RED}[DOWN]${NC}  ${name} — :${port}"
            STOPPED=$((STOPPED + 1))
        fi
    done
fi

echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "  Running: ${GREEN}${RUNNING}${NC}   Stopped: ${RED}${STOPPED}${NC}"
echo -e "${BLUE}======================================================${NC}"

if [ "$RUNNING" -gt 0 ]; then
    echo ""
    echo -e "${BLUE}Access URLs:${NC}"
    echo "  Graph API (GraphQL) -> http://localhost:${GRAPH_API_INTERNAL_PORT:-4000}/graphql"
    echo "  Insights API        -> http://localhost:${INSIGHTS_API_INTERNAL_PORT:-4001}"
    echo "  Eventing            -> http://localhost:${EVENTING_API_INTERNAL_PORT:-4002}"
    echo ""
    echo -e "${BLUE}Logs:${NC}  ${LOG_DIR}/<service-name>.log"
    echo -e "${BLUE}Stop:${NC}  ./scripts/stop-services.sh"
elif [ "$RUNNING" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}No services running. Start with:${NC} ./scripts/start-services.sh"
fi
