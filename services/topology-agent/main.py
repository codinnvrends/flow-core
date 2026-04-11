"""
FlowCore Topology Reconciliation Agent
Rule-based comparison of DCIM topology vs discovered reality.
Consumes: dcim.config.normalized, discovery.snmp.results, discovery.bmc.results, graph.mutations
Produces: drift.events, drift.suggestions
Writes:   drift_event + drift_suggestion to PostgreSQL
          proposed-namespace annotations to Neo4j (not live graph)
"""
import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import uvicorn
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("topology-agent")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
NEO4J_URI = f"bolt://{os.getenv('NEO4J_HOST','neo4j')}:{os.getenv('NEO4J_BOLT_PORT','7687')}"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "flowcore_secret")
PORT = int(os.getenv("TOPO_AGENT_PORT", "8020"))
AGENT_VERSION = "topology-reconciliation-agent@1.0.0"

stats = {
    "drift_events_generated": 0,
    "drift_suggestions_generated": 0,
    "dcim_records_seen": 0,
    "discovery_records_seen": 0,
    "errors": 0,
    "started_at": None,
}

_pool: Optional[asyncpg.Pool] = None
_producer: Optional[Producer] = None
_neo4j = None
_async_loop: Optional[asyncio.AbstractEventLoop] = None
CONSUMER_RUNNING = False

# In-memory seen sets for drift comparison
_dcim_entities: dict = {}        # entity_id → dcim_state (from dcim.config.normalized)
_discovered_entities: dict = {}  # signal_value → discovery_state


# ── Drift detection rules ─────────────────────────────────────────────────────

SEVERITY_MAP = {
    "MISSING_IN_REALITY": "CRITICAL",
    "MISSING_IN_DCIM": "MAJOR",
    "POSITION_MISMATCH": "MAJOR",
    "ATTRIBUTE_CONFLICT": "MINOR",
    "CAPACITY_DISCREPANCY": "MINOR",
    "POWER_PATH_MISMATCH": "MAJOR",
}


