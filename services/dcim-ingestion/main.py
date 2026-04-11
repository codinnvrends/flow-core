"""
FlowCore DCIM Ingestion Service
Reads source_system + field_mapping config from PostgreSQL.
In Option A (synthetic mode), acts as a pass-through admin API.
In production: connects to real DCIM REST APIs and normalises payloads.
Admin REST API on :8001
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import uvicorn
from confluent_kafka import Producer
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("dcim-ingestion")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
PORT = int(os.getenv("DCIM_INGESTION_PORT", "8001"))

stats = {
    "syncs_completed": 0,
    "records_published": 0,
    "records_rejected": 0,
    "errors": 0,
    "started_at": None,
    "last_sync_at": None,
}

_pool: Optional[asyncpg.Pool] = None
_producer: Optional[Producer] = None


def get_producer() -> Producer:
    return _producer


# ── Field mapping engine ──────────────────────────────────────────────────────

def apply_transform(value, transform_type: str, expression: Optional[str], value_type: str):
    if value is None:
        return None
    try:
        if transform_type == "DIRECT":
            pass
        elif transform_type == "UNIT_CONVERT" and expression:
            # Safe eval for simple math: value/1000, value*100, etc.
            val = float(value)
            result = eval(expression.replace("value", str(val)))  # noqa: S307
            return round(result, 4)
        elif transform_type == "ENUM_MAP" and expression:
            mapping = json.loads(expression)
            return mapping.get(str(value), value)
        elif transform_type == "CONSTANT" and expression:
            return expression

        if value_type == "FLOAT":
            return float(value)
        elif value_type == "INTEGER":
            return int(float(value))
        elif value_type == "BOOLEAN":
            return str(value).lower() in ("1", "true", "yes")
        return str(value)
    except Exception:
        return str(value) if value is not None else None


def extract_field(payload: dict, path: str):
    """Extract value from payload using dot-notation or JSONPath-lite."""
    if not path:
        return None
    # Strip leading $. for JSONPath
    clean = path.lstrip("$.").replace("[", ".").replace("]", "")
    parts = clean.split(".")
    current = payload
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def normalise_record(raw: dict, mappings: list[dict], source_id: str, tenant_id: str) -> dict:
    """Apply FIELD_MAPPING rules to a raw DCIM payload → canonical normalized record."""
    entity_class = raw.get("entity_class", "DEVICE")
    canonical_name = raw.get("name", raw.get("canonical_name", "Unknown"))
    attributes = []
    capacity_specs = []
    relationships = []
    identity_signals = []

    for mapping in mappings:
        src_path = mapping.get("source_field_path", "")
        raw_value = extract_field(raw, src_path)
        if raw_value is None:
            if mapping.get("is_required"):
                return None  # Required field missing — reject
            continue

        transformed = apply_transform(
            raw_value,
            mapping.get("transform_type", "DIRECT"),
            mapping.get("transform_expression"),
            mapping.get("value_type", "STRING"),
        )

        target = mapping.get("canonical_target", "ENTITY_ATTRIBUTE")

        if mapping.get("is_identity_field"):
            identity_signals.append({
                "signal_type": mapping.get("canonical_key", "ASSET_TAG").upper(),
                "signal_value": str(transformed),
                "confidence": 1.0,
            })

        if target == "ENTITY_FIELD":
            if mapping.get("canonical_key") == "canonical_name":
                canonical_name = str(transformed)
        elif target == "ENTITY_ATTRIBUTE":
            attributes.append({
                "namespace": mapping.get("canonical_namespace", "dcim"),
                "key": mapping.get("canonical_key", src_path.split(".")[-1]),
                "value": str(transformed),
                "value_type": mapping.get("value_type", "STRING"),
            })
        elif target == "CAPACITY_SPEC":
            capacity_specs.append({
                "dimension": mapping.get("canonical_key", "power_kw"),
                "rated_value": float(transformed) if transformed else 0.0,
                "unit": mapping.get("value_type", "kW"),
            })
        elif target == "IDENTITY_SIGNAL":
            identity_signals.append({
                "signal_type": mapping.get("canonical_key", "ASSET_TAG").upper(),
                "signal_value": str(transformed),
                "confidence": 1.0,
            })

    return {
        "message_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "source_id": source_id,
        "record_id": str(uuid.uuid4()),
        "entity_class": entity_class,
        "canonical_name": canonical_name,
        "operational_status": raw.get("status", "UNKNOWN"),
        "attributes": attributes,
        "capacity_specs": capacity_specs,
        "relationships": relationships,
        "identity_signals": identity_signals,
        "event_ts": datetime.now(timezone.utc).isoformat(),
        "ingest_ts": datetime.now(timezone.utc).isoformat(),
    }


# ── Sync runner ───────────────────────────────────────────────────────────────

async def run_sync(source_id: str) -> dict:
    """
    Execute a sync for the given source_system.
    In production: fetches from vendor REST API.
    In Option A: reads from infrastructure_entity_ref and publishes to Kafka.
    """
    sync_log_id = str(uuid.uuid4())
    received = mapped = rejected = created = updated = 0
    started = datetime.now(timezone.utc)

    try:
        async with _pool.acquire() as conn:
            source = await conn.fetchrow(
                "SELECT * FROM source_system WHERE source_id=$1", source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            tenant_id = str(source["tenant_id"])
            mappings = [dict(r) for r in await conn.fetch(
                "SELECT * FROM field_mapping WHERE source_id=$1", source_id)]

            # In Option A: use existing entity refs as synthetic "DCIM records"
            entities = [dict(r) for r in await conn.fetch(
                "SELECT * FROM infrastructure_entity_ref WHERE tenant_id=$1 LIMIT 500",
                tenant_id)]

        for entity in entities:
            received += 1
            raw = {
                "entity_class": entity["entity_class"],
                "name": entity["canonical_name"],
                "status": "ACTIVE",
            }

            # Publish raw payload
            raw_msg = {
                "source_id": source_id,
                "tenant_id": tenant_id,
                "raw_payload": raw,
                "ingest_ts": datetime.now(timezone.utc).isoformat(),
            }
            _producer.produce(
                "dcim.config.raw",
                json.dumps(raw_msg, default=str).encode(),
                key=source_id.encode(),
            )

            # Normalise and publish
            if mappings:
                normalised = normalise_record(raw, mappings, source_id, tenant_id)
            else:
                # No mappings: pass-through with defaults
                normalised = {
                    "message_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "record_id": str(uuid.uuid4()),
                    "entity_class": entity["entity_class"],
                    "canonical_name": entity["canonical_name"],
                    "operational_status": "ONLINE",
                    "attributes": [],
                    "capacity_specs": [],
                    "relationships": [],
                    "identity_signals": [{
                        "signal_type": "ASSET_TAG",
                        "signal_value": str(entity["entity_id"]),
                        "confidence": 1.0,
                    }],
                    "event_ts": datetime.now(timezone.utc).isoformat(),
                    "ingest_ts": datetime.now(timezone.utc).isoformat(),
                }

            if normalised:
                _producer.produce(
                    "dcim.config.normalized",
                    json.dumps(normalised, default=str).encode(),
                    key=tenant_id.encode(),
                )
                mapped += 1
                stats["records_published"] += 1
            else:
                rejected += 1
                stats["records_rejected"] += 1

        _producer.flush(5)

        duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_log(log_id, source_id, tenant_id, sync_type, sync_mode,
                    records_received, records_mapped, records_rejected, entities_created,
                    entities_updated, duration_ms, started_at, completed_at, status)
                VALUES($1,$2,$3,'FULL','INCREMENTAL',$4,$5,$6,$7,$8,$9,$10,NOW(),'COMPLETED')
                """,
                sync_log_id, source_id, tenant_id, received, mapped, rejected,
                created, updated, duration_ms, started,
            )
            await conn.execute(
                "UPDATE source_system SET last_sync_at=NOW() WHERE source_id=$1", source_id)

        stats["syncs_completed"] += 1
        stats["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        return {"status": "completed", "received": received, "mapped": mapped, "rejected": rejected}

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Sync error for {source_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore DCIM Ingestion", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _producer
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=8)
    _producer = Producer({"bootstrap.servers": KAFKA_BROKERS, "client.id": "dcim-ingestion", "acks": 1})
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info("DCIM ingestion service ready")


@app.on_event("shutdown")
async def shutdown():
    if _producer:
        _producer.flush(5)
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "dcim-ingestion"}


@app.get("/stats")
def get_stats():
    return stats


@app.get("/sources")
async def list_sources():
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_id, source_name, source_class, vendor_name, status, last_sync_at "
            "FROM source_system ORDER BY source_name")
    return [dict(r) for r in rows]


@app.post("/sources/{source_id}/sync")
async def trigger_sync(source_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(run_sync, source_id)
    return {"status": "sync_started", "source_id": source_id}


@app.post("/sync/all")
async def sync_all(background_tasks: BackgroundTasks):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_id FROM source_system WHERE status='ACTIVE' AND source_class='DCIM'")
    for row in rows:
        background_tasks.add_task(run_sync, str(row["source_id"]))
    return {"status": "sync_started", "count": len(rows)}


@app.get("/sync/logs")
async def sync_logs(limit: int = 50):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sync_log ORDER BY started_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
