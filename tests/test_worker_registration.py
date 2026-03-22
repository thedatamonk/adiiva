# tests/test_worker_registration.py
import pytest
import pytest_asyncio
import json
import redis.asyncio as redis

REDIS_URL = "redis://localhost:6379"

@pytest_asyncio.fixture
async def redis_client():
    client = redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()

@pytest.mark.asyncio
async def test_worker_register_and_deregister(redis_client):
    """Worker registration writes correct data to Redis and deregister cleans up."""
    from src.worker import register_worker, deregister_worker

    session_id = "test-session-123"
    port = 9001
    user_id = "alice"

    await register_worker(redis_client, session_id, port, user_id)

    key = f"worker:{session_id}"
    raw = await redis_client.get(key)
    assert raw is not None
    data = json.loads(raw)
    assert data["port"] == port
    assert data["user_id"] == user_id
    assert data["status"] == "ready"

    ttl = await redis_client.ttl(key)
    assert ttl > 0

    await deregister_worker(redis_client, session_id)
    assert await redis_client.get(key) is None
