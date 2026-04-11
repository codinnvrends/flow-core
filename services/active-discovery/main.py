"""
FlowCore Active Discovery Service
Executes scheduled SNMP walks and IPMI/Redfish probes.
Publishes to: discovery.snmp.results, discovery.bmc.results
Admin REST API on :8003
"""
import asyncio
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import uvicorn
from confluent_kafka import Producer
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("active-discovery")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
PORT = int(os.getenv("ACTIVE_DISCOVERY_PORT", "8003"))

stats = {
    "scans_completed": 0,
    "snmp_results_published": 0,
    "bmc_results_published": 0,
    "errors": 0,
    "started_at": None,
    "last_scan_at": None,
}

_pool: Optional[asyncpg.Pool] = None
_producer: Optional[Producer] = None
_scan_schedules: list = []
SCHEDULER_RUNNING = False


# ── SNMP walk simulator ───────────────────────────────────────────────────────
# In production: uses pysnmp. In Option A: uses existing identity_signal data.

async def run_snmp_walk(target_ip: str, tenant_id: str, source_id: str) -> Optional[dict]:
    """
    Simulate SNMP walk result using identity_signal data from PG.
    In production: runs actual SNMP walk against target_ip.
    """
    try:
        async with _pool.acquire() as conn:
            signals = await conn.fetch(
                """
                SELECT i.signal_type, i.signal_value, e.entity_class, e.canonical_name, e.entity_id
                FROM identity_signal i
                JOIN infrastructure_entity_ref e ON e.entity_id = i.entity_id
                WHERE e.tenant_id=$1 AND i.resolution_status='RESOLVED'
                LIMIT 1
                """,
                tenant_id,
            )
            if not signals:
                return None
            s = dict(signals[0])

        import random
        now = datetime.now(timezone.utc).isoformat()
        return {
            "message_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "source_id": source_id,
            "target_ip": target_ip,
            "sys_oid": f"1.3.6.1.4.1.{random.choice([9, 2636, 25506])}.1.{random.randint(1,100)}",
            "sys_descr": f"Cisco IOS Software, Version 15.{random.randint(1,9)}",
            "sys_name": s["canonical_name"].lower().replace(" ", "-"),
            "serial_number": s.get("signal_value") if s.get("signal_type") == "SERIAL_NUMBER" else None,
            "manufacturer": random.choice(["Cisco", "Juniper", "Dell", "HP", "Lenovo"]),
            "model": random.choice(["Catalyst 9300", "EX4300", "PowerEdge R750", "ProLiant DL380"]),
            "ip_addresses": [target_ip],
            "mac_addresses": [f"{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}"],
            "if_table": [
                {
                    "if_index": i,
                    "if_descr": f"GigabitEthernet0/{i}",
                    "if_type": 6,
                    "if_speed": 1000000000,
                    "if_oper_status": 1,
                }
                for i in range(1, random.randint(3, 8))
            ],
            "scan_ts": now,
            "ingest_ts": now,
        }
    except Exception as e:
        logger.debug(f"SNMP sim error: {e}")
        return None


async def run_bmc_probe(target_ip: str, tenant_id: str, source_id: str) -> Optional[dict]:
    """
    Simulate BMC/Redfish probe.
    In production: uses httpx against Redfish API at target_ip.
    """
    import random
    now = datetime.now(timezone.utc).isoformat()
    return {
        "message_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "source_id": source_id,
        "target_ip": target_ip,
        "redfish_type": "#Chassis.v1_14_0.Chassis",
        "chassis_type": random.choice(["RackMount", "Blade", "Tower"]),
        "manufacturer": random.choice(["Dell", "HP", "Lenovo", "Supermicro"]),
        "model": random.choice(["PowerEdge R750", "ProLiant DL380 Gen10", "SR650", "X11DPH-T"]),
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
            "virtual_media": True,
        },
        "scan_ts": now,
        "ingest_ts": now,
    }


# ── Subnet scanner ────────────────────────────────────────────────────────────

