"""Phase 1 Test Gate — Kafka + Cassandra connectivity and basic operations.

Prerequisites: docker-compose up (Kafka, Zookeeper, Cassandra all healthy).

Run: pytest tests/test_phase1_infra.py -v
"""

import json
import uuid

import pytest
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import NoBrokersAvailable
from cassandra.cluster import Cluster, NoHostAvailable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KAFKA_BOOTSTRAP = "localhost:9092"
CASSANDRA_HOST = "localhost"
CASSANDRA_PORT = 9042
TEST_TOPIC = "sentinel.test.phase1"


@pytest.fixture(scope="module")
def kafka_producer():
    """Create a Kafka producer connected to the local broker."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=10000,
        )
        yield producer
        producer.close()
    except NoBrokersAvailable:
        pytest.fail(
            "Kafka broker not available at localhost:9092. "
            "Is docker-compose up?"
        )


@pytest.fixture(scope="module")
def cassandra_session():
    """Create a Cassandra session connected to the local node."""
    try:
        cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
        session = cluster.connect()
        yield session
        session.shutdown()
        cluster.shutdown()
    except NoHostAvailable:
        pytest.fail(
            "Cassandra not available at localhost:9042. "
            "Is docker-compose up?"
        )


# ---------------------------------------------------------------------------
# Kafka Tests
# ---------------------------------------------------------------------------

class TestKafka:
    """Kafka broker connectivity and produce/consume round-trip."""

    def test_broker_accepts_connections(self, kafka_producer):
        """Kafka broker accepts connections on localhost:9092."""
        assert kafka_producer.bootstrap_connected()

    def test_produce_consume_roundtrip(self, kafka_producer):
        """Can create a topic, produce a message, consume it back, verify content."""
        test_event = {
            "event_id": str(uuid.uuid4()),
            "source": "test",
            "title": "Phase 1 connectivity test",
            "timestamp": "2026-04-03T12:00:00Z",
        }

        # Produce
        future = kafka_producer.send(TEST_TOPIC, value=test_event)
        result = future.get(timeout=10)
        assert result.topic == TEST_TOPIC

        # Consume
        consumer = KafkaConsumer(
            TEST_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset="earliest",
            consumer_timeout_ms=10000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id=f"test-phase1-{uuid.uuid4().hex[:8]}",
        )

        consumed = None
        for msg in consumer:
            if msg.value.get("event_id") == test_event["event_id"]:
                consumed = msg.value
                break

        consumer.close()

        assert consumed is not None, "Failed to consume the produced message"
        assert consumed["event_id"] == test_event["event_id"]
        assert consumed["source"] == "test"
        assert consumed["title"] == "Phase 1 connectivity test"


# ---------------------------------------------------------------------------
# Cassandra Tests
# ---------------------------------------------------------------------------

class TestCassandra:
    """Cassandra connectivity, schema creation, and CRUD operations."""

    def test_accepts_connections(self, cassandra_session):
        """Cassandra accepts connections on localhost:9042."""
        rows = cassandra_session.execute("SELECT cluster_name FROM system.local")
        assert rows.one() is not None

    def test_create_keyspace_and_table(self, cassandra_session):
        """Can create keyspace + table via init.cql schema."""
        cassandra_session.execute("""
            CREATE KEYSPACE IF NOT EXISTS sentinel WITH replication = {
                'class': 'SimpleStrategy', 'replication_factor': 1
            }
        """)
        cassandra_session.set_keyspace("sentinel")
        cassandra_session.execute("""
            CREATE TABLE IF NOT EXISTS sentinel.events (
                region text,
                time_bucket text,
                event_time timestamp,
                event_id uuid,
                source text,
                event_type text,
                title text,
                raw_text text,
                lat double,
                lon double,
                country_code text,
                location_name text,
                confidence double,
                severity int,
                source_url text,
                PRIMARY KEY ((region, time_bucket), event_time, event_id)
            ) WITH CLUSTERING ORDER BY (event_time DESC)
        """)
        # Verify table exists
        rows = cassandra_session.execute(
            "SELECT table_name FROM system_schema.tables "
            "WHERE keyspace_name = 'sentinel' AND table_name = 'events'"
        )
        assert rows.one() is not None

    def test_insert_select_delete(self, cassandra_session):
        """Can INSERT a sample event, SELECT it back, verify fields, and DELETE."""
        cassandra_session.set_keyspace("sentinel")
        test_id = uuid.uuid4()
        test_time = "2026-04-03T14:00:00.000Z"

        # INSERT
        cassandra_session.execute(
            """
            INSERT INTO events (
                region, time_bucket, event_time, event_id,
                source, event_type, title, raw_text,
                lat, lon, country_code, location_name,
                confidence, severity, source_url
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
            """,
            (
                "middle_east", "2026-04-03T14", test_time, test_id,
                "test", "conflict", "Test Event", "A test event in Gaza",
                31.5, 34.47, "PS", "Gaza",
                0.95, 8, "https://example.com/test",
            ),
        )

        # SELECT
        rows = cassandra_session.execute(
            "SELECT * FROM events WHERE region = %s AND time_bucket = %s",
            ("middle_east", "2026-04-03T14"),
        )
        found = None
        for row in rows:
            if row.event_id == test_id:
                found = row
                break

        assert found is not None, "Inserted event not found"
        assert found.source == "test"
        assert found.event_type == "conflict"
        assert found.title == "Test Event"
        assert found.lat == 31.5
        assert found.lon == 34.47
        assert found.country_code == "PS"
        assert found.severity == 8

        # DELETE
        cassandra_session.execute(
            "DELETE FROM events WHERE region = %s AND time_bucket = %s "
            "AND event_time = %s AND event_id = %s",
            ("middle_east", "2026-04-03T14", test_time, test_id),
        )

        # Verify deletion
        rows = cassandra_session.execute(
            "SELECT * FROM events WHERE region = %s AND time_bucket = %s "
            "AND event_time = %s AND event_id = %s",
            ("middle_east", "2026-04-03T14", test_time, test_id),
        )
        assert rows.one() is None, "Event should have been deleted"
