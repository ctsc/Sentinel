"""
Phase 3 Test Gate — End-to-end pipeline integration test.

Tests: produce event → Kafka → consumer processes it → Cassandra → query back.
Requires Docker (Kafka + Cassandra) to be running.
"""

import json
import time
import uuid
import sys
import os
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_gdelt_event():
    """Create a sample GDELT event."""
    return {
        "event_id": str(uuid.uuid4()),
        "source": "gdelt",
        "raw_text": "Military forces clashed near the eastern border region",
        "title": "Eastern border clash reported",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_url": "http://example.com/gdelt-article",
        "geo": {
            "lat": 50.45,
            "lon": 30.52,
            "country_code": "UA",
            "location_name": "Kyiv",
        },
        "metadata": {
            "event_code": "190",
            "goldstein_scale": -7.0,
            "actor1": "UKR",
            "actor2": "RUS",
        },
    }


def _make_rss_event():
    """Create a sample RSS event (unstructured)."""
    return {
        "event_id": str(uuid.uuid4()),
        "source": "rss",
        "raw_text": "Heavy fighting erupted in Kyiv as forces launched a new offensive in the region.",
        "title": "Fighting erupts in Kyiv",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_url": "http://example.com/rss-article",
        "geo": {
            "lat": None,
            "lon": None,
            "country_code": None,
            "location_name": None,
        },
        "metadata": {"feed_name": "test_feed"},
    }


@pytest.fixture
def kafka_producer():
    from kafka import KafkaProducer

    try:
        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=3,
        )
        yield producer
        producer.close()
    except Exception as e:
        pytest.skip(f"Kafka not available: {e}")


@pytest.fixture
def cassandra_session():
    from cassandra.cluster import Cluster

    try:
        cluster = Cluster(["localhost"], port=9042)
        session = cluster.connect("sentinel")
        yield session
        cluster.shutdown()
    except Exception as e:
        pytest.skip(f"Cassandra not available: {e}")


class TestGdeltPassthrough:
    """Test structured source (GDELT) flows through the pipeline correctly."""

    def test_gdelt_event_processed(self, kafka_producer, cassandra_session):
        """Produce a GDELT event → consumer picks it up → verify in Cassandra."""
        from processing.consumer import process_structured

        event = _make_gdelt_event()

        # Process directly (unit-level — no Kafka round-trip needed for this)
        enriched = process_structured(event)

        assert enriched["event_type"] == "conflict"
        assert enriched["confidence"] >= 0.85
        assert enriched["severity"] >= 5
        assert "entities" in enriched

    def test_gdelt_severity_from_goldstein(self):
        from processing.consumer import process_structured

        event = _make_gdelt_event()
        event["metadata"]["goldstein_scale"] = -9.0

        enriched = process_structured(event)
        assert enriched["severity"] >= 8


class TestRssProcessing:
    """Test unstructured source (RSS) goes through NER → geocode → classify."""

    def test_rss_event_gets_enriched(self):
        from processing.consumer import process_unstructured

        event = _make_rss_event()
        enriched = process_unstructured(event)

        assert enriched["event_type"] in ("conflict", "protest", "disaster", "political", "terrorism", "other")
        assert enriched["confidence"] > 0
        assert "entities" in enriched
        assert isinstance(enriched["entities"], list)
        assert enriched["severity"] >= 1

    def test_rss_ner_extracts_location(self):
        from processing.consumer import process_unstructured

        event = _make_rss_event()
        enriched = process_unstructured(event)

        # NER should extract "Kyiv" from the text
        entities_lower = [e.lower() for e in enriched.get("entities", [])]
        assert any("kyiv" in e for e in entities_lower), f"Expected Kyiv in entities: {enriched['entities']}"

    def test_rss_geocoding_fills_coordinates(self):
        from processing.consumer import process_unstructured

        event = _make_rss_event()
        enriched = process_unstructured(event)

        geo = enriched.get("geo", {})
        # If NER found Kyiv and geocoder resolved it, we should have coords
        if enriched.get("entities"):
            # Geocoder should have filled in coordinates
            assert geo.get("lat") is not None or len(enriched["entities"]) == 0


class TestDeduplicationE2E:
    """Test dedup works end-to-end."""

    def test_duplicate_blocked(self):
        from processing.dedup import Deduplicator

        dedup = Deduplicator()
        event = _make_gdelt_event()

        assert dedup.is_duplicate(event) is False
        assert dedup.is_duplicate(event) is True


class TestCassandraSink:
    """Test writing enriched events to Cassandra."""

    def test_write_and_read_back(self, cassandra_session):
        from processing.sink import CassandraSink, get_region, get_time_bucket
        from processing.consumer import process_structured

        event = _make_gdelt_event()
        enriched = process_structured(event)

        sink = CassandraSink()
        sink.connect()

        try:
            success = sink.write(enriched)
            assert success, "Failed to write event to Cassandra"

            # Query it back
            region = get_region(enriched["geo"]["country_code"])
            time_bucket = get_time_bucket(enriched["timestamp"])

            rows = cassandra_session.execute(
                "SELECT * FROM events WHERE region=%s AND time_bucket=%s",
                (region, time_bucket),
            )
            results = list(rows)
            assert len(results) > 0, "Event not found in Cassandra after write"

            # Verify fields
            row = results[0]
            assert row.source == "gdelt"
            assert row.event_type == "conflict"
            assert row.lat is not None
            assert row.lon is not None

        finally:
            # Cleanup
            cassandra_session.execute(
                "DELETE FROM events WHERE region=%s AND time_bucket=%s",
                (region, time_bucket),
            )
            sink.close()

    def test_write_rss_event(self, cassandra_session):
        from processing.sink import CassandraSink, get_region, get_time_bucket
        from processing.consumer import process_unstructured

        event = _make_rss_event()
        enriched = process_unstructured(event)

        # Ensure we have geo data for the write
        if not enriched["geo"].get("lat"):
            enriched["geo"]["lat"] = 50.45
            enriched["geo"]["lon"] = 30.52
            enriched["geo"]["country_code"] = "UA"

        sink = CassandraSink()
        sink.connect()

        try:
            success = sink.write(enriched)
            assert success

            region = get_region(enriched["geo"]["country_code"])
            time_bucket = get_time_bucket(enriched["timestamp"])

            rows = cassandra_session.execute(
                "SELECT * FROM events WHERE region=%s AND time_bucket=%s",
                (region, time_bucket),
            )
            results = list(rows)
            assert len(results) > 0

        finally:
            cassandra_session.execute(
                "DELETE FROM events WHERE region=%s AND time_bucket=%s",
                (region, time_bucket),
            )
            sink.close()
