"""
FlowCore Synthetic Replay Service
Reads from seeded PostgreSQL + TimescaleDB, publishes to all 5 Kafka topics.
Modes: live (continuous generation) | historical (30-day seed replay)
"""
import sys
import os
# Add parent directory to path for shared telemetry module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telemetry

# Setup OpenTelemetry for SigNoz (must be before other imports)
tracer = telemetry.setup_telemetry("synthetic-replay")


import asyncio
import json
import logging
import math
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import uvicorn
from confluent_kafka import Producer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("synthetic-replay")

# ── Config from env ───────────────────────────────────────────────────────────
KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
TS_DSN = f"postgresql://{os.getenv('TS_USER','flowcore')}:{os.getenv('TS_PASSWORD','flowcore_secret')}@{os.getenv('TS_HOST','timescaledb')}:{os.getenv('TS_PORT','5432')}/{os.getenv('TS_DB','flowcore_ts')}"
REPLAY_PORT = int(os.getenv("REPLAY_PORT", "8050"))
REPLAY_MODE = os.getenv("REPLAY_MODE", "live")  # live | historical
EVENTS_PER_SEC = int(os.getenv("REPLAY_EVENTS_PER_SEC", "1000"))
HISTORICAL_SPEED = int(os.getenv("REPLAY_HISTORICAL_SPEED", "60"))

# ── Global state ──────────────────────────────────────────────────────────────
state = {
    "running": False,
    "mode": REPLAY_MODE,
    "events_per_sec": EVENTS_PER_SEC,
    "events_published": 0,
    "errors": 0,
    "started_at": None,
    "topics": ["dcim.config.normalized", "metrics.timeseries.raw", "alerts.raw",
               "discovery.snmp.results", "discovery.bmc.results"],
}
_replay_thread: Optional[threading.Thread] = None

# ── Kafka producer ────────────────────────────────────────────────────────────
producer: Optional[Producer] = None


def get_producer() -> Producer:
    global producer
    if producer is None:
        producer = Producer({
            "bootstrap.servers": KAFKA_BROKERS,
            "client.id": "synthetic-replay",
            "acks": 1,
            "linger.ms": 10,
            "batch.size": 65536,
        })
    return producer


def publish(topic: str, msg: dict, key: Optional[str] = None) -> None:
    payload = json.dumps(msg, default=str).encode()
    key_bytes = str(key).encode() if key else None
    get_producer().produce(topic, value=payload, key=key_bytes)
    state["events_published"] += 1


# ── Data cache from seed DBs ──────────────────────────────────────────────────
seed_data: dict = {
    "tenants": [],
    "entities": [],
    "source_systems": [],
    "metrics": [],
    "alert_types": [],
    "metric_datapoints_sample": [],
    "drift_events_sample": [],
}


async def load_seed_data():
    logger.info("Loading seed data from PostgreSQL and TimescaleDB...")
    pg = await asyncpg.connect(PG_DSN)
    ts = await asyncpg.connect(TS_DSN)

    try:
        seed_data["tenants"] = [dict(r) for r in await pg.fetch(
            "SELECT tenant_id, name, slug FROM tenant WHERE status='ACTIVE' LIMIT 10")]

        seed_data["entities"] = [dict(r) for r in await pg.fetch(
            "SELECT entity_id, tenant_id, entity_class, canonical_name, dc_id FROM infrastructure_entity_ref LIMIT 2000")]

        seed_data["source_systems"] = [dict(r) for r in await pg.fetch(
            "SELECT source_id, tenant_id, source_class, vendor_name, source_name FROM source_system WHERE status='ACTIVE'")]

        seed_data["metrics"] = [dict(r) for r in await ts.fetch(
            "SELECT metric_id, canonical_metric_name, metric_family, unit FROM metric_catalogue WHERE is_active=true LIMIT 50")]

        seed_data["alert_types"] = [dict(r) for r in await ts.fetch(
            "SELECT alert_type_id, canonical_alert_name, default_severity FROM alert_catalogue WHERE is_active=true LIMIT 20")]

        # Sample historical datapoints to understand value ranges per metric
        seed_data["metric_stats"] = [dict(r) for r in await ts.fetch("""
            SELECT metric_id, entity_class,
                   avg(value) as mean_val, stddev(value) as std_val,
                   min(value) as min_val, max(value) as max_val
            FROM metric_datapoint
            WHERE event_ts > NOW() - INTERVAL '7 days'
            GROUP BY metric_id, entity_class
            LIMIT 100
        """)]

        logger.info(
            f"Loaded: {len(seed_data['tenants'])} tenants, "
            f"{len(seed_data['entities'])} entities, "
            f"{len(seed_data['source_systems'])} sources, "
            f"{len(seed_data['metrics'])} metrics"
        )
    finally:
        await pg.close()
        await ts.close()


