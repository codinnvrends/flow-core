#!/bin/bash
# =============================================================================
# FlowCore — Check Status of Databases + Kafka (Linux/Mac)
# 
# Shows running status of infrastructure services.
#
# Usage:
#   ./scripts/status-databases.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.databases.yml"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore Infrastructure Status${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# Check if containers are running
RUNNING=$(docker compose -f "${COMPOSE_FILE}" ps -q 2>/dev/null | wc -l)

if [ "$RUNNING" -eq 0 ]; then
    echo -e "${YELLOW}No infrastructure containers are currently running.${NC}"
    echo ""
    echo -e "${BLUE}To start:${NC} ./scripts/start-databases.sh"
    exit 0
fi

# Show container status
echo -e "${BLUE}Container Status:${NC}"
docker compose -f "${COMPOSE_FILE}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  Access URLs${NC}"
echo -e "${BLUE}======================================================${NC}"
echo "  Neo4j Browser  -> http://localhost:7474"
echo "  Kafka UI       -> http://localhost:8090"
echo "  PostgreSQL     -> localhost:5432"
echo "  TimescaleDB    -> localhost:5433"
echo "  Kafka          -> localhost:9092 (internal) / 19092 (external)"
