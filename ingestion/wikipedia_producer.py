"""Wikipedia Recent Changes SSE producer — streams English Wikipedia edits matching conflict keywords."""

import json
import logging
import time
import urllib.request

import sseclient

from ingestion.base_producer import BaseProducer
from ingestion.config import (
    CONFLICT_KEYWORDS,
    KAFKA_TOPICS,
    WIKIPEDIA_SSE_URL,
)

logger = logging.getLogger(__name__)

# Batch window defaults
_BATCH_TIMEOUT_SEC = 30
_BATCH_MAX_EVENTS = 100


class WikipediaProducer(BaseProducer):
    """Consumes the Wikimedia EventStreams SSE feed, filters for English Wikipedia
    edits whose title contains a conflict keyword, and emits them to Kafka."""

    @property
    def source_name(self) -> str:
        return "wikipedia"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["wikipedia"]

    # ------------------------------------------------------------------
    # Keyword matching
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_keywords(title: str) -> bool:
        """Return True if *title* contains at least one conflict keyword."""
        title_lower = title.lower()
        return any(kw in title_lower for kw in CONFLICT_KEYWORDS)

    # ------------------------------------------------------------------
    # SSE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _open_sse_stream() -> sseclient.SSEClient:
        """Open a streaming connection to the Wikimedia EventStreams endpoint."""
        req = urllib.request.Request(
            WIKIPEDIA_SSE_URL,
            headers={
                "Accept": "text/event-stream",
                # Wikimedia's streaming endpoint rejects the default Python UA.
                # Their policy requires a UA that identifies the tool + contact.
                "User-Agent": "Sentinel-OSINT/1.0 (https://github.com/ctsc/sentinel; academic research)",
            },
        )
        response = urllib.request.urlopen(req, timeout=60)  # noqa: S310
        return sseclient.SSEClient(response)

    # ------------------------------------------------------------------
    # poll() — called by the BaseProducer run loop
    # ------------------------------------------------------------------

    def poll(self) -> None:
        """Read SSE events for up to *_BATCH_TIMEOUT_SEC* seconds or
        *_BATCH_MAX_EVENTS* matching events, whichever comes first."""

        try:
            client = self._open_sse_stream()
        except Exception:
            logger.exception("[wikipedia] Failed to open SSE stream")
            return

        emitted = 0
        deadline = time.monotonic() + _BATCH_TIMEOUT_SEC

        try:
            for sse_event in client.events():
                # Respect batch window
                if emitted >= _BATCH_MAX_EVENTS or time.monotonic() >= deadline:
                    break

                if sse_event.event != "message":
                    continue

                try:
                    change = json.loads(sse_event.data)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Only English Wikipedia
                if change.get("wiki") != "enwiki":
                    continue

                title = change.get("title", "")
                if not self._matches_keywords(title):
                    continue

                # Build source URL from meta.uri
                source_url = change.get("meta", {}).get("uri")

                # Timestamp — Wikimedia provides epoch seconds
                ts_epoch = change.get("timestamp")
                timestamp = None
                if ts_epoch is not None:
                    try:
                        from datetime import datetime, timezone

                        timestamp = datetime.fromtimestamp(
                            int(ts_epoch), tz=timezone.utc
                        ).isoformat()
                    except (ValueError, OSError):
                        pass

                event = self.normalize(
                    raw_text=change.get("comment", ""),
                    title=title,
                    timestamp=timestamp,
                    source_url=source_url,
                    lat=None,
                    lon=None,
                    country_code=None,
                    location_name=None,
                    metadata={
                        "wiki": "enwiki",
                        "user": change.get("user", ""),
                        "type": change.get("type", ""),
                    },
                )
                self.emit(event)
                emitted += 1

        except Exception:
            logger.exception("[wikipedia] Error reading SSE stream")
        finally:
            logger.info("[wikipedia] Batch complete — emitted %d events", emitted)


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    producer = WikipediaProducer()
    # poll() returns after each batch; run() loops with a short interval
    # so we reconnect the SSE stream each cycle.
    producer.run(interval=5)
