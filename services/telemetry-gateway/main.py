"""
FlowCore Telemetry Gateway Service
Inbound paths:
  POST /prom/write   → Prometheus remote write (protobuf or JSON)
  POST /webhook      → Zabbix/Icinga alert webhooks (JSON)
  POST /metrics      → Generic metrics JSON endpoint
Publishes to: metrics.timeseries.raw, alerts.raw, events.raw
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
import uvicorn
from confluent_kafka import Producer
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("telemetry-gateway")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
TS_DSN = f"postgresql://{os.getenv('TS_USER','flowcore')}:{os.getenv('TS_PASSWORD','flowcore_secret')}@{os.getenv('TS_HOST','timescaledb')}:{os.getenv('TS_PORT','5432')}/{os.getenv('TS_DB','flowcore_ts')}"
PORT = int(os.getenv("TELEMETRY_GATEWAY_HTTP_PORT", "8002"))

stats = {
    "metrics_received": 0, "alerts_received": 0, "events_received": 0,
    "dead_letters": 0, "started_at": None,
}

_producer: Optional[Producer] = None
_pool: Optional[asyncpg.Pool] = None

# Source metric → canonical metric_id cache (loaded from DB)
_metric_map: dict = {}       # source_metric_name → (metric_id, conversion_expr)
_source_map: dict = {}       # source_name/token → source_id, tenant_id
_alert_type_map: dict = {}   # canonical_alert_name → (alert_type_id, default_severity)


async def load_metric_catalogue():
    """Load METRIC_SOURCE_MAPPING into memory for fast lookup."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT msm.source_metric_name, msm.metric_id, msm.unit_conversion_expr,
                   msm.source_id, mc.unit
            FROM metric_source_mapping msm
            JOIN metric_catalogue mc ON mc.metric_id = msm.metric_id
        """)
        for r in rows:
            _metric_map[r["source_metric_name"]] = {
                "metric_id": str(r["metric_id"]),
                "conversion": r.get("unit_conversion_expr"),
                "source_id": str(r["source_id"]),
                "unit": r["unit"],
            }

        rows2 = await conn.fetch(
            "SELECT source_id, tenant_id, source_name FROM source_system WHERE source_class='TELEMETRY' AND status='ACTIVE'")
        for r in rows2:
            _source_map[str(r["source_id"])] = {
                "source_id": str(r["source_id"]),
                "tenant_id": str(r["tenant_id"]),
                "source_name": r["source_name"],
            }

    async with _pool.acquire() as ts_conn:
        rows3 = await ts_conn.fetch("""
            SELECT alert_type_id, canonical_alert_name, default_severity
            FROM alert_catalogue WHERE is_active=true
        """)
        for r in rows3:
            _alert_type_map[r["canonical_alert_name"]] = {
                "alert_type_id": str(r["alert_type_id"]),
                "severity": r["default_severity"],
            }

    logger.info(f"Loaded {len(_metric_map)} metric mappings, {len(_source_map)} sources, {len(_alert_type_map)} alert types")


def apply_conversion(value: float, expr: Optional[str]) -> float:
    if not expr:
        return value
    try:
        return float(eval(expr.replace("value", str(value))))  # noqa: S307
    except Exception:
        return value


def first_source() -> tuple[str, str]:
    """Return first available telemetry source as fallback."""
    for info in _source_map.values():
        return info["source_id"], info["tenant_id"]
    return "00000000-0000-0000-0000-000000000000", "00000000-0000-0000-0000-000000000000"


def publish(topic: str, msg: dict, key: Optional[str] = None) -> None:
    _producer.produce(topic, json.dumps(msg, default=str).encode(),
                      key=key.encode() if key else None)
    _producer.poll(0)


def make_metric_msg(entity_id: str, entity_class: str, metric_id: str,
                    source_id: str, tenant_id: str, value: float,
                    event_ts: str, quality: str = "VALID") -> dict:
    return {
        "message_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "entity_class": entity_class,
        "metric_id": metric_id,
        "source_id": source_id,
        "value": round(value, 4),
        "quality_flag": quality,
        "event_ts": event_ts,
        "ingest_ts": datetime.now(timezone.utc).isoformat(),
    }


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Telemetry Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _producer, _pool
    _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=5)
    _producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "client.id": "telemetry-gateway",
        "acks": 1,
        "linger.ms": 5,
        "batch.size": 65536,
    })
    await load_metric_catalogue()
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info("Telemetry gateway ready")


@app.on_event("shutdown")
async def shutdown():
    if _producer:
        _producer.flush(5)
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "telemetry-gateway",
            "metric_mappings": len(_metric_map)}


@app.get("/stats")
def get_stats():
    return stats


# ── Prometheus remote write endpoint ─────────────────────────────────────────

class PrometheusMetric(BaseModel):
    name: str
    labels: dict[str, str] = {}
    value: float
    timestamp_ms: Optional[int] = None


class PrometheusWriteRequest(BaseModel):
    metrics: list[PrometheusMetric]
    source_id: Optional[str] = None


@app.post("/prom/write")
async def prometheus_write(request: Request):
    """Accept Prometheus remote write as JSON (simplified — no protobuf)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    metrics_list = body if isinstance(body, list) else body.get("metrics", [body])
    source_id, tenant_id = first_source()
    now = datetime.now(timezone.utc).isoformat()
    published = 0

    for item in metrics_list:
        name = item.get("name", item.get("__name__", ""))
        value = item.get("value", 0)
        labels = item.get("labels", item.get("label", {}))
        ts = item.get("timestamp_ms")
        event_ts = (
            datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            if ts else now
        )

        # Look up metric catalogue
        mapping = _metric_map.get(name)
        if mapping:
            converted = apply_conversion(float(value), mapping["conversion"])
            entity_id = labels.get("instance", labels.get("job", "unknown"))
            msg = make_metric_msg(entity_id, "DEVICE", mapping["metric_id"],
                                  mapping["source_id"], tenant_id, converted, event_ts)
            publish("metrics.timeseries.raw", msg, key=entity_id)
            stats["metrics_received"] += 1
            published += 1
        else:
            # Unknown metric — publish with placeholder metric_id for archival
            entity_id = labels.get("instance", "unknown")
            msg = {
                "message_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "entity_class": "DEVICE",
                "metric_id": f"unknown:{name}",
                "source_id": source_id,
                "value": float(value),
                "quality_flag": "VALID",
                "event_ts": event_ts,
                "ingest_ts": now,
                "source_metric_name": name,
                "labels": labels,
            }
            publish("metrics.timeseries.raw", msg, key=entity_id)
            stats["metrics_received"] += 1
            published += 1

    _producer.flush(1)
    return {"received": len(metrics_list), "published": published}


