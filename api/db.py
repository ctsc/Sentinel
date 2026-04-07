"""
Cassandra connection pool for FastAPI.

Uses the sync cassandra-driver, wrapped with asyncio.to_thread for async endpoints.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from cassandra.cluster import Cluster, Session

logger = logging.getLogger(__name__)

_cluster: Optional[Cluster] = None
_session: Optional[Session] = None


def get_session() -> Session:
    """Get or create a Cassandra session (sync)."""
    global _cluster, _session

    if _session is not None:
        return _session

    hosts = os.getenv("CASSANDRA_HOSTS", "localhost").split(",")
    port = int(os.getenv("CASSANDRA_PORT", "9042"))
    keyspace = os.getenv("CASSANDRA_KEYSPACE", "sentinel")

    _cluster = Cluster(hosts, port=port)
    _session = _cluster.connect(keyspace)
    logger.info("Cassandra connected: %s:%d/%s", hosts, port, keyspace)
    return _session


def close():
    """Shutdown Cassandra connection."""
    global _cluster, _session
    if _cluster:
        _cluster.shutdown()
        _cluster = None
        _session = None
        logger.info("Cassandra connection closed.")


async def query_events(
    region: Optional[str] = None,
    time_bucket: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    """Query events from Cassandra asynchronously."""

    def _sync_query():
        session = get_session()

        if region and time_bucket:
            cql = "SELECT * FROM events WHERE region=%s AND time_bucket=%s"
            params = [region, time_bucket]
        elif region:
            # Need time_bucket for partition key — use current hour
            bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
            cql = "SELECT * FROM events WHERE region=%s AND time_bucket=%s"
            params = [region, bucket]
        else:
            # Without partition key, we need ALLOW FILTERING or scan multiple
            # For now, return recent events from a few known regions
            all_events = []
            bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
            for r in ["middle_east", "europe", "africa", "south_asia", "east_asia",
                       "southeast_asia", "north_america", "south_america"]:
                rows = session.execute(
                    "SELECT * FROM events WHERE region=%s AND time_bucket=%s LIMIT %s",
                    (r, bucket, limit // 8 + 1),
                )
                all_events.extend(rows)
            return _rows_to_dicts(all_events[:limit])

        if event_type:
            cql += " AND event_type=%s ALLOW FILTERING"
            params.append(event_type)

        cql += f" LIMIT {limit}"
        rows = session.execute(cql, params)
        return _rows_to_dicts(list(rows))

    return await asyncio.to_thread(_sync_query)


def _rows_to_dicts(rows) -> List[dict]:
    """Convert Cassandra rows to API-friendly dicts."""
    results = []
    for row in rows:
        results.append({
            "event_id": str(row.event_id) if row.event_id else "",
            "source": row.source or "unknown",
            "event_type": row.event_type or "other",
            "title": row.title,
            "raw_text": row.raw_text or "",
            "timestamp": row.event_time.isoformat() if row.event_time else "",
            "source_url": row.source_url,
            "geo": {
                "lat": row.lat,
                "lon": row.lon,
                "country_code": row.country_code,
                "location_name": row.location_name,
            },
            "confidence": row.confidence or 0.0,
            "severity": row.severity or 1,
            "entities": [],
        })
    return results
