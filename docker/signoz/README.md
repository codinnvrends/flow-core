# SigNoz Observability Integration for FlowCore

This directory contains the SigNoz OpenTelemetry-native observability stack integrated into FlowCore.

## Overview

SigNoz provides distributed tracing, metrics, and logging for all FlowCore services through OpenTelemetry (OTLP) protocol.

**Key Components:**
- **SigNoz Query Service + UI**: Web interface for viewing traces, metrics, and logs
- **ClickHouse**: Columnar database for high-performance telemetry storage
- **Zookeeper**: Coordination service for ClickHouse
- **OpenTelemetry Collector**: Receives OTLP data from FlowCore services

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| SigNoz UI | http://localhost:8081 | Main observability dashboard |
| OTLP gRPC | `localhost:4317` | High-performance telemetry ingestion |
| OTLP HTTP | `localhost:4318` | Alternative telemetry ingestion |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FlowCore Services                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ platform│ │ api-ui  │ │ agents  │ │ replay  │ │  kafka  │   │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘   │
│       │           │           │           │           │         │
│       └───────────┴───────────┴───────────┴───────────┘         │
│                         │ OTLP (gRPC/HTTP)                       │
└─────────────────────────┼───────────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────────┐
│  SigNoz Stack           ▼                                       │
│  ┌──────────────────────────────────────────┐                  │
│  │  OpenTelemetry Collector (:4317 / :4318)  │                  │
│  └──────────────┬───────────────────────────┘                  │
│                 │                                               │
│  ┌──────────────▼───────────────────────────┐                  │
│  │           ClickHouse DB                  │                  │
│  │  ┌─────────┬─────────┬─────────┐        │                  │
│  │  │ traces  │ metrics │  logs   │        │                  │
│  │  └─────────┴─────────┴─────────┘        │                  │
│  └──────────────────────────────────────────┘                  │
│                 │                                               │
│  ┌──────────────▼──────┐                                        │
│  │  SigNoz UI (:8081)  │  ← Query & Visualization               │
│  └─────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Usage

### Starting SigNoz Only

```bash
cd docker
docker compose -f docker-compose.signoz.yml up -d
```

### Starting Full Stack with SigNoz

```bash
docker compose -f docker/docker-compose.full.yml up -d
```

Or to start specific layers:

```bash
# Stores + Kafka + SigNoz (observability infrastructure)
docker compose -f docker/docker-compose.full.yml up -d kafka signoz

# Full stack
docker compose -f docker/docker-compose.full.yml up -d
```

### Accessing the UI

Once running, open http://localhost:8081 in your browser.

Default retention:
- Logs: 7 days
- Traces: 7 days
- Metrics: 30 days

Change in SigNoz UI → Settings → General → Retention.

## Configuration

### Environment Variables

See `docker/.env`:

```env
SIGNOZ_UI_PORT=8081              # Host port for SigNoz UI
SIGNOZ_VERSION=v0.118.0          # SigNoz version
SIGNOZ_OTELCOL_VERSION=v0.144.2  # OTel Collector version
SIGNOZ_JWT_SECRET=...            # JWT secret for SigNoz auth

# OTLP endpoints
SIGNOZ_OTLP_GRPC_PORT=4317
SIGNOZ_OTLP_HTTP_PORT=4318
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### Service Instrumentation

FlowCore services are pre-configured with OTLP exporters. Each service sends:
- **Traces**: Request flows, database queries, Kafka operations
- **Metrics**: Performance counters, request rates, error rates
- **Logs**: Structured application logs

Service names in SigNoz:
- `flowcore-platform`
- `flowcore-api-ui`
- `flowcore-agents`
- `flowcore-replay`

## Files

| File | Purpose |
|------|---------|
| `docker-compose.signoz.yml` | SigNoz services definition |
| `otel-collector-config.yaml` | OTel Collector receivers, processors, exporters |
| `otel-collector-opamp-config.yaml` | OpAMP remote management config |
| `clickhouse-config.xml` | ClickHouse server configuration |
| `clickhouse-users.xml` | ClickHouse user permissions |

## Troubleshooting

### Check SigNoz services status
```bash
docker compose -f docker/docker-compose.signoz.yml ps
```

### View collector logs
```bash
docker logs flowcore-signoz-otel-collector -f
```

### Reset SigNoz data
```bash
docker compose -f docker/docker-compose.signoz.yml down -v
```

### Port conflicts
- Port 8080 is used by Keycloak. SigNoz UI is mapped to 8081.
- Ports 4317/4318 must be free for OTLP ingestion.
