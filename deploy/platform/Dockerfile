# =============================================================================
# FlowCore Platform Container
# Group 2: Schema Registry + Keycloak + dcim-ingestion + telemetry-gateway +
#           active-discovery + graph-updater + timeseries-writer + event-archive
#
# Base: Ubuntu 22.04 (Keycloak requires JDK 17, Go services are binaries,
#       Python health aggregator uses system Python)
# Process manager: supervisord
# =============================================================================

FROM ubuntu:22.04

ARG KEYCLOAK_VERSION=23.0.7
ARG DEBIAN_FRONTEND=noninteractive

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Java for Keycloak
    openjdk-17-jre-headless \
    # Supervisor
    supervisor \
    # Python for health aggregator
    python3 python3-pip \
    # Utilities
    curl wget ca-certificates netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# ── Keycloak ──────────────────────────────────────────────────────────────────
RUN curl -sL \
    "https://github.com/keycloak/keycloak/releases/download/${KEYCLOAK_VERSION}/keycloak-${KEYCLOAK_VERSION}.tar.gz" \
    | tar -xz -C /opt \
    && mv /opt/keycloak-${KEYCLOAK_VERSION} /opt/keycloak

# ── Health aggregator (simple FastAPI) ───────────────────────────────────────
RUN pip3 install --no-cache-dir fastapi uvicorn httpx

# ── Log directories ───────────────────────────────────────────────────────────
RUN mkdir -p \
    /var/log/supervisor \
    /app/dcim-ingestion \
    /app/telemetry-gateway \
    /app/active-discovery \
    /app/graph-updater \
    /app/timeseries-writer \
    /app/event-archive \
    /app/health-aggregator \
    /opt/keycloak/data/import

# ── Service binaries (injected at build time from each service's build) ───────
# In development: mount source dirs via docker-compose volumes instead.
# In CI: COPY --from=service-builder /output/binary /app/service-name/
#
# Placeholder: copy stub scripts so the container starts even before
# real binaries exist (they exit 0 immediately — useful for testing compose).
COPY stubs/ /app/stubs/
RUN for svc in dcim-ingestion telemetry-gateway active-discovery \
               graph-updater timeseries-writer event-archive; do \
      cp /app/stubs/stub.sh /app/${svc}/${svc}-service && \
      chmod +x /app/${svc}/${svc}-service; \
    done

# ── Health aggregator script ──────────────────────────────────────────────────
COPY health-aggregator/main.py /app/health-aggregator/main.py

# ── Keycloak realm import (pre-seeds RBAC roles + test users) ────────────────
COPY keycloak-realm.json /opt/keycloak/data/import/flowcore-realm.json

# ── supervisord config ────────────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/supervisord.conf

# ── Entrypoint: wait for Kafka, then start supervisor ────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose all service ports
EXPOSE 8001 8002 9999/udp 8003 8010 8011 8012 8080 8099

ENTRYPOINT ["/entrypoint.sh"]
