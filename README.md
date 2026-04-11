# FlowCore — Persistent Stores (Synthetic Data)

End-to-end pipeline that generates realistic synthetic data and loads it into all three FlowCore persistent stores with a single command.

## What's included

```
flowcore/
├── schema/
│   ├── 01_postgresql_schema.sql     # Layer 2 + Layer 4 DDL (PostgreSQL 15)
│   ├── 02_timescaledb_schema.sql    # Layer 3 DDL (TimescaleDB hypertables)
│   └── 03_neo4j_schema.cypher       # Layer 1 constraints + indexes (Neo4j 5)
├── generators/
│   ├── generate_all.py              # Synthetic data generator (stdlib only)
│   └── output/                      # Generated SQL/Cypher files (created on run)
│       ├── postgresql_seed.sql
│       ├── timescaledb_seed.sql
│       └── neo4j_seed.cypher
├── docker/
│   └── docker-compose.yml           # PostgreSQL + TimescaleDB + Neo4j
└── scripts/
    ├── run_all.sh                   # Master bootstrap — one command to run everything
    └── neo4j_loader.py              # Python-based Cypher loader
```

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker + Docker Compose | 24+ | Container runtime |
| Python 3 | 3.9+ | Data generator (stdlib only, no pip install needed) |
| psql | 15+ | PostgreSQL/TimescaleDB seed loader |
| neo4j (Python driver) | 5+ | Neo4j seed loader (`pip install neo4j`) |

## Quick start

```bash
# 1. Make the bootstrap script executable
chmod +x scripts/run_all.sh

# 2. Run everything — generates data, starts Docker, loads all stores
./scripts/run_all.sh

# That's it. End-to-end takes ~5–15 minutes depending on machine speed.
```

## What gets created

**Scale (medium staging):**
- 2 tenants: ENEA Fusion Research (EU) + Meridian Cloud Services (US)
- 3 sites: Naples IT, Ashburn US, Frankfurt DE
- 3 data centers: CRESCO 6 HPC, Meridian Ashburn DC-1, ENEA Frankfurt DR
- ~1,500 infrastructure entities (49 racks, 478 devices, 98 PDUs, 850 interfaces)
- 9 source systems (nlyte, Sunbird, Prometheus, SNMP — mixed vendors)
- 40 canonical metrics × 2 tenants
- 30 days of hourly metric datapoints (~2.3M rows in TimescaleDB)
- Full Layer 4 agent output data: drift events, correlated incidents, capacity forecasts, anomaly flags, failure probability scores, simulation scenarios/results

## Connection details (after bootstrap)

| Store | Host | Port | User | Password | DB |
|-------|------|------|------|----------|----|
| PostgreSQL (Layer 2+4) | localhost | 5432 | flowcore | flowcore_secret | flowcore |
| TimescaleDB (Layer 3) | localhost | 5433 | flowcore | flowcore_secret | flowcore_ts |
| Neo4j (Layer 1) | localhost | 7474/7687 | neo4j | flowcore_secret | — |

Neo4j Browser: http://localhost:7474

## CLI options

```bash
# Quick dev run — 7 days, 100 devices
./scripts/run_all.sh --days 7 --devices 100

# Reproducible run with explicit seed
./scripts/run_all.sh --seed 12345

# Generate SQL/Cypher only (no Docker, no loading)
./scripts/run_all.sh --generate-only

# Load into existing stores (skip Docker startup)
./scripts/run_all.sh --no-docker \
  --skip-generate          # if files already exist

# Override connection strings
PG_HOST=myserver PG_PORT=5432 ./scripts/run_all.sh --no-docker
NEO4J_URI=bolt://myserver:7687 ./scripts/run_all.sh --no-docker
```

## Sample queries

### PostgreSQL — Layer 2 & 4
```sql
-- All tenants
SELECT name, plan_tier, status FROM tenant;

-- Open drift events by type
SELECT drift_type, severity, COUNT(*) FROM drift_event
WHERE status = 'OPEN' GROUP BY drift_type, severity ORDER BY 2;

-- Capacity exhaustion forecasts (90-day)
SELECT cf.entity_class, cf.scope_level, cf.predicted_value, cf.unit,
       ie.canonical_name
FROM capacity_forecast cf
JOIN infrastructure_entity_ref ie ON cf.entity_id = ie.entity_id
WHERE cf.exhaustion_flag = TRUE AND cf.horizon_label = '90d';

-- Failure probability scores — top 10 at-risk devices
SELECT ie.canonical_name, fp.probability_score, fp.contributing_factors
FROM failure_probability fp
JOIN infrastructure_entity_ref ie ON fp.entity_id = ie.entity_id
ORDER BY fp.probability_score DESC LIMIT 10;

-- ITSM integration configs
SELECT target_system, trigger_event_type, is_active FROM itsm_integration_config;
```

