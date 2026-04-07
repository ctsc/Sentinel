"""
PyFlink wrapper for the NLP processing pipeline.

Phase 5 production path — wraps the same NLP code (ner.py, classifier.py,
geocoder.py) inside a Flink job for proper stream processing metrics.

Falls back to the plain Python consumer if Flink causes issues.
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


def build_flink_job():
    """Build and execute the PyFlink streaming job."""
    try:
        from pyflink.datastream import StreamExecutionEnvironment
        from pyflink.common.serialization import SimpleStringSchema
        from pyflink.datastream.connectors.kafka import (
            KafkaSource,
            KafkaOffsetsInitializer,
            KafkaSink,
            KafkaRecordSerializationSchema,
        )
    except ImportError:
        logger.error(
            "PyFlink not installed. Install with: pip install apache-flink. "
            "Falling back to Python consumer."
        )
        from processing.consumer import main as consumer_main
        consumer_main()
        return

    from processing.consumer import process_structured, process_unstructured
    from processing.dedup import Deduplicator
    from processing.sink import CassandraSink

    kafka_brokers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # Create Flink environment
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(2)
    env.enable_checkpointing(60000)  # checkpoint every 60 seconds

    # Define Kafka source for all sentinel topics
    topics = [
        "sentinel.raw.gdelt",
        "sentinel.raw.acled",
        "sentinel.raw.rss",
        "sentinel.raw.bluesky",
        "sentinel.raw.wikipedia",
    ]

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(kafka_brokers)
        .set_topics(*topics)
        .set_group_id("sentinel-flink-processor")
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    # Build the processing pipeline
    stream = env.from_source(source, watermark_strategy=None, source_name="kafka-source")

    # Process events using the same NLP logic as the Python consumer
    dedup = Deduplicator()
    sink = CassandraSink()
    sink.connect()

    def process_event(raw_json: str) -> str:
        """Process a single event — same logic as consumer.py."""
        try:
            event = json.loads(raw_json)

            # Dedup
            if dedup.is_duplicate(event):
                return ""

            # Route through appropriate processing path
            source_name = event.get("source", "")
            if source_name in ("gdelt", "acled"):
                enriched = process_structured(event)
            else:
                enriched = process_unstructured(event)

            # Sink to Cassandra
            sink.write(enriched)

            return json.dumps(enriched)

        except Exception as e:
            logger.error("Flink processing error: %s", e)
            return ""

    # Apply the processing function
    processed = stream.map(process_event)

    # Execute
    logger.info("Starting Flink job: sentinel-nlp-processor")
    env.execute("sentinel-nlp-processor")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    build_flink_job()


if __name__ == "__main__":
    main()
