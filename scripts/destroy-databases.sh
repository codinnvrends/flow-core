#!/usr/bin/env bash
# =============================================================================
# FlowCore — Destroy Databases (Nuke Data Tier Only)
#
# Stops and removes ONLY the infrastructure containers (PostgreSQL, TimescaleDB,
# Neo4j, Kafka) and their volumes. Application services are unaffected.
#
# Usage:
#   ./scripts/destroy-databases.sh              # interactive confirmation
#   ./scripts/destroy-databases.sh --force      # skip confirmation
#
# Run from the flowcore/ root directory.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOWCORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$FLOWCORE_DIR/docker"

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  C='\033[0;36m'; W='\033[1m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; N=''
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

FORCE=false
for arg in "$@"; do [[ "$arg" == "--force" ]] && FORCE=true; done

F_DB="$DOCKER_DIR/docker-compose.databases.yml"

if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else err "docker compose not found"; fi

hdr "FlowCore — DESTROY DATABASES"

echo -e "${R}${W}WARNING: This will permanently delete:${N}"
echo "  • flowcore-postgres  (PostgreSQL data)"
echo "  • flowcore-timescaledb (TimescaleDB data)"
echo "  • flowcore-neo4j     (Neo4j graph data)"
echo "  • flowcore-kafka     (Kafka/Redpanda data + topics)"
echo "  • flowcore-kafka-ui"
echo "  • flowcore-kafka-init"
echo "  • All associated Docker volumes (ALL DATA WILL BE LOST)"
echo ""

if [[ "$FORCE" != "true" ]]; then
  read -rp "Are you sure you want to destroy all database data? [y/N] " CONFIRM
  echo
  [[ "${CONFIRM,,}" =~ ^y(es)?$ ]] || { log "Cancelled."; exit 0; }
fi

log "Stopping and removing database containers + volumes..."
$DC -f "$F_DB" down -v

ok "All database containers and volumes removed"
echo ""
echo "  PostgreSQL, TimescaleDB, Neo4j, and Kafka data has been wiped."
echo "  To re-initialise databases, run:"
echo "    ./scripts/start-databases.sh       # restart empty databases"
echo "    ./scripts/run_all.sh               # restart + seed with synthetic data"
echo ""
