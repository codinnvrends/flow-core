# FlowCore Fixes Summary

This document summarizes all issues fixed during the Docker build and run setup session.

---

## 1. Docker Build Network Timeout

**Problem:** `pip install` failed with "Read timed out" when downloading `confluent-kafka` package during Docker image build.

**Root Cause:** Default pip timeout (15s) insufficient for large packages over slow network.

**Fix:** Added `--timeout 300` to pip install in `docker/dockerfiles/Dockerfile.platform`:

```dockerfile
RUN pip install --no-cache-dir --timeout 300 \
    fastapi==0.111.0 \
    "uvicorn[standard]==0.30.0" \
    ...
```

**File:** `docker/dockerfiles/Dockerfile.platform` (line 15)

---

## 2. Idempotency in run_all.sh Script

**Problem:** Running `scripts/run_all.sh` multiple times caused:
- Duplicate container starts
- Regeneration of seed data
- Duplicate schema application
- Duplicate data loading

**Fix:** Added helper functions and conditional checks:

- `containers_running()` - Skip `docker compose up` if containers already running
- `seed_files_exist()` - Skip data generation if seed files exist
- `pg_has_data()`, `ts_has_data()`, `neo4j_has_data()` - Skip data load if data exists
- `pg_has_schema()`, `ts_has_schema()`, `neo4j_has_constraints()` - Skip schema if applied
- `platform_running()` - Skip platform stack launch if already running

**File:** `scripts/run_all.sh` (lines 106-173, 189-218, 222-247, 311-416, 421-503, 574-581)

---

## 3. Docker Port Conflict (agents container)

**Problem:** `flowcore-agents` container failed to start with:
```
ports are not available: exposing port TCP 0.0.0.0:8021 -> ... bind: address already in use
```

**Root Cause:** Port 8021 already in use by another process.

**Fix:** Changed `CLASS_AGENT_PORT` from 8021 to 8022 in environment:

```bash
CLASS_AGENT_PORT=8022
```

**File:** `docker/.env` (line 77)

---

## 4. Missing API/UI Container

**Problem:** Port 8888 (NOC UI) not accessible - `flowcore-api-ui` container not running.

**Root Cause:** Container wasn't started - only infrastructure, platform, and agents were up.

**Fix:** Started `flowcore-api-ui` container:
```bash
docker compose -f docker/docker-compose.api.yml up -d
```

**Access:** http://localhost:8888/

---

## 5. NOC UI Shows "No Racks Found"

**Problem:** NOC UI displayed "No racks found. Make sure the Digital Twin is populated."

**Root Cause:** Frontend `.env` had non-existent `VITE_DEFAULT_TENANT_ID` that didn't match database.

**Fix:** Updated `noc-frontend/.env` with correct tenant ID from PostgreSQL:
```bash
VITE_GRAPHQL_URL=http://localhost:8888/graphql
VITE_GRAPHQL_WS_URL=ws://localhost:8888/graphql-ws
VITE_INSIGHTS_API_URL=http://localhost:8888/api/insights
VITE_DEFAULT_TENANT_ID=fbeb8fc1-fad9-4c0a-98b4-c6d410ee7a4b
```

**File:** `noc-frontend/.env` (new file)

---

## 6. Missing Kafka Web UI

**Problem:** Port 8090 not responding - no web UI for Kafka topic browsing.

**Root Cause:** Redpanda's built-in dashboard is not enabled in `dev-container` mode.

**Fix:** Added Redpanda Console service to `docker-compose.kafka.yml`:

```yaml
kafka-ui:
  image: redpandadata/console:latest
  ports:
    - "${KAFKA_UI_PORT:-8091}:8080"
  environment:
    KAFKA_BROKERS: kafka:9092
```

**Access:** http://localhost:8091/

**Files:** `docker/docker-compose.kafka.yml` (lines 96-118), `docker/.env` (line 36)

---

## 7. Synthetic Replay UUID Errors

**Problem:** Synthetic replay service showed `errors: 495` and `events_published: 0`.

**Root Cause:** `entity["entity_id"]` is `asyncpg` UUID object, not string:
- `key.encode()` failed - UUID has no `encode()` method
- `entity['entity_id'][:8]` failed - UUID not subscriptable

**Fix:** Convert UUID to string before operations:

```python
# Line 68 - Kafka message key
key_bytes = str(key).encode() if key else None

# Line 145 - Asset tag generation
"identity_signals": [{"signal_type": "ASSET_TAG", 
  "signal_value": f"AT-{str(entity['entity_id'])[:8]}", ...}]
```

**File:** `services/synthetic-replay/main.py` (lines 66-70, 145)

---

## 8. Large File Git Push Failure

**Problem:** Push rejected with:
```
remote: error: File generators/output/timescaledb_seed.sql is 403.75 MB; 
this exceeds GitHub's file size limit of 100.00 MB
```

