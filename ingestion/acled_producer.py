"""ACLED (Armed Conflict Location & Event Data) Kafka producer.

Polls the ACLED API for conflict events, normalizes them to the unified
Sentinel schema, and publishes to the sentinel.raw.acled Kafka topic.
"""

import json
import logging
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

from ingestion.base_producer import BaseProducer
from ingestion.config import (
    ACLED_API_URL,
    ACLED_BACKFILL_DAYS,
    ACLED_EMAIL,
    ACLED_MAX_PAGES_PER_POLL,
    ACLED_OAUTH_URL,
    ACLED_PAGE_SIZE,
    ACLED_PASSWORD,
    KAFKA_TOPICS,
)

logger = logging.getLogger(__name__)

# Refresh the access token 5 minutes before it expires
_TOKEN_REFRESH_MARGIN_SEC = 300


class ACLEDProducer(BaseProducer):
    """Producer that polls the ACLED REST API for conflict event data."""

    def __init__(self, bootstrap_servers: str | None = None):
        super().__init__(bootstrap_servers)
        self._last_event_date: str | None = None  # YYYY-MM-DD, tracks watermark
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # unix timestamp

    @property
    def source_name(self) -> str:
        return "acled"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["acled"]

    def poll(self) -> None:
        """Fetch new events from ACLED and emit each one to Kafka."""
        if not ACLED_EMAIL or not ACLED_PASSWORD:
            logger.error("[acled] ACLED_EMAIL and ACLED_PASSWORD must be set")
            return

        if not self._ensure_token():
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

            # Cap pagination so run_once() completes in bounded time
            if page > ACLED_MAX_PAGES_PER_POLL:
                logger.info("[acled] Hit max pages cap (%d), ending poll early", ACLED_MAX_PAGES_PER_POLL)
                break

        if latest_date_seen is not None:
            self._last_event_date = latest_date_seen

        logger.info(
            "[acled] Poll complete — emitted %d events (last_event_date=%s)",
            total_emitted,
            self._last_event_date,
        )

    def _ensure_token(self) -> bool:
        """Fetch a new OAuth access token if we don't have one or it's near expiry."""
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_REFRESH_MARGIN_SEC:
            return True

        data = urllib.parse.urlencode({
            "username": ACLED_EMAIL,
            "password": ACLED_PASSWORD,
            "grant_type": "password",
            "client_id": "acled",
        }).encode("utf-8")

        req = urllib.request.Request(
            ACLED_OAUTH_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (Sentinel OSINT Pipeline; +https://github.com/ctsc/sentinel)",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            logger.exception("[acled] OAuth token request failed")
            return False

        token = body.get("access_token")
        if not token:
            logger.error("[acled] OAuth response missing access_token: %s", body)
            return False

        expires_in = int(body.get("expires_in", 86400))
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        logger.info("[acled] Obtained access token (expires in %ds)", expires_in)
        return True

    def _fetch_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of results from the ACLED API."""
        if not self._ensure_token():
            return []

        params: dict[str, str] = {
            "page": str(page),
            "limit": str(ACLED_PAGE_SIZE),
            "_format": "json",
        }

        # Only request events newer than our watermark. On first poll (no
        # watermark), fall back to a N-day backfill window — ACLED returns
        # oldest-first by default, so without a floor we'd paginate from 1997.
        # ACLED free-tier accounts have a ~12-month embargo on recent data.
        # Query a window that's safely pre-embargo: 14 → 12 months ago.
        now = datetime.now(timezone.utc)
        ceiling = (now - timedelta(days=370)).strftime("%Y-%m-%d")  # ~12mo+5d ago
        floor_date = self._last_event_date
        if floor_date is None:
            floor_date = (now - timedelta(days=425)).strftime("%Y-%m-%d")  # ~14mo ago
        # BETWEEN is the most reliably-supported comparison in ACLED v2.
        params["event_date"] = f"{floor_date}|{ceiling}"
        params["event_date_where"] = "BETWEEN"

        url = f"{ACLED_API_URL}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Sentinel OSINT Pipeline; +https://github.com/ctsc/sentinel)",
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw)
        except Exception:
            logger.exception("[acled] Failed to fetch page %d (url=%s)", page, url)
            return []

        status = body.get("status")
        if status not in (200, "200", None):
            logger.error("[acled] API returned status %s on page %d: %s", status, page, body)
            return []

        data = body.get("data", [])
        if not isinstance(data, list):
            logger.error("[acled] Unexpected data type: %s — body=%s", type(data), body)
            return []

        if not data:
            logger.warning(
                "[acled] Empty page %d — url=%s count=%s body-preview=%.300s",
                page, url, body.get("count"), raw,
            )

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

            # ACLED's "source" field is the publication name (e.g. "BBC News"),
            # NOT a URL. ACLED doesn't expose the original article URL on the
            # free tier, so we link to the ACLED dashboard filtered to this
            # event's country + date — still a real, verifiable citation.
            source_publication = record.get("source", "") or ""
            acled_country = record.get("country", "") or ""
            event_date = record.get("event_date", "")
            if acled_country and event_date:
                src_url = (
                    "https://acleddata.com/dashboard/#/dashboard"
                    f"?country={urllib.parse.quote(acled_country)}&event_date={event_date}"
                )
            else:
                src_url = "https://acleddata.com/dashboard/"

            return self.normalize(
                raw_text=notes or title or "",
                title=title,
                timestamp=timestamp,
                source_url=src_url,
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
                    "source_publication": source_publication,
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


if __name__ == "__main__":
    from ingestion.config import ACLED_POLL_INTERVAL

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    producer = ACLEDProducer()
    producer.run(interval=ACLED_POLL_INTERVAL)