async def emit_drift_event(
    tenant_id: str,
    drift_type: str,
    affected_entity_id: str,
    affected_class: str,
    source_a_id: str,
    source_a_state: dict,
    source_b_id: str,
    source_b_state: dict,
    conflict_field: Optional[str],
    description: str,
    confidence: float,
) -> str:
    drift_id = str(uuid.uuid4())
    severity = SEVERITY_MAP.get(drift_type, "MINOR")
    now = datetime.now(timezone.utc).isoformat()

    # Write to PostgreSQL
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO drift_event(
                drift_id, tenant_id, drift_type, severity,
                affected_entity_id, affected_entity_class,
                source_a_id, source_a_state, source_b_id, source_b_state,
                conflict_field, description, detection_confidence,
                status, agent_version, detected_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'OPEN',$14,NOW())
            ON CONFLICT(drift_id) DO NOTHING
            """,
            drift_id, tenant_id, drift_type, severity,
            affected_entity_id, affected_class,
            source_a_id, json.dumps(source_a_state),
            source_b_id, json.dumps(source_b_state),
            conflict_field, description, confidence,
            AGENT_VERSION,
        )

    # Write proposed annotation to Neo4j (not live graph — proposed namespace)
    try:
        with _neo4j.session() as session:
            session.run(
                """
                MERGE (d:ProposedDriftAnnotation {drift_id: $did})
                SET d.entity_id = $eid,
                    d.drift_type = $dtype,
                    d.severity = $sev,
                    d.description = $desc,
                    d.detected_at = $now,
                    d.status = 'OPEN'
                """,
                did=drift_id, eid=affected_entity_id,
                dtype=drift_type, sev=severity,
                desc=description, now=now,
            )
    except Exception as e:
        logger.debug(f"Neo4j annotation error: {e}")

    # Publish to drift.events Kafka topic
    msg = {
        "message_id": str(uuid.uuid4()),
        "drift_id": drift_id,
        "tenant_id": tenant_id,
        "drift_type": drift_type,
        "severity": severity,
        "affected_entity_id": affected_entity_id,
        "affected_entity_class": affected_class,
        "source_a_id": source_a_id,
        "source_a_state": source_a_state,
        "source_b_id": source_b_id,
        "source_b_state": source_b_state,
        "conflict_field": conflict_field,
        "description": description,
        "detection_confidence": confidence,
        "agent_version": AGENT_VERSION,
        "detected_at": now,
    }
    _producer.produce("drift.events", json.dumps(msg, default=str).encode(),
                      key=tenant_id.encode())
    _producer.poll(0)
    stats["drift_events_generated"] += 1

    # Generate drift suggestion
    await emit_drift_suggestion(drift_id, tenant_id, drift_type, source_a_id)
    return drift_id


async def emit_drift_suggestion(drift_id: str, tenant_id: str,
                                 drift_type: str, dcim_source_id: str) -> None:
    suggestion_id = str(uuid.uuid4())
    action_map = {
        "MISSING_IN_DCIM": "ADD_TO_DCIM",
        "MISSING_IN_REALITY": "VERIFY_OR_DECOMMISSION",
        "ATTRIBUTE_CONFLICT": "UPDATE_CANONICAL_VALUE",
        "CAPACITY_DISCREPANCY": "RECONCILE_CAPACITY",
        "POSITION_MISMATCH": "CORRECT_RACK_POSITION",
        "POWER_PATH_MISMATCH": "VERIFY_POWER_CONNECTIONS",
    }
    proposed_action = action_map.get(drift_type, "MANUAL_REVIEW")

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO drift_suggestion(suggestion_id, drift_id, tenant_id, proposed_action, operator_decision)
            VALUES($1,$2,$3,$4,'PENDING')
            ON CONFLICT DO NOTHING
            """,
            suggestion_id, drift_id, tenant_id, proposed_action,
        )

    suggestion_msg = {
        "suggestion_id": suggestion_id,
        "drift_id": drift_id,
        "tenant_id": tenant_id,
        "proposed_action": proposed_action,
        "message_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _producer.produce("drift.suggestions", json.dumps(suggestion_msg, default=str).encode(),
                      key=drift_id.encode())
    _producer.poll(0)
    stats["drift_suggestions_generated"] += 1


# ── Reconciliation logic ──────────────────────────────────────────────────────

def reconcile_dcim_vs_discovery(dcim_msg: dict, tenant_id: str) -> None:
    entity_id = None
    for sig in dcim_msg.get("identity_signals", []):
        cache_key = f"{tenant_id}:{sig['signal_type']}:{sig['signal_value']}"
        _dcim_entities[cache_key] = {
            "entity_id": dcim_msg.get("record_id", ""),
            "source_id": dcim_msg.get("source_id", ""),
            "entity_class": dcim_msg.get("entity_class", "DEVICE"),
            "canonical_name": dcim_msg.get("canonical_name"),
            "status": dcim_msg.get("operational_status"),
        }
    stats["dcim_records_seen"] += 1


def check_discovery_vs_dcim(disc_msg: dict, tenant_id: str, disc_source_id: str) -> None:
    """Check if discovered device exists in DCIM. If not → MISSING_IN_DCIM drift."""
    signals = []
    if disc_msg.get("sys_oid"):
        signals.append(f"{tenant_id}:SNMP_OID:{disc_msg['sys_oid']}")
    if disc_msg.get("serial_number"):
        signals.append(f"{tenant_id}:SERIAL_NUMBER:{disc_msg['serial_number']}")
    for ip in disc_msg.get("ip_addresses", []):
        signals.append(f"{tenant_id}:IP_ADDRESS:{ip}")

    # Look for any matching DCIM entry
    found_in_dcim = any(key in _dcim_entities for key in signals)

    if not found_in_dcim and disc_msg.get("sys_name"):
        # Discovered but not in DCIM → emit drift
        asyncio.run_coroutine_threadsafe(
            emit_drift_event(
                tenant_id=tenant_id,
                drift_type="MISSING_IN_DCIM",
                affected_entity_id=str(uuid.uuid4()),  # new entity not yet in graph
                affected_class="DEVICE",
                source_a_id=_get_dcim_source_id(tenant_id),
                source_a_state={},
                source_b_id=disc_source_id,
                source_b_state={
                    "target_ip": disc_msg.get("target_ip"),
                    "sys_name": disc_msg.get("sys_name"),
                    "serial": disc_msg.get("serial_number"),
                    "manufacturer": disc_msg.get("manufacturer"),
                },
                conflict_field="canonical_name",
                description=f"Device {disc_msg.get('sys_name', disc_msg.get('target_ip', 'unknown'))} discovered but absent from DCIM",
                confidence=0.85,
            ),
            _async_loop,
        )
    stats["discovery_records_seen"] += 1