### TimescaleDB — Layer 3
```sql
-- Average CPU utilisation per hour over last 24h
SELECT time_bucket('1 hour', event_ts) AS hour,
       AVG(value) AS avg_cpu
FROM metric_datapoint md
JOIN metric_catalogue mc ON md.metric_id = mc.metric_id
WHERE mc.canonical_metric_name = 'cpu_utilisation_pct'
  AND event_ts > NOW() - INTERVAL '24 hours'
GROUP BY hour ORDER BY hour;

-- Alert storm detection — alerts per 15-min window
SELECT time_bucket('15 minutes', event_ts) AS window,
       canonical_severity, COUNT(*) AS alert_count
FROM alert_event
WHERE event_ts > NOW() - INTERVAL '7 days'
GROUP BY window, canonical_severity
HAVING COUNT(*) > 5
ORDER BY alert_count DESC LIMIT 20;

-- Metric rollup — max daily power draw per entity
SELECT entity_id, window_start::date AS day, max_value AS peak_power_w
FROM metric_rollup mr
JOIN metric_catalogue mc ON mr.metric_id = mc.metric_id
WHERE mc.canonical_metric_name = 'power_draw_w'
  AND window_size = '24h'
ORDER BY peak_power_w DESC LIMIT 20;

-- TimescaleDB chunk info
SELECT hypertable_name, num_chunks, total_bytes
FROM timescaledb_information.hypertables;
```

### Neo4j — Layer 1
```cypher
// Count all node types
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;

// Rack with all devices in it
MATCH (r:InfrastructureEntity {entity_class: 'RACK'})<-[:IN_RACK]-(d)
RETURN r.canonical_name AS rack, collect(d.canonical_name) AS devices
LIMIT 5;

// Power chain: device → PDU → feed
MATCH path = (d:InfrastructureEntity {entity_class: 'DEVICE'})
             -[:POWERED_BY]->(pdu:InfrastructureEntity {entity_class: 'PDU'})
             -[:POWERED_BY]->(feed:InfrastructureEntity {entity_class: 'FEED'})
RETURN d.canonical_name, pdu.canonical_name, feed.canonical_name
LIMIT 10;

// Health score distribution
MATCH (n:InfrastructureEntity)
WHERE n.entity_class = 'DEVICE'
RETURN CASE
  WHEN n.health_score >= 0.9 THEN 'Healthy'
  WHEN n.health_score >= 0.7 THEN 'Degraded'
  ELSE 'Critical'
END AS health_band, count(n) AS device_count;

// Blast radius: all entities reachable from a failed device
MATCH p = (root:InfrastructureEntity {entity_class: 'FEED'})
          <-[:POWERED_BY*1..3]-(affected)
WHERE root.canonical_name CONTAINS 'Feed-A'
RETURN affected.canonical_name, affected.entity_class,
       length(p) AS hops
ORDER BY hops;

// Topology: site → DC → location → entity chain
MATCH (s:Site)-[:CONTAINS]->(dc:DataCenter)
      -[:ORGANISES]->(l:Location)
      -[:CONTAINS]->(e:InfrastructureEntity)
WHERE e.entity_class = 'RACK'
RETURN s.canonical_name, dc.canonical_name, l.canonical_name, e.canonical_name
LIMIT 10;
```

## Docker management

```bash
# Stop containers (data persists in volumes)
docker compose -f docker/docker-compose.yml down

# Restart
docker compose -f docker/docker-compose.yml restart

# Destroy everything including volumes (start fresh)
docker compose -f docker/docker-compose.yml down -v

# View logs
docker compose -f docker/docker-compose.yml logs -f [postgres|timescaledb|neo4j]

# Connect to PostgreSQL directly
docker exec -it flowcore-postgres psql -U flowcore -d flowcore

# Connect to TimescaleDB directly
docker exec -it flowcore-timescaledb psql -U flowcore -d flowcore_ts
```

## Data model coverage

| Layer | Store | Entities Populated |
|-------|-------|--------------------|
| Layer 1 | Neo4j | Tenant, Site, CollectionAgent, DataCenter, Location, InfrastructureEntity (Rack/Device/PDU/Feed/Interface), EntityAttribute, CapacitySpec, PlatformConfig + all relationships |
| Layer 2 | PostgreSQL | SourceSystem, SourceRecord, FieldMapping, IdentitySignal, EntityResolutionRule, SyncLog, DeadLetterRecord, KafkaTopic, DiscoveryScanLog |
| Layer 3 | TimescaleDB | MetricCatalogue, MetricSourceMapping, MetricDatapoint, MetricRollup, MetricBaseline, AlertCatalogue, AlertSourceMapping, AlertEvent, GraphMutationLog, StaleTelemtryEvent, LogEvent |
| Layer 4 | PostgreSQL | DriftEvent, DriftSuggestion, ClassificationResult, CorrelatedIncident, CapacityForecast, AnomalyFlag, FailureProbability, SimulationScenario, SimulationResult, NodeQualityScore, ItsmIntegrationConfig, User, AuditLogEntry |