**Fix:** Added `generators/output/` to `.gitignore` and removed from tracking:

```gitignore
# Generated seed data and logs
generators/output/
```

**File:** `.gitignore` (new file)

---

## 9. Missing Container Management Script

**Problem:** No easy way to start/stop/restart all FlowCore containers.

**Fix:** Created `scripts/container.sh` with commands:
- `start` - Start all containers
- `stop` - Stop all containers
- `restart` - Full restart
- `ps` - Show container status
- `logs` - Follow logs
- `down` - Remove containers and volumes
- `pull` - Pull latest images
- `build` - Rebuild local images

**File:** `scripts/container.sh` (new file)

---

## Git Commands Reference

### Change Remote and Push Branch
```bash
# Verify current remote and branch
git remote -v
git branch --show-current

# Change remote to new repository
git remote remove origin
git remote add origin https://github.com/codinnvrends/flow-core.git

# Push your branch
git push -u origin fix-for-kafka-and-UI-etc-working-system
```

### Handle Large Files (Git Push Rejection)
```bash
# Create .gitignore for output folder
echo "generators/output/" >> .gitignore

# Remove large files from git index (keep locally)
git rm -r --cached generators/output/

# Stage .gitignore and commit
git add .gitignore
git commit -m "Add .gitignore and exclude generated output files"

# Push again
git push -u origin fix-for-kafka-and-UI-etc-working-system
```

### Commit All Changes
```bash
# Add new files
git add .gitignore
git add noc-frontend/.env
git add scripts/container.sh

# Stage modified files
git add docker/.env
git add docker/docker-compose.kafka.yml
git add docker/dockerfiles/Dockerfile.platform
git add scripts/neo4j_loader.py
git add scripts/rebuild.sh
git add scripts/run_all.sh
git add scripts/stack.sh
git add services/synthetic-replay/main.py

# Commit and push
git commit -m "Fix for kafka and UI etc working system"
git push -u origin fix-for-kafka-and-UI-etc-working-system
```

### Complete Fresh Push (if needed)
```bash
# Save your work to a new branch first
git checkout -b temp-backup

# Reset to clean state and cherry-pick fixes
git checkout fix-for-kafka-and-UI-etc-working-system
git reset --soft HEAD~1
git add .gitignore noc-frontend/.env scripts/container.sh
git add docker/ services/
git commit -m "Fix for kafka and UI etc working system"
git push -f -u origin fix-for-kafka-and-UI-etc-working-system
```

### Switch Branches with Local Changes
```bash
# Stash current changes and switch branch
git stash push -m "Description of changes"
git checkout main

# Or discard changes and switch
git checkout --force main

# Restore stashed changes later
git stash pop
git stash list  # View all stashes
```

### Copy Files from Another Branch
```bash
# Extract file from another branch to current branch
git show fix-for-kafka-and-UI-etc-working-system:README.md > README.md
git show fix-for-kafka-and-UI-etc-working-system:FIXES_SUMMARY.md > FIXES_SUMMARY.md

# Stage and commit
git add README.md FIXES_SUMMARY.md
git commit -m "Add updated documentation"
```

### Resolve Merge Conflicts (Keep Local Version)
```bash
# When pull creates conflicts, use local version (--ours)
git checkout --ours README.md
git add README.md
git commit -m "Resolved conflict keeping local version"

# Alternative: use remote version (--theirs)
git checkout --theirs README.md
git add README.md
git commit -m "Resolved conflict using remote version"
```

### Pull with Merge (Non-Rebase)
```bash
# When remote is ahead and you have local commits
git pull --no-rebase origin main

# Resolve any conflicts, then push
git push origin main
```

---

## Service URLs After Fixes

| Service | URL |
|---------|-----|
| NOC UI | http://localhost:8888/ |
| MLflow UI | http://localhost:5000/ |
| Kafka UI | http://localhost:8091/ |
| Synthetic Replay API | http://localhost:8050/ |
| Keycloak | http://localhost:8080/ |



Service endpoints:
  NOC Frontend     ->  http://localhost:8888/
  GraphQL          ->  http://localhost:8888/graphql
  Insights API     ->  http://localhost:8888/api/insights/
  Facility API     ->  http://localhost:8888/api/facility/summary
  Thermal API      ->  http://localhost:8888/api/thermal/zones
  Power API        ->  http://localhost:8888/api/power/summary
  Alerts API       ->  http://localhost:8888/api/alerts
  Reports API      ->  http://localhost:8888/api/reports
  Kafka UI         ->  http://localhost:8090/
  MLflow           ->  http://localhost:5000/
  Keycloak         ->  http://localhost:8080/
  Replay control   ->  http://localhost:8050/status

Test credentials:
  noc-operator / operator123
  change-manager / manager123
  dc-admin / dcadmin123
  platform-admin / platformadmin123
---

*Generated: April 11, 2026*
