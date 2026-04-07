"""
Plain Python Kafka consumer — the dev-path processor.

Reads from all sentinel.raw.* topics, routes events through the appropriate
processing path, and sinks to Cassandra.

Structured sources (GDELT, ACLED): passthrough — already have coords + type.
Unstructured sources (RSS, Bluesky, Wikipedia): NER → geocode → classify.
All events: dedup → sink.
"""

import json
import logging
import os
import signal
import sys
import time

from kafka import KafkaConsumer

from processing.nlp.ner import extract_locations
from processing.nlp.classifier import classify_text, classify_cameo, classify_acled
from processing.nlp.geocoder import geocode_entities
from processing.dedup import Deduplicator
from processing.sink import CassandraSink

logger = logging.getLogger(__name__)

STRUCTURED_SOURCES = {"gdelt", "acled"}
UNSTRUCTURED_SOURCES = {"rss", "bluesky", "wikipedia"}

ALL_TOPICS = [
    "sentinel.raw.gdelt",
    "sentinel.raw.acled",
    "sentinel.raw.rss",
    "sentinel.raw.bluesky",
    "sentinel.raw.wikipedia",
]


def _compute_severity(event: dict) -> int:
    """Compute a 1-10 severity score based on available signals."""
    severity = 5  # baseline

    source = event.get("source", "")
    metadata = event.get("metadata", {})

    # GDELT: use Goldstein scale (negative = more severe)
    if source == "gdelt":
        goldstein = metadata.get("goldstein_scale")
        if goldstein is not None:
            try:
                g = float(goldstein)
                if g < -8:
                    severity = 9
                elif g < -5:
                    severity = 7
                elif g < -2:
                    severity = 6
                else:
                    severity = 4
            except (ValueError, TypeError):
                pass

    # ACLED: use fatalities
    elif source == "acled":
        fatalities = metadata.get("fatalities")
        if fatalities is not None:
            try:
                f = int(fatalities)
                if f > 50:
                    severity = 10
                elif f > 20:
                    severity = 9
                elif f > 10:
                    severity = 8
                elif f > 5:
                    severity = 7
                elif f > 0:
                    severity = 6
                else:
                    severity = 4
            except (ValueError, TypeError):
                pass

    # Event type adjustments
    event_type = event.get("event_type", "other")
    if event_type == "terrorism":
        severity = min(severity + 2, 10)
    elif event_type == "conflict":
        severity = min(severity + 1, 10)

    return max(1, min(10, severity))


def process_structured(event: dict) -> dict:
    """
    Process a structured source event (GDELT/ACLED).
    These already have coordinates and event type — minimal processing needed.
    """
    source = event.get("source", "")
    metadata = event.get("metadata", {})

    # Classify based on source-specific fields
    if source == "gdelt":
        event_code = metadata.get("event_code", "")
        event_type, confidence = classify_cameo(event_code)
    elif source == "acled":
        acled_type = metadata.get("event_type", "")
        event_type, confidence = classify_acled(acled_type)
    else:
        event_type, confidence = "other", 0.3

    event["event_type"] = event_type
    event["confidence"] = confidence
    event["entities"] = []
    event["severity"] = _compute_severity(event)

    return event


def process_unstructured(event: dict) -> dict:
    """
    Process an unstructured source event (RSS/Bluesky/Wikipedia).
    Runs NER → geocoding → classification pipeline.
    """
    text = event.get("raw_text", "") or event.get("title", "") or ""

    # 1. NER: extract location entities
    entities = extract_locations(text)
    event["entities"] = entities

    # 2. Geocode: resolve entities to coordinates (only if no coords yet)
    geo = event.get("geo", {})
    if not geo.get("lat") or not geo.get("lon"):
        result = geocode_entities(entities)
        if result:
            lat, lon, country_code = result
            geo["lat"] = lat
            geo["lon"] = lon
            if country_code and not geo.get("country_code"):
                geo["country_code"] = country_code
            if entities:
                geo["location_name"] = entities[0]
            event["geo"] = geo

    # 3. Classify
    event_type, confidence = classify_text(text)
    event["event_type"] = event_type
    event["confidence"] = confidence

    # 4. Severity
    event["severity"] = _compute_severity(event)

    return event


