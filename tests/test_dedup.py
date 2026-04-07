"""
Phase 3 Test Gate — Deduplication tests.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.dedup import Deduplicator


class TestDeduplicator:
    """Test hash-based deduplication logic."""

    def setup_method(self):
        self.dedup = Deduplicator()

    def test_first_event_not_duplicate(self):
        event = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        assert self.dedup.is_duplicate(event) is False

    def test_same_event_is_duplicate(self):
        event = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        assert self.dedup.is_duplicate(event) is False  # First time
        assert self.dedup.is_duplicate(event) is True   # Duplicate

    def test_different_source_not_duplicate(self):
        event1 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        event2 = {
            "title": "Explosion in Kyiv",
            "source": "bluesky",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        assert self.dedup.is_duplicate(event1) is False
        assert self.dedup.is_duplicate(event2) is False  # Different source

    def test_different_hour_not_duplicate(self):
        event1 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        event2 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T15:30:00Z",  # Different hour
        }
        assert self.dedup.is_duplicate(event1) is False
        assert self.dedup.is_duplicate(event2) is False  # Different time window

    def test_same_hour_is_duplicate(self):
        event1 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:05:00Z",
        }
        event2 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:55:00Z",  # Same hour
        }
        assert self.dedup.is_duplicate(event1) is False
        assert self.dedup.is_duplicate(event2) is True  # Same hour = duplicate

    def test_case_insensitive_title(self):
        event1 = {
            "title": "Explosion in Kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        event2 = {
            "title": "explosion in kyiv",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        assert self.dedup.is_duplicate(event1) is False
        assert self.dedup.is_duplicate(event2) is True  # Same after normalization

    def test_dedupe_hash_attached(self):
        event = {
            "title": "Test event",
            "source": "rss",
            "timestamp": "2026-04-03T14:30:00Z",
        }
        self.dedup.is_duplicate(event)
        assert "dedupe_hash" in event
        assert len(event["dedupe_hash"]) == 16

    def test_eviction_at_max_entries(self):
        dedup = Deduplicator(max_entries=10)
        for i in range(15):
            event = {
                "title": f"Event {i}",
                "source": "rss",
                "timestamp": "2026-04-03T14:30:00Z",
            }
            dedup.is_duplicate(event)
        stats = dedup.get_stats()
        assert stats["cache_size"] <= 10

    def test_stats_tracking(self):
        event = {
            "title": "Test",
            "source": "rss",
            "timestamp": "2026-04-03T14:00:00Z",
        }
        self.dedup.is_duplicate(event)
        self.dedup.is_duplicate(event)

        stats = self.dedup.get_stats()
        assert stats["total_checked"] == 2
        assert stats["duplicates_blocked"] == 1

    def test_no_title_uses_raw_text(self):
        event = {
            "title": None,
            "raw_text": "Some raw text about conflict",
            "source": "bluesky",
            "timestamp": "2026-04-03T14:00:00Z",
        }
        assert self.dedup.is_duplicate(event) is False
        assert self.dedup.is_duplicate(event) is True