# ── Message generators ────────────────────────────────────────────────────────

def _make_dcim_message(entity: dict, source: dict, now: str) -> dict:
    return {
        "message_id": f"replay-{random.randint(0,999999)}",
        "tenant_id": entity["tenant_id"],
        "source_id": source["source_id"],
        "record_id": f"rec-{random.randint(0,999999)}",
        "entity_class": entity["entity_class"],
        "canonical_name": entity["canonical_name"],
        "canonical_type": _canonical_type(entity["entity_class"]),
        "operational_status": random.choice(["ONLINE", "ONLINE", "ONLINE", "DEGRADED", "UNKNOWN"]),
        "criticality_level": random.choice(["P1", "P2", "P2", "P3"]),
        "redundancy_posture": random.choice(["N+1", "2N", "N"]),
        "dc_id": entity.get("dc_id"),
        "attributes": [{"namespace": source.get("vendor_name", "dcim"), "key": "sync_ts", "value": now, "value_type": "TIMESTAMP"}],
        "capacity_specs": [{"dimension": "power_kw", "rated_value": round(random.uniform(2, 20), 2), "unit": "kW"}],
        "identity_signals": [{"signal_type": "ASSET_TAG", "signal_value": f"AT-{str(entity['entity_id'])[:8]}", "confidence": 1.0}],
        "relationships": [],
        "event_ts": now,
        "ingest_ts": now,
    }


def _canonical_type(entity_class: str) -> str:
    types = {
        "DEVICE": random.choice(["Server", "ToR-Switch", "GPU-Server", "Storage"]),
        "RACK": "StandardRack",
        "PDU": "ManagedPDU",
        "FEED": "PowerFeed",
        "SENSOR": random.choice(["CRAC", "Temperature", "Humidity"]),
        "INTERFACE": "EthernetInterface",
        "SERVICE": "Application",
    }
    return types.get(entity_class, entity_class)


def _make_metric_message(entity: dict, metric: dict, stats: dict, now: str) -> dict:
    mean = stats.get("mean_val", 50.0) or 50.0
    std = stats.get("std_val", 10.0) or 10.0
    value = max(0, random.gauss(mean, std * 0.3))
    value = min(value, stats.get("max_val", 100.0) or 100.0)
    return {
        "message_id": f"m-{random.randint(0,9999999)}",
        "tenant_id": entity["tenant_id"],
        "entity_id": entity["entity_id"],
        "entity_class": entity["entity_class"],
        "metric_id": metric["metric_id"],
        "source_id": _pick_telemetry_source(entity["tenant_id"]),
        "value": round(value, 3),
        "quality_flag": "VALID",
        "event_ts": now,
        "ingest_ts": now,
    }


def _pick_telemetry_source(tenant_id: str) -> str:
    for s in seed_data["source_systems"]:
        if s["tenant_id"] == tenant_id and s["source_class"] == "TELEMETRY":
            return s["source_id"]
    if seed_data["source_systems"]:
        return seed_data["source_systems"][0]["source_id"]
    return "00000000-0000-0000-0000-000000000000"


def _make_alert_message(entity: dict, alert_type: dict, now: str) -> dict:
    severity_map = {"CRITICAL": 95, "MAJOR": 78, "MINOR": 65, "WARNING": 50}
    severity = alert_type.get("default_severity", "WARNING")
    return {
        "message_id": f"a-{random.randint(0,9999999)}",
        "alert_id": f"alert-{random.randint(0,9999999)}",
        "tenant_id": entity["tenant_id"],
        "entity_id": entity["entity_id"],
        "entity_class": entity["entity_class"],
        "alert_type_id": alert_type["alert_type_id"],
        "source_id": _pick_telemetry_source(entity["tenant_id"]),
        "canonical_severity": severity,
        "source_severity": severity,
        "metric_value": round(severity_map.get(severity, 60) + random.uniform(-5, 5), 1),
        "status": "ACTIVE",
        "event_ts": now,
        "ingest_ts": now,
    }


def _make_snmp_message(entity: dict, source: dict, now: str) -> dict:
    return {
        "message_id": f"snmp-{random.randint(0,9999999)}",
        "tenant_id": entity["tenant_id"],
        "source_id": source["source_id"],
        "target_ip": f"10.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        "sys_oid": f"1.3.6.1.4.1.{random.choice([9,2636,25506])}.1.{random.randint(1,100)}",
        "sys_descr": f"Cisco IOS Software, Version {random.randint(12,16)}.{random.randint(1,9)}",
        "sys_name": entity["canonical_name"].lower().replace(" ", "-"),
        "serial_number": f"FCZ{random.randint(100000, 999999)}",
        "manufacturer": random.choice(["Cisco", "Juniper", "Dell", "HP"]),
        "model": random.choice(["Catalyst 9300", "EX3400", "PowerEdge R750", "ProLiant DL380"]),
        "ip_addresses": [f"10.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"],
        "mac_addresses": [f"{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}"],
        "if_table": [{"if_index": i, "if_descr": f"GigabitEthernet0/{i}", "if_type": 6,
                      "if_speed": 1000000000, "if_oper_status": 1} for i in range(1, random.randint(2, 5))],
        "scan_ts": now,
        "ingest_ts": now,
    }


