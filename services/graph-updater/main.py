"""
FlowCore Graph Updater Service
The core Digital Twin constructor.
Consumes: dcim.config.normalized, metrics.timeseries.raw, alerts.raw,
          discovery.snmp.results, discovery.bmc.results
Writes:   Neo4j (entities + relationships), graph.mutations Kafka topic
Performs: Entity resolution using entity_resolution_rule from PostgreSQL
"""
import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import uvicorn
from confluent_kafka import Producer, Consumer, KafkaError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("graph-updater")

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
NEO4J_URI = f"bolt://{os.getenv('NEO4J_HOST','neo4j')}:{os.getenv('NEO4J_BOLT_PORT','7687')}"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "flowcore_secret")
PORT = int(os.getenv("GRAPH_UPDATER_PORT", "8010"))

TOPICS = [
    "dcim.config.normalized",
    "metrics.timeseries.raw",
    "alerts.raw",
    "discovery.snmp.results",
    "discovery.bmc.results",
]

# ── State ─────────────────────────────────────────────────────────────────────
stats = {
    "entities_created": 0,
    "entities_updated": 0,
    "relationships_created": 0,
    "alerts_processed": 0,
    "metrics_processed": 0,
    "mutations_published": 0,
    "errors": 0,
    "started_at": None,
}

# Global driver and pool (sync Neo4j driver used in thread)
_neo4j_driver = None
_pg_pool: Optional[asyncpg.Pool] = None
_producer: Optional[Producer] = None
_resolution_rules: list = []
_entity_cache: dict = {}  # signal_value -> entity_id (in-memory for hot-path)

CONSUMER_RUNNING = False


# ── Entity resolution ─────────────────────────────────────────────────────────

def resolve_entity(signals: list[dict], tenant_id: str, entity_class: str) -> Optional[str]:
    """
    Try each signal against the in-memory entity cache.
    Returns canonical entity_id or None (will create new).
    """
    for signal in signals:
        cache_key = f"{tenant_id}:{signal['signal_type']}:{signal['signal_value']}"
        if cache_key in _entity_cache:
            return _entity_cache[cache_key]
    return None


def cache_entity_signals(entity_id: str, tenant_id: str, signals: list[dict]) -> None:
    for signal in signals:
        cache_key = f"{tenant_id}:{signal['signal_type']}:{signal['signal_value']}"
        _entity_cache[cache_key] = entity_id


# ── Neo4j upsert helpers ──────────────────────────────────────────────────────

def neo4j_upsert_entity(entity_id: str, tenant_id: str, entity_class: str,
                        canonical_name: str, props: dict) -> tuple[bool, bool]:
    """Idempotent MERGE on entity_id. Returns (was_created, was_updated)."""
    props["entity_id"] = entity_id
    props["tenant_id"] = tenant_id
    props["entity_class"] = entity_class
    props["canonical_name"] = canonical_name
    props["updated_at"] = datetime.now(timezone.utc).isoformat()

    with _neo4j_driver.session() as session:
        result = session.run(
            """
            MERGE (n:InfrastructureEntity {entity_id: $entity_id})
            ON CREATE SET n = $props, n.created_at = $now
            ON MATCH SET n += $props
            RETURN n.created_at = $now AS is_new
            """,
            entity_id=entity_id,
            props=props,
            now=props["updated_at"],
        )
        record = result.single()
        is_new = record["is_new"] if record else False
        return is_new, not is_new


def neo4j_upsert_relationship(from_id: str, to_id: str, rel_type: str, props: dict) -> None:
    with _neo4j_driver.session() as session:
        session.run(
            f"""
            MATCH (a:InfrastructureEntity {{entity_id: $from_id}})
            MATCH (b:InfrastructureEntity {{entity_id: $to_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            SET r += $props, r.last_confirmed_at = $now
            """,
            from_id=from_id,
            to_id=to_id,
            props=props,
            now=datetime.now(timezone.utc).isoformat(),
        )
        stats["relationships_created"] += 1


