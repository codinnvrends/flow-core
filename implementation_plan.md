# FlowCore — Docker & Scripts Audit + Gap Filling Plan

## Confirmed Answers
- **Shared venv** — one `venv/` at `flowcore/` root, activated once for all services  
- **destroy-all** — destruction only, no rebuild prompt  
- **Service entrypoints** — all services use `uvicorn main:app` (confirmed from supervisord configs)

## Background

Full analysis of `docker/` and `scripts/` directories to inventory what exists,
identify gaps, and create the missing scripts needed for all five scenarios.

---

## Current Inventory

### Docker Compose Files
| File | Purpose |
|------|---------|
| `docker-compose.yml` | PostgreSQL + TimescaleDB + Neo4j (stores) |
| `docker-compose.kafka.yml` | Redpanda + kafka-init + kafka-ui |
| `docker-compose.platform.yml` | Platform container (Keycloak + 6 services via supervisord) |
| `docker-compose.agents.yml` | Agents container (MLflow + 2 agents via supervisord) |
| `docker-compose.api.yml` | API+UI container (nginx + 3 APIs + frontend) |
| `docker-compose.replay.yml` | Synthetic replay container |
| `docker-compose.full.yml` | Orchestrator `include:` file — all 6 above |
| `docker-compose.databases.yml` | Self-contained: stores + Kafka in one file (for dev mode) |

### Existing Scripts
| Script | Type | What it does | Status |
|--------|------|-------------|--------|
| `container.sh` | sh | Start/stop/restart/build ALL containers via multi-`-f` compose | ✅ Exists |
| `stack.sh` | sh | Rich lifecycle: `up`, `down`, `build`, `restart`, `logs`, `status` | ✅ Exists |
| `run_all.sh` | sh | Full bootstrap: gen data → start stores → apply schema → seed → launch stack | ✅ Exists |
| `rebuild.sh` | sh | Clean wipe → no-cache build all → `run_all.sh` | ✅ Exists |
| `rebuild-frontend.sh/.bat` | sh+bat | Stop api-ui → rebuild → restart | ✅ Exists |
| `start-databases.sh/.bat` | sh+bat | `docker compose -f databases.yml up -d` | ✅ Exists |
| `stop-databases.sh/.bat` | sh+bat | `docker compose -f databases.yml down` | ✅ Exists |
| `start-services.sh/.bat` | sh+bat | Start platform → agents → api-ui via `full.yml` | ✅ Exists |
| `stop-services.sh/.bat` | sh+bat | Stop platform, agents, api-ui, replay | ✅ Exists |
| `status-databases.sh/.bat` | sh+bat | Show infra container status | ✅ Exists |
| `status-services.sh/.bat` | sh+bat | Show app service container status | ✅ Exists |

---

## Gap Analysis — What's MISSING

### ❌ Gap 1: Docker Destruction Scripts
`destroy-all.sh/.bat` — no script exists that performs **full teardown with volume wipe** interactively. `stack.sh down -v` does this but only as a sub-command; there is no standalone dedicated destruction script.

Additionally, there's no `destroy-databases.sh/.bat` (teardown databases+volumes only) or `destroy-services.sh/.bat` (teardown only app containers+volumes).

### ❌ Gap 2: Verify Script — Deploy ALL containers and start all stacks
A `verify-all.sh/.bat` that validates the full stack is up and healthy (all containers respond, all HTTP endpoints return OK). Currently not present as a standalone.

### ❌ Gap 3: Verify Script — Deploy Databases + Kafka only
A `verify-databases.sh/.bat` that validates only the infra tier (Postgres, TimescaleDB, Neo4j, Kafka) is healthy.

### ❌ Gap 4: Clean Build All Services Including UI
A `clean-build-all.sh/.bat` that does `--no-cache` builds for all 4 images: **platform, agents, api-ui, replay** (including the React frontend inside api-ui). The existing `rebuild.sh` does this, but it also wipes data and runs `run_all.sh`. A lightweight build-only script (no teardown, no data gen) is missing.

### ❌ Gap 5: Start UI + Services Locally (not in containers)
A `start-local.sh/.bat` script that:
- Assumes databases+Kafka are running in Docker
- Starts each Python service (`uvicorn`, `python -m`) in the background locally
- Starts the Vite dev server for `noc-frontend`
- Sources `.env` / sets env vars pointing to `localhost:PORT` instead of Docker service names
- Provides a `stop-local.sh/.bat` counterpart

---

## Proposed Changes

### 1. Docker Destruction Scripts (NEW)

#### [NEW] `scripts/destroy-all.sh`
- Warns user, requires `--force` or `y` confirmation
- Runs `stack.sh down -v` (stops all containers, removes all volumes)
- Removes the `flowcore_flowcore-net` Docker network
- Optionally removes local image cache (`--purge-images` flag)

#### [NEW] `scripts/destroy-all.bat`
- Windows equivalent

#### [NEW] `scripts/destroy-databases.sh` + `.bat`
- Tears down only the databases compose (`databases.yml down -v`)
- Removes only the database volumes (postgres_data, timescale_data, neo4j_data, neo4j_logs, kafka_data)

---

### 2. Verify Scripts (NEW)

#### [NEW] `scripts/verify-all.sh` + `.bat`
Checks full stack health:
- Container status for all 9 containers
- HTTP health check: `localhost:8888/health` (api-ui nginx)
- HTTP health check: `localhost:8080` (Keycloak)
- Kafka health via `rpk cluster health`
- PostgreSQL via `psql SELECT 1`
- Neo4j bolt via `cypher-shell`
- Prints pass/fail summary

