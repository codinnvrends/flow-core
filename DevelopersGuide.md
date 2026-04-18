# FlowCore — Developers Guide

---

## Mental Model

```
First time setup:   ./scripts/run_all.sh              generate → schema → seed → launch
Code change:        ./scripts/rebuild.sh [target]      build image → recreate container
Start/stop stack:   ./scripts/stack.sh up / down       full Docker stack lifecycle
Local dev mode:     ./scripts/start-services.sh        11 services natively, DBs in Docker
DB infra only:      ./scripts/start-databases.sh       Postgres, TimescaleDB, Neo4j, Kafka
Nuclear reset:      ./scripts/destroy-all.sh           wipe all containers + volumes
```

---

## Frontend Development (NOC UI)

The NOC frontend is a React + TypeScript + Vite application in `noc-frontend/`.

**Prerequisites:** Node.js 18+ LTS, npm 9+

### Option 1: Local Dev Server (recommended)

```bash
cd noc-frontend
npm install          # first time only
npm run dev          # starts at http://localhost:3000/
```

Hot module replacement is active. API proxy is configured in `vite.config.ts`.

### Option 2: Docker Build (production testing)

```bash
# Linux/Mac
./scripts/rebuild-frontend.sh
./scripts/rebuild-frontend.sh --no-cache   # force clean rebuild

# Windows
.\scripts\rebuild-frontend.bat
.\scripts\rebuild-frontend.bat --no-cache
```

### Frontend Configuration (`noc-frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_GRAPHQL_URL` | `http://localhost:8888/graphql` | GraphQL endpoint |
| `VITE_GRAPHQL_WS_URL` | `ws://localhost:8888/graphql-ws` | GraphQL WebSocket |
| `VITE_INSIGHTS_API_URL` | `http://localhost:8888/api/insights` | Insights API |
| `VITE_API_BASE_URL` | `http://localhost:8888/api` | Base API path |
| `VITE_DEFAULT_TENANT_ID` | (UUID) | Default tenant |
| `VITE_USE_MOCKS` | `false` | Set `true` for mock data mode |

Set `VITE_USE_MOCKS=true` to develop without a running backend. A blue banner indicates mock mode is active.

---

## Backend Development

### Option 1: Local Services (databases in Docker)

Start infrastructure first, then start all services natively:

```bash
# Linux/Mac
./scripts/start-databases.sh
./scripts/start-services.sh

# Windows
.\scripts\start-databases.bat
.\scripts\start-services.bat
```

Services connect to `localhost` for all databases and Kafka. Logs go to `/tmp/flowcore-logs/`.

To also start synthetic replay:
```bash
./scripts/start-services.sh --replay
```

Stop all local services (databases left running):
```bash
./scripts/stop-services.sh
```

### Option 2: Full Docker Stack

```bash
./scripts/stack.sh up             # start everything
./scripts/stack.sh up --no-replay # start without synthetic replay
./scripts/stack.sh down           # stop (keep data)
./scripts/stack.sh down -v        # stop + wipe all volumes
```

### Environment Variables (local dev)

All services read from `docker/.env`. For local mode, DB/Kafka hosts are overridden to `localhost`:

```
PG_HOST=localhost        PG_PORT=5432
TS_HOST=localhost        TS_PORT=5433
NEO4J_HOST=localhost     NEO4J_BOLT_PORT=7687
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
```

---

## Service Ports

| Service | Port |
|---------|------|
| DCIM Ingestion | 8001 |
| Telemetry Gateway | 8002 |
| Active Discovery | 8003 |
| Graph Updater | 8010 |
| Timeseries Writer | 8011 |
| Event Archive | 8012 |
| Graph API (GraphQL) | 4000 |
| Insights API | 4001 |
| Eventing Integration | 4002 |
| Topology Agent | 8020 |
| Classification Agent | 8021 |
| Synthetic Replay | 8050 |

---

## Project Structure

```
flowcore/
├── noc-frontend/                    # React NOC UI (Vite + TypeScript)
│   ├── src/
│   │   ├── components/             # Shared UI components
│   │   ├── components/layout/      # Sidebar, TopBar
│   │   ├── pages/                  # Dashboard, Alerts, etc.
│   │   ├── hooks/                  # useApi, usePollingApi
│   │   ├── lib/                    # api.ts, theme.ts, apollo.ts
│   │   └── mocks/                  # Mock data for development
│   └── .env                        # Frontend environment variables
│
├── services/
│   ├── dcim-ingestion/             # DCIM config ingest :8001
│   ├── telemetry-gateway/          # Telemetry ingest :8002
│   ├── active-discovery/           # SNMP/BMC discovery :8003
│   ├── graph-updater/              # Kafka → Neo4j writer :8010
│   ├── timeseries-writer/          # Kafka → TimescaleDB writer :8011
│   ├── event-archive/              # Event log archiver :8012
│   ├── graph-api/                  # GraphQL API (Strawberry) :4000
│   ├── insights-api/               # REST analytics API :4001
│   ├── eventing-integration/       # Kafka event streaming :4002
│   ├── topology-agent/             # Network topology agent :8020
│   ├── classification-agent/       # ML device classifier :8021
│   ├── synthetic-replay/           # Telemetry data generator :8050
│   └── shared/                     # Shared utilities
│
├── docker/
│   ├── docker-compose.databases.yml    # Infrastructure only (dev mode)
│   ├── docker-compose.full.yml         # Full stack orchestrator
│   ├── docker-compose.platform.yml     # Platform services
│   ├── docker-compose.agents.yml       # AI/ML agents
│   ├── docker-compose.api.yml          # API + UI
│   ├── docker-compose.replay.yml       # Synthetic replay
│   ├── .env                            # Shared environment config
│   └── dockerfiles/                    # Container definitions
│
├── scripts/                        # See Scripts Reference below
├── schema/                         # Database DDL
│   ├── 01_postgresql_schema.sql
│   ├── 02_timescaledb_schema.sql
│   └── 03_neo4j_schema.cypher
└── generators/
    └── generate_all.py             # Synthetic seed data generator
```

