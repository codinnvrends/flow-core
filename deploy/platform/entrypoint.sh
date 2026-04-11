#!/usr/bin/env bash
# =============================================================================
# FlowCore Platform Container — Entrypoint
# Waits for Kafka and all stores to be reachable before starting supervisord.
# This ensures no service crashes on startup due to missing dependencies.
# =============================================================================

set -e

log() { echo "[$(date '+%H:%M:%S')] [platform] $*"; }

wait_tcp() {
  local host="$1" port="$2" label="$3" attempts="${4:-60}"
  log "Waiting for $label ($host:$port)..."
  local i=0
  while ! nc -z "$host" "$port" 2>/dev/null; do
    i=$((i+1))
    [ $i -ge $attempts ] && { log "ERROR: $label not reachable after ${attempts}s"; exit 1; }
    sleep 1
  done
  log "$label is reachable"
}

# ── Wait for persistent stores ────────────────────────────────────────────────
wait_tcp "${POSTGRES_HOST}"  "${POSTGRES_PORT}"    "PostgreSQL"
wait_tcp "${TIMESCALE_HOST}" "${TIMESCALE_PORT}"   "TimescaleDB"
wait_tcp "${NEO4J_HOST}"     "${NEO4J_BOLT_PORT}"  "Neo4j Bolt"

# ── Wait for Kafka ────────────────────────────────────────────────────────────
KAFKA_HOST="${KAFKA_BOOTSTRAP%%:*}"
KAFKA_PORT="${KAFKA_BOOTSTRAP##*:}"
wait_tcp "$KAFKA_HOST" "$KAFKA_PORT" "Kafka"

# ── Wait for Kafka topic-init to complete ─────────────────────────────────────
# Topics may not exist yet even if Kafka is reachable.
# Retry for up to 60s checking for the dcim.config.normalized topic.
log "Waiting for Kafka topics to be initialised..."
i=0
while ! rpk topic list \
        --brokers "${KAFKA_BOOTSTRAP}" 2>/dev/null | grep -q "dcim.config.normalized"; do
  i=$((i+1))
  [ $i -ge 60 ] && { log "WARN: Topics not found after 60s — starting anyway"; break; }
  sleep 1
done
log "Kafka topics ready"

# ── Start supervisord ─────────────────────────────────────────────────────────
log "Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
