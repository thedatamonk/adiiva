# tests/test_integration.py
"""
Integration test: gateway spawns worker, worker registers, gateway returns URL.
Does NOT test actual audio — just the spawn/register/respond flow.
"""
import pytest
import pytest_asyncio
import json

import redis.asyncio as redis
from fastapi.testclient import TestClient


REDIS_URL = "redis://localhost:6379"


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset cached Redis connections in gateway and rate_limiter between tests.
    These modules cache a global Redis client that becomes stale across
    different async event loops."""
    import src.app as app_mod
    import src.rate_limiter as rl_mod

    old_app_redis = app_mod._redis
    old_rl_redis = rl_mod._redis

    app_mod._redis = None
    rl_mod._redis = None

    yield

    app_mod._redis = None
    rl_mod._redis = None


@pytest_asyncio.fixture
async def redis_client():
    client = redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    # Cleanup all test keys
    async for key in client.scan_iter("worker:*"):
        await client.delete(key)
    async for key in client.scan_iter("metrics:*"):
        await client.delete(key)
    async for key in client.scan_iter("user:*:sessions"):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
def gateway_client():
    from src.app import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_full_connect_flow(gateway_client, redis_client):
    """Gateway spawns a real worker, worker registers, gateway returns worker_url."""
    from src.auth import create_token

    token = create_token("alice")
    resp = gateway_client.post("/connect", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    data = resp.json()
    assert "worker_url" in data
    assert "session_id" in data

    # Verify worker registered in Redis
    session_id = data["session_id"]
    raw = await redis_client.get(f"worker:{session_id}")
    assert raw is not None
    worker_data = json.loads(raw)
    assert worker_data["status"] == "ready"
    assert worker_data["user_id"] == "alice"


@pytest.mark.asyncio
async def test_connect_returns_valid_websocket_url(gateway_client, redis_client):
    """The worker_url returned by /connect is a valid WebSocket URL."""
    from src.auth import create_token

    token = create_token("alice")
    resp = gateway_client.post("/connect", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["worker_url"].startswith("ws://")
    # URL should contain a port number
    parts = data["worker_url"].rsplit(":", 1)
    assert len(parts) == 2
    port = int(parts[1])
    assert 9000 <= port <= 65535
