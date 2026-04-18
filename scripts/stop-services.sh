#!/bin/bash
# =============================================================================
# FlowCore — Stop Application Services (Linux/Mac)
#
# Stops all locally-running FlowCore services started by start-services.sh.
# Databases and Kafka (Docker) are left running.
#
# Usage:
#   ./scripts/stop-services.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="/tmp/flowcore-services.pids"
LOG_DIR="/tmp/flowcore-logs"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore — Stopping Application Services${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

STOPPED=0
NOT_FOUND=0

if [ -f "$PID_FILE" ]; then
    while IFS=: read -r name pid port; do
        [ -z "$pid" ] && continue
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            # Give it a moment, then force-kill if still alive
            sleep 0.5
            kill -9 "$pid" 2>/dev/null || true
            echo -e "${GREEN}  [STOPPED] ${name} (PID ${pid}, :${port})${NC}"
            STOPPED=$((STOPPED + 1))
        else
            echo -e "${YELLOW}  [GONE]    ${name} (PID ${pid} already exited)${NC}"
            NOT_FOUND=$((NOT_FOUND + 1))
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
else
    # PID file missing — fall back to killing by port
    echo -e "${YELLOW}No PID file found. Attempting to stop by port...${NC}"
    for port in 8001 8002 8003 8010 8011 8012 4000 4001 4002 8020 8021 8050; do
        pid=$(lsof -ti :"$port" 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null || true
            echo -e "${GREEN}  [STOPPED] :${port} (PID ${pid})${NC}"
            STOPPED=$((STOPPED + 1))
        fi
    done
fi

echo ""
echo -e "${GREEN}Stopped ${STOPPED} service(s).${NC}"
echo -e "${YELLOW}Note: Databases and Kafka (Docker) are still running.${NC}"
echo ""
echo -e "${BLUE}Logs preserved at:${NC} ${LOG_DIR}/"
echo -e "${BLUE}To stop databases:${NC} ./scripts/stop-databases.sh"
