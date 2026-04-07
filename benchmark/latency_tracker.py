"""
End-to-end latency measurement.

Measures the time from event production to Cassandra write.
Produces tagged events, then queries Cassandra for them to measure latency.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import List

from cassandra.cluster import Cluster
from kafka import KafkaProducer

logger = logging.getLogger(__name__)


def measure_latency(
    num_events: int = 50,
    bootstrap_servers: str = "localhost:9092",
    cassandra_hosts: list = None,
) -> dict:
    """
    Produce tagged events and measure end-to-end latency.

    Returns latency statistics in milliseconds.
    """
    cassandra_hosts = cassandra_hosts or [os.getenv("CASSANDRA_HOSTS", "localhost")]
    keyspace = os.getenv("CASSANDRA_KEYSPACE", "sentinel")

    # Connect to Kafka and Cassandra
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    cluster = Cluster(cassandra_hosts)
    session = cluster.connect(keyspace)

    latencies: List[float] = []
    tag = f"latency-test-{uuid.uuid4().hex[:8]}"

    logger.info("Starting latency test: %d events, tag=%s", num_events, tag)

    for i in range(num_events):
        event_id = str(uuid.uuid4())
        send_time = time.time()

        event = {
            "event_id": event_id,
            "source": "gdelt",
            "raw_text": f"Latency test event {tag}/{i}",
            "title": f"Latency test {tag}/{i}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_url": None,
            "geo": {
                "lat": 50.45,
                "lon": 30.52,
                "country_code": "UA",
                "location_name": "Kyiv",
            },
            "metadata": {
                "event_code": "190",
                "goldstein_scale": -5.0,
                "latency_tag": tag,
                "latency_index": i,
            },
        }

        producer.send("sentinel.raw.gdelt", value=event)
        producer.flush()

        # Poll Cassandra until the event appears
        event_uuid = uuid.UUID(event_id)
        found = False
        poll_start = time.time()
        timeout = 30  # seconds

        while time.time() - poll_start < timeout:
            rows = session.execute(
                "SELECT event_id FROM events WHERE region='europe' "
                "AND time_bucket=%s AND event_id=%s ALLOW FILTERING",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H"), event_uuid),
            )
            if list(rows):
                latency_ms = (time.time() - send_time) * 1000
                latencies.append(latency_ms)
                found = True
                break
            time.sleep(0.1)

        if not found:
            logger.warning("Event %d timed out after %ds", i, timeout)

        if (i + 1) % 10 == 0:
            logger.info("Progress: %d/%d events measured", i + 1, num_events)

    producer.close()
    cluster.shutdown()

    if not latencies:
        return {"error": "No events were measured", "tag": tag}

    latencies.sort()
    results = {
        "tag": tag,
        "events_measured": len(latencies),
        "events_timeout": num_events - len(latencies),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
        "mean_ms": round(sum(latencies) / len(latencies), 2),
        "median_ms": round(latencies[len(latencies) // 2], 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 2) if len(latencies) >= 20 else None,
        "p99_ms": round(latencies[int(len(latencies) * 0.99)], 2) if len(latencies) >= 100 else None,
    }

    logger.info("Latency results: %s", json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    measure_latency()
