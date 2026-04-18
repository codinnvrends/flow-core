#!/usr/bin/env bash
# =============================================================================
# FlowCore — Rebuild + Redeploy Service(s)
#
# Rebuilds one or all service Docker images from source and recreates the
# running containers to pick up the new code.
#
# Does NOT touch databases, volumes, or Kafka.
# Does NOT run data generation or schema migration.
#
# Workflow per service:
#   1. Build new Docker image (delegates to build-all.sh)
#   2. Recreate container with --force-recreate (picks up new image)
#
# Usage:
#   ./scripts/rebuild.sh                  # rebuild + redeploy all 4 services
#   ./scripts/rebuild.sh platform         # rebuild + redeploy platform only
#   ./scripts/rebuild.sh agents           # rebuild + redeploy agents only
#   ./scripts/rebuild.sh api-ui           # rebuild + redeploy api-ui only
#   ./scripts/rebuild.sh replay           # rebuild + redeploy replay only
#   ./scripts/rebuild.sh --with-cache     # use Docker layer cache (faster)
#
# Run from the project root directory.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/../docker" && pwd)"
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
  echo -e "\n${W}${B}======================================================"
  echo -e "  $*"
  echo -e "======================================================${N}\n"
}

# ── Parse args ────────────────────────────────────────────────────────────────
TARGET="all"
CACHE_FLAG=""

for arg in "$@"; do
  case "$arg" in
    --with-cache) CACHE_FLAG="--with-cache" ;;
    all|platform|agents|api-ui|apiui|api|ui|replay|synthetic-replay) TARGET="$arg" ;;
    *) err "Unknown argument: '$arg'. Usage: rebuild.sh [all|platform|agents|api-ui|replay] [--with-cache]" ;;
  esac
done

# ── Sanity checks ─────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || err "Docker not found"
docker info >/dev/null 2>&1       || err "Docker daemon is not running"

if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else err "docker compose not found"; fi

# ── Compose file references (for force-recreate step) ─────────────────────────
F_STORES="$DOCKER_DIR/docker-compose.yml"
F_KAFKA="$DOCKER_DIR/docker-compose.kafka.yml"
F_PLATFORM="$DOCKER_DIR/docker-compose.platform.yml"
F_AGENTS="$DOCKER_DIR/docker-compose.agents.yml"
F_API="$DOCKER_DIR/docker-compose.api.yml"
F_REPLAY="$DOCKER_DIR/docker-compose.replay.yml"

# ── Helpers ───────────────────────────────────────────────────────────────────
is_running() {
  docker inspect --format='{{.State.Status}}' "$1" 2>/dev/null | grep -q "running"
}

recreate() {
  local service="$1" compose_files="$2" container="$3"
  if is_running "$container"; then
    log "Recreating $service container..."
    # shellcheck disable=SC2086
    $DC $compose_files --env-file "$ENV_FILE" up -d --force-recreate "$service"
    ok "$service redeployed"
  else
    warn "$container is not running — skipping recreate (start it with: stack.sh up)"
  fi
}

# ── Step 1: Build ─────────────────────────────────────────────────────────────
hdr "Step 1/2 — Build"
log "Delegating to build-all.sh ${TARGET} ${CACHE_FLAG}..."
"$SCRIPT_DIR/build-all.sh" "$TARGET" $CACHE_FLAG

# ── Step 2: Recreate containers ───────────────────────────────────────────────
hdr "Step 2/2 — Redeploy"

case "$TARGET" in
  all)
    recreate "platform" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM" \
      "flowcore-platform"

    recreate "agents" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM -f $F_AGENTS" \
      "flowcore-agents"

    recreate "api-ui" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM -f $F_AGENTS -f $F_API" \
      "flowcore-api-ui"

    recreate "synthetic-replay" \
      "-f $F_STORES -f $F_KAFKA -f $F_REPLAY" \
      "flowcore-replay"
    ;;

  platform)
    recreate "platform" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM" \
      "flowcore-platform"
    ;;

  agents)
    recreate "agents" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM -f $F_AGENTS" \
      "flowcore-agents"
    ;;

  api-ui|apiui|api|ui)
    recreate "api-ui" \
      "-f $F_STORES -f $F_KAFKA -f $F_PLATFORM -f $F_AGENTS -f $F_API" \
      "flowcore-api-ui"
    ;;

  replay|synthetic-replay)
    recreate "synthetic-replay" \
      "-f $F_STORES -f $F_KAFKA -f $F_REPLAY" \
      "flowcore-replay"
    ;;
esac

# ── Summary ───────────────────────────────────────────────────────────────────
hdr "Rebuild Complete"
echo -e "  ${W}Target:${N}  ${TARGET}"
echo -e "  ${W}Cache:${N}   ${CACHE_FLAG:-no-cache (default)}"
echo ""
echo "  Databases and volumes were not touched."
echo ""
echo -e "  ${B}Check status:${N}  ./scripts/stack.sh status"
echo -e "  ${B}View logs:${N}     ./scripts/stack.sh logs <platform|agents|api-ui|replay>"
echo ""
