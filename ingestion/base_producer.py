"""Abstract base Kafka producer with schema normalization, retry logic, and structured logging."""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError

from ingestion.config import KAFKA_BOOTSTRAP_SERVERS

logger = logging.getLogger(__name__)


class BaseProducer(ABC):
    """Base class for all Sentinel data source producers.

    Subclasses must implement:
        - source_name: str property
        - topic: str property
        - poll() -> None: fetch data and call self.emit() for each event
    """

    def __init__(self, bootstrap_servers: str | None = None):
        self._servers = bootstrap_servers or KAFKA_BOOTSTRAP_SERVERS
        self._producer: KafkaProducer | None = None

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier for this data source (e.g. 'gdelt', 'acled')."""
        ...

    @property
    @abstractmethod
    def topic(self) -> str:
        """Kafka topic to publish to."""
        ...

    @abstractmethod
    def poll(self) -> None:
        """Fetch data from the source and call self.emit() for each event."""
        ...

    # ------------------------------------------------------------------
    # Kafka connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initialize the Kafka producer connection."""
        if self._producer is not None:
            return
        self._producer = KafkaProducer(
            bootstrap_servers=self._servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            retries=3,
            retry_backoff_ms=500,
            request_timeout_ms=15000,
            acks="all",
        )
        logger.info("[%s] Connected to Kafka at %s", self.source_name, self._servers)

    def close(self) -> None:
        """Flush and close the Kafka producer."""
        if self._producer:
            self._producer.flush(timeout=10)
            self._producer.close(timeout=10)
            self._producer = None
            logger.info("[%s] Producer closed", self.source_name)

    # ------------------------------------------------------------------
    # Schema normalization + emit
    # ------------------------------------------------------------------

    def normalize(
        self,
        raw_text: str,
        title: str | None = None,
        timestamp: str | None = None,
        source_url: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        country_code: str | None = None,
        location_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a unified-schema event dict."""
        return {
            "event_id": str(uuid.uuid4()),
            "source": self.source_name,
            "raw_text": raw_text,
            "title": title,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "geo": {
                "lat": lat,
                "lon": lon,
                "country_code": country_code,
                "location_name": location_name,
            },
            "metadata": metadata or {},
        }

    def emit(self, event: dict[str, Any]) -> None:
        """Publish a normalized event to Kafka."""
        if self._producer is None:
            self.connect()
        try:
            self._producer.send(self.topic, value=event)  # type: ignore[union-attr]
            logger.debug(
                "[%s] Emitted event %s", self.source_name, event.get("event_id", "?")
            )
        except KafkaError:
            logger.exception("[%s] Failed to emit event", self.source_name)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """Connect (if needed), poll once, and flush."""
        self.connect()
        try:
            self.poll()
            if self._producer:
                self._producer.flush(timeout=10)
        except Exception:
            logger.exception("[%s] Error during poll", self.source_name)

    def run(self, interval: float | None = None) -> None:
        """Run the producer in a loop with the given interval (seconds).

        If interval is None, runs poll() once and returns.
        """
        import time

        self.connect()
        try:
            if interval is None:
                self.poll()
                return
            logger.info("[%s] Starting poll loop (every %ss)", self.source_name, interval)
            while True:
                try:
                    self.poll()
                    if self._producer:
                        self._producer.flush(timeout=10)
                except Exception:
                    logger.exception("[%s] Error during poll cycle", self.source_name)
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("[%s] Shutting down", self.source_name)
        finally:
            self.close()
