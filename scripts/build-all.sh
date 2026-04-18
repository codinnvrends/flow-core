#!/usr/bin/env bash
# =============================================================================
# FlowCore — Build All Images (no-cache, no teardown)
#
# Rebuilds all Docker images from source WITHOUT stopping containers or wiping
# data. Use this after code changes when you want a fresh image build.
#
# To apply the new images you must restart the relevant containers after this:
#   ./scripts/stack.sh restart <platform|agents|api-ui|replay>
#
# Usage:
#   ./scripts/build-all.sh                  # rebuild all 4 images
#   ./scripts/build-all.sh platform         # rebuild only platform
#   ./scripts/build-all.sh agents           # rebuild only agents
#   ./scripts/build-all.sh api-ui           # rebuild only api-ui (incl. React)
#   ./scripts/build-all.sh replay           # rebuild only replay
#   ./scripts/build-all.sh --with-cache     # use Docker layer cache (faster)
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
  C='\033[0;36m'; W='\033[1m'; B='\033[0;34m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; B=''; N=''
fi

log()   { echo -e "${C}[$(date '+%H:%M:%S')]${N} $*"; }
ok()    { echo -e "${G}[$(date '+%H:%M:%S')] ✔ $*${N}"; }
warn()  { echo -e "${Y}[$(date '+%H:%M:%S')] ! $*${N}"; }
err()   { echo -e "${R}[$(date '+%H:%M:%S')] ✘ $*${N}"; exit 1; }
hdr()   {
  echo -e "\n${W}${B}======================================================"
  echo -e "  $*"
  echo -e "======================================================${N}\n"
}
elapsed() { echo -e "  ${Y}($(( $(date +%s) - START_TS ))s elapsed)${N}"; }

# ── Parse args ────────────────────────────────────────────────────────────────
TARGET="${1:-all}"
NO_CACHE="--no-cache"
for arg in "$@"; do [[ "$arg" == "--with-cache" ]] && NO_CACHE=""; done
[[ "$TARGET" == "--with-cache" ]] && TARGET="all"

# ── Detect compose ────────────────────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else err "docker compose not found"; fi

command -v docker >/dev/null 2>&1 || err "Docker not found"
docker info >/dev/null 2>&1       || err "Docker daemon not running"

# ── Compose file references ───────────────────────────────────────────────────
F_STORES="$DOCKER_DIR/docker-compose.yml"
F_KAFKA="$DOCKER_DIR/docker-compose.kafka.yml"
F_PLATFORM="$DOCKER_DIR/docker-compose.platform.yml"
F_AGENTS="$DOCKER_DIR/docker-compose.agents.yml"
F_API="$DOCKER_DIR/docker-compose.api.yml"
F_REPLAY="$DOCKER_DIR/docker-compose.replay.yml"

BUILD_OPTS="${NO_CACHE}"
[[ -n "$NO_CACHE" ]] && CACHE_MSG="(no-cache)" || CACHE_MSG="(with-cache)"

# ── Build functions ───────────────────────────────────────────────────────────
build_platform() {
  hdr "Building: platform $CACHE_MSG"
  START_TS=$(date +%s)
  $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" \
      --env-file "$ENV_FILE" build $BUILD_OPTS platform
  elapsed
  ok "Platform image built → flowcore/platform:local"
}

build_agents() {
  hdr "Building: agents $CACHE_MSG"
  START_TS=$(date +%s)
  $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" \
      --env-file "$ENV_FILE" build $BUILD_OPTS agents
  elapsed
  ok "Agents image built → flowcore/agents:local"
}

build_api_ui() {
  hdr "Building: api-ui $CACHE_MSG (includes React frontend build)"
  START_TS=$(date +%s)
  $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_PLATFORM" -f "$F_AGENTS" -f "$F_API" \
      --env-file "$ENV_FILE" build $BUILD_OPTS api-ui
  elapsed
  ok "API+UI image built → flowcore/api-ui:local"
}

build_replay() {
  hdr "Building: synthetic-replay $CACHE_MSG"
  START_TS=$(date +%s)
  $DC -f "$F_STORES" -f "$F_KAFKA" -f "$F_REPLAY" \
      --env-file "$ENV_FILE" build $BUILD_OPTS synthetic-replay
  elapsed
  ok "Replay image built → flowcore/synthetic-replay:local"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
TOTAL_START=$(date +%s)

case "$TARGET" in
  all)
    hdr "FlowCore — Clean Build All Images $CACHE_MSG"
    warn "Running --no-cache builds. This will take several minutes."
    echo  "  Running services will NOT be stopped."
    echo  "  Restart containers after this to pick up new images:"
    echo  "    ./scripts/stack.sh restart <platform|agents|api-ui|replay>"
    echo ""
    build_platform
    build_agents
    build_api_ui
    build_replay
    hdr "All Builds Complete"
    echo -e "  Total time: $(( $(date +%s) - TOTAL_START ))s"
    echo ""
    echo "  Images built:"
    echo "    flowcore/platform:local"
    echo "    flowcore/agents:local"
    echo "    flowcore/api-ui:local"
    echo "    flowcore/synthetic-replay:local"
    echo ""
    echo "  Next step — restart containers to pick up new images:"
    echo "    ./scripts/stack.sh restart platform"
    echo "    ./scripts/stack.sh restart agents"
    echo "    ./scripts/stack.sh restart api-ui"
    echo "    ./scripts/stack.sh restart replay"
    ;;
  platform)
    build_platform ;;
  agents)
    build_agents ;;
  api-ui|apiui|api|ui)
    build_api_ui ;;
  replay|synthetic-replay)
    build_replay ;;
  *)
    err "Unknown target: '$TARGET'. Use: all | platform | agents | api-ui | replay"
    ;;
esac
