#!/bin/bash
# =============================================================================
# FlowCore — Start Databases + Kafka Only (Linux/Mac)
# 
# Starts ONLY the persistent stores and message bus:
#   - PostgreSQL, TimescaleDB, Neo4j, Kafka, Kafka UI
#
# Does NOT start any application services.
# Use this for local development where you run services natively or in IDE.
#
# Usage:
#   ./scripts/start-databases.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.databases.yml"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore — Starting Databases + Kafka${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${YELLOW}Error: Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Start the infrastructure services
echo -e "${BLUE}Starting PostgreSQL, TimescaleDB, Neo4j, and Kafka...${NC}"
docker compose -f "${COMPOSE_FILE}" up -d

# Wait for services to be healthy
echo ""
echo -e "${BLUE}Waiting for services to be healthy...${NC}"
sleep 5

# Check status
echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  FlowCore Infrastructure Status${NC}"
echo -e "${BLUE}======================================================${NC}"
docker compose -f "${COMPOSE_FILE}" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo -e "${GREEN}Infrastructure services are starting...${NC}"
echo ""
echo -e "${BLUE}Access URLs:${NC}"
echo "  Neo4j Browser  -> http://localhost:7474"
echo "  Kafka UI       -> http://localhost:8090"
echo "  PostgreSQL     -> localhost:5432"
echo "  TimescaleDB    -> localhost:5433"
echo "  Kafka          -> localhost:9092 (internal) / 19092 (external)"
echo ""
echo -e "${BLUE}To stop:${NC} ./scripts/stop-databases.sh"