def neo4j_update_alert_count(entity_id: str, delta: int) -> None:
    with _neo4j_driver.session() as session:
        session.run(
            """
            MATCH (n:InfrastructureEntity {entity_id: $eid})
            SET n.active_alert_count = COALESCE(n.active_alert_count, 0) + $delta,
                n.updated_at = $now
            """,
            eid=entity_id,
            delta=delta,
            now=datetime.now(timezone.utc).isoformat(),
        )


def neo4j_update_metric(entity_id: str, metric_name: str, value: float) -> None:
    """Update live metric properties on the entity node."""
    prop_name = f"live_{metric_name.replace('.', '_').replace(' ', '_')}"
    with _neo4j_driver.session() as session:
        session.run(
            f"""
            MATCH (n:InfrastructureEntity {{entity_id: $eid}})
            SET n.{prop_name} = $val, n.last_seen_at = $now, n.updated_at = $now
            """,
            eid=entity_id,
            val=value,
            now=datetime.now(timezone.utc).isoformat(),
        )


# ── Mutation publisher ────────────────────────────────────────────────────────

def publish_mutation(tenant_id: str, operation: str, entity_class: str,
                     entity_id: str, before: Optional[dict], after: Optional[dict],
                     source_topic: Optional[str] = None) -> None:
    msg = {
        "message_id": f"mut-{int(time.time()*1000)}",
        "tenant_id": tenant_id,
        "mutation_id": f"mut-{entity_id[:8]}-{int(time.time())}",
        "operation_type": operation,
        "entity_class": entity_class,
        "entity_id": entity_id,
        "before_state": before,
        "after_state": after,
        "source_service": "graph-updater",
        "kafka_topic": source_topic,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    _producer.produce("graph.mutations", json.dumps(msg, default=str).encode(),
                      key=entity_id.encode())
    _producer.poll(0)
    stats["mutations_published"] += 1


# ── PG write-back helpers ─────────────────────────────────────────────────────

async def pg_upsert_entity_ref(entity_id: str, tenant_id: str, entity_class: str,
                                canonical_name: str, dc_id: Optional[str]) -> None:
    """Keep infrastructure_entity_ref in PostgreSQL in sync."""
    async with _pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO infrastructure_entity_ref(entity_id, tenant_id, entity_class, canonical_name, dc_id)
            VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(entity_id) DO UPDATE
              SET canonical_name=EXCLUDED.canonical_name, entity_class=EXCLUDED.entity_class
            """,
            entity_id, tenant_id, entity_class, canonical_name, dc_id,
        )


async def pg_write_identity_signals(signals: list[dict], entity_id: str,
                                     tenant_id: str, source_id: str) -> None:
    async with _pg_pool.acquire() as conn:
        for s in signals:
            await conn.execute(
                """
                INSERT INTO identity_signal(entity_id, source_id, tenant_id, signal_type, signal_value,
                                            match_confidence, resolution_status, observed_at, resolved_at)
                VALUES($1,$2,$3,$4,$5,1.0,'RESOLVED',NOW(),NOW())
                ON CONFLICT DO NOTHING
                """,
                entity_id, source_id, tenant_id, s["signal_type"], s["signal_value"],
            )


# ── Message handlers ──────────────────────────────────────────────────────────

def handle_dcim_normalized(msg: dict) -> None:
    try:
        tenant_id = msg["tenant_id"]
        source_id = msg.get("source_id", "")
        entity_class = msg.get("entity_class", "DEVICE")
        canonical_name = msg.get("canonical_name", "Unknown")
        signals = msg.get("identity_signals", [])
        dc_id = msg.get("dc_id")

        # Entity resolution
        entity_id = resolve_entity(signals, tenant_id, entity_class)
        is_new = entity_id is None

        if is_new:
            import uuid
            entity_id = str(uuid.uuid4())

        # Build Neo4j properties
        props = {
            "canonical_type": msg.get("canonical_type"),
            "operational_status": msg.get("operational_status", "UNKNOWN"),
            "criticality_level": msg.get("criticality_level"),
            "redundancy_posture": msg.get("redundancy_posture"),
            "health_score": 0.9 if msg.get("operational_status") == "ONLINE" else 0.5,
        }

        created, updated = neo4j_upsert_entity(entity_id, tenant_id, entity_class, canonical_name, props)

        if created:
            stats["entities_created"] += 1
        elif updated:
            stats["entities_updated"] += 1

        # Cache signals
        cache_entity_signals(entity_id, tenant_id, signals)

        # Handle relationships
        for rel in msg.get("relationships", []):
            try:
                neo4j_upsert_relationship(entity_id, rel["to_entity_id"],
                                          rel["relationship_type"].upper(), rel.get("properties", {}))
            except Exception:
                pass

        publish_mutation(tenant_id, "CREATE" if is_new else "UPDATE",
                         entity_class, entity_id, None, props, "dcim.config.normalized")

        # Async PG write-back (fire and forget via loop)
        asyncio.run_coroutine_threadsafe(
            pg_upsert_entity_ref(entity_id, tenant_id, entity_class, canonical_name, dc_id),
            _async_loop
        )
        if signals:
            asyncio.run_coroutine_threadsafe(
                pg_write_identity_signals(signals, entity_id, tenant_id, source_id),
                _async_loop
            )

    except Exception as e:
        stats["errors"] += 1
        logger.error(f"DCIM handler error: {e}", exc_info=True)


def handle_metric(msg: dict) -> None:
    try:
        entity_id = msg.get("entity_id")
        metric_id = msg.get("metric_id", "")
        value = msg.get("value", 0)

        if entity_id and value is not None:
            neo4j_update_metric(entity_id, metric_id[:20], float(value))
            stats["metrics_processed"] += 1
    except Exception as e:
        stats["errors"] += 1
        logger.debug(f"Metric handler error: {e}")


def handle_alert(msg: dict) -> None:
    try:
        entity_id = msg.get("entity_id")
        status = msg.get("status", "ACTIVE")
        if entity_id:
            delta = 1 if status == "ACTIVE" else -1
            neo4j_update_alert_count(entity_id, delta)
            stats["alerts_processed"] += 1
    except Exception as e:
        stats["errors"] += 1
        logger.debug(f"Alert handler error: {e}")


def handle_snmp(msg: dict) -> None:
    try:
        tenant_id = msg.get("tenant_id")
        source_id = msg.get("source_id", "")
        if not tenant_id:
            return

        signals = []
        if msg.get("sys_oid"):
            signals.append({"signal_type": "SNMP_OID", "signal_value": msg["sys_oid"]})
        if msg.get("serial_number"):
            signals.append({"signal_type": "SERIAL_NUMBER", "signal_value": msg["serial_number"]})
        for ip in msg.get("ip_addresses", []):
            signals.append({"signal_type": "IP_ADDRESS", "signal_value": ip})

        entity_id = resolve_entity(signals, tenant_id, "DEVICE")
        if entity_id:
            # Update with discovered info
            props = {
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "discovered_manufacturer": msg.get("manufacturer"),
                "discovered_model": msg.get("model"),
            }
            neo4j_upsert_entity(entity_id, tenant_id, "DEVICE",
                                 msg.get("sys_name", "Unknown"), props)
        # If no match, don't create — topology agent will raise a drift event

    except Exception as e:
        stats["errors"] += 1
        logger.debug(f"SNMP handler error: {e}")


def handle_bmc(msg: dict) -> None:
    try:
        tenant_id = msg.get("tenant_id")
        if not tenant_id:
            return
        signals = []
        if msg.get("serial_number"):
            signals.append({"signal_type": "SERIAL_NUMBER", "signal_value": msg["serial_number"]})

        entity_id = resolve_entity(signals, tenant_id, "DEVICE")
        if entity_id:
            props = {
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "power_state": msg.get("power_state"),
                "health_state": msg.get("health_state"),
            }
            neo4j_upsert_entity(entity_id, tenant_id, "DEVICE", msg.get("model", "Unknown"), props)
    except Exception as e:
        stats["errors"] += 1
        logger.debug(f"BMC handler error: {e}")


HANDLERS = {
    "dcim.config.normalized": handle_dcim_normalized,
    "metrics.timeseries.raw": handle_metric,
    "alerts.raw": handle_alert,
    "discovery.snmp.results": handle_snmp,
    "discovery.bmc.results": handle_bmc,
}


def message_handler(topic: str, msg: dict) -> None:
    handler = HANDLERS.get(topic)
    if handler:
        handler(msg)


# ── Consumer thread ───────────────────────────────────────────────────────────
_async_loop: Optional[asyncio.AbstractEventLoop] = None


def consumer_thread():
    global CONSUMER_RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "graph-updater-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "max.poll.interval.ms": 300000,
    })
    consumer.subscribe(TOPICS)
    logger.info(f"Graph updater consuming from {TOPICS}")
    CONSUMER_RUNNING = True

    flush_counter = 0
    while CONSUMER_RUNNING:
        msgs = consumer.consume(num_messages=100, timeout=1.0)
        for msg in msgs:
            if msg.error():
                continue
            try:
                value = json.loads(msg.value().decode())
                message_handler(msg.topic(), value)
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Consumer error: {e}")

        flush_counter += 1
        if flush_counter % 50 == 0 and _producer:
            _producer.flush(1)

    consumer.close()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Graph Updater", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _neo4j_driver, _pg_pool, _producer, _resolution_rules, _async_loop

    _async_loop = asyncio.get_event_loop()

    # Neo4j (sync driver for thread use)
    _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    logger.info("Neo4j driver ready")

    # PostgreSQL async pool
    _pg_pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=8)
    logger.info("PostgreSQL pool ready")

    # Kafka producer
    _producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "client.id": "graph-updater",
        "acks": 1,
        "linger.ms": 5,
    })

    # Load entity resolution rules
    async with _pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM entity_resolution_rule WHERE is_active=true ORDER BY priority ASC"
        )
        _resolution_rules = [dict(r) for r in rows]
    logger.info(f"Loaded {len(_resolution_rules)} entity resolution rules")

    # Warm entity cache from existing PG entity refs
    async with _pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT e.entity_id, e.tenant_id, i.signal_type, i.signal_value "
            "FROM infrastructure_entity_ref e "
            "JOIN identity_signal i ON i.entity_id = e.entity_id "
            "WHERE i.resolution_status = 'RESOLVED' LIMIT 50000"
        )
        for r in rows:
            cache_key = f"{r['tenant_id']}:{r['signal_type']}:{r['signal_value']}"
            _entity_cache[cache_key] = str(r["entity_id"])
    logger.info(f"Entity cache warmed with {len(_entity_cache)} signals")

    stats["started_at"] = datetime.now(timezone.utc).isoformat()

    # Start consumer thread
    t = threading.Thread(target=consumer_thread, daemon=True, name="graph-consumer")
    t.start()


@app.on_event("shutdown")
async def shutdown():
    global CONSUMER_RUNNING
    CONSUMER_RUNNING = False
    if _producer:
        _producer.flush(5)
    if _pg_pool:
        await _pg_pool.close()
    if _neo4j_driver:
        _neo4j_driver.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "graph-updater", "consumer_running": CONSUMER_RUNNING}


@app.get("/stats")
def get_stats():
    return stats


@app.get("/cache/size")
def cache_size():
    return {"entity_cache_size": len(_entity_cache)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
