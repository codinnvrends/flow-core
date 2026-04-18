#!/usr/bin/env bash
# =============================================================================
# FlowCore — Verify Databases + Kafka
#
# Checks health of ONLY the infrastructure tier:
#   PostgreSQL, TimescaleDB, Neo4j, Kafka
#
# Exits 0 if all pass, 1 if any fail.
#
# Usage:
#   ./scripts/verify-databases.sh
#
# Run from the flowcore/ root directory.
# =============================================================================

set -euo pipefail

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
  C='\033[0;36m'; W='\033[1m'; B='\033[0;34m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; W=''; B=''; N=''
fi

PASS=0; FAIL=0
FAILED_CHECKS=()

pass() { PASS=$((PASS+1)); echo -e "  ${G}[PASS]${N} $*"; }
fail() { FAIL=$((FAIL+1)); FAILED_CHECKS+=("$*"); echo -e "  ${R}[FAIL]${N} $*"; }
skip() { echo -e "  ${Y}[SKIP]${N} $*"; }
hdr()  { echo -e "\n${W}${B}======================================================"
         echo -e "  $*"
         echo -e "======================================================${N}\n"; }

check_container() {
  local name="$1" label="${2:-$1}"
  local status health
  status=$(docker inspect --format='{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
  health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$name" 2>/dev/null || echo "missing")

  if   [[ "$status" == "missing" ]];  then fail "$label — container not found"
  elif [[ "$status" != "running" ]];  then fail "$label — status: $status (expected: running)"
  elif [[ "$health" == "healthy" || "$health" == "no-healthcheck" ]]; then pass "$label — running ($health)"
  elif [[ "$health" == "starting" ]]; then skip "$label — still starting"
  else fail "$label — unhealthy (health: $health)"
  fi
}

check_exec() {
  local container="$1" label="$2"; shift 2
  if docker exec "$container" "$@" >/dev/null 2>&1; then
    pass "$label"
  else
    fail "$label"
  fi
}

check_port() {
  local host="${1:-localhost}" port="$2" label="$3"
  if (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
    pass "$label — port $port open"
  else
    fail "$label — port $port not reachable"
  fi
}

hdr "FlowCore Infrastructure Verification"

# ── Container health ──────────────────────────────────────────────────────────
echo -e "${W}─── Container Status ────────────────────────────────────────${N}"
check_container "flowcore-postgres"    "PostgreSQL"
check_container "flowcore-timescaledb" "TimescaleDB"
check_container "flowcore-neo4j"       "Neo4j"
check_container "flowcore-kafka"       "Kafka (Redpanda)"
check_container "flowcore-kafka-ui"    "Kafka UI"
check_container "flowcore-kafka-init"  "Kafka topic-init (may be exited=OK)"

# ── Connectivity tests ────────────────────────────────────────────────────────
echo ""
echo -e "${W}─── Connectivity Tests ──────────────────────────────────────${N}"

# PostgreSQL — direct psql query
check_exec "flowcore-postgres" \
  "PostgreSQL — SELECT 1" \
  psql -U flowcore -d flowcore --no-align --tuples-only -c "SELECT 1;"

# TimescaleDB — query + extension check
check_exec "flowcore-timescaledb" \
  "TimescaleDB — SELECT 1" \
  psql -U flowcore -d flowcore_ts --no-align --tuples-only -c "SELECT 1;"

check_exec "flowcore-timescaledb" \
  "TimescaleDB — extension loaded" \
  psql -U flowcore -d flowcore_ts --no-align --tuples-only \
    -c "SELECT COUNT(*) FROM timescaledb_information.hypertables;"

# Neo4j — bolt query
check_exec "flowcore-neo4j" \
  "Neo4j — Bolt query" \
  cypher-shell -u neo4j -p flowcore_secret "RETURN 1;"

# Kafka — cluster health
check_exec "flowcore-kafka" \
  "Kafka — cluster health" \
  rpk cluster health

# Kafka — topic list (checks topics were created)
TOPIC_COUNT=$(MSYS_NO_PATHCONV=1 docker exec flowcore-kafka \
  rpk topic list --brokers kafka:9092 2>/dev/null | tail -n +2 | wc -l || echo "0")
if [[ "${TOPIC_COUNT:-0}" -ge 10 ]]; then
  pass "Kafka — topics exist ($TOPIC_COUNT topics found)"
else
  fail "Kafka — fewer topics than expected ($TOPIC_COUNT found, expected ≥10)"
fi

# ── Port checks (host-side) ───────────────────────────────────────────────────
echo ""
echo -e "${W}─── Host Port Availability ─────────────────────────────────${N}"
check_port localhost 5432 "PostgreSQL  :5432"
check_port localhost 5433 "TimescaleDB :5433"
check_port localhost 7474 "Neo4j HTTP  :7474"
check_port localhost 7687 "Neo4j Bolt  :7687"
check_port localhost 9092 "Kafka       :9092"
check_port localhost 8090 "Kafka UI    :8090"

# ── Summary ───────────────────────────────────────────────────────────────────
hdr "Verification Summary"
echo -e "  ${G}PASS: $PASS${N}   ${R}FAIL: $FAIL${N}"
echo ""

if [[ ${#FAILED_CHECKS[@]} -gt 0 ]]; then
  echo -e "${R}Failed checks:${N}"
  for c in "${FAILED_CHECKS[@]}"; do echo "  ✘ $c"; done
  echo ""
  exit 1
else
  echo -e "${G}All infrastructure checks passed — databases and Kafka are healthy!${N}"
  echo ""
fi
