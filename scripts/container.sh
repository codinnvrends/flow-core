#!/bin/bash
# =============================================================================
# FlowCore Container Manager
# Start/stop/restart all FlowCore Docker containers
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/../docker" && pwd)"
PROJECT_NAME="flowcore"

# Compose files in dependency order
COMPOSE_FILES=(
    "$DOCKER_DIR/docker-compose.yml"
    "$DOCKER_DIR/docker-compose.kafka.yml"
    "$DOCKER_DIR/docker-compose.signoz.yml"
    "$DOCKER_DIR/docker-compose.platform.yml"
    "$DOCKER_DIR/docker-compose.agents.yml"
    "$DOCKER_DIR/docker-compose.api.yml"
    "$DOCKER_DIR/docker-compose.replay.yml"
)

# Build compose command with all files
COMPOSE_CMD="docker compose"
for f in "${COMPOSE_FILES[@]}"; do
    COMPOSE_CMD="$COMPOSE_CMD -f $f"
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✓${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] !${NC} $*"; }
err() { echo -e "${RED}[$(date +%H:%M:%S]) ✗${NC} $*"; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [COMMAND]

Commands:
  start     Start all containers (creates network if needed)
  stop      Stop all containers
  restart   Stop then start all containers
  ps        Show running containers status
  logs      Follow logs from all containers (Ctrl+C to exit)
  down      Stop and remove containers, networks, volumes
  pull      Pull latest images
  build     Rebuild all local images

Examples:
  $(basename "$0") start      # Start everything
  $(basename "$0") stop       # Stop everything
  $(basename "$0") restart    # Full restart
  $(basename "$0") logs       # Watch logs

EOF
    exit 1
}

create_network() {
    if ! docker network ls | grep -q "flowcore_flowcore-net"; then
        log "Creating Docker network: flowcore_flowcore-net"
        docker network create flowcore_flowcore-net
        ok "Network created"
    fi
}

cmd_start() {
    log "Starting FlowCore containers..."
    create_network
    $COMPOSE_CMD --project-name "$PROJECT_NAME" up -d
    ok "Containers started"
    echo
    cmd_ps
}

cmd_stop() {
    log "Stopping FlowCore containers..."
    $COMPOSE_CMD --project-name "$PROJECT_NAME" stop
    ok "Containers stopped"
}

cmd_restart() {
    cmd_stop
    echo
    cmd_start
}

cmd_ps() {
    log "Container status:"
    $COMPOSE_CMD --project-name "$PROJECT_NAME" ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
}

cmd_logs() {
    log "Following logs (Ctrl+C to exit)..."
    $COMPOSE_CMD --project-name "$PROJECT_NAME" logs -f --tail=100
}

cmd_down() {
    warn "This will remove containers, networks, and volumes!"
    read -p "Are you sure? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Removing FlowCore containers..."
        $COMPOSE_CMD --project-name "$PROJECT_NAME" down -v
        ok "Containers and volumes removed"
    else
        log "Cancelled"
    fi
}

cmd_pull() {
    log "Pulling latest images..."
    $COMPOSE_CMD --project-name "$PROJECT_NAME" pull
    ok "Images pulled"
}

cmd_build() {
    log "Building local images..."
    $COMPOSE_CMD --project-name "$PROJECT_NAME" build
    ok "Build complete"
}

# Main
case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    ps)      cmd_ps ;;
    logs)    cmd_logs ;;
    down)    cmd_down ;;
    pull)    cmd_pull ;;
    build)   cmd_build ;;
    *)       usage ;;
esac
