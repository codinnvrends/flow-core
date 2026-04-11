#!/usr/bin/env bash
# =============================================================================
# FlowCore — Local Stack Management Script
# Run from the flowcore/ root directory.
#
# Usage:
#   ./scripts/stack.sh up          # start full stack (Option A with replay)
#   ./scripts/stack.sh up --no-replay   # start without synthetic replay
#   ./scripts/stack.sh down        # stop all containers (keep volumes)
#   ./scripts/stack.sh down -v     # stop and wipe all data
#   ./scripts/stack.sh build       # rebuild all images
#   ./scripts/stack.sh restart <group>  # restart one group
#   ./scripts/stack.sh logs <group>     # tail logs for a group
#   ./scripts/stack.sh status      # show all container states + ports
#   ./scripts/stack.sh stores      # start stores only
#   ./scripts/stack.sh ps          # show running containers
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOWCORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$FLOWCORE_DIR/docker"

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  B='\033[0;34m'; C='\033[0;36m'; W='\033[1m'; N='\033[0m'
else
  R=''; G=''; Y=''; B=''; C=''; W=''; N=''
fi

log()  { echo -e "${C}[$(date '+%H:%M:%S')]${N} $*"; }
ok()   { echo -e "${G}[$(date '+%H:%M:%S')] v $*${N}"; }
warn() { echo -e "${Y}[$(date '+%H:%M:%S')] ! $*${N}"; }
err()  { echo -e "${R}[$(date '+%H:%M:%S')] X $*${N}"; exit 1; }
hdr()  { echo -e "\n${W}${B}======================================================${N}"; \
         echo -e "${W}${B}  $*${N}"; \
         echo -e "${W}${B}======================================================${N}\n"; }

# ── Compose command detection ─────────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  err "docker compose not found"
fi

# ── File references ───────────────────────────────────────────────────────────
F_STORES="$DOCKER_DIR/docker-compose.yml"
F_KAFKA="$DOCKER_DIR/docker-compose.kafka.yml"
F_PLATFORM="$DOCKER_DIR/docker-compose.platform.yml"
F_REPLAY="$DOCKER_DIR/docker-compose.replay.yml"
F_AGENTS="$DOCKER_DIR/docker-compose.agents.yml"
F_API="$DOCKER_DIR/docker-compose.api.yml"
F_FULL="$DOCKER_DIR/docker-compose.full.yml"
ENV_FILE="$DOCKER_DIR/.env"

# ── Ensure network exists (stores compose creates it; other files reference it)
ensure_network() {
  if ! docker network inspect flowcore_flowcore-net >/dev/null 2>&1; then
    log "Creating flowcore_flowcore-net network..."
    docker network create flowcore_flowcore-net >/dev/null
  fi
}

CMD="${1:-help}"
shift || true

