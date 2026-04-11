#!/usr/bin/env bash
# =============================================================================
# FlowCore — Full Clean Rebuild Script
#
# Wipes all containers + volumes, rebuilds all Docker images from scratch,
# seeds the databases, and launches the full stack.
#
# Usage:
#   ./scripts/rebuild.sh              # full rebuild (regenerates synthetic data)
#   ./scripts/rebuild.sh --skip-generate  # reuse existing seed files (faster)
#
# Run from the flowcore/ root directory.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOWCORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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
  echo -e "\n${W}${B}======================================================"
  echo -e "  $*"
  echo -e "======================================================${N}\n"
}

# ── Parse args ────────────────────────────────────────────────────────────────
SKIP_GENERATE=""
for arg in "$@"; do
  [[ "$arg" == "--skip-generate" ]] && SKIP_GENERATE="--skip-generate"
done

hdr "FlowCore — Full Clean Rebuild"

# ── Step 1: Shutdown all containers + wipe volumes ────────────────────────────
hdr "Step 1/3 — Stopping all containers and wiping volumes"
"$SCRIPT_DIR/stack.sh" down -v
ok "All containers stopped and volumes wiped"

# Remove dangling Docker network if leftover
if docker network inspect flowcore_flowcore-net >/dev/null 2>&1; then
  log "Removing leftover flowcore_flowcore-net network..."
  docker network rm flowcore_flowcore-net >/dev/null 2>&1 || true
fi

# ── Step 2: Rebuild all images from scratch ───────────────────────────────────
hdr "Step 2/3 — Building all Docker images (no cache)"

DOCKER_DIR="$FLOWCORE_DIR/docker"
ENV_FILE="$DOCKER_DIR/.env"

if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  err "docker compose not found"
fi

F_STORES="$DOCKER_DIR/docker-compose.yml"
F_KAFKA="$DOCKER_DIR/docker-compose.kafka.yml"
F_PLATFORM="$DOCKER_DIR/docker-compose.platform.yml"
F_AGENTS="$DOCKER_DIR/docker-compose.agents.yml"
F_API="$DOCKER_DIR/docker-compose.api.yml"
F_REPLAY="$DOCKER_DIR/docker-compose.replay.yml"

log "Building platform image..."
$DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" --env-file "$ENV_FILE" \
  build --no-cache platform

log "Building agents image..."
$DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" --env-file "$ENV_FILE" \
  build --no-cache agents

log "Building api-ui image..."
$DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" -f "$F_API" --env-file "$ENV_FILE" \
  build --no-cache api-ui

log "Building replay image..."
$DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_REPLAY" --env-file "$ENV_FILE" \
  build --no-cache synthetic-replay

ok "All images built successfully"

# ── Step 3: Bootstrap data + launch full stack ────────────────────────────────
hdr "Step 3/3 — Bootstrapping data and launching full stack"
"$SCRIPT_DIR/run_all.sh" $SKIP_GENERATE

ok "Full rebuild complete!"