def _make_bmc_message(entity: dict, source: dict, now: str) -> dict:
    return {
        "message_id": f"bmc-{random.randint(0,9999999)}",
        "tenant_id": entity["tenant_id"],
        "source_id": source["source_id"],
        "target_ip": f"10.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        "redfish_type": "#Chassis.v1_14_0.Chassis",
        "chassis_type": "RackMount",
        "manufacturer": random.choice(["Dell", "HP", "Lenovo", "Supermicro"]),
        "model": random.choice(["PowerEdge R750", "ProLiant DL380 Gen10", "ThinkSystem SR650"]),
        "serial_number": f"SN{random.randint(10000000, 99999999)}",
        "firmware_version": f"2.{random.randint(40, 90)}.{random.randint(0, 9)}",
        "power_state": random.choice(["On", "On", "On", "Off"]),
        "health_state": random.choice(["OK", "OK", "OK", "Warning"]),
        "processor_count": random.choice([2, 4]),
        "memory_gib": random.choice([64, 128, 256, 512]),
        "capabilities": {
            "redundant_psu": True,
            "ipmi_enabled": True,
            "secure_boot": random.choice([True, False]),
        },
        "scan_ts": now,
        "ingest_ts": now,
    }


# ── Replay loop ───────────────────────────────────────────────────────────────

def _get_metric_stats(metric_id: str, entity_class: str) -> dict:
    for s in seed_data.get("metric_stats", []):
        if s["metric_id"] == metric_id and s["entity_class"] == entity_class:
            return s
    return {"mean_val": 50.0, "std_val": 10.0, "min_val": 0.0, "max_val": 100.0}


def _live_replay_loop():
    """Continuously generates events at state['events_per_sec'] rate."""
    logger.info("Starting LIVE replay loop")
    p = get_producer()
    entities = seed_data["entities"]
    metrics = seed_data["metrics"]
    alert_types = seed_data["alert_types"]
    dcim_sources = [s for s in seed_data["source_systems"] if s["source_class"] == "DCIM"]
    disc_sources = [s for s in seed_data["source_systems"] if s["source_class"] in ("DISCOVERY", "DCIM")]

    if not entities or not metrics:
        logger.warning("No seed data loaded — replay cannot start")
        return

    cycle = 0
    while state["running"]:
        rate = max(1, state["events_per_sec"])
        sleep_per_event = 1.0 / rate
        batch_start = time.time()
        batch_size = min(rate, 500)  # publish in batches of up to 500

        now = datetime.now(timezone.utc).isoformat()

        try:
            for _ in range(batch_size):
                if not state["running"]:
                    break

                entity = random.choice(entities)

                # 60% metrics, 20% DCIM, 10% alerts, 5% SNMP, 5% BMC
                roll = random.random()
                if roll < 0.60 and metrics:
                    metric = random.choice(metrics)
                    stats = _get_metric_stats(metric["metric_id"], entity["entity_class"])
                    msg = _make_metric_message(entity, metric, stats, now)
                    publish("metrics.timeseries.raw", msg, key=entity["entity_id"])

                elif roll < 0.80 and dcim_sources:
                    source = random.choice(dcim_sources)
                    msg = _make_dcim_message(entity, source, now)
                    publish("dcim.config.normalized", msg, key=entity["entity_id"])

                elif roll < 0.90 and alert_types and random.random() < 0.05:
                    alert = random.choice(alert_types)
                    msg = _make_alert_message(entity, alert, now)
                    publish("alerts.raw", msg, key=entity["entity_id"])

                elif roll < 0.95 and disc_sources:
                    source = random.choice(disc_sources)
                    msg = _make_snmp_message(entity, source, now)
                    publish("discovery.snmp.results", msg, key=entity["entity_id"])

                else:
                    if disc_sources:
                        source = random.choice(disc_sources)
                        if entity["entity_class"] in ("DEVICE", "SERVICE"):
                            msg = _make_bmc_message(entity, source, now)
                            publish("discovery.bmc.results", msg, key=entity["entity_id"])

            p.poll(0)
            cycle += 1
            if cycle % 100 == 0:
                p.flush(5)

        except Exception as e:
            state["errors"] += 1
            logger.error(f"Replay error: {e}", exc_info=True)

        # Rate limiting: sleep the remainder of the batch window
        elapsed = time.time() - batch_start
        target = batch_size / rate
        if elapsed < target:
            time.sleep(target - elapsed)


