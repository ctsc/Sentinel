"""
CAP theorem experiment — ONE vs QUORUM consistency.

Measures write latency and read staleness under write pressure
at different Cassandra consistency levels.

Requires a 3-node Cassandra cluster for meaningful QUORUM testing.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import List

from cassandra import ConsistencyLevel
from cassandra.cluster import Cluster
from cassandra.query import SimpleStatement

logger = logging.getLogger(__name__)


def run_cap_test(
    num_writes: int = 200,
    cassandra_hosts: list = None,
    keyspace: str = "sentinel",
) -> dict:
    """
    Run CAP experiment comparing ONE vs QUORUM consistency.

    Returns latency measurements for both consistency levels.
    """
    cassandra_hosts = cassandra_hosts or [os.getenv("CASSANDRA_HOSTS", "localhost")]

    cluster = Cluster(cassandra_hosts)
    session = cluster.connect(keyspace)

    results = {}

    for level_name, level in [("ONE", ConsistencyLevel.ONE), ("QUORUM", ConsistencyLevel.QUORUM)]:
        logger.info("Testing consistency level: %s (%d writes)", level_name, num_writes)

        write_latencies: List[float] = []
        read_latencies: List[float] = []
        stale_reads = 0

        insert_cql = SimpleStatement(
            """INSERT INTO events (region, time_bucket, event_time, event_id,
               source, event_type, title, raw_text, lat, lon, country_code,
               location_name, confidence, severity, source_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            consistency_level=level,
        )

        select_cql = SimpleStatement(
            "SELECT event_id FROM events WHERE region=%s AND time_bucket=%s AND event_id=%s ALLOW FILTERING",
            consistency_level=level,
        )

        tag = f"cap-{level_name.lower()}-{uuid.uuid4().hex[:6]}"
        region = "europe"
        time_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

        for i in range(num_writes):
            event_id = uuid.uuid4()
            event_time = datetime.now(timezone.utc)

            # Measure write latency
            start = time.time()
            try:
                session.execute(insert_cql, (
                    region, time_bucket, event_time, event_id,
                    "gdelt", "conflict", f"CAP test {tag}/{i}",
                    f"CAP experiment event", 50.45, 30.52, "UA",
                    "Kyiv", 0.9, 7, None,
                ))
                write_latency = (time.time() - start) * 1000
                write_latencies.append(write_latency)
            except Exception as e:
                logger.warning("Write failed at %s: %s", level_name, e)
                continue

            # Immediate read — check for staleness
            read_start = time.time()
            try:
                rows = list(session.execute(select_cql, (region, time_bucket, event_id)))
                read_latency = (time.time() - read_start) * 1000
                read_latencies.append(read_latency)

                if not rows:
                    stale_reads += 1

            except Exception as e:
                logger.warning("Read failed at %s: %s", level_name, e)

        # Cleanup test data
        try:
            session.execute(
                SimpleStatement(
                    "DELETE FROM events WHERE region=%s AND time_bucket=%s",
                    consistency_level=ConsistencyLevel.ONE,
                ),
                (region, time_bucket),
            )
        except Exception:
            pass

        # Compute statistics
        if write_latencies:
            write_latencies.sort()
            read_latencies.sort()

            results[level_name] = {
                "writes": num_writes,
                "successful_writes": len(write_latencies),
                "write_latency_ms": {
                    "min": round(min(write_latencies), 2),
                    "max": round(max(write_latencies), 2),
                    "mean": round(sum(write_latencies) / len(write_latencies), 2),
                    "median": round(write_latencies[len(write_latencies) // 2], 2),
                    "p95": round(write_latencies[int(len(write_latencies) * 0.95)], 2),
                },
                "read_latency_ms": {
                    "min": round(min(read_latencies), 2) if read_latencies else 0,
                    "max": round(max(read_latencies), 2) if read_latencies else 0,
                    "mean": round(sum(read_latencies) / len(read_latencies), 2) if read_latencies else 0,
                },
                "stale_reads": stale_reads,
                "stale_read_pct": round(stale_reads / num_writes * 100, 2),
            }

        logger.info("%s results: %s", level_name, json.dumps(results.get(level_name, {}), indent=2))

    cluster.shutdown()

    logger.info("CAP test complete. Full results:\n%s", json.dumps(results, indent=2))

    # Save results to file
    output_path = os.path.join(os.path.dirname(__file__), "results", "cap_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Results saved to %s", output_path)

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    run_cap_test()
