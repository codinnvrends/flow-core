#!/bin/bash
# =============================================================================
# FlowCore — Start Application Services Locally (Linux/Mac)
#
# Starts all 11 FlowCore services natively using uvicorn (no Docker).
# Databases and Kafka must already be running in Docker.
#
# Prerequisites:
#   ./scripts/start-databases.sh        (start Postgres, TimescaleDB, Neo4j, Kafka)
#
# Usage:
#   ./scripts/start-services.sh              # Start all services
#   ./scripts/start-services.sh --replay     # Also start synthetic-replay
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICES_DIR="${PROJECT_ROOT}/services"
ENV_FILE="${PROJECT_ROOT}/docker/.env"
PID_FILE="/tmp/flowcore-services.pids"
LOG_DIR="/tmp/flowcore-logs"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore — Starting Application Services (Local)${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# ── Check Docker is running (databases need it) ───────────────────────────────
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Databases need Docker.${NC}"
    exit 1
fi

# ── Check databases are up ────────────────────────────────────────────────────
echo -e "${BLUE}Checking databases are running...${NC}"
if ! docker ps --format "{{.Names}}" | grep -q "flowcore-postgres"; then
    echo -e "${RED}Error: PostgreSQL not running. Run ./scripts/start-databases.sh first.${NC}"
    exit 1
fi
if ! docker ps --format "{{.Names}}" | grep -q "flowcore-kafka"; then
    echo -e "${RED}Error: Kafka not running. Run ./scripts/start-databases.sh first.${NC}"
    exit 1
fi
echo -e "${GREEN}Databases are running ✓${NC}"
echo ""

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""
for candidate in \
    "${PROJECT_ROOT}/venv/bin/python" \
    "${PROJECT_ROOT}/.venv/bin/python" \
    "python3" \
    "python"; do
    if command -v "$candidate" > /dev/null 2>&1 || [ -f "$candidate" ]; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}Error: Python not found. Set up a venv at ${PROJECT_ROOT}/venv/${NC}"
    exit 1
fi
echo -e "${BLUE}Using Python: ${PYTHON}${NC}"

# ── Load env vars from docker/.env, override hosts to localhost ───────────────
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$')
    set +o allexport
fi

# Override DB/Kafka hosts so services connect to localhost (Docker-exposed ports)
export PG_HOST=localhost
export PG_PORT=5432
export TS_HOST=localhost
export TS_PORT=5433
export NEO4J_HOST=localhost
export NEO4J_BOLT_PORT=7687
export KAFKA_BOOTSTRAP_SERVERS=localhost:19092

# ── Parse flags ───────────────────────────────────────────────────────────────
INCLUDE_REPLAY=false
if [ "$1" = "--replay" ] || [ "$1" = "--with-replay" ]; then
    INCLUDE_REPLAY=true
fi

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"
touch "$PID_FILE"

# ── Helper: start one service ─────────────────────────────────────────────────
start_service() {
    local name="$1"
    local dir="${SERVICES_DIR}/${name}"
    local port="$2"
    local label="$3"

    if [ ! -f "${dir}/main.py" ]; then
        echo -e "${YELLOW}  [SKIP] ${label} — ${dir}/main.py not found${NC}"
        return
    fi

    local log_file="${LOG_DIR}/${name}.log"

    nohup "$PYTHON" -m uvicorn main:app \
        --host 0.0.0.0 \
        --port "$port" \
        --log-level info \
        --app-dir "$dir" \
        > "$log_file" 2>&1 &

    local pid=$!
    echo "${name}:${pid}:${port}" >> "$PID_FILE"
    echo -e "${GREEN}  [OK] ${label} — :${port} (PID ${pid}) → ${log_file}${NC}"
}

# ── Start all services ────────────────────────────────────────────────────────
echo -e "${BLUE}Starting platform services...${NC}"
start_service "dcim-ingestion"   "${DCIM_INGESTION_PORT:-8001}"           "DCIM Ingestion"
start_service "telemetry-gateway" "${TELEMETRY_GATEWAY_HTTP_PORT:-8002}"  "Telemetry Gateway"
start_service "active-discovery" "${ACTIVE_DISCOVERY_PORT:-8003}"         "Active Discovery"
start_service "graph-updater"    "${GRAPH_UPDATER_PORT:-8010}"            "Graph Updater"
start_service "timeseries-writer" "${TIMESERIES_WRITER_PORT:-8011}"       "Timeseries Writer"
start_service "event-archive"    "${EVENT_ARCHIVE_PORT:-8012}"            "Event Archive"

echo ""
echo -e "${BLUE}Starting API services...${NC}"
start_service "graph-api"           "${GRAPH_API_INTERNAL_PORT:-4000}"    "Graph API (GraphQL)"
start_service "insights-api"        "${INSIGHTS_API_INTERNAL_PORT:-4001}" "Insights API"
start_service "eventing-integration" "${EVENTING_API_INTERNAL_PORT:-4002}" "Eventing Integration"

echo ""
echo -e "${BLUE}Starting agent services...${NC}"
start_service "topology-agent"      "${TOPO_AGENT_PORT:-8020}"            "Topology Agent"
start_service "classification-agent" "${CLASS_AGENT_PORT:-8021}"          "Classification Agent"

if $INCLUDE_REPLAY; then
    echo ""
    echo -e "${BLUE}Starting synthetic replay...${NC}"
    start_service "synthetic-replay" "${REPLAY_PORT:-8050}"               "Synthetic Replay"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "${GREEN}  All services started locally${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "${BLUE}Access URLs:${NC}"
echo "  DCIM Ingestion      -> http://localhost:${DCIM_INGESTION_PORT:-8001}"
echo "  Telemetry Gateway   -> http://localhost:${TELEMETRY_GATEWAY_HTTP_PORT:-8002}"
echo "  Active Discovery    -> http://localhost:${ACTIVE_DISCOVERY_PORT:-8003}"
echo "  Graph Updater       -> http://localhost:${GRAPH_UPDATER_PORT:-8010}"
echo "  Timeseries Writer   -> http://localhost:${TIMESERIES_WRITER_PORT:-8011}"
echo "  Event Archive       -> http://localhost:${EVENT_ARCHIVE_PORT:-8012}"
echo "  Graph API (GraphQL) -> http://localhost:${GRAPH_API_INTERNAL_PORT:-4000}/graphql"
echo "  Insights API        -> http://localhost:${INSIGHTS_API_INTERNAL_PORT:-4001}"
echo "  Eventing            -> http://localhost:${EVENTING_API_INTERNAL_PORT:-4002}"
echo "  Topology Agent      -> http://localhost:${TOPO_AGENT_PORT:-8020}"
echo "  Classification Agent-> http://localhost:${CLASS_AGENT_PORT:-8021}"
if $INCLUDE_REPLAY; then
echo "  Synthetic Replay    -> http://localhost:${REPLAY_PORT:-8050}"
fi
echo ""
echo -e "${BLUE}Logs:${NC}  ${LOG_DIR}/<service-name>.log"
echo -e "${BLUE}Stop:${NC}  ./scripts/stop-services.sh"
echo -e "${BLUE}PIDs:${NC}  ${PID_FILE}"
