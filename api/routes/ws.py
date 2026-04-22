"""
WebSocket route for live event streaming.

Connects to Kafka as a consumer and fans out to all connected WebSocket clients.
Each client gets its own asyncio.Queue to avoid backpressure issues.
"""

import asyncio
import json
import logging
import os
import queue as stdqueue
import threading
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Global set of connected client queues
_client_queues: Set[asyncio.Queue] = set()
_kafka_thread: threading.Thread | None = None
_kafka_raw_queue: stdqueue.Queue = stdqueue.Queue(maxsize=5000)
_kafka_pump_task: asyncio.Task | None = None
_kafka_stop_event = threading.Event()


def _kafka_thread_loop():
    """Dedicated thread that owns the KafkaConsumer for its entire lifetime.

    kafka-python is not thread-safe; the consumer's selector binds to the
    creator thread and fails with 'Invalid file descriptor: -1' on Windows
    if polled from a different thread (which asyncio.to_thread does via a
    pool). Keeping the consumer on one pinned thread avoids that.

    Includes retry with exponential backoff: if the consumer crashes, it
    reconnects after 5s, 10s, 30s, then caps at 30s.
    """
    from kafka import KafkaConsumer as SyncKafkaConsumer

    backoff_schedule = [5, 10, 30]  # seconds
    attempt = 0

    while not _kafka_stop_event.is_set():
        consumer = None
        try:
            consumer = SyncKafkaConsumer(
                "sentinel.enriched",
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                group_id="sentinel-ws-live",
                auto_offset_reset="latest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                consumer_timeout_ms=1000,
            )
        except Exception as e:
            logger.error("Failed to connect Kafka for WebSocket feed: %s", e)
            delay = backoff_schedule[min(attempt, len(backoff_schedule) - 1)]
            logger.info("Retrying Kafka connection in %ds (attempt %d)", delay, attempt + 1)
            attempt += 1
            _kafka_stop_event.wait(delay)
            continue

        # Connection succeeded — reset attempt counter
        attempt = 0
        logger.info("WebSocket Kafka consumer thread started")

        try:
            while not _kafka_stop_event.is_set():
                try:
                    records = consumer.poll(timeout_ms=500)
                except Exception as e:
                    logger.error("Kafka poll error: %s", e)
                    _kafka_stop_event.wait(1.0)
                    continue

                for _tp, msgs in records.items():
                    for msg in msgs:
                        try:
                            _kafka_raw_queue.put_nowait(msg.value)
                        except stdqueue.Full:
                            pass  # Drop oldest policy: just drop the new one
        except Exception as e:
            logger.error("WebSocket Kafka consumer thread crashed: %s", e)
        finally:
            try:
                consumer.close()
            except Exception:
                pass
            logger.info("WebSocket Kafka consumer thread stopped")

        # If we get here, the consumer crashed — retry with backoff
        if not _kafka_stop_event.is_set():
            delay = backoff_schedule[min(attempt, len(backoff_schedule) - 1)]
            logger.info("Restarting Kafka consumer in %ds (attempt %d)", delay, attempt + 1)
            attempt += 1
            _kafka_stop_event.wait(delay)


async def _pump_to_clients():
    """Async task: move events from the thread-safe queue into per-client async queues."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            msg = await loop.run_in_executor(None, _kafka_raw_queue.get, True, 1.0)
        except Exception:
            await asyncio.sleep(0.1)
            continue

        if msg is None:
            continue

        for queue in list(_client_queues):
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass


def _ensure_kafka_consumer():
    """Start the Kafka consumer thread + async pump if not already running."""
    global _kafka_thread, _kafka_pump_task

    if _kafka_thread is None or not _kafka_thread.is_alive():
        _kafka_stop_event.clear()
        _kafka_thread = threading.Thread(target=_kafka_thread_loop, daemon=True)
        _kafka_thread.start()

    if _kafka_pump_task is None or _kafka_pump_task.done():
        _kafka_pump_task = asyncio.create_task(_pump_to_clients())


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """
    WebSocket endpoint for live event streaming.

    Sends events batched at ~1 per second to each connected client.
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    _ensure_kafka_consumer()

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _client_queues.add(queue)

    try:
        while True:
            # Batch events for ~1 second before sending
            batch = []
            try:
                # Wait for at least one event
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
                batch.append(event)

                # Drain any additional events available immediately
                while not queue.empty() and len(batch) < 50:
                    batch.append(queue.get_nowait())

            except asyncio.TimeoutError:
                # Send heartbeat if no events
                await websocket.send_json({"type": "heartbeat", "events": []})
                continue

            if batch:
                await websocket.send_json({"type": "events", "events": batch})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        _client_queues.discard(queue)
