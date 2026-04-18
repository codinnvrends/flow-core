#!/bin/bash
# =============================================================================
# FlowCore — Stop Databases + Kafka (Linux/Mac)
# 
# Stops the persistent stores and message bus.
# Data volumes are preserved for next restart.
#
# Usage:
#   ./scripts/stop-databases.sh
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
echo -e "${BLUE}  FlowCore — Stopping Databases + Kafka${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

docker compose -f "${COMPOSE_FILE}" down

echo ""
echo -e "${GREEN}Infrastructure services stopped.${NC}"
echo -e "${YELLOW}Note: Data volumes are preserved. Use 'docker volume rm' to delete data.${NC}"
