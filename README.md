# FlowCore — Complete Digital Twin Platform

End-to-end Digital Twin platform for data center infrastructure management with real-time telemetry ingestion, graph-based topology, ML-powered insights, and NOC visualization.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NOC FRONTEND (UI)                              │
│                     http://localhost:8888/                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  API Gateway (:8888)  │  GraphQL API  │  Insights API  │  Eventing API      │
├─────────────────────────────────────────────────────────────────────────────┤
│  PLATFORM CONTAINER (:8080, 8001-8012, 9999)                              │
│  ├── Keycloak (Auth)  ├── Graph Updater  ├── Ingestion Services           │
├─────────────────────────────────────────────────────────────────────────────┤
│  AGENTS CONTAINER (:5000, 8020, 8022)                                       │
│  ├── MLflow UI (:5000)  ├── Topology Agent (:8020)  ├── Class Agent (:8022)│
├─────────────────────────────────────────────────────────────────────────────┤
│  REPLAY SERVICE (:8050)  →  KAFKA  →  All downstream consumers              │
├─────────────────────────────────────────────────────────────────────────────┤
│  PERSISTENT STORES                                                          │
│  ├── Neo4j (Graph) :7474/:7687  ├── PostgreSQL :5432  ├── TimescaleDB :5433│
│  └── Kafka (Redpanda) :9092  + Kafka UI :8091                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## What's Included

### Core Infrastructure (docker/docker-compose.yml)
- **PostgreSQL** — Layer 2 reference data + Layer 4 agent outputs
- **TimescaleDB** — Layer 3 time-series telemetry
- **Neo4j** — Layer 1 graph topology

### Streaming (docker/docker-compose.kafka.yml)
- **Redpanda (Kafka)** — Event streaming, 12 topics
- **Kafka UI** — Topic browser at http://localhost:8091/

### Platform Services (docker/docker-compose.platform.yml)
- **Keycloak** — Authentication at http://localhost:8080/
- **Graph Updater** — Neo4j graph synchronization
- **Ingestion Services** — DCIM, SNMP, BMC data ingestion

### AI/ML Agents (docker/docker-compose.agents.yml)
- **MLflow** — ML experiment tracking at http://localhost:5000/
- **Topology Agent** — Network topology discovery (:8020)
- **Classification Agent** — Device classification (:8022)

### API + UI (docker/docker-compose.api.yml)
- **GraphQL API** — Digital twin queries
- **Insights API** — Anomaly detection, forecasting
- **Eventing API** — Real-time event streaming
- **NOC Frontend** — React UI at http://localhost:8888/

### Synthetic Data (docker/docker-compose.replay.yml)
- **Synthetic Replay** — Generates telemetry at 1000 events/sec, API at http://localhost:8050/

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker + Docker Compose | 24+ | Container runtime |
| Python 3 | 3.9+ | Data generator (stdlib only) |
| 8GB RAM | — | Minimum for all containers |
| 20GB disk | — | For volumes and images |

## Quick Start

### Option 1: One-Command Bootstrap (Recommended for first run)

```bash
# Make executable and run
chmod +x scripts/run_all.sh
./scripts/run_all.sh

# End-to-end: ~10-20 minutes (generates data + starts all containers)
```

### Option 2: Container Manager Script (Recommended for daily use)

```bash
# Start all containers
./scripts/container.sh start

# Other commands
./scripts/container.sh stop      # Stop all
./scripts/container.sh restart   # Full restart
./scripts/container.sh ps        # Show status
./scripts/container.sh logs      # Follow logs
```

### Option 3: Manual Docker Compose

```bash
# Create Docker network
docker network create flowcore_flowcore-net

# Start all services
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.kafka.yml \
  -f docker/docker-compose.platform.yml \
  -f docker/docker-compose.agents.yml \
  -f docker/docker-compose.api.yml \
  -f docker/docker-compose.replay.yml \
  up -d
```

## Service URLs After Startup