def _historical_replay_loop():
    """Replays the 30-day seed window in compressed time."""
    logger.info(f"Starting HISTORICAL replay loop at {HISTORICAL_SPEED}x speed")
    import asyncio

    async def fetch_and_replay():
        ts = await asyncpg.connect(TS_DSN)
        p = get_producer()
        entities_map = {e["entity_id"]: e for e in seed_data["entities"]}
        metrics_map = {m["metric_id"]: m for m in seed_data["metrics"]}
        dcim_sources = [s for s in seed_data["source_systems"] if s["source_class"] == "DCIM"]
        source = dcim_sources[0] if dcim_sources else seed_data["source_systems"][0] if seed_data["source_systems"] else None

        try:
            # Fetch 30 days of metric data in time-ordered chunks
            cursor = await ts.cursor(
                "SELECT entity_id, metric_id, value, quality_flag, event_ts FROM metric_datapoint "
                "ORDER BY event_ts ASC",
                prefetch=1000
            )

            prev_event_ts = None
            async for row in cursor:
                if not state["running"]:
                    break

                entity_id = str(row["entity_id"])
                entity = entities_map.get(entity_id)
                if not entity:
                    continue

                metric_id = str(row["metric_id"])
                metric = metrics_map.get(metric_id)
                event_ts = row["event_ts"]
                ts_str = event_ts.isoformat() if hasattr(event_ts, 'isoformat') else str(event_ts)

                msg = {
                    "message_id": f"hist-{random.randint(0,9999999)}",
                    "tenant_id": entity["tenant_id"],
                    "entity_id": entity_id,
                    "entity_class": entity["entity_class"],
                    "metric_id": metric_id,
                    "source_id": _pick_telemetry_source(entity["tenant_id"]),
                    "value": float(row["value"]),
                    "quality_flag": row["quality_flag"] or "VALID",
                    "event_ts": ts_str,
                    "ingest_ts": datetime.now(timezone.utc).isoformat(),
                }
                p.produce("metrics.timeseries.raw", json.dumps(msg, default=str).encode(),
                          key=entity_id.encode())
                state["events_published"] += 1

                # Time compression: sleep proportional to real inter-event gap
                if prev_event_ts and hasattr(event_ts, 'timestamp'):
                    real_gap = (event_ts.timestamp() - prev_event_ts.timestamp())
                    sleep_time = real_gap / HISTORICAL_SPEED
                    if sleep_time > 0.001:
                        await asyncio.sleep(min(sleep_time, 1.0))

                prev_event_ts = event_ts
                if state["events_published"] % 1000 == 0:
                    p.poll(0)

        finally:
            await ts.close()
            p.flush()
            logger.info("Historical replay completed")
            state["running"] = False

    asyncio.run(fetch_and_replay())


def start_replay():
    global _replay_thread
    if state["running"]:
        return
    state["running"] = True
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    state["events_published"] = 0

    fn = _live_replay_loop if state["mode"] == "live" else _historical_replay_loop
    _replay_thread = threading.Thread(target=fn, daemon=True, name="replay-loop")
    _replay_thread.start()
    logger.info(f"Replay started in {state['mode']} mode at {state['events_per_sec']} events/sec")


def stop_replay():
    state["running"] = False
    if producer:
        producer.flush(5)
    logger.info("Replay stopped")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Synthetic Replay", version="1.0.0")

# Instrument FastAPI for automatic tracing
telemetry.instrument_fastapi(app, tracer)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await load_seed_data()
    start_replay()


@app.on_event("shutdown")
async def shutdown():
    stop_replay()


@app.get("/health")
def health():
    return {"status": "ok", "service": "synthetic-replay", "running": state["running"]}


@app.get("/status")
def status():
    return {**state, "topics": state["topics"]}


class RateRequest(BaseModel):
    events_per_sec: int


@app.post("/control/pause")
def pause():
    state["running"] = False
    return {"status": "paused"}


@app.post("/control/resume")
def resume():
    if not state["running"]:
        start_replay()
    return {"status": "running"}


@app.post("/control/rate")
def set_rate(body: RateRequest):
    state["events_per_sec"] = max(1, min(body.events_per_sec, 50000))
    return {"events_per_sec": state["events_per_sec"]}


@app.post("/control/reset")
async def reset():
    stop_replay()
    await asyncio.sleep(0.5)
    await load_seed_data()
    start_replay()
    return {"status": "reset and restarted"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=REPLAY_PORT, log_level="info")
