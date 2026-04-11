"""
FlowCore Event Archive Service
Consumes from all major Kafka topics and writes time-partitioned
compressed JSON batches to S3-compatible object store (or local filesystem).
"""
import gzip
import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from confluent_kafka import Consumer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("event-archive")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
ARCHIVE_PATH = os.getenv("ARCHIVE_PATH", "/tmp/flowcore-archive")
PORT = int(os.getenv("EVENT_ARCHIVE_PORT", "8012"))
FLUSH_INTERVAL = int(os.getenv("ARCHIVE_FLUSH_INTERVAL", "60"))  # seconds
BATCH_MAX = int(os.getenv("ARCHIVE_BATCH_MAX", "5000"))

TOPICS = [
    "dcim.config.raw", "dcim.config.normalized",
    "metrics.timeseries.raw", "alerts.raw", "events.raw",
    "discovery.snmp.results", "discovery.bmc.results",
    "graph.mutations",
]

stats = {"events_archived": 0, "batches_written": 0, "errors": 0, "started_at": None}
_buffers: dict = defaultdict(list)
_lock = threading.Lock()
RUNNING = False
Path(ARCHIVE_PATH).mkdir(parents=True, exist_ok=True)


def write_batch(topic: str, events: list) -> None:
    now = datetime.now(timezone.utc)
    partition = now.strftime("%Y/%m/%d/%H")
    dir_path = Path(ARCHIVE_PATH) / topic.replace(".", "_") / partition
    dir_path.mkdir(parents=True, exist_ok=True)
    fname = dir_path / f"{now.strftime('%M%S')}_{len(events)}.jsonl.gz"
    try:
        with gzip.open(str(fname), "wb") as f:
            for evt in events:
                f.write((json.dumps(evt, default=str) + "\n").encode())
        stats["batches_written"] += 1
        logger.debug(f"Archived {len(events)} events → {fname}")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Archive write error for {topic}: {e}")


def flush_all():
    with _lock:
        to_flush = {t: list(b) for t, b in _buffers.items() if b}
        for t in to_flush:
            _buffers[t].clear()
    for topic, events in to_flush.items():
        if events:
            write_batch(topic, events)


def consumer_thread():
    global RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "event-archive-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(TOPICS)
    logger.info(f"Event archive consuming from {len(TOPICS)} topics")
    RUNNING = True
    last_flush = time.time()

    while RUNNING:
        msgs = consumer.consume(num_messages=500, timeout=0.5)
        for msg in msgs:
            if msg.error():
                continue
            try:
                value = json.loads(msg.value().decode())
                with _lock:
                    _buffers[msg.topic()].append(value)
                    buffer_size = len(_buffers[msg.topic()])
                stats["events_archived"] += 1
                if buffer_size >= BATCH_MAX:
                    flush_all()
                    last_flush = time.time()
            except Exception:
                stats["errors"] += 1

        if time.time() - last_flush > FLUSH_INTERVAL:
            flush_all()
            last_flush = time.time()

    consumer.close()


app = FastAPI(title="FlowCore Event Archive", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    t = threading.Thread(target=consumer_thread, daemon=True, name="archive-consumer")
    t.start()


@app.on_event("shutdown")
async def shutdown():
    global RUNNING
    RUNNING = False
    flush_all()


@app.get("/health")
def health():
    return {"status": "ok", "service": "event-archive"}


@app.get("/stats")
def get_stats():
    pending = {t: len(b) for t, b in _buffers.items() if b}
    return {**stats, "pending_buffers": pending, "archive_path": ARCHIVE_PATH}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