class SentinelConsumer:
    """Main event processor — consumes from Kafka, processes, sinks to Cassandra."""

    def __init__(
        self,
        bootstrap_servers: str = None,
        topics: list = None,
        group_id: str = "sentinel-processor",
        enable_cassandra: bool = True,
    ):
        self._bootstrap_servers = bootstrap_servers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        )
        self._topics = topics or ALL_TOPICS
        self._group_id = group_id
        self._enable_cassandra = enable_cassandra

        self._consumer = None
        self._dedup = Deduplicator()
        self._sink = CassandraSink() if enable_cassandra else None
        self._running = False

        self._events_processed = 0
        self._events_dropped = 0
        self._start_time = None

    def start(self):
        """Initialize Kafka consumer and Cassandra sink."""
        self._consumer = KafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset="latest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=1000,
            max_poll_interval_ms=300000,
        )

        if self._sink:
            self._sink.connect()

        self._running = True
        self._start_time = time.time()
        logger.info(
            "Sentinel consumer started. Topics: %s, Cassandra: %s",
            self._topics,
            self._enable_cassandra,
        )

    def process_event(self, event: dict) -> dict:
        """Route an event through the appropriate processing path."""
        source = event.get("source", "")

        if source in STRUCTURED_SOURCES:
            return process_structured(event)
        elif source in UNSTRUCTURED_SOURCES:
            return process_unstructured(event)
        else:
            # Unknown source — try unstructured path
            logger.warning("Unknown source '%s', using unstructured path", source)
            return process_unstructured(event)

    def run(self, max_events: int = None):
        """
        Main consumer loop. Processes events until stopped or max_events reached.

        Args:
            max_events: Stop after processing this many events (None = run forever).
        """
        self.start()

        try:
            while self._running:
                # Poll for messages
                for message in self._consumer:
                    if not self._running:
                        break

                    try:
                        event = message.value

                        # Dedup check
                        if self._dedup.is_duplicate(event):
                            self._events_dropped += 1
                            continue

                        # Process
                        enriched = self.process_event(event)

                        # Sink to Cassandra
                        if self._sink:
                            self._sink.write(enriched)

                        self._events_processed += 1

                        if self._events_processed % 50 == 0:
                            self._log_stats()

                        if max_events and self._events_processed >= max_events:
                            logger.info("Reached max_events=%d, stopping.", max_events)
                            self._running = False
                            break

                    except Exception as e:
                        logger.error("Error processing event: %s", e, exc_info=True)

                if max_events and self._events_processed >= max_events:
                    break

        except KeyboardInterrupt:
            logger.info("Consumer interrupted by user.")
        finally:
            self.stop()

    def stop(self):
        """Gracefully shut down consumer and sink."""
        self._running = False
        if self._consumer:
            self._consumer.close()
        if self._sink:
            self._sink.close()
        self._log_stats()
        logger.info("Sentinel consumer stopped.")

    def _log_stats(self):
        elapsed = time.time() - self._start_time if self._start_time else 0
        rate = self._events_processed / elapsed if elapsed > 0 else 0
        logger.info(
            "Consumer stats: processed=%d, dropped=%d, rate=%.1f events/sec, "
            "dedup=%s, geocoder=%s",
            self._events_processed,
            self._events_dropped,
            rate,
            self._dedup.get_stats(),
            "N/A",
        )

    def get_stats(self) -> dict:
        return {
            "events_processed": self._events_processed,
            "events_dropped": self._events_dropped,
            "dedup": self._dedup.get_stats(),
            "sink": self._sink.get_stats() if self._sink else {},
        }


def main():
    """Entry point for running the consumer standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    consumer = SentinelConsumer()

    # Graceful shutdown on SIGINT/SIGTERM
    def handle_signal(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        consumer.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    consumer.run()


if __name__ == "__main__":
    main()
