"""
FlowCore TimeSeries Writer Service
Consumes metrics.timeseries.raw → writes to TimescaleDB metric_datapoint hypertable.
Batches inserts for throughput efficiency.
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
from confluent_kafka import Consumer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("timeseries-writer")

KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TS_DSN = f"postgresql://{os.getenv('TS_USER','flowcore')}:{os.getenv('TS_PASSWORD','flowcore_secret')}@{os.getenv('TS_HOST','timescaledb')}:{os.getenv('TS_PORT','5432')}/{os.getenv('TS_DB','flowcore_ts')}"
PORT = int(os.getenv("TIMESERIES_WRITER_PORT", "8011"))
BATCH_SIZE = int(os.getenv("TS_BATCH_SIZE", "500"))
FLUSH_INTERVAL_SEC = float(os.getenv("TS_FLUSH_INTERVAL", "2.0"))

stats = {"rows_written": 0, "batches_flushed": 0, "errors": 0, "started_at": None}
_pool: Optional[asyncpg.Pool] = None
_batch: list = []
_batch_lock = threading.Lock()
RUNNING = False


async def flush_batch(batch: list) -> None:
    if not batch or not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO metric_datapoint(tenant_id, entity_id, entity_class, metric_id, source_id,
                                             value, event_ts, ingest_ts, quality_flag)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT DO NOTHING
                """,
                batch,
            )
        stats["rows_written"] += len(batch)
        stats["batches_flushed"] += 1
        logger.debug(f"Flushed {len(batch)} metric rows")
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"Flush error: {e}")


_async_loop: Optional[asyncio.AbstractEventLoop] = None


def consumer_thread():
    global RUNNING
    consumer = Consumer({
        "bootstrap.servers": KAFKA_BROKERS,
        "group.id": "timeseries-writer-group",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(["metrics.timeseries.raw"])
    logger.info("TimeSeries writer consuming metrics.timeseries.raw")
    RUNNING = True
    last_flush = time.time()

    while RUNNING:
        msgs = consumer.consume(num_messages=500, timeout=0.5)
        for msg in msgs:
            if msg.error():
                continue
            try:
                m = json.loads(msg.value().decode())
                row = (
                    m.get("tenant_id"),
                    m.get("entity_id"),
                    m.get("entity_class", "DEVICE"),
                    m.get("metric_id"),
                    m.get("source_id"),
                    float(m.get("value", 0)),
                    m.get("event_ts", datetime.now(timezone.utc).isoformat()),
                    datetime.now(timezone.utc).isoformat(),
                    m.get("quality_flag", "VALID"),
                )
                with _batch_lock:
                    _batch.append(row)
            except Exception as e:
                stats["errors"] += 1
                logger.debug(f"Parse error: {e}")

        # Flush if batch full or interval elapsed
        with _batch_lock:
            should_flush = len(_batch) >= BATCH_SIZE or (time.time() - last_flush > FLUSH_INTERVAL_SEC and _batch)
            if should_flush:
                batch_copy = list(_batch)
                _batch.clear()
            else:
                batch_copy = None

        if should_flush and batch_copy:
            asyncio.run_coroutine_threadsafe(flush_batch(batch_copy), _async_loop)
            last_flush = time.time()

    consumer.close()


app = FastAPI(title="FlowCore TimeSeries Writer", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    global _pool, _async_loop
    _async_loop = asyncio.get_event_loop()
    _pool = await asyncpg.create_pool(TS_DSN, min_size=2, max_size=10)
    logger.info("TimescaleDB pool ready")
    stats["started_at"] = datetime.now(timezone.utc).isoformat()
    t = threading.Thread(target=consumer_thread, daemon=True, name="ts-consumer")
    t.start()


@app.on_event("shutdown")
async def shutdown():
    global RUNNING
    RUNNING = False
    if _pool:
        await _pool.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "timeseries-writer"}


@app.get("/stats")
def get_stats():
    return {**stats, "pending_batch": len(_batch)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