async def scan_subnet(subnet: str, tenant_id: str, source_id: str,
                      scan_type: str = "snmp") -> dict:
    """Scan a subnet (or single IP). Returns scan summary."""
    scan_log_id = str(uuid.uuid4())
    discovered = 0
    errors = 0

    # In Option A: scan a synthetic range of 5-10 IPs
    import ipaddress, random
    try:
        net = ipaddress.ip_network(subnet, strict=False)
        hosts = list(net.hosts())[:10] or [ipaddress.ip_address("10.0.1.1")]
    except Exception:
        hosts = [subnet]

    for host in hosts[:10]:
        ip = str(host)
        try:
            if scan_type in ("snmp", "both"):
                result = await run_snmp_walk(ip, tenant_id, source_id)
                if result:
                    _producer.produce(
                        "discovery.snmp.results",
                        json.dumps(result, default=str).encode(),
                        key=tenant_id.encode(),
                    )
                    stats["snmp_results_published"] += 1
                    discovered += 1

            if scan_type in ("bmc", "both") and random.random() < 0.4:
                bmc_result = await run_bmc_probe(ip, tenant_id, source_id)
                if bmc_result:
                    _producer.produce(
                        "discovery.bmc.results",
                        json.dumps(bmc_result, default=str).encode(),
                        key=tenant_id.encode(),
                    )
                    stats["bmc_results_published"] += 1

        except Exception as e:
            errors += 1
            logger.debug(f"Scan error for {ip}: {e}")

    _producer.flush(2)
    stats["scans_completed"] += 1
    stats["last_scan_at"] = datetime.now(timezone.utc).isoformat()

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO discovery_scan_log(scan_id, source_id, tenant_id, subnet, scan_type,
                devices_discovered, scan_errors, started_at, completed_at, status)
            VALUES($1,$2,$3,$4,$5,$6,$7,NOW(),NOW(),'COMPLETED')
            ON CONFLICT DO NOTHING
            """,
            scan_log_id, source_id, tenant_id, subnet, scan_type, discovered, errors,
        )

    return {"scan_id": scan_log_id, "subnet": subnet, "discovered": discovered, "errors": errors}


# ── Scheduler ─────────────────────────────────────────────────────────────────

def scheduler_thread():
    global SCHEDULER_RUNNING
    SCHEDULER_RUNNING = True
    logger.info("Discovery scheduler started")

    async def scheduled_scan():
        async with _pool.acquire() as conn:
            sources = await conn.fetch(
                "SELECT source_id, tenant_id, connection_config FROM source_system "
                "WHERE source_class='DISCOVERY' AND status='ACTIVE'"
            )
        for src in sources:
            config = src["connection_config"] or {}
            if isinstance(config, str):
                config = json.loads(config)
            subnet = config.get("subnet", config.get("target_subnet", "10.0.0.0/28"))
            await scan_subnet(subnet, str(src["tenant_id"]), str(src["source_id"]), "both")

    while SCHEDULER_RUNNING:
        try:
            asyncio.run(scheduled_scan())
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        time.sleep(300)  # Every 5 minutes


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Active Discovery", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _producer
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=5)
    _producer = Producer({"bootstrap.servers": KAFKA_BROKERS, "client.id": "active-discovery", "acks": 1})
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    t = threading.Thread(target=scheduler_thread, daemon=True, name="discovery-scheduler")
    t.start()
    logger.info("Active discovery service ready")


@app.on_event("shutdown")
async def shutdown():
    global SCHEDULER_RUNNING
    SCHEDULER_RUNNING = False
    if _producer:
        _producer.flush(3)
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "active-discovery"}


@app.get("/stats")
def get_stats():
    return stats


class ScanRequest(BaseModel):
    subnet: str
    source_id: str
    tenant_id: str
    scan_type: str = "both"  # snmp | bmc | both


@app.post("/scan")
async def trigger_scan(req: ScanRequest):
    result = await scan_subnet(req.subnet, req.tenant_id, req.source_id, req.scan_type)
    return result


@app.get("/scans/recent")
async def recent_scans(limit: int = 20):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM discovery_scan_log ORDER BY started_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
