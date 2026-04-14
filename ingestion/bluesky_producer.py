"""Bluesky firehose Kafka producer — keyword-filtered, rate-limited."""

import logging
import threading
import time
from datetime import datetime, timezone

from ingestion.base_producer import BaseProducer
from ingestion.config import (
    BLUESKY_MAX_EVENTS_PER_MIN,
    CONFLICT_KEYWORDS,
    KAFKA_TOPICS,
)

logger = logging.getLogger(__name__)

# Pre-build lower-cased keyword list for substring matching.
# Some keywords are multi-word (e.g. "air strike"), so we need substring search.
_KEYWORDS_LOWER = [kw.lower() for kw in CONFLICT_KEYWORDS]

# How long each poll() call listens to the firehose (seconds).
_BATCH_WINDOW_SECONDS = 30


def _text_matches(text: str) -> bool:
    """Return True if *text* contains at least one conflict keyword."""
    lowered = text.lower()
    return any(kw in lowered for kw in _KEYWORDS_LOWER)


# ---------------------------------------------------------------------------
# Lazy import helpers — resolved once at first poll()
# ---------------------------------------------------------------------------
_atproto_available: bool | None = None
_FirehoseSubscribeReposClient = None
_parse_subscribe_repos_message = None
_CAR = None


def _ensure_atproto() -> bool:
    """Try to import atproto firehose utilities.  Returns True on success."""
    global _atproto_available, _FirehoseSubscribeReposClient
    global _parse_subscribe_repos_message, _CAR

    if _atproto_available is not None:
        return _atproto_available

    try:
        from atproto import (  # type: ignore[import-untyped]
            FirehoseSubscribeReposClient,
            parse_subscribe_repos_message,
            CAR,
        )
        _FirehoseSubscribeReposClient = FirehoseSubscribeReposClient
        _parse_subscribe_repos_message = parse_subscribe_repos_message
        _CAR = CAR
        _atproto_available = True
    except ImportError:
        logger.warning(
            "[bluesky] 'atproto' package not installed or import failed. "
            "Install with: pip install atproto"
        )
        _atproto_available = False

    return _atproto_available


class BlueskyProducer(BaseProducer):
    """Consumes the Bluesky firehose, keyword-filters posts, and emits to Kafka."""

    # ------------------------------------------------------------------ #
    # BaseProducer interface
    # ------------------------------------------------------------------ #

    @property
    def source_name(self) -> str:
        return "bluesky"

    @property
    def topic(self) -> str:
        return KAFKA_TOPICS["bluesky"]

    def poll(self) -> None:
        """Connect to the firehose for a batch window and emit matching posts.

        The firehose client is blocking, so we run it in a background thread
        and collect events into a shared list.  After *_BATCH_WINDOW_SECONDS*
        (or once the per-minute rate cap is hit) we stop the client and return.
        """
        if not _ensure_atproto():
            return

        collected: list[dict] = []
        stop_event = threading.Event()

        # Rate-limit bookkeeping
        rate_lock = threading.Lock()
        rate_state = {"window_start": time.monotonic(), "count": 0}

        def _on_message(message) -> None:  # noqa: ANN001
            """Callback invoked for every firehose message."""
            if stop_event.is_set():
                return

            # Reset rate-limit window every 60 seconds
            with rate_lock:
                now = time.monotonic()
                if now - rate_state["window_start"] >= 60:
                    rate_state["window_start"] = now
                    rate_state["count"] = 0

                if rate_state["count"] >= BLUESKY_MAX_EVENTS_PER_MIN:
                    return  # rate cap — skip until window resets

            try:
                commit = _parse_subscribe_repos_message(message)
                if not hasattr(commit, "ops") or commit.ops is None:
                    return

                for op in commit.ops:
                    if stop_event.is_set():
                        return
                    if op.action != "create":
                        continue
                    if not op.path.startswith("app.bsky.feed.post"):
                        continue

                    # Decode the CAR block to get the record
                    try:
                        car = _CAR.from_bytes(commit.blocks)
                    except Exception:
                        continue

                    # op.path is "app.bsky.feed.post/{rkey}" — extract rkey so we
                    # can build a real bsky.app URL for click-through.
                    rkey = op.path.split("/", 1)[1] if "/" in op.path else None
                    post_url = (
                        f"https://bsky.app/profile/{commit.repo}/post/{rkey}"
                        if rkey and commit.repo
                        else None
                    )

                    for _cid, block in car.blocks.items():
                        if not isinstance(block, dict):
                            continue
                        text = block.get("text")
                        if not text or not isinstance(text, str):
                            continue
                        if not _text_matches(text):
                            continue

                        event = self.normalize(
                            raw_text=text,
                            title=None,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            source_url=post_url,
                            metadata={"did": commit.repo, "rkey": rkey},
                        )
                        collected.append(event)

                        with rate_lock:
                            rate_state["count"] += 1
                            if rate_state["count"] >= BLUESKY_MAX_EVENTS_PER_MIN:
                                return
            except Exception:
                # Malformed or unexpected message — skip silently.
                pass

        # -------------------------------------------------------------- #
        # Run the firehose in a daemon thread for the batch window.
        # -------------------------------------------------------------- #
        client = _FirehoseSubscribeReposClient()

        def _run_client() -> None:
            try:
                client.start(_on_message)
            except Exception:
                if not stop_event.is_set():
                    logger.exception("[bluesky] Firehose client error")

        thread = threading.Thread(target=_run_client, daemon=True)
        thread.start()

        logger.info(
            "[bluesky] Listening to firehose for %ds (max %d events/min)",
            _BATCH_WINDOW_SECONDS,
            BLUESKY_MAX_EVENTS_PER_MIN,
        )

        # Wait for the batch window to expire.
        stop_event.wait(timeout=_BATCH_WINDOW_SECONDS)

        # Signal the handler to stop, then tear down the client.
        stop_event.set()
        try:
            client.stop()
        except Exception:
            pass
        thread.join(timeout=5)

        # Emit all collected events to Kafka.
        for event in collected:
            self.emit(event)

        logger.info("[bluesky] Poll complete — emitted %d events", len(collected))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    producer = BlueskyProducer()
    # Bluesky poll() runs a 30s batch window internally; loop every 5s between batches
    producer.run(interval=5)