#### [NEW] `scripts/verify-databases.sh` + `.bat`
Checks infra tier only:
- `flowcore-postgres` container healthy + psql SELECT 1
- `flowcore-timescaledb` container healthy + psql SELECT 1
- `flowcore-neo4j` container healthy + cypher-shell
- `flowcore-kafka` container healthy + `rpk cluster health`
- Reports pass/fail per service

---

### 3. Clean Build All (NEW — lightweight, no data wipe)

#### [NEW] `scripts/build-all.sh` + `.bat`
- `--no-cache` build of: `platform`, `agents`, `api-ui` (includes React build), `synthetic-replay`
- Does NOT stop containers or wipe volumes
- Accepts optional `--target <name>` to build a single image
- Reports build times per image

This is distinct from the existing `rebuild.sh` which does a full destroy + data gen cycle.

---

### 4. Local Development Runner (NEW)

#### [NEW] `scripts/start-local.sh`
Starts all services natively on the laptop (no containers for services):
- Sources `docker/.env` for base config
- Overrides `PG_HOST=localhost`, `TS_HOST=localhost`, `NEO4J_HOST=localhost`, `KAFKA_BOOTSTRAP_SERVERS=localhost:19092`
- Sets `VITE_USE_MOCKS=false`, `VITE_API_BASE_URL=http://localhost:4000`
- Starts 10 Python services via `uvicorn` in background (with PID tracking):
  - `dcim-ingestion-service` :8001
  - `telemetry-gateway-service` :8002
  - `active-discovery-service` :8003
  - `graph-updater-service` :8010
  - `timeseries-writer-service` :8011
  - `event-archive-service` :8012
  - `graph-api-service` (strawberry GraphQL) :4000
  - `insights-api` (FastAPI) :4001
  - `eventing-integration` :4002
  - `topology-agent` :8020
  - `classification-agent` :8021
- Starts `noc-frontend` Vite dev server on :3000 (via `npm run dev`)
- Writes PIDs to `/tmp/flowcore-local.pids`
- Prints all access URLs

#### [NEW] `scripts/stop-local.sh`
- Reads PID file and kills all local processes
- Stops the Vite dev server

#### [NEW] `scripts/start-local.bat` + `scripts/stop-local.bat`
- Windows equivalents using `start /B` for background processes
- Writes PIDs to `%TEMP%\flowcore-local.pids`

> [!IMPORTANT]
> The local runner requires Python virtual environments to be properly set up per service. The script should check for a `venv` or `.venv` in each service directory and use it.

---

## Redundancy Audit — Scripts to Remove / Consolidate

| Script | Verdict | Reason |
|--------|---------|--------|
| `container.sh` | ❌ **Redundant** | 100% superseded by `stack.sh` which has all the same commands (`start/stop/restart/ps/logs/down/pull/build`) plus more. No unique functionality. |
| `run_all.sh` | ⚠️ **Semi-redundant** | The full bootstrap logic is called by `rebuild.sh` and `stack.sh up`. It stands alone for schema seeding—keep but don't advertise as a primary entrypoint. |
| `start-services.sh/.bat` | ⚠️ **Thin wrapper** | Calls `docker-compose.full.yml` but incorrectly uses service name `replay` (actual name is `synthetic-replay`). Bug exists. Superseded by `stack.sh up`. Keep but fix the bug. |
| `status-databases.sh/.bat` | ✅ **Keep** | Useful standalone quick-check. |
| `status-services.sh/.bat` | ✅ **Keep** | Useful standalone quick-check. |

> [!WARNING]
> **`container.sh` should be deleted** — it is a strict subset of `stack.sh` and causes confusion. Two scripts doing the same thing with different names is a maintenance burden.

---

## Open Issues Found in Existing Scripts

| Script | Bug |
|--------|-----|
| `start-services.sh` | Uses service name `replay` but actual compose service name is `synthetic-replay` |
| `start-services.bat` | Same bug |
| `stack.sh status` | `KAFKA_UI_PORT` default says 8091 but `.env` sets `REDPANDA_UI_PORT=8090` — inconsistent |

---

## User Review Required

> [!WARNING]
> **Local services startup** — The `start-local.sh` script needs to know the exact entrypoint (module path) for each service. For example:
> - Is `graph-api` started as `uvicorn main:app` or `python -m graph_api`?
> - Does each service have its own `venv`, or is there a project-level `venv`?
> - Should `start-local` also start `synthetic-replay` natively, or always leave it in Docker?
>
> Please confirm before I create this script. I can make reasonable assumptions from the `Dockerfile` build configs.

> [!IMPORTANT]
> **destroy-all vs rebuild** — The existing `rebuild.sh` already does teardown + build + bootstrap. The new `destroy-all` will only destroy (no rebuild). Do you want `destroy-all` to ask "also rebuild?" or stay strictly a destruction-only tool?

---

## Verification Plan

### Automated
- After creating scripts: `bash -n <script>` syntax check on all `.sh` files
- Dry-run `docker compose config` check on verify scripts to confirm compose file references are correct

### Manual
- Run `verify-databases.sh` after `start-databases.sh` succeeds
- Run `verify-all.sh` after full `stack.sh up` completes
- Run `build-all.sh` without data wipe and confirm images are rebuilt
- Run `start-local.sh` with databases running and confirm Vite connects to live APIs
