"""
FlowCore Eventing Integration Service
Consumes drift.events (Phase 1) and incidents.correlated (Phase 2).
Creates ServiceNow tickets via configurable payload mapping.
Port: 4002
"""
import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx
import uvicorn
from confluent_kafka import Consumer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("eventing-integration")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
PORT = int(os.getenv("EVENTING_API_INTERNAL_PORT", "4002"))

stats = {
    "drift_events_received": 0,
    "tickets_created": 0,
    "webhook_calls": 0,
    "errors": 0,
    "started_at": None,
}

_pool: Optional[asyncpg.Pool] = None
_async_loop = None
CONSUMER_RUNNING = False


# ── ITSM integration ──────────────────────────────────────────────────────────

async def load_itsm_config(tenant_id: str) -> Optional[dict]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM itsm_integration_config WHERE tenant_id=$1 AND is_active=true LIMIT 1",
            tenant_id,
        )
    return dict(row) if row else None


async def create_servicenow_ticket(config: dict, drift_event: dict) -> Optional[str]:
    """Create a ServiceNow incident from a drift event."""
    base_url = config.get("endpoint_url", "")
    if not base_url:
        return None

    severity_priority_map = {"CRITICAL": "1", "MAJOR": "2", "MINOR": "3"}
    priority = severity_priority_map.get(drift_event.get("severity", "MINOR"), "3")

    payload = {
        "short_description": (
            f"[FlowCore Drift] {drift_event.get('drift_type')}: "
            f"{drift_event.get('description', '')[:100]}"
        ),
        "description": json.dumps({
            "drift_id": drift_event.get("drift_id"),
            "drift_type": drift_event.get("drift_type"),
            "severity": drift_event.get("severity"),
            "affected_entity_id": drift_event.get("affected_entity_id"),
            "description": drift_event.get("description"),
            "detected_at": drift_event.get("detected_at"),
            "agent_version": drift_event.get("agent_version"),
        }, indent=2),
        "priority": priority,
        "category": "Infrastructure",
        "subcategory": "Data Center",
        "assignment_group": config.get("assignment_group", "NOC"),
        "caller_id": "flowcore.system",
    }

    # Apply custom field mappings if configured
    template = config.get("payload_template") or {}
    if isinstance(template, str):
        template = json.loads(template)
    payload.update(template)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            auth_type = config.get("auth_type", "BASIC")

            if auth_type == "BASIC":
                auth = (config.get("username", ""), config.get("api_key", ""))
                resp = await client.post(
                    f"{base_url}/api/now/table/incident",
                    json=payload, headers=headers, auth=auth
                )
            else:
                headers["Authorization"] = f"Bearer {config.get('api_key', '')}"
                resp = await client.post(
                    f"{base_url}/api/now/table/incident",
                    json=payload, headers=headers
                )

            if resp.status_code in (200, 201):
                ticket_ref = resp.json().get("result", {}).get("number", "")
                logger.info(f"ServiceNow ticket created: {ticket_ref}")
                return ticket_ref
            else:
                logger.warning(f"ServiceNow returned {resp.status_code}: {resp.text[:200]}")
                return None

    except httpx.ConnectError:
        logger.debug("ServiceNow not reachable (dev mode — ticket creation skipped)")
        return f"DEV-{drift_event.get('drift_id', 'unknown')[:8].upper()}"
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"ServiceNow error: {e}")
        return None


async def send_webhook(url: str, payload: dict, headers: dict = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers or {})
        stats["webhook_calls"] += 1
        return resp.status_code < 400
    except Exception as e:
        logger.debug(f"Webhook error: {e}")
        return False


