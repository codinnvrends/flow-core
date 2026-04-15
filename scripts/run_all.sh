#!/usr/bin/env bash
# =============================================================================
# FlowCore — Full Bootstrap Script
# Tested on: Windows Git Bash, Windows WSL2, macOS, Linux
#
# Run from the flowcore/ root directory:
#   chmod +x scripts/run_all.sh          # Linux / macOS / WSL only
#   ./scripts/run_all.sh                 # default: 30 days, 500 devices
#   ./scripts/run_all.sh --days 7 --devices 100   # quick dev run
#   ./scripts/run_all.sh --no-docker     # skip docker startup
#   ./scripts/run_all.sh --generate-only # generate SQL/Cypher files only
#   ./scripts/run_all.sh --skip-generate # skip generation, load existing files
#   ./scripts/run_all.sh --with-replay   # include synthetic replay service
#
# Platform notes
# --------------
# Windows Git Bash: MSYS_NO_PATHCONV=1 is set on every docker exec call via the
#   dexec() wrapper so Git Bash never converts /tmp/... container paths to
#   C:\Users\...\AppData paths.
#
# The hypertable SQL fragment and all intermediate files are written to
# $OUTPUT_DIR (a user-controlled path) instead of /tmp so that docker cp
#   picks them up without any path translation issues on Windows.
#
# du / file-size display: uses Python for portable output so behaviour is
#   identical across macOS (BSD du), Linux (GNU du), and Git Bash.
# =============================================================================

set -euo pipefail

# ── Colour support (suppressed on non-TTY) ────────────────────────────────────
if [ -t 1 ]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
  BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] v $*${NC}"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ! $*${NC}"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')] X $*${NC}"; exit 1; }
hdr()  {
  echo -e "\n${BOLD}${BLUE}======================================================"
  echo -e "  $*"
  echo -e "======================================================${NC}\n"
}

# ── Cross-platform file size (avoids du -h field-separator differences) ───────
filesize() {
  python3 -c "
import os, sys
b = os.path.getsize(sys.argv[1])
for unit in ['B','KB','MB','GB']:
    if b < 1024 or unit == 'GB':
        print(f'{b:.1f} {unit}'); break
    b /= 1024
" "$1" 2>/dev/null || echo "?"
}

# ── dexec: docker exec with MSYS_NO_PATHCONV=1 ───────────────────────────────
# Prevents Git Bash (MSYS2) converting /tmp/... container-internal paths into
# C:\Users\...\AppData paths before passing them to the docker CLI.
# On macOS / Linux MSYS_NO_PATHCONV is silently ignored — no side effects.
dexec() { MSYS_NO_PATHCONV=1 docker exec "$@"; }

# ── Argument defaults ─────────────────────────────────────────────────────────
DAYS=30; DEVICES=500; SEED=42
USE_DOCKER=true; GENERATE_ONLY=false; SKIP_GENERATE=false; WITH_REPLAY=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --days)          DAYS="$2";          shift 2 ;;
    --devices)       DEVICES="$2";       shift 2 ;;
    --seed)          SEED="$2";          shift 2 ;;
    --no-docker)     USE_DOCKER=false;   shift ;;
    --generate-only) GENERATE_ONLY=true; shift ;;
    --skip-generate) SKIP_GENERATE=true; shift ;;
    --with-replay)   WITH_REPLAY=true;   shift ;;
    *) warn "Unknown argument: $1"; shift ;;
  esac
done

# ── Directories ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOWCORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GENERATORS_DIR="$FLOWCORE_DIR/generators"
OUTPUT_DIR="$GENERATORS_DIR/output"   # all intermediate files go here
DOCKER_DIR="$FLOWCORE_DIR/docker"
SCHEMA_DIR="$FLOWCORE_DIR/schema"

mkdir -p "$OUTPUT_DIR"