def _get_dcim_source_id(tenant_id: str) -> str:
    for state in _dcim_entities.values():
        if state.get("source_id"):
            return state["source_id"]
    return "00000000-0000-0000-0000-000000000000"


# ── Consumer thread ───────────────────────────────────────────────────────────

def consumer_thread():
    global CONSUMER_RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "topology-agent-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([
        "dcim.config.normalized",
        "discovery.snmp.results",
        "discovery.bmc.results",
        "graph.mutations",
    ])
    logger.info("Topology agent consuming")
    CONSUMER_RUNNING = True
    import random

    while CONSUMER_RUNNING:
        msgs = consumer.consume(num_messages=50, timeout=1.0)
        for msg in msgs:
            if msg.error():
                continue
            try:
                payload = json.loads(msg.value().decode())
                topic = msg.topic()

                if topic == "dcim.config.normalized":
                    reconcile_dcim_vs_discovery(payload, payload.get("tenant_id", ""))

                elif topic in ("discovery.snmp.results", "discovery.bmc.results"):
                    tenant_id = payload.get("tenant_id", "")
                    source_id = payload.get("source_id", "")
                    # Only check ~10% of discoveries to avoid drift flood in Option A
                    if random.random() < 0.10:
                        check_discovery_vs_dcim(payload, tenant_id, source_id)

            except Exception as e:
                stats["errors"] += 1
                logger.debug(f"Handler error: {e}")

    consumer.close()


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Topology Reconciliation Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _producer, _neo4j, _async_loop
    _async_loop = asyncio.get_event_loop()
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=8)
    _producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "client.id": "topology-agent",
        "acks": 1,
    })
    _neo4j = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    t = threading.Thread(target=consumer_thread, daemon=True, name="topo-consumer")
    t.start()
    logger.info("Topology reconciliation agent ready")


@app.on_event("shutdown")
async def shutdown():
    global CONSUMER_RUNNING
    CONSUMER_RUNNING = False
    if _producer:
        _producer.flush(3)
    if _pool:
        await _pool.close()
    if _neo4j:
        _neo4j.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "topology-reconciliation-agent"}


@app.get("/stats")
def get_stats():
    return {**stats, "dcim_cache_size": len(_dcim_entities)}


@app.get("/drift/open")
async def get_open_drifts(tenant_id: Optional[str] = None, limit: int = 50):
    q = "SELECT * FROM drift_event WHERE status='OPEN'"
    params = []
    if tenant_id:
        q += " AND tenant_id=$1"
        params.append(tenant_id)
    q += f" ORDER BY detected_at DESC LIMIT {limit}"
    async with _pool.acquire() as conn:
        rows = await conn.fetch(q, *params)
    return [dict(r) for r in rows]


@app.post("/drift/{drift_id}/resolve")
async def resolve_drift(drift_id: str, decision: str = "ACCEPTED"):
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE drift_event SET status=$1, resolved_at=NOW() WHERE drift_id=$2",
            decision, drift_id,
        )
        await conn.execute(
            "UPDATE drift_suggestion SET operator_decision=$1, decided_at=NOW() WHERE drift_id=$2",
            decision, drift_id,
        )
    return {"status": "updated", "drift_id": drift_id}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
