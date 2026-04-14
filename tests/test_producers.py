"""Phase 2 Test Gate — Producer schema validation and Kafka integration.

Tests each producer's output against the unified schema.
Requires: docker-compose up (Kafka running on localhost:9092).

Run: pytest tests/test_producers.py -v
"""

import json
import uuid

import pytest
from kafka import KafkaConsumer, TopicPartition

from ingestion.config import KAFKA_TOPICS

KAFKA_BOOTSTRAP = "localhost:9092"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_event_schema(event: dict) -> list[str]:
    """Validate a single event against the unified Sentinel schema.

    Returns a list of error strings (empty = valid).
    """
    errors = []

    # Required top-level fields
    for field in ("event_id", "source", "raw_text", "timestamp", "geo"):
        if field not in event:
            errors.append(f"Missing required field: {field}")

    # event_id should be a valid UUID
    if "event_id" in event:
        try:
            uuid.UUID(event["event_id"])
        except (ValueError, TypeError):
            errors.append(f"event_id is not a valid UUID: {event.get('event_id')}")

    # source should be a known source name
    valid_sources = {"gdelt", "acled", "rss", "bluesky", "wikipedia", "telegram"}
    if event.get("source") not in valid_sources:
        errors.append(f"Unknown source: {event.get('source')}")

    # timestamp should be a non-empty string (ISO8601)
    ts = event.get("timestamp")
    if not isinstance(ts, str) or len(ts) < 10:
        errors.append(f"Invalid timestamp: {ts}")

    # geo must be a dict with lat, lon, country_code, location_name keys
    geo = event.get("geo")
    if isinstance(geo, dict):
        for gfield in ("lat", "lon", "country_code", "location_name"):
            if gfield not in geo:
                errors.append(f"Missing geo field: {gfield}")
    else:
        errors.append("geo is not a dict")

    # title can be str or None
    if "title" in event and event["title"] is not None and not isinstance(event["title"], str):
        errors.append(f"title should be str or None, got {type(event['title'])}")

    # source_url can be str or None
    if "source_url" in event and event["source_url"] is not None and not isinstance(event["source_url"], str):
        errors.append(f"source_url should be str or None, got {type(event['source_url'])}")

    # metadata should be a dict
    if "metadata" in event and not isinstance(event.get("metadata"), dict):
        errors.append("metadata should be a dict")

    return errors


def _consume_events(topic: str, max_events: int = 5, timeout_ms: int = 15000) -> list[dict]:
    """Consume up to max_events from a topic, return deserialized events.

    Uses manual partition assignment (no group_id) to avoid a kafka-python-ng
    coordinator bug on Python 3.12 Windows.
    """
    import time
    time.sleep(1)
    consumer = KafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        consumer_timeout_ms=timeout_ms,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    tp = TopicPartition(topic, 0)
    consumer.assign([tp])
    consumer.seek_to_beginning(tp)
    events = []
    for msg in consumer:
        events.append(msg.value)
        if len(events) >= max_events:
            break
    consumer.close()
    return events


# ---------------------------------------------------------------------------
# GDELT Producer Tests
# ---------------------------------------------------------------------------

class TestGdeltProducer:
    """GDELT producer schema and connectivity."""

    def test_produces_valid_schema(self):
        """GDELT producer outputs messages matching the unified schema."""
        from ingestion.gdelt_producer import GdeltProducer

        producer = GdeltProducer()
        producer.run_once()

        events = _consume_events(KAFKA_TOPICS["gdelt"])
        assert len(events) > 0, "GDELT producer emitted no events"

        for event in events:
            errors = _validate_event_schema(event)
            assert not errors, f"Schema errors: {errors}"
            assert event["source"] == "gdelt"

    def test_geo_populated(self):
        """GDELT events have lat/lon populated (structured source)."""
        events = _consume_events(KAFKA_TOPICS["gdelt"])
        if not events:
            pytest.skip("No GDELT events available")
        for event in events:
            assert event["geo"]["lat"] is not None, "GDELT event missing lat"
            assert event["geo"]["lon"] is not None, "GDELT event missing lon"


# ---------------------------------------------------------------------------
# ACLED Producer Tests
# ---------------------------------------------------------------------------

