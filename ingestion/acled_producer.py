"""ACLED (Armed Conflict Location & Event Data) Kafka producer.

Polls the ACLED API for conflict events, normalizes them to the unified
Sentinel schema, and publishes to the sentinel.raw.acled Kafka topic.
"""

import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from ingestion.base_producer import BaseProducer
from ingestion.config import (
    ACLED_API_KEY,
    ACLED_API_URL,
    ACLED_EMAIL,
    ACLED_PAGE_SIZE,
    KAFKA_TOPICS,
)

logger = logging.getLogger(__name__)


class ACLEDProducer(BaseProducer):
    """Producer that polls the ACLED REST API for conflict event data."""

    def __init__(self, bootstrap_servers: str | None = None):
        super().__init__(bootstrap_servers)
        self._last_event_date: str | None = None  # YYYY-MM-DD, tracks watermark

    @property
    def source_name(self) -> str:
        return "acled"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["acled"]

    def poll(self) -> None:
        """Fetch new events from ACLED and emit each one to Kafka."""
        if not ACLED_API_KEY or not ACLED_EMAIL:
            logger.error("[acled] ACLED_API_KEY and ACLED_EMAIL must be set")
            return

        page = 1
        total_emitted = 0
        latest_date_seen: str | None = None

        while True:
            records = self._fetch_page(page)
            if not records:
                break

            for record in records:
                event = self._to_event(record)
                if event is not None:
                    self.emit(event)
                    total_emitted += 1

                # Track the latest event_date we've seen
                event_date = record.get("event_date", "")
                if event_date and (latest_date_seen is None or event_date > latest_date_seen):
                    latest_date_seen = event_date

            # If we got fewer records than a full page, no more pages
            if len(records) < ACLED_PAGE_SIZE:
                break

            page += 1

        if latest_date_seen is not None:
            self._last_event_date = latest_date_seen

        logger.info(
            "[acled] Poll complete — emitted %d events (last_event_date=%s)",
            total_emitted,
            self._last_event_date,
        )

    def _fetch_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of results from the ACLED API."""
        params: dict[str, str] = {
            "key": ACLED_API_KEY,
            "email": ACLED_EMAIL,
            "page": str(page),
            "limit": str(ACLED_PAGE_SIZE),
        }

        # Only request events newer than our watermark
        if self._last_event_date is not None:
            params["event_date"] = self._last_event_date
            params["event_date_where"] = ">="

        url = f"{ACLED_API_URL}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Sentinel/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            logger.exception("[acled] Failed to fetch page %d", page)
            return []

        status = body.get("status")
        if status != 200 and status != "200":
            logger.error("[acled] API returned status %s on page %d", status, page)
            return []

        data = body.get("data", [])
        if not isinstance(data, list):
            logger.error("[acled] Unexpected data type: %s", type(data))
            return []

        logger.debug("[acled] Fetched page %d — %d records", page, len(data))
        return data

    def _to_event(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a single ACLED record to a unified Sentinel event."""
        try:
            lat = _safe_float(record.get("latitude"))
            lon = _safe_float(record.get("longitude"))

            # Build a readable summary from the notes field
            notes = record.get("notes", "") or ""
            event_type = record.get("event_type", "") or ""
            actor1 = record.get("actor1", "") or ""
            actor2 = record.get("actor2", "") or ""

            # Title: "event_type: actor1 vs actor2" or just event_type
            title_parts = [event_type]
            if actor1 and actor2:
                title_parts.append(f"{actor1} vs {actor2}")
            elif actor1:
                title_parts.append(actor1)
            title = ": ".join(title_parts) if title_parts else None

            # Timestamp — ACLED provides event_date as YYYY-MM-DD; use midnight UTC
            event_date = record.get("event_date", "")
            if event_date:
                timestamp = f"{event_date}T00:00:00+00:00"
            else:
                timestamp = datetime.now(timezone.utc).isoformat()

            # Country code from the iso field (numeric ISO 3166-1)
            country_code = record.get("iso", None)
            if country_code is not None:
                country_code = str(country_code)

            fatalities = record.get("fatalities")
            if fatalities is not None:
                try:
                    fatalities = int(fatalities)
                except (ValueError, TypeError):
                    fatalities = None

            return self.normalize(
                raw_text=notes or title or "",
                title=title,
                timestamp=timestamp,
                source_url=record.get("source", None),
                lat=lat,
                lon=lon,
                country_code=country_code,
                location_name=record.get("country", None),
                metadata={
                    "event_type": event_type,
                    "sub_event_type": record.get("sub_event_type", ""),
                    "actor1": actor1,
                    "actor2": actor2,
                    "fatalities": fatalities,
                    "source_scale": record.get("source_scale", ""),
                },
            )
        except Exception:
            logger.exception("[acled] Failed to convert record: %s", record.get("event_id_cnty", "?"))
            return None


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
