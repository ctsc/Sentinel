"""Phase 2 Test Gate — Schema consistency across all sources.

Verifies that events from all 5 sources deserialize to the same unified schema.
Requires: Kafka running + producers to have emitted at least one event each.

Run: pytest tests/test_schema_consistency.py -v
"""

import json
import uuid

import pytest
from kafka import KafkaConsumer, TopicPartition

from ingestion.config import KAFKA_TOPICS

KAFKA_BOOTSTRAP = "localhost:9092"

# The sources we expect to validate
SOURCES = ["gdelt", "acled", "rss", "wikipedia", "bluesky"]

REQUIRED_TOP_LEVEL = {"event_id", "source", "raw_text", "timestamp", "source_url", "geo", "metadata"}
REQUIRED_GEO = {"lat", "lon", "country_code", "location_name"}


def _consume_one(topic: str, timeout_ms: int = 10000) -> dict | None:
    """Consume a single event from a topic.

    Uses manual partition assignment (no group_id) to avoid a kafka-python-ng
    coordinator bug on Python 3.12 Windows.
    """
    consumer = KafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        consumer_timeout_ms=timeout_ms,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    tp = TopicPartition(topic, 0)
    consumer.assign([tp])
    consumer.seek_to_beginning(tp)
    event = None
    for msg in consumer:
        event = msg.value
        break
    consumer.close()
    return event


class TestSchemaConsistency:
    """All 5 sources must produce events with the same schema structure."""

    def _get_events(self) -> dict[str, dict]:
        """Fetch one event from each source topic."""
        events = {}
        for source in SOURCES:
            topic = KAFKA_TOPICS.get(source)
            if topic:
                event = _consume_one(topic)
                if event is not None:
                    events[source] = event
        return events

    def test_all_sources_same_schema(self):
        """Events from all available sources share the same top-level keys."""
        events = self._get_events()
        if len(events) < 2:
            pytest.skip(
                f"Need at least 2 sources with events, got {len(events)}: "
                f"{list(events.keys())}"
            )

        # Check each event has the required top-level fields
        for source, event in events.items():
            missing = REQUIRED_TOP_LEVEL - set(event.keys())
            assert not missing, f"[{source}] Missing top-level fields: {missing}"

        # Check geo sub-fields
        for source, event in events.items():
            geo = event.get("geo", {})
            missing_geo = REQUIRED_GEO - set(geo.keys())
            assert not missing_geo, f"[{source}] Missing geo fields: {missing_geo}"

    def test_all_events_deserialize_without_error(self):
        """All source events deserialize cleanly from Kafka JSON."""
        events = self._get_events()
        if not events:
            pytest.skip("No events available from any source")

        for source, event in events.items():
            assert isinstance(event, dict), f"[{source}] Event is not a dict"
            assert isinstance(event.get("event_id"), str), f"[{source}] event_id not str"
            assert isinstance(event.get("source"), str), f"[{source}] source not str"
            assert isinstance(event.get("geo"), dict), f"[{source}] geo not dict"
            assert isinstance(event.get("metadata"), dict), f"[{source}] metadata not dict"

    def test_event_id_is_uuid(self):
        """event_id from every source is a valid UUID."""
        events = self._get_events()
        if not events:
            pytest.skip("No events available")

        for source, event in events.items():
            try:
                uuid.UUID(event["event_id"])
            except (ValueError, KeyError):
                pytest.fail(f"[{source}] event_id is not a valid UUID: {event.get('event_id')}")