class TestAcledProducer:
    """ACLED producer schema and connectivity."""

    def test_produces_valid_schema(self):
        """ACLED producer outputs messages matching the unified schema."""
        from ingestion.acled_producer import ACLEDProducer

        producer = ACLEDProducer()
        producer.run_once()

        events = _consume_events(KAFKA_TOPICS["acled"])
        # ACLED may return 0 events if OAuth credentials are missing or invalid
        if not events:
            pytest.skip("No ACLED events (check ACLED_EMAIL + ACLED_PASSWORD in .env)")

        for event in events:
            errors = _validate_event_schema(event)
            assert not errors, f"Schema errors: {errors}"
            assert event["source"] == "acled"

    def test_geo_populated(self):
        """ACLED events have lat/lon populated (structured source)."""
        events = _consume_events(KAFKA_TOPICS["acled"])
        if not events:
            pytest.skip("No ACLED events available")
        for event in events:
            assert event["geo"]["lat"] is not None, "ACLED event missing lat"
            assert event["geo"]["lon"] is not None, "ACLED event missing lon"


# ---------------------------------------------------------------------------
# RSS Producer Tests
# ---------------------------------------------------------------------------

class TestRssProducer:
    """RSS producer schema and connectivity."""

    def test_produces_valid_schema(self):
        """RSS producer outputs messages matching the unified schema."""
        from ingestion.rss_producer import RSSProducer

        producer = RSSProducer()
        producer.run_once()

        events = _consume_events(KAFKA_TOPICS["rss"])
        assert len(events) > 0, "RSS producer emitted no events"

        for event in events:
            errors = _validate_event_schema(event)
            assert not errors, f"Schema errors: {errors}"
            assert event["source"] == "rss"

    def test_source_url_populated(self):
        """RSS events always have source_url populated."""
        events = _consume_events(KAFKA_TOPICS["rss"])
        if not events:
            pytest.skip("No RSS events available")
        for event in events:
            assert event.get("source_url"), "RSS event missing source_url"


# ---------------------------------------------------------------------------
# Wikipedia Producer Tests
# ---------------------------------------------------------------------------

class TestWikipediaProducer:
    """Wikipedia producer schema and connectivity."""

    def test_produces_valid_schema(self):
        """Wikipedia producer outputs messages matching the unified schema."""
        from ingestion.wikipedia_producer import WikipediaProducer

        producer = WikipediaProducer()
        producer.run_once()

        events = _consume_events(KAFKA_TOPICS["wikipedia"], timeout_ms=45000)
        # Wikipedia may produce 0 events if no conflict edits happen during the batch window
        if not events:
            pytest.skip("No Wikipedia events in batch window (no matching edits)")

        for event in events:
            errors = _validate_event_schema(event)
            assert not errors, f"Schema errors: {errors}"
            assert event["source"] == "wikipedia"

    def test_keyword_filter(self):
        """Wikipedia events should only contain entries matching conflict keywords."""
        from ingestion.config import CONFLICT_KEYWORDS

        events = _consume_events(KAFKA_TOPICS["wikipedia"], timeout_ms=5000)
        if not events:
            pytest.skip("No Wikipedia events available")
        for event in events:
            title = (event.get("title") or "").lower()
            matched = any(kw in title for kw in CONFLICT_KEYWORDS)
            assert matched, f"Wikipedia event title doesn't match keywords: {event.get('title')}"


# ---------------------------------------------------------------------------
# Bluesky Producer Tests
# ---------------------------------------------------------------------------

class TestBlueskyProducer:
    """Bluesky producer schema and connectivity."""

    def test_produces_valid_schema(self):
        """Bluesky producer outputs messages matching the unified schema."""
        from ingestion.bluesky_producer import BlueskyProducer

        producer = BlueskyProducer()
        producer.run_once()

        events = _consume_events(KAFKA_TOPICS["bluesky"], timeout_ms=45000)
        # Bluesky may produce 0 if atproto isn't installed or no matching posts
        if not events:
            pytest.skip("No Bluesky events (atproto may not be installed)")

        for event in events:
            errors = _validate_event_schema(event)
            assert not errors, f"Schema errors: {errors}"
            assert event["source"] == "bluesky"

    def test_keyword_filter(self):
        """Bluesky events should contain at least one conflict keyword."""
        from ingestion.config import CONFLICT_KEYWORDS

        events = _consume_events(KAFKA_TOPICS["bluesky"], timeout_ms=5000)
        if not events:
            pytest.skip("No Bluesky events available")
        for event in events:
            text = (event.get("raw_text") or "").lower()
            matched = any(kw in text for kw in CONFLICT_KEYWORDS)
            assert matched, f"Bluesky event doesn't match keywords: {event.get('raw_text')[:80]}"
