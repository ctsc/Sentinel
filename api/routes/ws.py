"""
WebSocket route for live event streaming.

Connects to Kafka as a consumer and fans out to all connected WebSocket clients.
Each client gets its own asyncio.Queue to avoid backpressure issues.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Global set of connected client queues
_client_queues: Set[asyncio.Queue] = set()
_kafka_consumer_task = None


async def _kafka_to_queues():
    """Background task: consume from Kafka and fan out to all client queues."""
    from kafka import KafkaConsumer as SyncKafkaConsumer

    def _consume_batch():
        """Sync Kafka consumer that yields batches."""
        try:
            consumer = SyncKafkaConsumer(
                "sentinel.raw.gdelt",
                "sentinel.raw.acled",
                "sentinel.raw.rss",
                "sentinel.raw.bluesky",
                "sentinel.raw.wikipedia",
                bootstrap_servers="localhost:9092",
                group_id="sentinel-ws-live",
                auto_offset_reset="latest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                consumer_timeout_ms=1000,
            )
            return consumer
        except Exception as e:
            logger.error("Failed to connect Kafka for WebSocket feed: %s", e)
            return None

    consumer = await asyncio.to_thread(_consume_batch)
    if not consumer:
        logger.error("WebSocket Kafka consumer failed to start")
        return

    logger.info("WebSocket Kafka consumer started")

    try:
        while True:
            # Poll in a thread to not block the event loop
            def _poll():
                records = consumer.poll(timeout_ms=1000)
                messages = []
                for tp, msgs in records.items():
                    for msg in msgs:
                        messages.append(msg.value)
                return messages

            messages = await asyncio.to_thread(_poll)

            if messages and _client_queues:
                for msg in messages:
                    for queue in list(_client_queues):
                        try:
                            queue.put_nowait(msg)
                        except asyncio.QueueFull:
                            pass  # Drop messages for slow clients

            await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.info("WebSocket Kafka consumer cancelled")
    except Exception as e:
        logger.error("WebSocket Kafka consumer error: %s", e)
    finally:
        await asyncio.to_thread(consumer.close)


def _ensure_kafka_consumer():
    """Start the Kafka consumer background task if not already running."""
    global _kafka_consumer_task
    if _kafka_consumer_task is None or _kafka_consumer_task.done():
        _kafka_consumer_task = asyncio.create_task(_kafka_to_queues())


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