| Service | URL | Description |
|---------|-----|-------------|
| **NOC UI** | http://localhost:8888/ | Main dashboard, racks, devices |
| **GraphQL** | http://localhost:8888/graphql | Digital twin queries |
| **MLflow UI** | http://localhost:5000/ | ML experiments, model registry |
| **Kafka UI** | http://localhost:8091/ | Topic browser, consumer groups |
| **Keycloak** | http://localhost:8080/ | Authentication admin |
| **Replay API** | http://localhost:8050/ | Synthetic data control |
| **Neo4j Browser** | http://localhost:7474/ | Graph visualization |

## Connection Details

### Databases
| Store | Host | Port | User | Password | DB |
|-------|------|------|------|----------|----|
| PostgreSQL | localhost | 5432 | flowcore | flowcore_secret | flowcore |
| TimescaleDB | localhost | 5433 | flowcore | flowcore_secret | flowcore_ts |
| Neo4j | localhost | 7474/7687 | neo4j | flowcore_secret | — |

### Kafka Topics
```
dcim.config.raw              dcim.config.normalized
metrics.timeseries.raw       alerts.raw
events.raw                   discovery.snmp.results
discovery.bmc.results        graph.mutations
drift.events                 drift.suggestions
classification.results       incidents.correlated
```

## Project Structure

```
flowcore/
├── docker/
│   ├── docker-compose.yml              # Core: Postgres, TimescaleDB, Neo4j
│   ├── docker-compose.kafka.yml        # Redpanda + Kafka UI
│   ├── docker-compose.platform.yml     # Keycloak, Graph Updater, Ingestion
│   ├── docker-compose.agents.yml       # MLflow, Topology, Classification
│   ├── docker-compose.api.yml          # GraphQL, Insights, Eventing, NOC UI
│   ├── docker-compose.replay.yml       # Synthetic telemetry generator
│   └── dockerfiles/                    # Container build definitions
├── services/
│   ├── graph-api/                      # GraphQL resolvers
│   ├── insights-api/                   # Analytics endpoints
│   ├── eventing-integration/           # Real-time event streaming
│   ├── synthetic-replay/               # Telemetry generator
│   ├── classification-agent/           # ML classification
│   └── topology-agent/                 # Network discovery
├── noc-frontend/                       # React NOC UI
├── schema/                             # SQL/Cypher DDL
│   ├── 01_postgresql_schema.sql
│   ├── 02_timescaledb_schema.sql
│   └── 03_neo4j_schema.cypher
├── generators/                         # Synthetic data generation
│   └── generate_all.py
├── scripts/
│   ├── run_all.sh                      # Master bootstrap
│   ├── container.sh                    # Container manager
│   └── stack.sh                        # Stack orchestrator
└── FIXES_SUMMARY.md                    # Troubleshooting guide
```

## What Gets Created

**Scale (medium staging):**
- 2 tenants: ENEA Fusion Research (EU) + Meridian Cloud Services (US)
- 3 sites: Naples IT, Ashburn US, Frankfurt DE
- 3 data centers: CRESCO 6 HPC, Meridian Ashburn DC-1, ENEA Frankfurt DR
- ~1,500 infrastructure entities (49 racks, 478 devices, 98 PDUs, 850 interfaces)
- 9 source systems (nlyte, Sunbird, Prometheus, SNMP — mixed vendors)
- 40 canonical metrics × 2 tenants
- 30 days of hourly metric datapoints (~2.3M rows in TimescaleDB)
- Full Layer 4 agent output data: drift events, correlated incidents, capacity forecasts, anomaly flags, failure probability scores, simulation scenarios/results

## Troubleshooting

See `FIXES_SUMMARY.md` for detailed fixes including:
- Docker build network timeouts
- Port conflicts
- UUID handling in synthetic replay
- Large file git push issues
- Container startup problems

## Sample Queries

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

---

## Quick Reference

```bash
# Full startup
./scripts/container.sh start

# Or with data generation (first run)
./scripts/run_all.sh

# Check all services
curl http://localhost:8888/health     # NOC UI
curl http://localhost:8050/status     # Synthetic Replay
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**Key Files:**
- `FIXES_SUMMARY.md` — Detailed troubleshooting guide
- `docker/.env` — Environment configuration
- `scripts/container.sh` — Container management
- `scripts/run_all.sh` — Complete bootstrap

---

*FlowCore — Digital Twin Platform for Data Center Infrastructure*