---

## Rebuilding After Code Changes

```bash
# Rebuild all service images + recreate containers (data untouched)
./scripts/rebuild.sh

# Rebuild a specific service only
./scripts/rebuild.sh platform
./scripts/rebuild.sh agents
./scripts/rebuild.sh api-ui
./scripts/rebuild.sh replay

# Use layer cache for faster iteration
./scripts/rebuild.sh api-ui --with-cache
```

---

## Synthetic Replay

Control the replay service (publishes synthetic events to Kafka):

```bash
./scripts/replay.sh start                      # live mode, 1000 events/s
./scripts/replay.sh start --rate 500           # custom rate
./scripts/replay.sh start --mode historical    # replay 30-day seed data
./scripts/replay.sh status
./scripts/replay.sh pause
./scripts/replay.sh resume
./scripts/replay.sh rate 2000
./scripts/replay.sh logs -f
./scripts/replay.sh stop
```

---

## API Development

### Adding New Endpoints

1. Add endpoint in the relevant service (`services/<name>/main.py`)
2. Define types in `noc-frontend/src/lib/api.ts`
3. Add mock in `noc-frontend/src/mocks/index.ts` (optional)
4. Use in components with `useApi()` or `usePollingApi()`

### Example

**Backend (`services/insights-api/main.py`):**
```python
@app.get("/api/custom/metric")
async def get_custom_metric():
    return {"value": 42.0, "unit": "kW"}
```

**Frontend (`src/lib/api.ts`):**
```typescript
export const api = {
  custom: {
    metric: (): Promise<{ value: number; unit: string }> =>
      fetch(`${BASE_URL}/custom/metric`).then(r => r.json())
  }
}
```

**Component:**
```typescript
const { data } = useApi(() => api.custom.metric(), mockCustomMetric)
```

---

## Testing

### Frontend

```bash
cd noc-frontend
npm test
npm run test:coverage
npm run lint
npx tsc --noEmit
```

### Backend

```bash
cd services/insights-api
pytest
pytest --cov=app
```

---

## Debugging

### Logs

```bash
# Local services
tail -f /tmp/flowcore-logs/<service-name>.log

# Docker services
./scripts/stack.sh logs platform
./scripts/stack.sh logs agents
./scripts/stack.sh logs api-ui
./scripts/stack.sh logs replay
```

### Database Access

```bash
# PostgreSQL
docker exec -it flowcore-postgres psql -U flowcore -d flowcore

# TimescaleDB
docker exec -it flowcore-timescaledb psql -U flowcore -d flowcore_ts

# Neo4j Browser → http://localhost:7474
```

### Health Checks

```bash
./scripts/verify-databases.sh    # check DB + Kafka health
./scripts/verify-all.sh          # check full stack health
./scripts/stack.sh status        # container status overview
```

---

## Full Reset

```bash
# Destroy all containers + volumes (irreversible)
./scripts/destroy-all.sh

# Destroy databases only
./scripts/destroy-databases.sh

# Start fresh after destroy
./scripts/run_all.sh
```

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `run_all.sh` | **First-time setup** — generate seed data, apply schemas, seed DBs, launch stack |
| `stack.sh up / down` | Start / stop full Docker stack |
| `stack.sh build [target]` | Build Docker images via compose |
| `build-all.sh [target]` | Build images only, no container lifecycle |
| `rebuild.sh [target]` | Build image + recreate container (code change workflow) |
| `start-databases.sh/.bat` | Start Postgres, TimescaleDB, Neo4j, Kafka in Docker |
| `stop-databases.sh/.bat` | Stop database containers (data preserved) |
| `status-databases.sh/.bat` | Show database container status |
| `start-services.sh/.bat` | Start all 11 services locally (natively, no Docker) |
| `stop-services.sh/.bat` | Stop local services |
| `rebuild-frontend.sh/.bat` | Rebuild api-ui image (React + nginx) |
| `replay.sh/.bat` | Control synthetic replay (start/stop/pause/rate/reset) |
| `verify-databases.sh/.bat` | Health check — databases + Kafka |
| `verify-all.sh/.bat` | Health check — full stack + HTTP endpoints |
| `destroy-all.sh/.bat` | Wipe all containers, volumes, and network |
| `destroy-databases.sh/.bat` | Wipe database containers and volumes only |
