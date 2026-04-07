"""
Hash-based deduplication for the event pipeline.

Dedup key: hash(title + source + 1-hour time window).
Uses a bounded in-memory set to prevent unbounded memory growth.
"""

import hashlib
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Max number of hashes to keep in memory
MAX_DEDUP_ENTRIES = 50000


class Deduplicator:
    """Hash-based event deduplicator with a 1-hour time window."""

    def __init__(self, max_entries: int = MAX_DEDUP_ENTRIES):
        self._seen: OrderedDict[str, bool] = OrderedDict()
        self._max_entries = max_entries
        self._duplicates_blocked = 0
        self._total_checked = 0

    def _compute_hash(self, title: Optional[str], source: str, timestamp: str) -> str:
        """
        Compute a dedup hash from title + source + hourly time bucket.

        The time bucket truncates to the hour, so events with the same title
        and source within the same hour are considered duplicates.
        """
        # Normalize title
        norm_title = (title or "").strip().lower()

        # Extract hourly bucket from ISO8601 timestamp
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_bucket = dt.strftime("%Y-%m-%dT%H")
        except (ValueError, AttributeError):
            time_bucket = "unknown"

        raw = f"{norm_title}|{source}|{time_bucket}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_duplicate(self, event: dict) -> bool:
        """
        Check if an event is a duplicate.

        Returns True if the event should be dropped (is a duplicate).
        """
        self._total_checked += 1

        title = event.get("title") or event.get("raw_text", "")[:100]
        source = event.get("source", "")
        timestamp = event.get("timestamp", "")

        dedupe_hash = self._compute_hash(title, source, timestamp)

        if dedupe_hash in self._seen:
            self._duplicates_blocked += 1
            logger.debug("Duplicate blocked: %s (hash=%s)", title[:50], dedupe_hash)
            return True

        # Add to seen set
        self._seen[dedupe_hash] = True

        # Evict oldest entries if over limit
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)

        # Attach hash to event for downstream use
        event["dedupe_hash"] = dedupe_hash
        return False

    def get_stats(self) -> dict:
        return {
            "total_checked": self._total_checked,
            "duplicates_blocked": self._duplicates_blocked,
            "cache_size": len(self._seen),
        }
