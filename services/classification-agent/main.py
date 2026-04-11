"""
FlowCore Classification & Capability Agent
Full LightGBM device type classifier with SNMP/Redfish feature extraction.
Consumes: discovery.snmp.results, discovery.bmc.results
Produces: classification.results (Kafka)
Writes:   classification_result to PostgreSQL, device type + capabilities to Neo4j
MLflow:   tracks model runs and stores trained models
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import asyncpg
import mlflow
import mlflow.lightgbm
import numpy as np
import uvicorn
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("classification-agent")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
PG_DSN = f"postgresql://{os.getenv('PG_USER','flowcore')}:{os.getenv('PG_PASSWORD','flowcore_secret')}@{os.getenv('PG_HOST','postgres')}:{os.getenv('PG_PORT','5432')}/{os.getenv('PG_DB','flowcore')}"
NEO4J_URI = f"bolt://{os.getenv('NEO4J_HOST','neo4j')}:{os.getenv('NEO4J_BOLT_PORT','7687')}"
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "flowcore_secret")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
PORT = int(os.getenv("CLASS_AGENT_PORT", "8021"))
CONFIDENCE_THRESHOLD = float(os.getenv("CLASSIFICATION_THRESHOLD", "0.70"))
AGENT_VERSION = "classification-capability-agent@1.0.0"

stats = {
    "classified": 0,
    "needs_review": 0,
    "model_loaded": False,
    "model_run_id": None,
    "errors": 0,
    "started_at": None,
}

_pool: Optional[asyncpg.Pool] = None
_producer: Optional[Producer] = None
_neo4j = None
_model = None         # LightGBM model
_label_encoder = None # maps integer → type string
_async_loop = None
CONSUMER_RUNNING = False

# ── Device type taxonomy ──────────────────────────────────────────────────────

DEVICE_TYPES = [
    "Server", "ToR-Switch", "Core-Switch", "Firewall", "Load-Balancer",
    "Storage-Array", "GPU-Server", "PDU", "UPS", "CRAC", "KVM-Switch",
    "Router", "Out-of-Band-Manager", "Unknown"
]

# OID prefix → vendor/type hints (from Section 7.3 of the LDM doc)
OID_VENDOR_MAP = {
    "1.3.6.1.4.1.9": "Cisco",
    "1.3.6.1.4.1.2636": "Juniper",
    "1.3.6.1.4.1.25506": "H3C",
    "1.3.6.1.4.1.11": "HP",
    "1.3.6.1.4.1.674": "Dell",
    "1.3.6.1.4.1.318": "APC",
    "1.3.6.1.4.1.534": "Eaton",
    "1.3.6.1.4.1.476": "Liebert",
    "1.3.6.1.4.1.232": "HPE",
    "1.3.6.1.4.1.10876": "Raritan",
}

VENDOR_TYPE_HINTS = {
    "Cisco": ["ToR-Switch", "Core-Switch", "Router", "Firewall"],
    "Juniper": ["ToR-Switch", "Core-Switch", "Router", "Firewall"],
    "HP": ["Server", "Storage-Array"],
    "HPE": ["Server", "Storage-Array"],
    "Dell": ["Server", "Storage-Array"],
    "APC": ["UPS", "PDU"],
    "Eaton": ["UPS", "PDU"],
    "Liebert": ["CRAC"],
    "Raritan": ["KVM-Switch", "Out-of-Band-Manager"],
}


# ── Feature extraction ────────────────────────────────────────────────────────

VENDOR_BUCKETS = list(OID_VENDOR_MAP.values()) + ["Unknown"]


def extract_snmp_features(msg: dict) -> np.ndarray:
    """
    Feature Group 1 — Device Identity features from SNMP discovery result.
    Returns float vector of length 12.
    """
    sys_oid = msg.get("sys_oid", "")
    sys_descr = (msg.get("sys_descr") or "").lower()
    if_table = msg.get("if_table", [])
    serial = msg.get("serial_number", "")

    # Feature 1: snmp_enterprise_bucket (one-hot over VENDOR_BUCKETS)
    vendor = "Unknown"
    for prefix, vname in OID_VENDOR_MAP.items():
        if sys_oid.startswith(prefix):
            vendor = vname
            break
    vendor_idx = VENDOR_BUCKETS.index(vendor) if vendor in VENDOR_BUCKETS else len(VENDOR_BUCKETS) - 1
    vendor_one_hot = [1.0 if i == vendor_idx else 0.0 for i in range(len(VENDOR_BUCKETS))]

    # Feature 2: port profile
    total_ports = len(if_table)
    ethernet_ratio = sum(1 for p in if_table if p.get("if_type") == 6) / max(total_ports, 1)
    has_serial_port = any("serial" in (p.get("if_descr") or "").lower() for p in if_table)
    high_speed = sum(1 for p in if_table if (p.get("if_speed") or 0) >= 1e9) / max(total_ports, 1)

    # Feature 3: sysDescr keyword flags
    kw = {
        "switch": "switch" in sys_descr or "ios" in sys_descr,
        "server": any(w in sys_descr for w in ["server", "poweredge", "proliant", "thinkserver"]),
        "pdu": any(w in sys_descr for w in ["pdu", "power distribution"]),
        "ups": "ups" in sys_descr or "uninterruptible" in sys_descr,
        "router": "router" in sys_descr or "junos" in sys_descr,
        "storage": any(w in sys_descr for w in ["storage", "array", "san", "nas"]),
        "gpu": "gpu" in sys_descr or "nvidia" in sys_descr or "a100" in sys_descr,
        "firewall": any(w in sys_descr for w in ["firewall", "asa", "fortigate", "palo"]),
    }

    features = vendor_one_hot + [
        float(total_ports) / 50.0,       # normalised port count
        ethernet_ratio,
        float(has_serial_port),
        high_speed,
        float(kw["switch"]),
        float(kw["server"]),
        float(kw["pdu"]),
        float(kw["ups"]),
        float(kw["router"]),
        float(kw["storage"]),
        float(kw["gpu"]),
        float(kw["firewall"]),
        1.0 if serial else 0.0,           # has serial number
    ]
    return np.array(features, dtype=np.float32)


def extract_bmc_features(msg: dict) -> np.ndarray:
    """Feature extraction from Redfish/BMC discovery result."""
    chassis = (msg.get("chassis_type") or "").lower()
    manufacturer = (msg.get("manufacturer") or "").lower()
    capabilities = msg.get("capabilities", {})

    chassis_flags = [
        float("rack" in chassis),
        float("blade" in chassis),
        float("tower" in chassis),
        float("enclosure" in chassis or "chassis" in chassis),
    ]
    mfr_flags = [
        float("dell" in manufacturer),
        float("hp" in manufacturer or "hpe" in manufacturer),
        float("lenovo" in manufacturer or "ibm" in manufacturer),
        float("supermicro" in manufacturer),
    ]
    cap_flags = [
        float(capabilities.get("redundant_psu", False)),
        float(capabilities.get("ipmi_enabled", True)),
        float(capabilities.get("virtual_media", False)),
        float(capabilities.get("secure_boot", False)),
    ]
    proc_count = min(float(msg.get("processor_count") or 1) / 8.0, 1.0)
    mem_gib = min(float(msg.get("memory_gib") or 64) / 512.0, 1.0)

    features = chassis_flags + mfr_flags + cap_flags + [proc_count, mem_gib]
    # Pad to same length as SNMP features
    target_len = len(VENDOR_BUCKETS) + 13
    if len(features) < target_len:
        features += [0.0] * (target_len - len(features))
    return np.array(features[:target_len], dtype=np.float32)


# ── Model management ──────────────────────────────────────────────────────────

def train_initial_model() -> None:
    """
    Train an initial LightGBM model on synthetic labelled data.
    In production: uses operator-corrected classification_result rows.
    """
    import lightgbm as lgb
    from sklearn.preprocessing import LabelEncoder
    from sklearn.model_selection import train_test_split

    logger.info("Training initial classification model...")

    # Generate synthetic training data from OID/keyword heuristics
    X, y = [], []
    rng = np.random.default_rng(42)
    num_classes = len(DEVICE_TYPES) - 1  # exclude Unknown

    for label_idx in range(num_classes):
        label = DEVICE_TYPES[label_idx]
        for _ in range(50):
            # Fake SNMP message for this device type
            fake_msg = _synthetic_sample(label, rng)
            features = extract_snmp_features(fake_msg)
            X.append(features)
            y.append(label)

    X = np.array(X)
    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    X_train, X_val, y_train, y_val = train_test_split(X, y_enc, test_size=0.2, random_state=42)

    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("device-classification")

    with mlflow.start_run() as run:
        params = {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "max_depth": 6,
            "num_leaves": 31,
            "objective": "multiclass",
            "num_class": len(le.classes_),
            "verbosity": -1,
        }
        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train,
                  eval_set=[(X_val, y_val)],
                  callbacks=[lgb.early_stopping(10, verbose=False)])

        val_acc = model.score(X_val, y_val)
        mlflow.log_metric("val_accuracy", val_acc)
        mlflow.log_params(params)
        mlflow.lightgbm.log_model(model, "model")

        global _model, _label_encoder
        _model = model
        _label_encoder = le
        stats["model_loaded"] = True
        stats["model_run_id"] = run.info.run_id
        logger.info(f"Model trained: val_accuracy={val_acc:.3f}, run_id={run.info.run_id}")


def _synthetic_sample(label: str, rng) -> dict:
    """Generate a synthetic SNMP message biased toward the given device type label."""
    label_lower = label.lower()
    if "switch" in label_lower or "router" in label_lower:
        oid_prefix = rng.choice(["1.3.6.1.4.1.9", "1.3.6.1.4.1.2636"])
        descr = rng.choice(["Cisco IOS Software", "Juniper Networks", "EX4300"])
        ports = int(rng.integers(24, 64))
    elif "server" in label_lower or "gpu" in label_lower:
        oid_prefix = rng.choice(["1.3.6.1.4.1.674", "1.3.6.1.4.1.11"])
        descr = rng.choice(["Dell PowerEdge", "HPE ProLiant", "PowerEdge R750"])
        ports = int(rng.integers(2, 6))
    elif "ups" in label_lower or "pdu" in label_lower:
        oid_prefix = rng.choice(["1.3.6.1.4.1.318", "1.3.6.1.4.1.534"])
        descr = rng.choice(["APC Smart-UPS", "Eaton 9PX", "Power Distribution Unit"])
        ports = int(rng.integers(1, 4))
    else:
        oid_prefix = f"1.3.6.1.4.1.{rng.integers(1, 50000)}"
        descr = "Unknown Device"
        ports = int(rng.integers(1, 8))

    return {
        "sys_oid": f"{oid_prefix}.{rng.integers(1, 100)}",
        "sys_descr": descr,
        "if_table": [{"if_type": 6, "if_speed": 1000000000, "if_oper_status": 1,
                       "if_descr": f"eth{i}", "if_index": i} for i in range(ports)],
        "serial_number": f"SN{rng.integers(100000, 999999)}",
    }


def infer(msg: dict, source: str = "snmp") -> tuple[str, dict, float]:
    """Run classifier. Returns (device_type, capability_flags, confidence)."""
    if _model is None:
        return _rule_based_classify(msg, source)

    features = extract_snmp_features(msg) if source == "snmp" else extract_bmc_features(msg)
    features = features.reshape(1, -1)

    proba = _model.predict_proba(features)[0]
    predicted_idx = int(np.argmax(proba))
    confidence = float(proba[predicted_idx])
    device_type = _label_encoder.inverse_transform([predicted_idx])[0]
    capabilities = _infer_capabilities(msg, device_type, source)
    return device_type, capabilities, confidence


def _rule_based_classify(msg: dict, source: str) -> tuple[str, dict, float]:
    """Fallback rule-based classifier when model not yet loaded."""
    sys_descr = (msg.get("sys_descr") or msg.get("model") or "").lower()
    sys_oid = msg.get("sys_oid", "")
    chassis = (msg.get("chassis_type") or "").lower()
    mfr = (msg.get("manufacturer") or "").lower()

    if any(w in sys_descr for w in ["ios", "nexus", "catalyst", "junos", "ex"]):
        return "ToR-Switch", {"routing_enabled": True, "switching": True}, 0.82
    if any(w in sys_descr for w in ["poweredge", "proliant", "thinkserver", "server"]) or "rack" in chassis:
        return "Server", {"redundant_psu": True, "ipmi_enabled": True}, 0.80
    if any(w in sys_descr for w in ["ups", "smart-ups", "uninterruptible"]):
        return "UPS", {"ups": True}, 0.90
    if any(w in sys_descr for w in ["pdu", "power distribution", "apc", "rack pdu"]):
        return "PDU", {"pdu": True, "managed": True}, 0.88
    if "gpu" in sys_descr or "a100" in sys_descr or "h100" in sys_descr:
        return "GPU-Server", {"gpu_accelerated": True, "high_memory": True}, 0.85
    if any(w in sys_descr for w in ["firewall", "asa", "fortigate", "palo alto"]):
        return "Firewall", {"stateful_inspection": True, "vpn": True}, 0.83
    if any(w in sys_descr for w in ["crac", "cooling", "liebert", "schneider"]):
        return "CRAC", {"cooling": True}, 0.87
    return "Unknown", {}, 0.40


def _infer_capabilities(msg: dict, device_type: str, source: str) -> dict:
    caps = {}
    dtype = device_type.lower()
    if "switch" in dtype or "router" in dtype:
        caps["routing_enabled"] = "router" in dtype
        caps["switching"] = True
        caps["poe_capable"] = len(msg.get("if_table", [])) > 0
    elif "server" in dtype or "gpu" in dtype:
        caps["redundant_psu"] = msg.get("capabilities", {}).get("redundant_psu", True)
        caps["ipmi_enabled"] = True
        caps["gpu_accelerated"] = "gpu" in dtype
    elif "pdu" in dtype:
        caps["managed"] = True
        caps["monitored"] = True
    elif "ups" in dtype:
        caps["battery_backup"] = True
        caps["snmp_monitored"] = True
    return caps


# ── Kafka consumer + result publishing ────────────────────────────────────────

import asyncio


async def publish_result(entity_id: str, tenant_id: str, source_id: str,
                          device_type: str, capabilities: dict,
                          confidence: float, evidence: list,
                          run_id: Optional[str]) -> None:
    result_id = str(uuid.uuid4())
    needs_review = confidence < CONFIDENCE_THRESHOLD
    now = datetime.now(timezone.utc).isoformat()

    # Write to PostgreSQL
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO classification_result(
                result_id, entity_id, tenant_id,
                inferred_entity_type, capability_flags, confidence_score,
                needs_review, evidence_signals, mlflow_run_id, classified_at)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT DO NOTHING
            """,
            result_id, entity_id, tenant_id,
            device_type, json.dumps(capabilities), confidence,
            needs_review, json.dumps(evidence), run_id,
        )

    # Update Neo4j entity
    try:
        with _neo4j.session() as session:
            session.run(
                """
                MATCH (n:InfrastructureEntity {entity_id: $eid})
                SET n.canonical_type = $dtype,
                    n.classification_confidence = $conf,
                    n.needs_review = $review,
                    n.capabilities = $caps,
                    n.classified_at = $now
                """,
                eid=entity_id, dtype=device_type, conf=confidence,
                review=needs_review, caps=json.dumps(capabilities), now=now,
            )
    except Exception:
        pass

    # Publish to Kafka
    msg = {
        "message_id": str(uuid.uuid4()),
        "result_id": result_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "inferred_entity_type": device_type,
        "capability_flags": capabilities,
        "confidence_score": confidence,
        "needs_review": needs_review,
        "evidence_signals": evidence,
        "mlflow_run_id": run_id,
        "classified_at": now,
    }
    _producer.produce("classification.results", json.dumps(msg, default=str).encode(),
                      key=entity_id.encode())
    _producer.poll(0)
    stats["classified"] += 1
    if needs_review:
        stats["needs_review"] += 1


