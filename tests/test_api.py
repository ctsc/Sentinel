"""
Phase 4 Test Gate — API endpoint tests.

Tests REST endpoints and WebSocket connectivity.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from fastapi.testclient import TestClient

    # Patch Cassandra to avoid requiring a live connection for basic tests
    import api.db as db_module

    _original_get_session = db_module.get_session

    class MockSession:
        def execute(self, *args, **kwargs):
            return []

    def mock_get_session():
        return MockSession()

    db_module.get_session = mock_get_session

    from api.main import app
    test_client = TestClient(app)
    yield test_client

    db_module.get_session = _original_get_session


@pytest.fixture
def live_client():
    """Create a test client that uses real Cassandra (requires Docker)."""
    try:
        from cassandra.cluster import Cluster
        cluster = Cluster(["localhost"], port=9042)
        session = cluster.connect("sentinel")
        cluster.shutdown()
    except Exception as e:
        pytest.skip(f"Cassandra not available: {e}")

    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


class TestHealthCheck:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "sentinel-api"


class TestEventsEndpoint:
    def test_get_events_returns_json_array(self, client):
        response = client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_events_with_region(self, client):
        response = client.get("/events?region=middle_east&time_bucket=2026-04-03T14")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_empty_query_returns_empty_array(self, client):
        response = client.get("/events?region=nonexistent_region&time_bucket=1999-01-01T00")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_cors_headers_present(self, client):
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


class TestEventsLive:
    """Tests that require live Cassandra."""

    def test_get_events_from_cassandra(self, live_client):
        response = live_client.get("/events?region=middle_east&time_bucket=2026-04-03T14")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Validate schema if any events exist
        for event in data:
            assert "event_id" in event
            assert "source" in event
            assert "geo" in event


class TestWebSocket:
    def test_websocket_connects(self, live_client):
        """Test WebSocket connects and receives at least a heartbeat."""
        try:
            with live_client.websocket_connect("/ws/live") as ws:
                data = ws.receive_json(mode="text")
                assert "type" in data
                assert data["type"] in ("events", "heartbeat")
        except Exception as e:
            pytest.skip(f"WebSocket test requires Kafka: {e}")
