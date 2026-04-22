"""
Cassandra connection pool for FastAPI.

Uses the sync cassandra-driver, wrapped with asyncio.to_thread for async endpoints.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from cassandra.cluster import Cluster, Session

logger = logging.getLogger(__name__)

_cluster: Optional[Cluster] = None
_session: Optional[Session] = None

REGIONS = [
    "middle_east", "europe", "africa", "south_asia", "east_asia",
    "southeast_asia", "north_america", "south_america",
    "central_america", "caribbean", "oceania", "other", "unknown",
]


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


def _hour_buckets(hours: int) -> List[str]:
    """Generate hourly partition keys from now going back `hours` hours."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        for h in range(hours)
    ]


async def query_events(
    region: Optional[str] = None,
    time_bucket: Optional[str] = None,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    hours: int = 168,
    limit: int = 1000,
) -> List[dict]:
    """Query events from Cassandra asynchronously.

    Default: sweeps all regions over the last 7 days (168 hours), returns up to
    `limit` events. Pass `region` + `time_bucket` to target a single partition
    (faster, used for benchmarks). `source` and `event_type` are applied as
    post-filters in Python since neither is part of the partition key.
    """

    def _sync_query():
        session = get_session()

        # Targeted single-partition query (backwards compat)
        if region and time_bucket:
            cql = "SELECT * FROM events WHERE region=%s AND time_bucket=%s"
            params = [region, time_bucket]
            if event_type:
                cql += " AND event_type=%s ALLOW FILTERING"
                params.append(event_type)
            cql += f" LIMIT {limit}"
            rows = list(session.execute(cql, params))
            return _apply_post_filters(_rows_to_dicts(rows), source)

        # Full sweep: all regions × N hours, return newest-first
        regions = [region] if region else REGIONS
        buckets = [time_bucket] if time_bucket else _hour_buckets(hours)

        # Cap partition queries to avoid runaway cost — 13 regions × 168 hours
        # = 2184 partitions worst case, each a fast primary-key lookup.
        per_partition_cap = max(50, limit // max(1, len(regions)))
        collected = []
        for r in regions:
            for b in buckets:
                rows = session.execute(
                    "SELECT * FROM events WHERE region=%s AND time_bucket=%s LIMIT %s",
                    (r, b, per_partition_cap),
                )
                collected.extend(rows)
                if len(collected) >= limit * 4:
                    # gathered enough — stop early to keep latency reasonable
                    break
            if len(collected) >= limit * 4:
                break

        events = _rows_to_dicts(collected)
        events = _apply_post_filters(events, source, event_type)
        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[:limit]

    return await asyncio.to_thread(_sync_query)


def _apply_post_filters(
    events: List[dict],
    source: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[dict]:
    if source:
        events = [e for e in events if e.get("source") == source]
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    return events


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