# ── Store connection defaults ─────────────────────────────────────────────────
PG_USER="${PG_USER:-flowcore}";  PG_DB="${PG_DB:-flowcore}"
TS_USER="${TS_USER:-flowcore}";  TS_DB="${TS_DB:-flowcore_ts}"
PG_CONTAINER="${PG_CONTAINER:-flowcore-postgres}"
TS_CONTAINER="${TS_CONTAINER:-flowcore-timescaledb}"
NEO4J_CONTAINER="${NEO4J_CONTAINER:-flowcore-neo4j}"

# ── Helpers ───────────────────────────────────────────────────────────────────
detect_compose() {
  if docker compose version >/dev/null 2>&1; then echo "docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"
  else err "Neither 'docker compose' nor 'docker-compose' found"; fi
}

containers_running() {
  local compose_file="$1"
  local running_count
  running_count=$(docker compose -f "$compose_file" ps --format json 2>/dev/null | grep -c '"State":"running"' 2>/dev/null || echo "0")
  running_count=$(echo "$running_count" | tr -d '[:space:]')
  [[ "${running_count:-0}" -gt 0 ]]
}

seed_files_exist() {
  [[ -f "$OUTPUT_DIR/postgresql_seed.sql" ]] && \
  [[ -f "$OUTPUT_DIR/timescaledb_seed.sql" ]] && \
  [[ -f "$OUTPUT_DIR/neo4j_seed.cypher" ]]
}

