"""
Sentinel unified runner -- starts all producers, the NLP consumer, and the
FastAPI API server in a single process using daemon threads.

Usage:
    python run_all.py
"""

import logging
import os
import signal
import sys
import threading
import time

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(threadName)s] %(levelname)-8s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("sentinel.runner")

# ---------------------------------------------------------------------------
# Shutdown flag (shared across all threads)
# ---------------------------------------------------------------------------

shutdown_event = threading.Event()

# ---------------------------------------------------------------------------
# Producer definitions
# ---------------------------------------------------------------------------

PRODUCERS = {
    "gdelt": {
        "module": "ingestion.gdelt_producer",
        "class": "GdeltProducer",
        "interval_config": "GDELT_POLL_INTERVAL",
    },
    "acled": {
        "module": "ingestion.acled_producer",
        "class": "ACLEDProducer",
        "interval_config": "ACLED_POLL_INTERVAL",
    },
    "rss": {
        "module": "ingestion.rss_producer",
        "class": "RSSProducer",
        "interval_config": "RSS_POLL_INTERVAL",
    },
    "bluesky": {
        "module": "ingestion.bluesky_producer",
        "class": "BlueskyProducer",
        "interval": 5,  # poll() has internal 30s batch window
    },
    "wikipedia": {
        "module": "ingestion.wikipedia_producer",
        "class": "WikipediaProducer",
        "interval": 5,  # poll() does internal SSE batching
    },
}

MAX_RESTARTS = 3
RESTART_DELAY = 30  # seconds

# ---------------------------------------------------------------------------
# Thread wrappers
# ---------------------------------------------------------------------------


def _run_producer(name: str, spec: dict, restart_counts: dict) -> None:
    """Import, instantiate, and run a single producer in a loop that respects
    the global shutdown_event.  This replaces BaseProducer.run() so we can
    check the shutdown flag between poll cycles."""
    import importlib

    mod = importlib.import_module(spec["module"])
    cls = getattr(mod, spec["class"])

    # Resolve poll interval
    if "interval" in spec:
        interval = spec["interval"]
    else:
        from ingestion import config as cfg
        interval = getattr(cfg, spec["interval_config"])

    producer = cls()
    try:
        producer.connect()
    except Exception:
        logger.exception("[%s] Failed to connect to Kafka", name)
        return

    logger.info("[%s] Producer started (poll every %ss)", name, interval)

    try:
        while not shutdown_event.is_set():
            try:
                producer.poll()
                if producer._producer:
                    producer._producer.flush(timeout=10)
            except Exception:
                logger.exception("[%s] Error during poll cycle", name)
            # Sleep in small increments so we can respond to shutdown quickly
            _interruptible_sleep(interval)
    finally:
        try:
            producer.close()
        except Exception:
            pass
        logger.info("[%s] Producer stopped", name)


def _run_producer_with_restarts(name: str, spec: dict, restart_counts: dict) -> None:
    """Wrapper that restarts a producer up to MAX_RESTARTS times on crash."""
    while not shutdown_event.is_set():
        try:
            _run_producer(name, spec, restart_counts)
            # If _run_producer returns cleanly (shutdown requested), exit
            if shutdown_event.is_set():
                return
        except Exception:
            logger.exception("[%s] Producer thread crashed", name)

        restart_counts[name] = restart_counts.get(name, 0) + 1
        count = restart_counts[name]

        if count > MAX_RESTARTS:
            logger.error(
                "[%s] Exceeded max restarts (%d). Giving up.", name, MAX_RESTARTS
            )
            return

        logger.warning(
            "[%s] Will restart in %ds (attempt %d/%d)",
            name, RESTART_DELAY, count, MAX_RESTARTS,
        )
        # Interruptible wait for restart delay
        _interruptible_sleep(RESTART_DELAY)


def _run_consumer() -> None:
    """Run the Sentinel NLP consumer."""
    from processing.consumer import SentinelConsumer

    consumer = SentinelConsumer()
    try:
        consumer.start()
    except Exception:
        logger.exception("[consumer] Failed to start consumer")
        return

    logger.info("[consumer] Consumer started")

    try:
        while not shutdown_event.is_set():
            try:
                # Poll manually rather than calling consumer.run() which has
                # its own infinite loop.  consumer._consumer is the KafkaConsumer
                # and iterating over it respects consumer_timeout_ms (1000ms).
                for message in consumer._consumer:
                    if shutdown_event.is_set():
                        break
                    try:
                        consumer._process_message(message)
                    except AttributeError:
                        # _process_message may not exist -- fall back to inline
                        _consumer_process_message(consumer, message)
            except Exception:
                if shutdown_event.is_set():
                    break
                logger.exception("[consumer] Error in consumer loop")
                _interruptible_sleep(5)
    finally:
        try:
            consumer.stop()
        except Exception:
            pass
        logger.info("[consumer] Consumer stopped")


