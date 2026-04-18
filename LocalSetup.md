# FlowCore — Local Setup Scripts

Quick reference for starting/stopping FlowCore components.

---

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `start-databases.sh/.bat` | Start PostgreSQL, TimescaleDB, Neo4j, Kafka |
| `stop-databases.sh/.bat` | Stop databases |
| `status-databases.sh/.bat` | Check database status |
| `start-services.sh/.bat` | Start platform, agents, api-ui (requires databases) |
| `stop-services.sh/.bat` | Stop application services |
| `status-services.sh/.bat` | Check application services status |
| `rebuild-frontend.sh/.bat` | Rebuild frontend Docker image |

---

## Quick Start — Databases Only

For local development where you run services in IDE:

**Start:**
```bash
# Linux/Mac
./scripts/start-databases.sh

# Windows
.\scripts\start-databases.bat
```

**Check:**
```bash
./scripts/status-databases.sh
```

**Stop:**
```bash
./scripts/stop-databases.sh
```

---

## Quick Start — Full Stack in Containers

For running everything in Docker:

**Start:**
```bash
# 1. Databases
./scripts/start-databases.sh

# 2. Application services
./scripts/start-services.sh

# Optional: Include synthetic replay
./scripts/start-services.sh --replay
```

**Check:**
```bash
./scripts/status-databases.sh
./scripts/status-services.sh
```

**Stop:**
```bash
# Stop services only (keep databases)
./scripts/stop-services.sh

# Stop everything
./scripts/stop-services.sh
./scripts/stop-databases.sh
```

---

## Access URLs

| Service | URL |
|---------|-----|
| NOC Frontend | http://localhost:8888/ |
| GraphQL API | http://localhost:8888/graphql |
| MLflow | http://localhost:5000/ |
| Keycloak | http://localhost:8080/ |
| Kafka UI | http://localhost:8090/ |
| Neo4j Browser | http://localhost:7474/ |

---

## Rebuild Frontend

After code changes:

```bash
./scripts/rebuild-frontend.sh        # Linux/Mac
.\scripts\rebuild-frontend.bat     # Windows
```

With no cache:
```bash
./scripts/rebuild-frontend.sh --no-cache
```

---

## Full Cleanup

Stop and remove everything:

```bash
./scripts/stop-services.sh
./scripts/stop-databases.sh
docker container prune -f
```

Nuclear option (removes images, volumes, networks):
```bash
docker compose -f docker/docker-compose.databases.yml down -v
docker compose -f docker/docker-compose.full.yml down -v
docker volume prune -f
```
