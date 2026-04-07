"""
Sink — writes enriched events to Cassandra (and S3 in production).

Phase 3: Cassandra only.
Phase 5: Adds S3 JSON archive.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from cassandra.cluster import Cluster

logger = logging.getLogger(__name__)

# Region mapping by country code prefix
REGION_MAP = {
    "AF": "south_asia", "PK": "south_asia", "IN": "south_asia", "BD": "south_asia",
    "LK": "south_asia", "NP": "south_asia", "MM": "southeast_asia",
    "TH": "southeast_asia", "PH": "southeast_asia", "VN": "southeast_asia",
    "MY": "southeast_asia", "ID": "southeast_asia", "KH": "southeast_asia",
    "CN": "east_asia", "TW": "east_asia", "JP": "east_asia", "KR": "east_asia",
    "KP": "east_asia", "MN": "east_asia", "HK": "east_asia",
    "IL": "middle_east", "PS": "middle_east", "LB": "middle_east",
    "SY": "middle_east", "IQ": "middle_east", "IR": "middle_east",
    "YE": "middle_east", "SA": "middle_east", "AE": "middle_east",
    "QA": "middle_east", "BH": "middle_east", "KW": "middle_east",
    "OM": "middle_east", "JO": "middle_east", "TR": "middle_east",
    "SD": "africa", "SS": "africa", "SO": "africa", "ET": "africa",
    "KE": "africa", "NG": "africa", "CD": "africa", "CF": "africa",
    "ML": "africa", "BF": "africa", "NE": "africa", "TD": "africa",
    "LY": "africa", "EG": "africa", "TN": "africa", "DZ": "africa",
    "MA": "africa", "MZ": "africa", "ZA": "africa", "UG": "africa",
    "RW": "africa", "BI": "africa", "AO": "africa", "GH": "africa",
    "SN": "africa", "CI": "africa", "SL": "africa", "LR": "africa",
    "CM": "africa",
    "UA": "europe", "RU": "europe", "BY": "europe", "PL": "europe",
    "DE": "europe", "FR": "europe", "GB": "europe", "IT": "europe",
    "ES": "europe", "RO": "europe", "GR": "europe", "RS": "europe",
    "XK": "europe", "BA": "europe", "HR": "europe", "ME": "europe",
    "MK": "europe", "AL": "europe", "MD": "europe", "GE": "europe",
    "AM": "europe", "AZ": "europe", "BE": "europe", "NL": "europe",
    "CH": "europe", "AT": "europe", "SE": "europe", "NO": "europe",
    "FI": "europe", "DK": "europe",
    "US": "north_america", "CA": "north_america", "MX": "north_america",
    "GT": "central_america", "HN": "central_america", "SV": "central_america",
    "NI": "central_america", "CR": "central_america", "PA": "central_america",
    "HT": "caribbean", "CU": "caribbean", "DO": "caribbean", "JM": "caribbean",
    "CO": "south_america", "VE": "south_america", "BR": "south_america",
    "AR": "south_america", "CL": "south_america", "PE": "south_america",
    "EC": "south_america", "BO": "south_america", "PY": "south_america",
    "UY": "south_america", "GY": "south_america",
    "AU": "oceania", "NZ": "oceania", "PG": "oceania", "FJ": "oceania",
}


def get_region(country_code: Optional[str]) -> str:
    """Map a country code to a region for the partition key."""
    if not country_code:
        return "unknown"
    return REGION_MAP.get(country_code.upper(), "other")


def get_time_bucket(timestamp: str) -> str:
    """Extract hourly time bucket from ISO8601 timestamp."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H")
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


class CassandraSink:
    """Writes enriched events to Cassandra."""

    def __init__(self, hosts: Optional[list] = None, keyspace: str = "sentinel"):
        self._hosts = hosts or [os.getenv("CASSANDRA_HOSTS", "localhost")]
        self._keyspace = keyspace
        self._cluster = None
        self._session = None
        self._insert_stmt = None
        self._events_written = 0

    def connect(self):
        """Establish Cassandra connection and prepare statements."""
        port = int(os.getenv("CASSANDRA_PORT", "9042"))
        self._cluster = Cluster(self._hosts, port=port)
        self._session = self._cluster.connect(self._keyspace)

        self._insert_stmt = self._session.prepare("""
            INSERT INTO events (
                region, time_bucket, event_time, event_id,
                source, event_type, title, raw_text,
                lat, lon, country_code, location_name,
                confidence, severity, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)
        logger.info("Cassandra sink connected to %s/%s", self._hosts, self._keyspace)

    def write(self, event: dict) -> bool:
        """Write a single enriched event to Cassandra. Returns True on success."""
        try:
            geo = event.get("geo", {})
            country_code = geo.get("country_code")
            region = get_region(country_code)
            time_bucket = get_time_bucket(event.get("timestamp", ""))

            # Parse timestamp
            ts_str = event.get("timestamp", "")
            try:
                event_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                event_time = datetime.now(timezone.utc)

            # Parse event_id
            try:
                event_id = uuid.UUID(event["event_id"])
            except (ValueError, KeyError):
                event_id = uuid.uuid4()

            self._session.execute(self._insert_stmt, (
                region,
                time_bucket,
                event_time,
                event_id,
                event.get("source", "unknown"),
                event.get("event_type", "other"),
                event.get("title"),
                event.get("raw_text", ""),
                geo.get("lat"),
                geo.get("lon"),
                country_code,
                geo.get("location_name"),
                event.get("confidence", 0.0),
                event.get("severity", 1),
                event.get("source_url"),
            ))

            self._events_written += 1
            if self._events_written % 100 == 0:
                logger.info("Cassandra sink: %d events written", self._events_written)
            return True

        except Exception as e:
            logger.error("Failed to write event to Cassandra: %s", e)
            return False

    def close(self):
        """Close the Cassandra connection."""
        if self._cluster:
            self._cluster.shutdown()
            logger.info("Cassandra sink closed. Total events written: %d", self._events_written)

    def get_stats(self) -> dict:
        return {"events_written": self._events_written}