def _consumer_process_message(consumer, message) -> None:
    """Replicate the inner loop from SentinelConsumer.run() without the
    outer while/KeyboardInterrupt handling."""
    from processing.consumer import _is_fresh, _is_english

    event = message.value

    if not _is_fresh(event):
        consumer._events_dropped += 1
        return

    text = (event.get("title") or "") + " " + (event.get("raw_text") or "")
    if not _is_english(text):
        consumer._events_dropped += 1
        return

    if consumer._dedup.is_duplicate(event):
        consumer._events_dropped += 1
        return

    enriched = consumer.process_event(event)

    if consumer._sink:
        consumer._sink.write(enriched)

    if consumer._producer:
        try:
            consumer._producer.send("sentinel.enriched", value=enriched)
        except Exception as e:
            logger.debug("Failed to publish enriched event: %s", e)

    consumer._events_processed += 1

    if consumer._events_processed % 50 == 0:
        consumer._log_stats()


def _run_api() -> None:
    """Run the FastAPI server via uvicorn."""
    import uvicorn

    logger.info("[api] Starting uvicorn on 0.0.0.0:8000")
    try:
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
            # Disable uvicorn signal handlers -- we handle signals ourselves
            # This avoids conflicts on Windows
        )
    except Exception:
        if not shutdown_event.is_set():
            logger.exception("[api] Uvicorn crashed")
    finally:
        logger.info("[api] API server stopped")


def _run_health_monitor(threads: dict) -> None:
    """Periodically log which threads are alive and which have died."""
    while not shutdown_event.is_set():
        _interruptible_sleep(60)
        if shutdown_event.is_set():
            break

        alive = []
        dead = []
        for name, t in threads.items():
            if t.is_alive():
                alive.append(name)
            else:
                dead.append(name)

        alive_str = ", ".join(sorted(alive)) if alive else "(none)"
        dead_str = ", ".join(sorted(dead)) if dead else "(none)"
        logger.info("[monitor] Alive: %s | Dead: %s", alive_str, dead_str)


def _interruptible_sleep(seconds: float) -> None:
    """Sleep for up to *seconds*, waking early if shutdown_event is set."""
    shutdown_event.wait(timeout=seconds)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _setup_signal_handlers() -> None:
    """Register handlers for SIGINT and SIGTERM to trigger graceful shutdown."""

    def _handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received %s -- initiating graceful shutdown", sig_name)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)

    # SIGTERM doesn't exist on Windows
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _setup_signal_handlers()

    logger.info("=" * 60)
    logger.info("  SENTINEL -- Unified Runner")
    logger.info("=" * 60)

    threads: dict[str, threading.Thread] = {}
    restart_counts: dict[str, int] = {}

    # 1. Start API server first (so WebSocket is ready)
    api_thread = threading.Thread(
        target=_run_api, name="api", daemon=True
    )
    api_thread.start()
    threads["api"] = api_thread
    logger.info("[startup] API server thread started")

    # Brief pause to let uvicorn bind its port
    time.sleep(2)

    # 2. Start consumer
    consumer_thread = threading.Thread(
        target=_run_consumer, name="consumer", daemon=True
    )
    consumer_thread.start()
    threads["consumer"] = consumer_thread
    logger.info("[startup] Consumer thread started")

    # 3. Wait before starting producers (let consumer connect to Kafka first)
    time.sleep(5)

    # 4. Start producers
    for name, spec in PRODUCERS.items():
        # Skip ACLED if credentials are missing
        if name == "acled":
            acled_email = os.getenv("ACLED_EMAIL", "")
            acled_password = os.getenv("ACLED_PASSWORD", "")
            if not acled_email or not acled_password:
                logger.warning(
                    "[startup] ACLED credentials not set (ACLED_EMAIL / ACLED_PASSWORD). "
                    "Skipping ACLED producer."
                )
                continue

        t = threading.Thread(
            target=_run_producer_with_restarts,
            args=(name, spec, restart_counts),
            name=name,
            daemon=True,
        )
        t.start()
        threads[name] = t
        logger.info("[startup] Producer '%s' thread started", name)

    # 5. Start health monitor
    monitor_thread = threading.Thread(
        target=_run_health_monitor,
        args=(threads,),
        name="monitor",
        daemon=True,
    )
    monitor_thread.start()

    logger.info("=" * 60)
    logger.info("  All services started.  Press Ctrl+C to stop.")
    logger.info("=" * 60)

    # 6. Wait for shutdown signal
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        shutdown_event.set()

    logger.info("Shutdown flag set -- waiting for threads to finish...")

    # Give threads a few seconds to clean up
    deadline = time.time() + 10
    for name, t in threads.items():
        remaining = max(0, deadline - time.time())
        t.join(timeout=remaining)
        if t.is_alive():
            logger.warning("[shutdown] Thread '%s' did not stop in time", name)
        else:
            logger.info("[shutdown] Thread '%s' stopped", name)

    logger.info("Sentinel runner exited.")


if __name__ == "__main__":
    main()
