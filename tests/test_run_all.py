"""
Tests for run_all.py — the unified Sentinel runner.

These tests verify the runner's orchestration logic (threading, shutdown,
health monitoring, restart) without requiring Docker, Kafka, or Cassandra.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Module imports without error
# ---------------------------------------------------------------------------

def test_run_all_imports():
    """run_all module imports without raising."""
    import run_all  # noqa: F401


def test_run_all_has_main():
    """run_all exposes a main() entry point."""
    from run_all import main
    assert callable(main)


def test_run_all_has_shutdown_event():
    """run_all exposes a threading.Event for coordinated shutdown."""
    from run_all import shutdown_event
    assert isinstance(shutdown_event, threading.Event)


# ---------------------------------------------------------------------------
# 2. Shutdown flag mechanism
# ---------------------------------------------------------------------------

def test_shutdown_event_is_clear_initially():
    """The shutdown event starts in an unset state."""
    from run_all import shutdown_event
    # Reset in case a prior test set it
    shutdown_event.clear()
    assert not shutdown_event.is_set()


def test_shutdown_event_stops_interruptible_sleep():
    """_interruptible_sleep returns early when shutdown_event is set."""
    from run_all import shutdown_event, _interruptible_sleep

    shutdown_event.clear()

    # Set the event after a short delay from another thread
    def _set_flag():
        time.sleep(0.1)
        shutdown_event.set()

    setter = threading.Thread(target=_set_flag, daemon=True)
    setter.start()

    start = time.time()
    _interruptible_sleep(60)  # would block 60s without the flag
    elapsed = time.time() - start

    assert elapsed < 2.0, f"Sleep took {elapsed:.1f}s, expected <2s"
    shutdown_event.clear()


def test_threads_see_shutdown_flag():
    """A worker thread checking shutdown_event observes the flag set from
    the main thread."""
    from run_all import shutdown_event

    shutdown_event.clear()
    saw_flag = threading.Event()

    def worker():
        while not shutdown_event.is_set():
            time.sleep(0.05)
        saw_flag.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    time.sleep(0.1)
    shutdown_event.set()
    saw_flag.wait(timeout=2)

    assert saw_flag.is_set(), "Worker thread did not observe shutdown flag"
    shutdown_event.clear()


# ---------------------------------------------------------------------------
# 3. Health monitor
# ---------------------------------------------------------------------------

def test_health_monitor_reports_alive_threads():
    """_run_health_monitor correctly classifies alive vs dead threads."""
    from run_all import shutdown_event, _run_health_monitor

    shutdown_event.clear()

    # Create a fake thread dict: one alive, one dead
    alive_thread = MagicMock()
    alive_thread.is_alive.return_value = True

    dead_thread = MagicMock()
    dead_thread.is_alive.return_value = False

    threads = {"gdelt": alive_thread, "bluesky": dead_thread}

    logged_messages = []

    with patch("run_all.logger") as mock_logger:
        def capture_info(msg, *args):
            logged_messages.append(msg % args)
        mock_logger.info.side_effect = capture_info

        # Run monitor in a thread; let it emit one report then shut down
        def run_monitor():
            _run_health_monitor(threads)

        # Override sleep to be very short
        original_sleep = time.sleep
        shutdown_timer = threading.Timer(0.3, shutdown_event.set)
        shutdown_timer.start()

        with patch("run_all._interruptible_sleep") as mock_sleep:
            # First call: the 60s interval -- return immediately
            # Second call (after logging): trigger shutdown
            call_count = [0]
            def fast_sleep(secs):
                call_count[0] += 1
                if call_count[0] >= 2:
                    shutdown_event.set()
                    return
                # Just wait a tiny bit
                time.sleep(0.01)
            mock_sleep.side_effect = fast_sleep

            _run_health_monitor(threads)

    shutdown_event.clear()

    # Check that at least one log message contains the expected names
    monitor_msgs = [m for m in logged_messages if "Alive:" in m]
    assert len(monitor_msgs) >= 1, f"No monitor messages found. Got: {logged_messages}"
    msg = monitor_msgs[0]
    assert "gdelt" in msg
    assert "bluesky" in msg
    assert "Alive:" in msg
    assert "Dead:" in msg


# ---------------------------------------------------------------------------
# 4. Producer restart logic
# ---------------------------------------------------------------------------

def test_producer_restart_on_crash():
    """If a producer crashes, _run_producer_with_restarts retries up to
    MAX_RESTARTS times."""
    from run_all import shutdown_event

    shutdown_event.clear()

    call_count = [0]

    # Patch _run_producer to raise on the first 2 calls, then succeed
    def mock_run_producer(name, spec, restart_counts):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise RuntimeError(f"Simulated crash #{call_count[0]}")
        # On the 3rd call, pretend shutdown was requested
        shutdown_event.set()

    with patch("run_all._run_producer", side_effect=mock_run_producer), \
         patch("run_all.RESTART_DELAY", 0.01), \
         patch("run_all._interruptible_sleep", lambda s: time.sleep(min(s, 0.01))):

        from run_all import _run_producer_with_restarts

        restart_counts: dict[str, int] = {}
        _run_producer_with_restarts("test_producer", {}, restart_counts)

    shutdown_event.clear()

    # Should have been called 3 times: 2 crashes + 1 clean run
    assert call_count[0] == 3
    # restart_counts should show 2 restarts
    assert restart_counts["test_producer"] == 2


def test_producer_gives_up_after_max_restarts():
    """After MAX_RESTARTS crashes, the producer thread stops trying."""
    from run_all import shutdown_event, MAX_RESTARTS

    shutdown_event.clear()

    call_count = [0]

    def mock_run_producer(name, spec, restart_counts):
        call_count[0] += 1
        raise RuntimeError("Always crash")

    with patch("run_all._run_producer", side_effect=mock_run_producer), \
         patch("run_all.RESTART_DELAY", 0.01), \
         patch("run_all._interruptible_sleep", lambda s: time.sleep(min(s, 0.01))):

        from run_all import _run_producer_with_restarts

        restart_counts: dict[str, int] = {}
        _run_producer_with_restarts("crash_producer", {}, restart_counts)

    shutdown_event.clear()

    # Initial run + MAX_RESTARTS retries = MAX_RESTARTS + 1 calls total
    assert call_count[0] == MAX_RESTARTS + 1
    assert restart_counts["crash_producer"] == MAX_RESTARTS + 1


# ---------------------------------------------------------------------------
# 5. Signal handler setup
# ---------------------------------------------------------------------------

def test_setup_signal_handlers_does_not_raise():
    """Signal handler registration works on the current platform."""
    from run_all import _setup_signal_handlers, shutdown_event
    shutdown_event.clear()
    # Should not raise even on Windows (SIGTERM handled with try/except)
    _setup_signal_handlers()


# ---------------------------------------------------------------------------
# 6. ACLED skip when credentials missing
# ---------------------------------------------------------------------------

def test_acled_skipped_without_credentials():
    """When ACLED_EMAIL/ACLED_PASSWORD are empty, the ACLED producer should
    not be started."""
    from run_all import shutdown_event

    shutdown_event.clear()

    started_producers = []

    with patch.dict("os.environ", {"ACLED_EMAIL": "", "ACLED_PASSWORD": ""}, clear=False), \
         patch("run_all._run_api"), \
         patch("run_all._run_consumer"), \
         patch("run_all._run_health_monitor"), \
         patch("run_all.threading") as mock_threading:

        mock_thread = MagicMock()
        mock_threading.Thread.return_value = mock_thread
        mock_threading.Event = threading.Event

        # Track which Thread() calls are made
        thread_names = []
        original_thread = threading.Thread

        def track_thread(*args, **kwargs):
            name = kwargs.get("name", "")
            thread_names.append(name)
            t = MagicMock()
            t.is_alive.return_value = True
            return t

        mock_threading.Thread.side_effect = track_thread

        # Run main but shut down almost immediately
        shutdown_event.set()

        from run_all import main
        main()

    shutdown_event.clear()

    assert "acled" not in thread_names, (
        f"ACLED thread should not have been created. Threads: {thread_names}"
    )
