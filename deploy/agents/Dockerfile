# =============================================================================
# FlowCore Agents Container
# Group 4: topology-reconciliation-agent + classification-capability-agent
#          + MLflow tracking server
#
# Base: Python 3.11 slim
# Process manager: supervisord
# =============================================================================

FROM python:3.11-slim

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    netcat-openbsd \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# ── Python ML dependencies (shared by both agents) ───────────────────────────
RUN pip install --no-cache-dir \
    # Web framework
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    # ML stack
    scikit-learn==1.4.0 \
    lightgbm==4.3.0 \
    numpy==1.26.4 \
    pandas==2.2.0 \
    # MLflow
    mlflow==2.10.2 \
    # Data stores
    neo4j==5.17.0 \
    psycopg2-binary==2.9.9 \
    # Kafka
    confluent-kafka==2.3.0 \
    # Utilities
    httpx==0.26.0 \
    pydantic==2.6.0 \
    python-dotenv==1.0.1

# ── App directories ───────────────────────────────────────────────────────────
RUN mkdir -p \
    /app/topology-agent \
    /app/classification-agent \
    /mlflow/db \
    /mlflow/artifacts \
    /var/log/supervisor

# ── supervisord config ────────────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/supervisord.conf

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8020 8021 5000

ENTRYPOINT ["/entrypoint.sh"]
