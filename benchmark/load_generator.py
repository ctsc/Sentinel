"""
Synthetic load generator for benchmarking.

Generates events at configurable throughput tiers:
  1×  = baseline (~10 events/sec)
  5×  = moderate (~50 events/sec)
  10× = heavy (~100 events/sec)
  25× = stress (~250 events/sec)
  50× = saturation (~500 events/sec)
"""

import argparse
import json
import logging
import random
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer

logger = logging.getLogger(__name__)

BASELINE_RATE = 10  # events per second

TIERS = {
    "1x": 1,
    "5x": 5,
    "10x": 10,
    "25x": 25,
    "50x": 50,
}

SOURCES = ["gdelt", "acled", "rss", "bluesky", "wikipedia"]
EVENT_TYPES = ["conflict", "protest", "disaster", "political", "terrorism", "other"]

SAMPLE_LOCATIONS = [
    {"lat": 50.45, "lon": 30.52, "country_code": "UA", "location_name": "Kyiv"},
    {"lat": 31.35, "lon": 34.31, "country_code": "PS", "location_name": "Gaza"},
    {"lat": 15.50, "lon": 32.56, "country_code": "SD", "location_name": "Khartoum"},
    {"lat": 33.51, "lon": 36.28, "country_code": "SY", "location_name": "Damascus"},
    {"lat": 33.32, "lon": 44.37, "country_code": "IQ", "location_name": "Baghdad"},
    {"lat": 2.05, "lon": 45.32, "country_code": "SO", "location_name": "Mogadishu"},
    {"lat": 34.55, "lon": 69.21, "country_code": "AF", "location_name": "Kabul"},
    {"lat": 9.03, "lon": 38.75, "country_code": "ET", "location_name": "Addis Ababa"},
    {"lat": 6.52, "lon": 3.38, "country_code": "NG", "location_name": "Lagos"},
    {"lat": -1.68, "lon": 29.23, "country_code": "CD", "location_name": "Goma"},
    {"lat": 36.20, "lon": 37.13, "country_code": "SY", "location_name": "Aleppo"},
    {"lat": 15.37, "lon": 44.19, "country_code": "YE", "location_name": "Sanaa"},
    {"lat": 48.60, "lon": 38.00, "country_code": "UA", "location_name": "Bakhmut"},
    {"lat": 25.03, "lon": 121.57, "country_code": "TW", "location_name": "Taipei"},
    {"lat": 39.90, "lon": 116.41, "country_code": "CN", "location_name": "Beijing"},
]

SAMPLE_TITLES = [
    "Military offensive launched in {location}",
    "Protests erupt across {location}",
    "Explosion reported near {location} center",
    "Ceasefire negotiations underway in {location}",
    "Humanitarian crisis deepens in {location}",
    "Armed clashes reported on the outskirts of {location}",
    "UN condemns violence in {location}",
    "Drone strike hits target near {location}",
    "Mass displacement reported from {location}",
    "Earthquake strikes near {location}",
]

TOPICS = {
    "gdelt": "sentinel.raw.gdelt",
    "acled": "sentinel.raw.acled",
    "rss": "sentinel.raw.rss",
    "bluesky": "sentinel.raw.bluesky",
    "wikipedia": "sentinel.raw.wikipedia",
}


def generate_event() -> dict:
    """Generate a single synthetic event."""
    source = random.choice(SOURCES)
    location = random.choice(SAMPLE_LOCATIONS)
    title_template = random.choice(SAMPLE_TITLES)
    title = title_template.format(location=location["location_name"])

    return {
        "event_id": str(uuid.uuid4()),
        "source": source,
        "raw_text": f"{title}. Detailed report follows with additional context.",
        "title": title,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_url": f"https://example.com/article/{uuid.uuid4().hex[:8]}",
        "geo": {
            "lat": location["lat"] + random.uniform(-0.5, 0.5),
            "lon": location["lon"] + random.uniform(-0.5, 0.5),
            "country_code": location["country_code"],
            "location_name": location["location_name"],
        },
        "metadata": {
            "synthetic": True,
            "event_type": random.choice(EVENT_TYPES),
            "goldstein_scale": random.uniform(-10, 0) if source == "gdelt" else None,
            "fatalities": random.randint(0, 50) if source == "acled" else None,
        },
    }


def run_load_test(
    tier: str,
    duration_seconds: int = 120,
    bootstrap_servers: str = "localhost:9092",
):
    """Run load test at the specified tier."""
    multiplier = TIERS[tier]
    target_rate = BASELINE_RATE * multiplier
    interval = 1.0 / target_rate

    logger.info(
        "Starting load test: tier=%s, target_rate=%d events/sec, duration=%ds",
        tier, target_rate, duration_seconds,
    )

    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        batch_size=16384,
        linger_ms=10,
        retries=3,
    )

    events_sent = 0
    start_time = time.time()
    last_report = start_time

    try:
        while time.time() - start_time < duration_seconds:
            event = generate_event()
            topic = TOPICS[event["source"]]
            producer.send(topic, value=event)
            events_sent += 1

            # Rate limiting
            elapsed = time.time() - start_time
            expected_events = elapsed * target_rate
            if events_sent > expected_events:
                time.sleep(interval)

            # Progress report every 10 seconds
            now = time.time()
            if now - last_report >= 10:
                actual_rate = events_sent / (now - start_time)
                logger.info(
                    "Progress: %d events sent, actual_rate=%.1f events/sec",
                    events_sent, actual_rate,
                )
                last_report = now

    except KeyboardInterrupt:
        logger.info("Load test interrupted by user")
    finally:
        producer.flush()
        producer.close()

    elapsed = time.time() - start_time
    actual_rate = events_sent / elapsed if elapsed > 0 else 0

    results = {
        "tier": tier,
        "target_rate": target_rate,
        "actual_rate": round(actual_rate, 2),
        "events_sent": events_sent,
        "duration_seconds": round(elapsed, 2),
    }

    logger.info("Load test complete: %s", json.dumps(results, indent=2))
    return results


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Sentinel load generator")
    parser.add_argument(
        "--tier", choices=list(TIERS.keys()), default="1x",
        help="Load tier multiplier (default: 1x)",
    )
    parser.add_argument(
        "--duration", type=int, default=120,
        help="Test duration in seconds (default: 120)",
    )
    parser.add_argument(
        "--kafka", default="localhost:9092",
        help="Kafka bootstrap servers",
    )
    args = parser.parse_args()

    run_load_test(args.tier, args.duration, args.kafka)


if __name__ == "__main__":
    main()