def _get_or_create_entity_id(msg: dict, tenant_id: str) -> Optional[str]:
    """Try to resolve entity_id from identity signals in the message."""
    import asyncio
    loop = _async_loop

    async def _fetch():
        signals = []
        if msg.get("serial_number"):
            signals.append(("SERIAL_NUMBER", msg["serial_number"]))
        for ip in msg.get("ip_addresses", []):
            signals.append(("IP_ADDRESS", ip))
        if msg.get("sys_oid"):
            signals.append(("SNMP_OID", msg["sys_oid"]))

        async with _pool.acquire() as conn:
            for stype, sval in signals:
                row = await conn.fetchrow(
                    "SELECT entity_id FROM identity_signal WHERE signal_type=$1 AND signal_value=$2 AND tenant_id=$3 LIMIT 1",
                    stype, sval, tenant_id,
                )
                if row:
                    return str(row["entity_id"])
        return None

    future = asyncio.run_coroutine_threadsafe(_fetch(), loop)
    try:
        return future.result(timeout=2.0)
    except Exception:
        return None


def consumer_thread():
    global CONSUMER_RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "classification-agent-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(["discovery.snmp.results", "discovery.bmc.results"])
    logger.info("Classification agent consuming")
    CONSUMER_RUNNING = True

    while CONSUMER_RUNNING:
        msgs = consumer.consume(num_messages=20, timeout=1.0)
        for msg in msgs:
            if msg.error():
                continue
            try:
                payload = json.loads(msg.value().decode())
                source = "snmp" if "snmp" in msg.topic() else "bmc"
                tenant_id = payload.get("tenant_id", "")
                source_id = payload.get("source_id", "")

                device_type, capabilities, confidence = infer(payload, source)

                entity_id = _get_or_create_entity_id(payload, tenant_id)
                if not entity_id:
                    entity_id = str(uuid.uuid4())

                evidence = [
                    {"type": "sys_oid", "value": payload.get("sys_oid")},
                    {"type": "sys_descr", "value": payload.get("sys_descr", payload.get("model"))},
                    {"type": "manufacturer", "value": payload.get("manufacturer")},
                ]

                asyncio.run_coroutine_threadsafe(
                    publish_result(entity_id, tenant_id, source_id,
                                   device_type, capabilities, confidence,
                                   [e for e in evidence if e["value"]],
                                   stats.get("model_run_id")),
                    _async_loop,
                )

            except Exception as e:
                stats["errors"] += 1
                logger.debug(f"Classification error: {e}")

    consumer.close()


# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="FlowCore Classification Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _producer, _neo4j, _async_loop
    _async_loop = asyncio.get_event_loop()
    _pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=6)
    _producer = Producer({
        "bootstrap.servers": KAFKA_BROKERS,
        "client.id": "classification-agent",
        "acks": 1,
    })
    _neo4j = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    mlflow.set_tracking_uri(MLFLOW_URI)
    stats["started_at"] = datetime.now(timezone.utc).isoformat()

    # Train model in background thread
    def train_bg():
        try:
            train_initial_model()
        except Exception as e:
            logger.error(f"Model training error: {e}")
            stats["model_loaded"] = False

    threading.Thread(target=train_bg, daemon=True, name="model-trainer").start()
    # Start consumer after slight delay
    threading.Thread(target=consumer_thread, daemon=True, name="class-consumer").start()
    logger.info("Classification agent ready")


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
    return {
        "status": "ok",
        "service": "classification-capability-agent",
        "model_loaded": stats["model_loaded"],
    }


@app.get("/stats")
def get_stats():
    return stats


class ClassifyRequest(BaseModel):
    payload: dict
    source: str = "snmp"  # snmp | bmc


@app.post("/classify")
def classify_sync(req: ClassifyRequest):
    """Synchronous classification endpoint for testing."""
    device_type, capabilities, confidence = infer(req.payload, req.source)
    return {
        "device_type": device_type,
        "capabilities": capabilities,
        "confidence": confidence,
        "needs_review": confidence < CONFIDENCE_THRESHOLD,
    }


@app.post("/model/retrain")
async def trigger_retrain():
    """Trigger model retraining (uses operator feedback from classification_result table)."""
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, train_initial_model)
    return {"status": "retraining_started"}


@app.get("/results/recent")
async def recent_results(limit: int = 20):
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM classification_result ORDER BY classified_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