case "$CMD" in

  # ── Full stack up ─────────────────────────────────────────────────────────
  up)
    NO_REPLAY=false
    for arg in "$@"; do [[ "$arg" == "--no-replay" ]] && NO_REPLAY=true; done

    hdr "Starting FlowCore local stack"
    command -v docker >/dev/null 2>&1 || err "Docker not found"
    docker info >/dev/null 2>&1       || err "Docker daemon not running"

    # Step 1 — Stores (creates the shared network)
    log "Step 1/5 — Persistent stores (PostgreSQL, TimescaleDB, Neo4j)..."
    $DC -f "$F_STORES" --env-file "$ENV_FILE" up -d
    log "Waiting for stores to be ready..."
    sleep 10
    for ctr in flowcore-postgres flowcore-timescaledb flowcore-neo4j; do
      for i in $(seq 1 30); do
        if docker inspect --format='{{.State.Health.Status}}' "$ctr" 2>/dev/null | grep -q healthy; then
          ok "$ctr healthy"; break
        fi
        sleep 3
        [[ $i -eq 30 ]] && warn "$ctr not healthy after 90s — continuing anyway"
      done
    done

    # Step 2 — Kafka
    log "Step 2/5 — Kafka (Redpanda + topic init)..."
    ensure_network
    $DC -f "$F_STORES" -f "$F_KAFKA" --env-file "$ENV_FILE" up -d kafka
    log "Waiting for Kafka to be ready..."
    for i in $(seq 1 30); do
      if MSYS_NO_PATHCONV=1 docker exec flowcore-kafka rpk cluster health \
           2>/dev/null | grep -q "Healthy:.*true"; then
        ok "Kafka healthy"; break
      fi
      sleep 4
      [[ $i -eq 30 ]] && warn "Kafka not healthy after 120s — continuing anyway"
    done
    $DC -f "$F_STORES" -f "$F_KAFKA" --env-file "$ENV_FILE" up -d kafka-init
    log "Waiting for topic init to complete..."
    for i in $(seq 1 20); do
      status=$(docker inspect --format='{{.State.Status}}' flowcore-kafka-init 2>/dev/null || echo "missing")
      [[ "$status" == "exited" ]] && { ok "Kafka topics created"; break; }
      sleep 3
      [[ $i -eq 20 ]] && warn "kafka-init did not complete in 60s"
    done

    # Step 3 — Platform + optional replay (parallel)
    log "Step 3/5 — Platform services (Keycloak + ingestion + processing)..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" --env-file "$ENV_FILE" up -d platform
    if [[ "$NO_REPLAY" == "false" ]]; then
      log "          Synthetic replay (Option A)..."
      $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_REPLAY" --env-file "$ENV_FILE" up -d synthetic-replay
    fi
    log "Waiting for platform to be healthy (may take 60s for Keycloak)..."
    for i in $(seq 1 40); do
      if docker inspect --format='{{.State.Health.Status}}' flowcore-platform \
           2>/dev/null | grep -q healthy; then
        ok "Platform healthy"; break
      fi
      sleep 5
      [[ $((i % 6)) -eq 0 ]] && log "  still waiting ($((i*5))s)..."
      [[ $i -eq 40 ]] && warn "Platform not healthy after 200s — continuing anyway"
    done

    # Step 4 — Agents
    log "Step 4/5 — AI agents (topology + classification + MLflow)..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" \
        --env-file "$ENV_FILE" up -d agents
    log "Waiting for agents..."
    for i in $(seq 1 20); do
      if docker inspect --format='{{.State.Health.Status}}' flowcore-agents \
           2>/dev/null | grep -q healthy; then
        ok "Agents healthy"; break
      fi
      sleep 5
      [[ $i -eq 20 ]] && warn "Agents not healthy after 100s — continuing anyway"
    done

    # Step 5 — API + UI
    log "Step 5/5 — API gateway + NOC frontend..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" -f "$F_API" \
        --env-file "$ENV_FILE" up -d api-ui
    log "Waiting for API + UI..."
    for i in $(seq 1 20); do
      if docker inspect --format='{{.State.Health.Status}}' flowcore-api-ui \
           2>/dev/null | grep -q healthy; then
        ok "API + UI healthy"; break
      fi
      sleep 5
      [[ $i -eq 20 ]] && warn "API+UI not healthy after 100s"
    done

    hdr "Stack Ready"
    echo -e "${W}Service endpoints:${N}"
    echo "  NOC Frontend     ->  http://localhost:${API_GATEWAY_PORT:-8888}/"
    echo "  GraphQL          ->  http://localhost:${API_GATEWAY_PORT:-8888}/graphql"
    echo "  Insights API     ->  http://localhost:${API_GATEWAY_PORT:-8888}/api/insights/"
    echo "  Kafka UI         ->  http://localhost:${REDPANDA_UI_PORT:-8090}/"
    echo "  MLflow           ->  http://localhost:${MLFLOW_PORT:-5000}/"
    echo "  Keycloak         ->  http://localhost:${KEYCLOAK_PORT:-8080}/"
    echo "  Replay control   ->  http://localhost:${REPLAY_PORT:-8050}/status"
    echo ""
    echo -e "${W}Test credentials:${N}"
    echo "  noc-operator / operator123"
    echo "  change-manager / manager123"
    echo "  dc-admin / dcadmin123"
    echo "  platform-admin / platformadmin123"
    echo ""
    $DC -f "$F_FULL" --env-file "$ENV_FILE" ps
    ;;

  # ── Stores only ───────────────────────────────────────────────────────────
  stores)
    hdr "Starting persistent stores only"
    $DC -f "$F_STORES" --env-file "$ENV_FILE" up -d
    ok "Stores started (postgres :5432, timescaledb :5433, neo4j :7474/:7687)"
    ;;

  # ── Down ──────────────────────────────────────────────────────────────────
  down)
    hdr "Stopping FlowCore stack"
    EXTRA_ARGS="$*"
    $DC -f "$F_FULL" --env-file "$ENV_FILE" down $EXTRA_ARGS
    if echo "$EXTRA_ARGS" | grep -q "\-v"; then
      ok "Stack stopped and all volumes wiped."
    else
      ok "Stack stopped. Data volumes preserved. Use 'down -v' to wipe data."
    fi
    ;;

  # ── Build ─────────────────────────────────────────────────────────────────
  build)
    hdr "Building all FlowCore images"
    log "Building platform image..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" --env-file "$ENV_FILE" build platform
    log "Building agents image..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" --env-file "$ENV_FILE" build agents
    log "Building api-ui image..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" -f "$F_API" --env-file "$ENV_FILE" build api-ui
    log "Building replay image..."
    $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_REPLAY" --env-file "$ENV_FILE" build synthetic-replay
    ok "All images built."
    ;;

  # ── Restart a group ───────────────────────────────────────────────────────
  restart)
    GROUP="${1:-}"
    [[ -z "$GROUP" ]] && err "Usage: stack.sh restart <stores|kafka|platform|agents|api-ui|replay>"
    case "$GROUP" in
      stores)   $DC -f "$F_STORES" --env-file "$ENV_FILE" restart ;;
      kafka)    $DC -f "$F_STORES" -f "$F_KAFKA" --env-file "$ENV_FILE" restart kafka ;;
      platform) $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" --env-file "$ENV_FILE" restart platform ;;
      agents)   $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" --env-file "$ENV_FILE" restart agents ;;
      api-ui)   $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" -f "$F_API" --env-file "$ENV_FILE" restart api-ui ;;
      replay)   $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_REPLAY" --env-file "$ENV_FILE" restart synthetic-replay ;;
      *) err "Unknown group: $GROUP" ;;
    esac
    ok "$GROUP restarted."
    ;;

  # ── Logs ──────────────────────────────────────────────────────────────────
  logs)
    GROUP="${1:-}"
    CTR=""
    case "$GROUP" in
      stores|postgres)    CTR="flowcore-postgres" ;;
      timescaledb)        CTR="flowcore-timescaledb" ;;
      neo4j)              CTR="flowcore-neo4j" ;;
      kafka)              CTR="flowcore-kafka" ;;
      platform)           CTR="flowcore-platform" ;;
      agents)             CTR="flowcore-agents" ;;
      api-ui|api|ui)      CTR="flowcore-api-ui" ;;
      replay)             CTR="flowcore-replay" ;;
      all|"")             $DC -f "$F_FULL" --env-file "$ENV_FILE" logs -f; exit 0 ;;
      *) err "Unknown group: $GROUP. Use: stores kafka platform agents api-ui replay all" ;;
    esac
    docker logs -f "$CTR"
    ;;

  # ── Status ────────────────────────────────────────────────────────────────
  status|ps)
    hdr "FlowCore Container Status"
    echo -e "${W}Container          Status          Ports${N}"
    echo "--------------------------------------------------------------"
    for ctr in \
      flowcore-postgres \
      flowcore-timescaledb \
      flowcore-neo4j \
      flowcore-kafka \
      flowcore-kafka-init \
      flowcore-platform \
      flowcore-replay \
      flowcore-agents \
      flowcore-api-ui; do
      status=$(docker inspect --format='{{.State.Status}}' "$ctr" 2>/dev/null || echo "not found")
      health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' \
               "$ctr" 2>/dev/null || echo "-")
      ports=$(docker inspect --format='{{range $p,$b := .NetworkSettings.Ports}}{{if $b}}{{(index $b 0).HostPort}}->{{$p}} {{end}}{{end}}' \
              "$ctr" 2>/dev/null | tr -s ' ' | head -c 60 || echo "")
      color="$G"
      [[ "$status" != "running" ]] && color="$Y"
      [[ "$status" == "not found" ]] && color="$R"
      printf "${color}%-25s %-12s %-10s${N} %s\n" "$ctr" "$status" "$health" "$ports"
    done
    echo ""
    echo -e "${W}Endpoints (when running):${N}"
    ENV_PORT_API=$(grep "^API_GATEWAY_PORT" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8888")
    ENV_PORT_KAFKA=$(grep "^REDPANDA_UI_PORT" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8090")
    ENV_PORT_MLFLOW=$(grep "^MLFLOW_PORT" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "5000")
    ENV_PORT_KC=$(grep "^KEYCLOAK_PORT" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "8080")
    echo "  NOC UI + APIs  ->  http://localhost:${ENV_PORT_API}/"
    echo "  Kafka UI       ->  http://localhost:${ENV_PORT_KAFKA}/"
    echo "  MLflow         ->  http://localhost:${ENV_PORT_MLFLOW}/"
    echo "  Keycloak       ->  http://localhost:${ENV_PORT_KC}/"
    ;;

  # ── Help ──────────────────────────────────────────────────────────────────
  help|*)
    echo ""
    echo -e "${W}FlowCore Local Stack Manager${N}"
    echo ""
    echo -e "  ${C}./scripts/stack.sh up${N}                    Start full stack (Option A)"
    echo -e "  ${C}./scripts/stack.sh up --no-replay${N}        Start without synthetic replay"
    echo -e "  ${C}./scripts/stack.sh stores${N}                Start stores only"
    echo -e "  ${C}./scripts/stack.sh down${N}                  Stop all (keep data)"
    echo -e "  ${C}./scripts/stack.sh down -v${N}               Stop and wipe all volumes"
    echo -e "  ${C}./scripts/stack.sh build${N}                 Rebuild all images"
    echo -e "  ${C}./scripts/stack.sh restart <group>${N}       Restart one group"
    echo -e "  ${C}./scripts/stack.sh logs <group>${N}          Tail logs for a group"
    echo -e "  ${C}./scripts/stack.sh status${N}                Show all container states"
    echo ""
    echo -e "  Groups: ${Y}stores  kafka  platform  agents  api-ui  replay  all${N}"
    echo ""
    ;;
esac
