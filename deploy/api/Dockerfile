# =============================================================================
# FlowCore API Container
# Group 3: graph-api-service + insights-api-service +
#          eventing-integration + noc-frontend
#
# Process manager: supervisord
# External access: single nginx proxy on port 8000
#
# Routing (nginx → internal):
#   /graphql        → :4000  graph-api (GraphQL + WebSocket)
#   /api/insights/  → :4001  insights-api (REST)
#   /api/events/    → :4002  eventing-integration (REST)
#   /               → :3000  noc-frontend (React Vite dev)
# =============================================================================

FROM node:20-alpine

# ── System packages ───────────────────────────────────────────────────────────
RUN apk add --no-cache \
    nginx \
    supervisor \
    curl \
    bash

# ── App directories ───────────────────────────────────────────────────────────
RUN mkdir -p \
    /app/graph-api \
    /app/insights-api \
    /app/eventing-integration \
    /app/noc-frontend \
    /var/log/supervisor \
    /var/log/nginx \
    /run/nginx

# ── nginx config ──────────────────────────────────────────────────────────────
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# ── supervisord config ────────────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/supervisord.conf

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Single external port via nginx proxy
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