pg_has_data() {
  local ctr="$1" user="$2" db="$3"
  local count
  count=$(dexec "$ctr" psql -U "$user" -d "$db" --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM tenant;" 2>/dev/null || echo "0")
  count="${count//[[:space:]]/}"
  [[ "${count:-0}" -gt 0 ]]
}

ts_has_data() {
  local ctr="$1" user="$2" db="$3"
  local count
  count=$(dexec "$ctr" psql -U "$user" -d "$db" --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM metric_catalogue;" 2>/dev/null || echo "0")
  count="${count//[[:space:]]/}"
  [[ "${count:-0}" -gt 0 ]]
}

neo4j_has_data() {
  local ctr="$1"
  local count
  count=$(dexec "$ctr" cypher-shell -u neo4j -p flowcore_secret \
    "MATCH (n) RETURN count(n) AS c;" --format plain 2>/dev/null | tail -1 | tr -d ' ' || echo "0")
  [[ "${count:-0}" -gt 0 ]]
}

pg_has_schema() {
  local ctr="$1" user="$2" db="$3"
  local count
  count=$(dexec "$ctr" psql -U "$user" -d "$db" --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" 2>/dev/null || echo "0")
  count="${count//[[:space:]]/}"
  [[ "${count:-0}" -gt 0 ]]
}

ts_has_schema() {
  local ctr="$1" user="$2" db="$3"
  local count
  count=$(dexec "$ctr" psql -U "$user" -d "$db" --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" 2>/dev/null || echo "0")
  count="${count//[[:space:]]/}"
  [[ "${count:-0}" -gt 0 ]]
}

neo4j_has_constraints() {
  local ctr="$1"
  local count
  count=$(dexec "$ctr" cypher-shell -u neo4j -p flowcore_secret \
    "SHOW CONSTRAINTS YIELD name RETURN count(name) AS c;" --format plain 2>/dev/null | tail -1 | tr -d ' ' || echo "0")
  [[ "${count:-0}" -gt 0 ]]
}

platform_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -q "flowcore-platform\|flowcore-keycloak" 2>/dev/null
}

wait_for_postgres() {
  local ctr="$1" user="$2" db="$3" label="$4"
  log "Waiting for $label to accept connections..."
  local i
  for i in $(seq 1 60); do
    if dexec "$ctr" psql -U "$user" -d "$db" -c "SELECT 1;" >/dev/null 2>&1; then
      ok "$label is ready"; return 0
    fi
    sleep 3
    [[ $((i % 5)) -eq 0 ]] && log "  still waiting ($((i * 3))s elapsed)..."
  done
  err "$label did not become ready within 180s"
}

wait_for_neo4j() {
  local ctr="$1"
  log "Waiting for Neo4j Bolt..."
  local i
  for i in $(seq 1 60); do
    if dexec "$ctr" cypher-shell -u neo4j -p flowcore_secret \
         "RETURN 1;" >/dev/null 2>&1; then
      ok "Neo4j is ready"; return 0
    fi
    sleep 5
    [[ $((i % 6)) -eq 0 ]] && log "  still waiting ($((i * 5))s elapsed)..."
  done
  err "Neo4j did not become ready within 300s"
}

# =============================================================================
# STEP 1 — GENERATE SYNTHETIC DATA
# =============================================================================
if [[ "$SKIP_GENERATE" == "false" ]]; then
  # Check if seed files already exist with content
  if seed_files_exist; then
    warn "Seed files already exist — skipping generation (use --skip-generate to bypass this warning)"
    log "Existing files:"
    for f in "$OUTPUT_DIR"/*.sql "$OUTPUT_DIR"/*.cypher; do
      [[ -f "$f" ]] && log "  $(basename "$f")  $(filesize "$f")"
    done
  else
    hdr "Step 1 -- Generating Synthetic Data"

    python3 --version >/dev/null 2>&1 || \
      err "python3 not found in PATH (required for data generator)"

    python3 "$GENERATORS_DIR/generate_all.py" \
      --days "$DAYS" --devices "$DEVICES" --seed "$SEED"

    ok "Generation complete"
    log "Output files:"
    for f in "$OUTPUT_DIR"/*.sql "$OUTPUT_DIR"/*.cypher; do
      [[ -f "$f" ]] && log "  $(basename "$f")  $(filesize "$f")"
    done
  fi
else
  log "Skipping generation (--skip-generate)"
  for f in postgresql_seed.sql timescaledb_seed.sql neo4j_seed.cypher; do
    [[ -f "$OUTPUT_DIR/$f" ]] || err "$f not found in $OUTPUT_DIR — run without --skip-generate first"
  done
  ok "Using existing seed files"
fi

[[ "$GENERATE_ONLY" == "true" ]] && { ok "Generate-only mode complete."; exit 0; }

# =============================================================================
# STEP 2 — START DOCKER COMPOSE
# =============================================================================
if [[ "$USE_DOCKER" == "true" ]]; then
  hdr "Step 2 -- Starting Docker Compose"

  command -v docker >/dev/null 2>&1 || err "docker not found in PATH"
  docker info >/dev/null 2>&1       || err "Docker daemon is not running"

  COMPOSE=$(detect_compose)
  log "Compose command: $COMPOSE"

  # Check if containers are already running
  if containers_running "$DOCKER_DIR/docker-compose.yml"; then
    warn "Containers already running — skipping docker compose up"
    $COMPOSE -f "$DOCKER_DIR/docker-compose.yml" ps
  else
    $COMPOSE -f "$DOCKER_DIR/docker-compose.yml" pull
    $COMPOSE -f "$DOCKER_DIR/docker-compose.yml" up -d
    ok "Containers started"
    $COMPOSE -f "$DOCKER_DIR/docker-compose.yml" ps
  fi
fi

# =============================================================================
# STEP 3 — WAIT FOR ALL STORES
# =============================================================================
hdr "Step 3 -- Waiting for Stores"

log "Allowing 15s for container init (TimescaleDB background worker needs extra time)..."
sleep 15

wait_for_postgres "$PG_CONTAINER" "$PG_USER" "$PG_DB"  "PostgreSQL"
wait_for_postgres "$TS_CONTAINER" "$TS_USER" "$TS_DB"  "TimescaleDB"
wait_for_neo4j    "$NEO4J_CONTAINER"

# Extra buffer: TimescaleDB BGW registers after pg_isready fires
log "Allowing 10s for TimescaleDB background worker to fully register..."
sleep 10

# Confirm the extension is operable before we run the schema
log "Confirming TimescaleDB extension is operational..."
local_i=0
while [[ $local_i -lt 20 ]]; do
  if dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
       -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;" \
       >/dev/null 2>&1; then
    ok "TimescaleDB extension confirmed operational"; break
  fi
  sleep 3
  local_i=$((local_i + 1))
  [[ $local_i -eq 20 ]] && warn "Could not confirm TimescaleDB extension — will proceed anyway"
done

# =============================================================================
# STEP 4 — APPLY SCHEMAS
#
# All schema files are copied into containers via docker cp from $OUTPUT_DIR,
# which is a path in the project tree. This avoids using /tmp on the host
# (where Git Bash would translate it to a Windows Temp path).
#
# PostgreSQL: standard SQL, no extensions. ON_ERROR_STOP=1 is safe.
#
# TimescaleDB: two-pass approach.
#   Pass 1 — CREATE TABLE (without ON_ERROR_STOP so a transient hypertable
#             error does not abort the tables that come later in the file).
#   Pass 2 — create_hypertable() calls only, in a retry loop, giving the
#             TimescaleDB background worker extra time to be ready.
#
# Neo4j: schema constraints via cypher-shell.
# =============================================================================
hdr "Step 4 -- Applying Schemas"

# ── PostgreSQL ────────────────────────────────────────────────────────────────
if pg_has_schema "$PG_CONTAINER" "$PG_USER" "$PG_DB"; then
  warn "PostgreSQL schema already exists — skipping schema application"
else
  log "Applying PostgreSQL schema..."
  docker cp "$SCHEMA_DIR/01_postgresql_schema.sql" \
    "${PG_CONTAINER}:/tmp/flowcore_schema_pg.sql"

  if dexec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" \
       -v ON_ERROR_STOP=1 \
       -f /tmp/flowcore_schema_pg.sql \
       > "$OUTPUT_DIR/schema_pg.log" 2>&1; then
    ok "PostgreSQL schema applied"
  else
    warn "PostgreSQL schema had errors — check $OUTPUT_DIR/schema_pg.log"
    grep -i "ERROR" "$OUTPUT_DIR/schema_pg.log" | head -5 || true
  fi
fi

# ── TimescaleDB — pass 1: CREATE TABLEs ──────────────────────────────────────
if ts_has_schema "$TS_CONTAINER" "$TS_USER" "$TS_DB"; then
  warn "TimescaleDB schema already exists — skipping schema application"
else
  log "Applying TimescaleDB schema (pass 1 — tables)..."
  docker cp "$SCHEMA_DIR/02_timescaledb_schema.sql" \
    "${TS_CONTAINER}:/tmp/flowcore_schema_ts.sql"

  # No ON_ERROR_STOP here: a transient create_hypertable failure must not
  # prevent the CREATE TABLE statements that follow it from executing.
  dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
    -f /tmp/flowcore_schema_ts.sql \
    > "$OUTPUT_DIR/schema_ts_p1.log" 2>&1 || true

  TABLE_COUNT=$(dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
    --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE';" \
    2>/dev/null || echo "0")
  TABLE_COUNT="${TABLE_COUNT//[[:space:]]/}"
  log "TimescaleDB tables present after pass 1: ${TABLE_COUNT}"
  [[ "${TABLE_COUNT:-0}" -lt 5 ]] && {
    warn "Fewer tables than expected — check $OUTPUT_DIR/schema_ts_p1.log"
    grep -i "ERROR" "$OUTPUT_DIR/schema_ts_p1.log" | head -10 || true
  }

  # ── TimescaleDB — pass 2: hypertable promotion (retry) ───────────────────────
  # Write the hypertable fragment to OUTPUT_DIR (not /tmp on host) so that
  # docker cp works identically on Windows Git Bash, macOS, and Linux.
  log "Applying TimescaleDB schema (pass 2 — hypertable promotion)..."

  HYPER_FRAG="$OUTPUT_DIR/flowcore_hypertables.sql"
  cat > "$HYPER_FRAG" << 'HYPERTABLES'
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
SELECT create_hypertable('metric_datapoint',     'event_ts',    chunk_time_interval => INTERVAL '7 days',  if_not_exists => TRUE);
SELECT create_hypertable('metric_rollup',         'window_start',chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
SELECT create_hypertable('alert_event',           'event_ts',    chunk_time_interval => INTERVAL '7 days',  if_not_exists => TRUE);
SELECT create_hypertable('graph_mutation_log',    'occurred_at', chunk_time_interval => INTERVAL '7 days',  if_not_exists => TRUE);
SELECT create_hypertable('stale_telemetry_event', 'stale_since', chunk_time_interval => INTERVAL '7 days',  if_not_exists => TRUE);
SELECT create_hypertable('log_event',             'event_ts',    chunk_time_interval => INTERVAL '7 days',  if_not_exists => TRUE);
HYPERTABLES

  docker cp "$HYPER_FRAG" "${TS_CONTAINER}:/tmp/flowcore_hypertables.sql"

  HT_OK=false
  local_attempt=1
  while [[ $local_attempt -le 3 ]]; do
    log "  Hypertable promotion attempt ${local_attempt}/3..."
    if dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
         -f /tmp/flowcore_hypertables.sql \
         > "$OUTPUT_DIR/schema_ts_hyper_${local_attempt}.log" 2>&1; then
      HT_OK=true; break
    fi
    grep -i "ERROR" "$OUTPUT_DIR/schema_ts_hyper_${local_attempt}.log" | head -3 || true
    sleep 5
    local_attempt=$((local_attempt + 1))
  done

  if [[ "$HT_OK" == "true" ]]; then
    ok "TimescaleDB hypertables promoted"
  else
    warn "Hypertable promotion had errors — seed will load into regular tables"
  fi

  HT_COUNT=$(dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
    --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM timescaledb_information.hypertables;" \
    2>/dev/null || echo "0")
  HT_COUNT="${HT_COUNT//[[:space:]]/}"
  log "Hypertables registered: ${HT_COUNT}"
fi  # End of TimescaleDB schema check

# ── Neo4j constraints ─────────────────────────────────────────────────────────
if neo4j_has_constraints "$NEO4J_CONTAINER"; then
  warn "Neo4j constraints already exist — skipping schema application"
else
  log "Applying Neo4j schema constraints..."
  docker cp "$SCHEMA_DIR/03_neo4j_schema.cypher" \
    "${NEO4J_CONTAINER}:/tmp/flowcore_neo4j_schema.cypher"
  dexec "$NEO4J_CONTAINER" \
    cypher-shell -u neo4j -p flowcore_secret \
    --file /tmp/flowcore_neo4j_schema.cypher \
    > "$OUTPUT_DIR/schema_neo4j.log" 2>&1 || true
  ok "Neo4j constraints applied"
fi

# =============================================================================
# STEP 5 — LOAD POSTGRESQL SEED
# =============================================================================
hdr "Step 5 -- Loading PostgreSQL (Layer 2 + Layer 4)"

# Check if data already exists
if pg_has_data "$PG_CONTAINER" "$PG_USER" "$PG_DB"; then
  warn "PostgreSQL already has data — skipping seed load"
else
  PG_SEED="$OUTPUT_DIR/postgresql_seed.sql"
  log "Seed: $(filesize "$PG_SEED")"
  log "Copying into container..."
  docker cp "$PG_SEED" "${PG_CONTAINER}:/tmp/flowcore_pg_seed.sql"

  log "Running psql..."
  if dexec "$PG_CONTAINER" psql \
       -U "$PG_USER" -d "$PG_DB" \
       -v ON_ERROR_STOP=1 \
       -f /tmp/flowcore_pg_seed.sql \
       > "$OUTPUT_DIR/load_pg.log" 2>&1; then
    ok "PostgreSQL seed loaded"
  else
    warn "PostgreSQL load had errors — check $OUTPUT_DIR/load_pg.log"
    grep -i "ERROR" "$OUTPUT_DIR/load_pg.log" | head -10 || true
  fi
fi

log "Row counts:"
dexec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c \
  "SELECT 'tenant'                       AS tbl, COUNT(*) FROM tenant
   UNION ALL SELECT 'site',                      COUNT(*) FROM site
   UNION ALL SELECT 'data_center',               COUNT(*) FROM data_center
   UNION ALL SELECT 'source_system',             COUNT(*) FROM source_system
   UNION ALL SELECT 'infrastructure_entity_ref', COUNT(*) FROM infrastructure_entity_ref
   UNION ALL SELECT 'drift_event',               COUNT(*) FROM drift_event
   UNION ALL SELECT 'correlated_incident',       COUNT(*) FROM correlated_incident
   UNION ALL SELECT 'capacity_forecast',         COUNT(*) FROM capacity_forecast
   UNION ALL SELECT 'anomaly_flag',              COUNT(*) FROM anomaly_flag
   UNION ALL SELECT 'failure_probability',       COUNT(*) FROM failure_probability
   UNION ALL SELECT 'simulation_result',         COUNT(*) FROM simulation_result
   UNION ALL SELECT 'audit_log_entry',           COUNT(*) FROM audit_log_entry
   ORDER BY 1;" 2>/dev/null || warn "Row count query failed"

# =============================================================================
# STEP 6 — LOAD TIMESCALEDB SEED
# =============================================================================
hdr "Step 6 -- Loading TimescaleDB (Layer 3)"

# Check if data already exists
if ts_has_data "$TS_CONTAINER" "$TS_USER" "$TS_DB"; then
  warn "TimescaleDB already has data — skipping seed load"
else
  TS_SEED="$OUTPUT_DIR/timescaledb_seed.sql"
  log "Seed: $(filesize "$TS_SEED")"
  log "Copying into container (large file — please wait)..."
  docker cp "$TS_SEED" "${TS_CONTAINER}:/tmp/flowcore_ts_seed.sql"

  log "Running psql (may take several minutes for 30-day dataset)..."
  if dexec "$TS_CONTAINER" psql \
       -U "$TS_USER" -d "$TS_DB" \
       -v ON_ERROR_STOP=1 \
       -f /tmp/flowcore_ts_seed.sql \
       > "$OUTPUT_DIR/load_ts.log" 2>&1; then
    ok "TimescaleDB seed loaded"
  else
    warn "TimescaleDB load had errors — check $OUTPUT_DIR/load_ts.log"
    grep -i "ERROR" "$OUTPUT_DIR/load_ts.log" | head -10 || true
  fi
fi

log "Row counts:"
dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" -c \
  "SELECT 'metric_catalogue'          AS tbl, COUNT(*) FROM metric_catalogue
   UNION ALL SELECT 'metric_datapoint',       COUNT(*) FROM metric_datapoint
   UNION ALL SELECT 'metric_rollup',          COUNT(*) FROM metric_rollup
   UNION ALL SELECT 'metric_baseline',        COUNT(*) FROM metric_baseline
   UNION ALL SELECT 'alert_catalogue',        COUNT(*) FROM alert_catalogue
   UNION ALL SELECT 'alert_event',            COUNT(*) FROM alert_event
   UNION ALL SELECT 'log_event',              COUNT(*) FROM log_event
   UNION ALL SELECT 'graph_mutation_log',     COUNT(*) FROM graph_mutation_log
   UNION ALL SELECT 'stale_telemetry_event',  COUNT(*) FROM stale_telemetry_event
   ORDER BY 1;" 2>/dev/null || warn "Row count query failed"

log "Hypertable chunk summary:"
dexec "$TS_CONTAINER" psql -U "$TS_USER" -d "$TS_DB" \
  --no-align --tuples-only -c \
  "SELECT hypertable_name, num_chunks, pg_size_pretty(total_bytes)
   FROM timescaledb_information.hypertables ORDER BY hypertable_name;" \
  2>/dev/null | awk -F'|' '{printf "  %-30s %s chunks  %s\n",$1,$2,$3}' || true

# =============================================================================
# STEP 7 — LOAD NEO4J SEED
# =============================================================================
hdr "Step 7 -- Loading Neo4j (Layer 1)"

# Check if data already exists
if neo4j_has_data "$NEO4J_CONTAINER"; then
  warn "Neo4j already has data — skipping seed load"
else
  NEO4J_SEED="$OUTPUT_DIR/neo4j_seed.cypher"
  log "Seed: $(filesize "$NEO4J_SEED")"
  log "Copying into container..."
  docker cp "$NEO4J_SEED" "${NEO4J_CONTAINER}:/tmp/flowcore_neo4j_seed.cypher"

  log "Running cypher-shell (may take a few minutes)..."
  if dexec "$NEO4J_CONTAINER" \
       cypher-shell -u neo4j -p flowcore_secret \
       --file /tmp/flowcore_neo4j_seed.cypher \
       > "$OUTPUT_DIR/load_neo4j.log" 2>&1; then
    ok "Neo4j seed loaded"
  else
    warn "Neo4j load had warnings — check $OUTPUT_DIR/load_neo4j.log"
    grep -i "^.*ERROR" "$OUTPUT_DIR/load_neo4j.log" | head -10 || true
  fi
fi

log "Node counts:"
dexec "$NEO4J_CONTAINER" \
  cypher-shell -u neo4j -p flowcore_secret \
  "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;" \
  2>/dev/null || warn "Neo4j count query failed"

# =============================================================================
# STEP 8 — SUMMARY
# =============================================================================
hdr "Bootstrap Complete"

echo -e "${BOLD}Store Endpoints:${NC}"
echo "  PostgreSQL   -> localhost:5432  db=${PG_DB}     user=${PG_USER}   pass=flowcore_secret"
echo "  TimescaleDB  -> localhost:5433  db=${TS_DB}   user=${TS_USER}   pass=flowcore_secret"
echo "  Neo4j Bolt   -> bolt://localhost:7687  user=neo4j  pass=flowcore_secret"
echo "  Neo4j UI     -> http://localhost:7474"
echo ""
echo -e "${BOLD}Smoke-test commands:${NC}"
echo "  docker exec $PG_CONTAINER psql -U $PG_USER -d $PG_DB -c 'SELECT name FROM tenant;'"
echo "  docker exec $TS_CONTAINER psql -U $TS_USER -d $TS_DB -c 'SELECT COUNT(*) FROM metric_datapoint;'"
echo "  docker exec $NEO4J_CONTAINER cypher-shell -u neo4j -p flowcore_secret \\"
echo "    \"MATCH (n) RETURN labels(n)[0], count(n) ORDER BY count(n) DESC;\""
echo ""
echo -e "${BOLD}Load logs written to:${NC} $OUTPUT_DIR/"
echo "  schema_pg.log  schema_ts_p1.log  schema_neo4j.log"
echo "  load_pg.log    load_ts.log       load_neo4j.log"
echo ""

if [[ "$USE_DOCKER" == "true" ]]; then
  COMPOSE=$(detect_compose)
  echo -e "${BOLD}Docker management:${NC}"
  echo "  Stop (keep data):  $COMPOSE -f docker/docker-compose.yml down"
  echo "  WIPE all data:     $COMPOSE -f docker/docker-compose.yml down -v"
  echo "  Tail logs:         $COMPOSE -f docker/docker-compose.yml logs -f"
  echo ""

  # =============================================================================
  # STEP 9 — LAUNCH FULL PLATFORM STACK
  # Now that all stores are seeded we can safely bring up the rest of the stack.
  # =============================================================================
  hdr "Step 9 -- Launching full platform stack"

  if platform_running; then
    warn "Platform services already running — skipping stack launch"
  else
    log "Starting platform services (Keycloak + ingestion + processing)..."
    if [[ "$WITH_REPLAY" == "true" ]]; then
      "$SCRIPT_DIR/stack.sh" up
    else
      "$SCRIPT_DIR/stack.sh" up --no-replay
    fi
  fi
fi

ok "FlowCore persistent stores are ready."