# ── Generic JSON metrics endpoint ─────────────────────────────────────────────

@app.post("/metrics")
async def receive_metrics(request: Request):
    """Accept arbitrary JSON metric payloads."""
    body = await request.json()
    items = body if isinstance(body, list) else [body]
    source_id, tenant_id = first_source()
    now = datetime.now(timezone.utc).isoformat()

    for item in items:
        entity_id = item.get("entity_id", item.get("host", "unknown"))
        metric_id = item.get("metric_id", "unknown:generic")
        value = item.get("value", item.get("v", 0))
        msg = make_metric_msg(entity_id, item.get("entity_class", "DEVICE"),
                               metric_id, source_id, tenant_id, float(value), now)
        publish("metrics.timeseries.raw", msg, key=entity_id)
        stats["metrics_received"] += 1

    _producer.flush(1)
    return {"received": len(items)}


# ── Webhook endpoint (Zabbix / Icinga / generic) ──────────────────────────────

class WebhookAlert(BaseModel):
    entity_id: Optional[str] = None
    entity_class: Optional[str] = "DEVICE"
    alert_name: Optional[str] = "generic_alert"
    severity: Optional[str] = "WARNING"
    value: Optional[float] = None
    status: Optional[str] = "ACTIVE"
    source_alert_id: Optional[str] = None
    timestamp: Optional[str] = None
    extra: dict[str, Any] = {}


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Accept Zabbix/Icinga webhook payloads."""
    body = await request.json()
    items = body if isinstance(body, list) else [body]
    source_id, tenant_id = first_source()
    now = datetime.now(timezone.utc).isoformat()
    published = 0

    for item in items:
        alert_name = item.get("alert_name", item.get("trigger_name", "generic_alert"))
        alert_info = _alert_type_map.get(alert_name, {})
        severity = item.get("severity", alert_info.get("severity", "WARNING"))
        alert_type_id = alert_info.get("alert_type_id", "00000000-0000-0000-0000-000000000001")
        entity_id = item.get("entity_id", item.get("host", item.get("hostname", "unknown")))

        msg = {
            "message_id": str(uuid.uuid4()),
            "alert_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "entity_class": item.get("entity_class", "DEVICE"),
            "alert_type_id": alert_type_id,
            "source_id": source_id,
            "canonical_severity": severity.upper(),
            "source_severity": severity,
            "metric_value": item.get("value"),
            "metric_id": None,
            "source_alert_id": item.get("source_alert_id", item.get("trigger_id")),
            "status": item.get("status", "ACTIVE").upper(),
            "event_ts": item.get("timestamp", now),
            "ingest_ts": now,
        }
        publish("alerts.raw", msg, key=entity_id)
        stats["alerts_received"] += 1
        published += 1

    _producer.flush(1)
    return {"received": len(items), "published": published}


# ── Events endpoint ───────────────────────────────────────────────────────────

@app.post("/events")
async def receive_events(request: Request):
    """Accept general infrastructure events."""
    body = await request.json()
    items = body if isinstance(body, list) else [body]
    source_id, tenant_id = first_source()
    now = datetime.now(timezone.utc).isoformat()

    for item in items:
        item["ingest_ts"] = now
        item.setdefault("tenant_id", tenant_id)
        item.setdefault("source_id", source_id)
        publish("events.raw", item, key=item.get("entity_id"))
        stats["events_received"] += 1

    _producer.flush(1)
    return {"received": len(items)}


@app.post("/reload/mappings")
async def reload_mappings():
    """Hot-reload metric catalogue from DB."""
    await load_metric_catalogue()
    return {"status": "reloaded", "mappings": len(_metric_map)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
