"""RSS feed Kafka producer — polls BBC, Al Jazeera, and Google News."""

import logging
import time
from calendar import timegm
from collections import deque
from datetime import datetime, timezone
from typing import Any

import feedparser

from ingestion.base_producer import BaseProducer
from ingestion.config import KAFKA_TOPICS, RSS_FEEDS, RSS_POLL_INTERVAL

logger = logging.getLogger(__name__)

# Maximum number of seen entry IDs to retain (prevents unbounded growth).
_MAX_SEEN = 5000


class RSSProducer(BaseProducer):
    """Ingests articles from multiple RSS feeds and publishes to Kafka."""

    def __init__(self, bootstrap_servers: str | None = None):
        super().__init__(bootstrap_servers)
        # Track entry IDs/links already emitted so we don't duplicate across polls.
        # Using a deque as a bounded FIFO — oldest IDs are evicted first.
        self._seen_ids: deque[str] = deque(maxlen=_MAX_SEEN)
        self._seen_set: set[str] = set()

    # ------------------------------------------------------------------
    # Abstract property implementations
    # ------------------------------------------------------------------

    @property
    def source_name(self) -> str:
        return "rss"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["rss"]

    # ------------------------------------------------------------------
    # Dedup helpers
    # ------------------------------------------------------------------

    def _entry_key(self, entry: Any) -> str:
        """Return a unique key for an RSS entry (prefer id, fall back to link)."""
        return entry.get("id") or entry.get("link") or ""

    def _mark_seen(self, key: str) -> None:
        """Add a key to the seen set, evicting the oldest if at capacity."""
        if key in self._seen_set:
            return
        if len(self._seen_ids) == _MAX_SEEN:
            evicted = self._seen_ids[0]  # will be auto-evicted by deque
            self._seen_set.discard(evicted)
        self._seen_ids.append(key)
        self._seen_set.add(key)

    # ------------------------------------------------------------------
    # Timestamp conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_published(entry: Any) -> str:
        """Convert feedparser's published_parsed to ISO8601, falling back to now()."""
        parsed = entry.get("published_parsed")
        if parsed:
            try:
                dt = datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
                return dt.isoformat()
            except (ValueError, OSError, OverflowError):
                pass
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Poll implementation
    # ------------------------------------------------------------------

    def poll(self) -> None:  # noqa: D401
        """Fetch all configured RSS feeds and emit new entries."""
        total_new = 0

        for feed_cfg in RSS_FEEDS:
            feed_name: str = feed_cfg["name"]
            feed_url: str = feed_cfg["url"]

            try:
                # Reddit and many CDNs block the default feedparser UA.
                # Send a real browser UA so they hand us the feed.
                parsed = feedparser.parse(
                    feed_url,
                    agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
            except Exception:
                logger.exception("[rss] Failed to fetch feed %s", feed_name)
                continue

            if parsed.bozo and not parsed.entries:
                logger.warning(
                    "[rss] Feed %s returned bozo error: %s",
                    feed_name,
                    parsed.get("bozo_exception", "unknown"),
                )
                continue

            for entry in parsed.entries:
                key = self._entry_key(entry)
                if not key or key in self._seen_set:
                    continue

                title = entry.get("title", "")
                raw_text = entry.get("summary", "")
                source_url = entry.get("link", "")
                timestamp = self._parse_published(entry)

                # source_url must be populated for every RSS event
                if not source_url:
                    logger.debug("[rss] Skipping entry with no link in %s", feed_name)
                    continue

                event = self.normalize(
                    raw_text=raw_text,
                    title=title,
                    timestamp=timestamp,
                    source_url=source_url,
                    lat=None,
                    lon=None,
                    country_code=None,
                    location_name=None,
                    metadata={"feed_name": feed_name},
                )
                self.emit(event)
                self._mark_seen(key)
                total_new += 1

        logger.info("[rss] Poll complete — %d new entries emitted", total_new)


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    producer = RSSProducer()
    producer.run(interval=RSS_POLL_INTERVAL)
