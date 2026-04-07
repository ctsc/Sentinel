"""GDELT Project Kafka producer — polls 15-minute CSV exports for conflict events."""

import csv
import gzip
import io
import logging
import urllib.request
from datetime import datetime, timezone

from ingestion.base_producer import BaseProducer
from ingestion.config import (
    GDELT_LAST_UPDATE_URL,
    GDELT_POLL_INTERVAL,
    KAFKA_TOPICS,
)

logger = logging.getLogger(__name__)

# GDELT V2 event CSV column indices (tab-separated, no header)
_COL_ACTOR1_NAME = 6
_COL_ACTOR2_NAME = 16
_COL_EVENT_CODE = 26
_COL_GOLDSTEIN_SCALE = 30
_COL_ACTION_GEO_COUNTRY_CODE = 53
_COL_ACTION_GEO_LAT = 56
_COL_ACTION_GEO_LONG = 57
_COL_SOURCE_URL = 60


def _safe_float(value: str) -> float | None:
    """Parse a float from a string, returning None on failure."""
    try:
        return float(value) if value.strip() else None
    except (ValueError, TypeError):
        return None


def _is_conflict_event(event_code: str, goldstein: float | None) -> bool:
    """Return True if the event qualifies as a conflict event.

    Criteria:
    - CAMEO EventCode starting with "18" (assault) or "19" (fight)
    - OR GoldsteinScale < -5 (highly negative / conflictual)
    """
    code = event_code.strip()
    if code.startswith("18") or code.startswith("19"):
        return True
    if goldstein is not None and goldstein < -5:
        return True
    return False


class GdeltProducer(BaseProducer):
    """Polls GDELT V2 lastupdate endpoint and emits conflict events to Kafka."""

    def __init__(self, bootstrap_servers: str | None = None):
        super().__init__(bootstrap_servers)
        self._last_processed_url: str | None = None

    # ------------------------------------------------------------------
    # BaseProducer interface
    # ------------------------------------------------------------------

    @property
    def source_name(self) -> str:
        return "gdelt"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["gdelt"]

    def poll(self) -> None:
        """Fetch the latest GDELT export, filter for conflict events, and emit."""
        csv_url = self._get_latest_export_url()
        if csv_url is None:
            logger.warning("[gdelt] Could not determine latest export URL")
            return

        if csv_url == self._last_processed_url:
            logger.debug("[gdelt] Export already processed: %s", csv_url)
            return

        logger.info("[gdelt] Processing export: %s", csv_url)
        count = self._process_export(csv_url)
        self._last_processed_url = csv_url
        logger.info("[gdelt] Emitted %d conflict events from %s", count, csv_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_latest_export_url(self) -> str | None:
        """Fetch lastupdate.txt and return the URL of the latest events CSV."""
        try:
            req = urllib.request.Request(
                GDELT_LAST_UPDATE_URL,
                headers={"User-Agent": "Sentinel/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8").strip()
        except Exception:
            logger.exception("[gdelt] Failed to fetch lastupdate.txt")
            return None

        # Each line: byte_count hash url — first line is the events export
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
                return parts[2]
            # Also accept .csv.zip or .CSV.zip variants
            if len(parts) >= 3 and ".export." in parts[2].lower():
                return parts[2]

        logger.warning("[gdelt] No export URL found in lastupdate.txt")
        return None

    def _process_export(self, csv_url: str) -> int:
        """Download and parse a gzipped GDELT export CSV, emit conflict events.

        Returns the number of events emitted.
        """
        try:
            req = urllib.request.Request(
                csv_url,
                headers={"User-Agent": "Sentinel/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw_bytes = resp.read()
        except Exception:
            logger.exception("[gdelt] Failed to download export: %s", csv_url)
            return 0

        # Decompress — GDELT exports are typically zip-compressed
        try:
            csv_text = self._decompress(raw_bytes, csv_url)
        except Exception:
            logger.exception("[gdelt] Failed to decompress export: %s", csv_url)
            return 0

        count = 0
        reader = csv.reader(io.StringIO(csv_text), delimiter="\t")
        for row in reader:
            if len(row) <= _COL_SOURCE_URL:  # need at least 61 columns
                continue

            event_code = row[_COL_EVENT_CODE]
            goldstein = _safe_float(row[_COL_GOLDSTEIN_SCALE])

            if not _is_conflict_event(event_code, goldstein):
                continue

            lat = _safe_float(row[_COL_ACTION_GEO_LAT])
            lon = _safe_float(row[_COL_ACTION_GEO_LONG])
            if lat is None or lon is None:
                continue

            country_code = row[_COL_ACTION_GEO_COUNTRY_CODE].strip() or None
            source_url = row[_COL_SOURCE_URL].strip() or None
            actor1 = row[_COL_ACTOR1_NAME].strip() if row[_COL_ACTOR1_NAME] else None
            actor2 = row[_COL_ACTOR2_NAME].strip() if row[_COL_ACTOR2_NAME] else None

            # Build a descriptive raw_text from available fields
            actors = " vs ".join(filter(None, [actor1, actor2]))
            raw_text = f"CAMEO {event_code}"
            if actors:
                raw_text = f"{actors} — {raw_text}"
            if goldstein is not None:
                raw_text += f" (Goldstein {goldstein:+.1f})"

            event = self.normalize(
                raw_text=raw_text,
                title=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
                source_url=source_url,
                lat=lat,
                lon=lon,
                country_code=country_code,
                location_name=None,
                metadata={
                    "event_code": event_code,
                    "goldstein_scale": goldstein,
                    "actor1": actor1,
                    "actor2": actor2,
                },
            )

            self.emit(event)
            count += 1

        return count

    @staticmethod
    def _decompress(raw_bytes: bytes, url: str) -> str:
        """Decompress raw bytes based on the file extension.

        GDELT exports come as .zip (standard zip archive) containing a single CSV.
        """
        if url.endswith(".zip"):
            import zipfile

            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                # The zip contains a single CSV file
                names = zf.namelist()
                if not names:
                    raise ValueError("Empty zip archive")
                return zf.read(names[0]).decode("utf-8", errors="replace")
        elif url.endswith(".gz"):
            return gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
        else:
            # Try gzip first, fall back to raw
            try:
                return gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
            except gzip.BadGzipFile:
                return raw_bytes.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    producer = GdeltProducer()
    producer.run(interval=GDELT_POLL_INTERVAL)