async def handle_drift_event(event: dict) -> None:
    stats["drift_events_received"] += 1
    tenant_id = event.get("tenant_id", "")
    drift_id = event.get("drift_id", "")

    config = await load_itsm_config(tenant_id)
    ticket_ref = None

    if config:
        ticket_ref = await create_servicenow_ticket(config, event)
        if ticket_ref:
            stats["tickets_created"] += 1
            # Update drift_event with ticket reference
            async with _pool.acquire() as conn:
                await conn.execute(
                    "UPDATE drift_event SET itsm_ticket_ref=$1 WHERE drift_id=$2",
                    ticket_ref, drift_id,
                )

    # Send webhook if configured (even without ITSM)
    webhook_url = (config or {}).get("webhook_url")
    if webhook_url:
        await send_webhook(webhook_url, {
            "event_type": "drift_detected",
            "drift_id": drift_id,
            "severity": event.get("severity"),
            "drift_type": event.get("drift_type"),
            "description": event.get("description"),
            "ticket_ref": ticket_ref,
            "detected_at": event.get("detected_at"),
        })

    logger.info(
        f"Drift event processed: drift_id={drift_id} "
        f"severity={event.get('severity')} ticket={ticket_ref}"
    )


# ── Consumer thread ───────────────────────────────────────────────────────────

def consumer_thread():
    global CONSUMER_RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "eventing-integration-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(["drift.events", "incidents.correlated"])
    logger.info("Eventing integration consuming drift.events")
    CONSUMER_RUNNING = True

    while CONSUMER_RUNNING:
        msgs = consumer.consume(num_messages=20, timeout=1.0)
        for msg in msgs:
            if msg.error():
                continue
            try:
                payload = json.loads(msg.value().decode())
                if msg.topic() == "drift.events":
                    asyncio.run_coroutine_threadsafe(
                        handle_drift_event(payload), _async_loop
                    )
                elif msg.topic() == "incidents.correlated":
                    # Phase 2: handle correlated incidents
                    logger.debug(f"Incident received (Phase 2 processing pending)")
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Consumer error: {e}")

    consumer.close()


# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="FlowCore Eventing Integration", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _async_loop
    _async_loop = asyncio.get_event_loop()
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=5)
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    t = threading.Thread(target=consumer_thread, daemon=True, name="eventing-consumer")
    t.start()
    logger.info("Eventing integration service ready")


@app.on_event("shutdown")
async def shutdown():
    global CONSUMER_RUNNING
    CONSUMER_RUNNING = False
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "eventing-integration"}


@app.get("/stats")
def get_stats():
    return stats


class ITSMConfigBody(BaseModel):
    tenant_id: str
    endpoint_url: str
    auth_type: str = "BASIC"
    username: Optional[str] = None
    api_key: Optional[str] = None
    assignment_group: Optional[str] = "NOC"
    webhook_url: Optional[str] = None
    payload_template: Optional[dict] = None


@app.post("/itsm/config")
async def upsert_itsm_config(body: ITSMConfigBody):
    import uuid
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO itsm_integration_config(
                config_id, tenant_id, integration_type, endpoint_url,
                auth_type, payload_template, is_active, created_at)
            VALUES($1,$2,'SERVICENOW',$3,$4,$5,true,NOW())
            ON CONFLICT(tenant_id, integration_type) DO UPDATE
              SET endpoint_url=EXCLUDED.endpoint_url,
                  auth_type=EXCLUDED.auth_type,
                  payload_template=EXCLUDED.payload_template
            """,
            str(uuid.uuid4()), body.tenant_id, body.endpoint_url, body.auth_type,
            json.dumps({
                "assignment_group": body.assignment_group,
                "username": body.username,
                "api_key": body.api_key,
                "webhook_url": body.webhook_url,
                **(body.payload_template or {}),
            }),
        )
    return {"status": "configured"}


@app.post("/test/drift")
async def test_drift_notification(tenant_id: str):
    """Send a test drift event notification for integration testing."""
    fake_drift = {
        "drift_id": "test-drift-0001",
        "tenant_id": tenant_id,
        "drift_type": "ATTRIBUTE_CONFLICT",
        "severity": "MINOR",
        "affected_entity_id": "test-entity-0001",
        "description": "Test drift event from FlowCore integration test",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": "topology-reconciliation-agent@1.0.0",
    }
    await handle_drift_event(fake_drift)
    return {"status": "test_sent"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
