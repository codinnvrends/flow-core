import json
import logging
import threading
from typing import Callable, Optional
from confluent_kafka import Producer, Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)


class KafkaProducer:
    def __init__(self, bootstrap_servers: str, client_id: str = "flowcore-producer"):
        self._producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "acks": "all",
            "retries": 5,
            "retry.backoff.ms": 500,
            "enable.idempotence": True,
            "compression.type": "lz4",
            "linger.ms": 5,
            "batch.size": 65536,
        })
        self._lock = threading.Lock()

    def publish(self, topic: str, message: dict, key: Optional[str] = None,
                headers: Optional[dict] = None) -> None:
        payload = json.dumps(message, default=str).encode("utf-8")
        kafka_key = key.encode("utf-8") if key else None
        kafka_headers = [(k, v.encode()) for k, v in (headers or {}).items()]

        def delivery_cb(err, msg):
            if err:
                logger.error(f"Delivery failed for topic={topic}: {err}")
            else:
                logger.debug(f"Delivered to {msg.topic()}[{msg.partition()}]@{msg.offset()}")

        with self._lock:
            self._producer.produce(
                topic,
                value=payload,
                key=kafka_key,
                headers=kafka_headers,
                callback=delivery_cb,
            )
            self._producer.poll(0)

    def flush(self, timeout: float = 30.0) -> None:
        self._producer.flush(timeout)

    def close(self) -> None:
        self.flush()


class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str],
                 auto_offset_reset: str = "earliest"):
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
            "max.poll.interval.ms": 300000,
            "session.timeout.ms": 30000,
            "heartbeat.interval.ms": 10000,
        })
        self._consumer.subscribe(topics)
        self._running = False
        logger.info(f"Kafka consumer group={group_id} subscribed to {topics}")

    def consume(self, handler: Callable[[str, dict], None],
                batch_size: int = 50, poll_timeout: float = 1.0) -> None:
        self._running = True
        while self._running:
            messages = self._consumer.consume(num_messages=batch_size, timeout=poll_timeout)
            for msg in messages:
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(f"Consumer error: {msg.error()}")
                    continue
                try:
                    value = json.loads(msg.value().decode("utf-8"))
                    handler(msg.topic(), value)
                except json.JSONDecodeError as e:
                    logger.error(f"Bad JSON on {msg.topic()}: {e}")
                except Exception as e:
                    logger.error(f"Handler error on {msg.topic()}: {e}", exc_info=True)

    def stop(self) -> None:
        self._running = False
        self._consumer.close()
