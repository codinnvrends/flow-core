#!/usr/bin/env bash
# =============================================================================
# FlowCore — Destroy All (Nuke Everything)
#
# Stops ALL containers, removes ALL volumes, and deletes the shared network.
# This is a DESTRUCTIVE operation — all data will be lost.
#
# Usage:
#   ./scripts/destroy-all.sh              # interactive confirmation
#   ./scripts/destroy-all.sh --force      # skip confirmation
#   ./scripts/destroy-all.sh --purge-images  # also remove built images
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
  B='\033[0;34m'; C='\033[0;36m'; W='\033[1m'; N='\033[0m'
else
  R=''; G=''; Y=''; B=''; C=''; W=''; N=''
fi

log()  { echo -e "${C}[$(date '+%H:%M:%S')]${N} $*"; }
ok()   { echo -e "${G}[$(date '+%H:%M:%S')] ✔ $*${N}"; }
warn() { echo -e "${Y}[$(date '+%H:%M:%S')] ! $*${N}"; }
err()  { echo -e "${R}[$(date '+%H:%M:%S')] ✘ $*${N}"; exit 1; }
hdr()  {
  echo -e "\n${W}${R}======================================================"
  echo -e "  $*"
  echo -e "======================================================${N}\n"
}

# ── Parse args ────────────────────────────────────────────────────────────────
FORCE=false
PURGE_IMAGES=false
for arg in "$@"; do
  [[ "$arg" == "--force" ]]        && FORCE=true
  [[ "$arg" == "--purge-images" ]] && PURGE_IMAGES=true
done

# ── Detect compose ────────────────────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else err "docker compose not found"; fi

F_FULL="$DOCKER_DIR/docker-compose.full.yml"
F_DB="$DOCKER_DIR/docker-compose.databases.yml"

hdr "FlowCore — DESTROY ALL"

echo -e "${R}${W}WARNING: This will permanently delete:${N}"
echo "  • All FlowCore Docker containers"
echo "  • All FlowCore Docker volumes (ALL DATA WILL BE LOST)"
echo "  • The flowcore_flowcore-net Docker network"
if [[ "$PURGE_IMAGES" == "true" ]]; then
  echo "  • All locally-built FlowCore images (platform, agents, api-ui, replay)"
fi
echo ""

if [[ "$FORCE" != "true" ]]; then
  read -rp "Are you sure you want to destroy everything? [y/N] " CONFIRM
  echo
  [[ "${CONFIRM,,}" =~ ^y(es)?$ ]] || { log "Cancelled."; exit 0; }
fi

# ── Step 1: Graceful compose teardown (15s timeout, output visible) ───────────
log "Step 1/3 — Stopping all containers and wiping all volumes..."
$DC -f "$F_FULL" --env-file "$ENV_FILE" down -v --timeout 15 --remove-orphans 2>&1 || \
  { warn "full.yml down had errors — continuing with direct teardown"; }
$DC -f "$F_DB" down -v --timeout 15 --remove-orphans 2>&1 || true

# ── Step 2: Force-remove any containers still running ─────────────────────────
log "Step 2/3 — Force-removing any remaining FlowCore containers..."
STRAY=$(docker ps -aq --filter "name=flowcore" 2>/dev/null || true)
if [[ -n "$STRAY" ]]; then
  # shellcheck disable=SC2086
  docker rm -f $STRAY 2>/dev/null || true
  ok "Remaining containers removed"
else
  log "  No remaining containers found"
fi

# ── Remove named volumes explicitly (belt-and-suspenders) ─────────────────────
log "  Removing named volumes..."
for vol in postgres_data timescale_data neo4j_data neo4j_logs kafka_data; do
  docker volume rm "${vol}" 2>/dev/null && log "  Removed volume: ${vol}" || true
done

# ── Step 3: Remove shared Docker network ─────────────────────────────────────
log "Step 3/3 — Removing Docker network..."
if docker network inspect flowcore_flowcore-net >/dev/null 2>&1; then
  docker network rm flowcore_flowcore-net >/dev/null 2>&1 && ok "Network flowcore_flowcore-net removed" || warn "Could not remove network (may still have endpoints)"
else
  log "  Network flowcore_flowcore-net not found — already gone"
fi

# ── Optional: purge built images ──────────────────────────────────────────────
if [[ "$PURGE_IMAGES" == "true" ]]; then
  log "Purging locally-built FlowCore images..."
  for img in flowcore/platform:local flowcore/agents:local flowcore/api-ui:local flowcore/synthetic-replay:local; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      docker rmi "$img" && ok "Removed $img" || warn "Could not remove $img"
    fi
  done
fi

# ── Summary ───────────────────────────────────────────────────────────────────
hdr "Destroy Complete"
echo -e "${W}All FlowCore data, containers, and volumes have been removed.${N}"
echo ""
echo -e "To rebuild from scratch:"
echo "  ./scripts/rebuild.sh              # full rebuild + data generation"
echo "  ./scripts/stack.sh up             # start stack (existing images)"
echo "  ./scripts/start-databases.sh      # start databases only"
echo ""
