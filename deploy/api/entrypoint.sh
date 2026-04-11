#!/usr/bin/env bash
set -e

log() { echo "[$(date '+%H:%M:%S')] [api] $*"; }

wait_tcp() {
  local host="$1" port="$2" label="$3"
  log "Waiting for $label ($host:$port)..."
  local i=0
  while ! nc -z "$host" "$port" 2>/dev/null; do
    i=$((i+1)); [ $i -ge 60 ] && { log "ERROR: $label unreachable"; exit 1; }
    sleep 2
  done
  log "$label ready"
}

# Wait for Neo4j (graph-api needs it)
wait_tcp "${NEO4J_HOST}" "${NEO4J_BOLT_PORT}" "Neo4j"

# Wait for platform container's graph-updater health (indicates platform is ready)
log "Waiting for platform container (graph-updater)..."
i=0
while ! curl -sf "http://flowcore-platform:${GRAPH_UPDATER_PORT}/health" >/dev/null 2>&1; do
  i=$((i+1)); [ $i -ge 60 ] && { log "WARN: Platform not ready after 120s — starting anyway"; break; }
  sleep 2
done
log "Platform container ready"

# Install npm deps if node_modules missing (dev mode with mounted source)
for dir in /app/graph-api /app/insights-api /app/eventing-integration /app/noc-frontend; do
  if [ -f "$dir/package.json" ] && [ ! -d "$dir/node_modules" ]; then
    log "Installing npm dependencies in $dir..."
    cd "$dir" && npm install --prefer-offline 2>&1 | tail -3
  fi
done

log "Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
