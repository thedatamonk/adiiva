"""
Integration tests for rate_limiter against a real Redis instance.

Verifies:
1. Acquire up to limit, reject beyond it
2. Release frees a slot
3. TTL expiry unblocks users
4. Concurrent acquires never exceed the limit (race condition check)
"""

import asyncio
import uuid

import pytest
import pytest_asyncio

import src.rate_limiter as rl
from src.rate_limiter import (
    acquire_session_slot,
    get_redis,
    release_session_slot,
    refresh_session_ttl,
    MAX_CONCURRENT_SESSIONS,
)


def _sid():
    return str(uuid.uuid4())


@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis():
    """Reset the global Redis connection and wipe test keys before/after each test."""
    # Force a fresh connection for this event loop
    if rl._redis is not None:
        await rl._redis.aclose()
        rl._redis = None

    r = await get_redis()
    for user in ("test_user", "race_user"):
        await r.delete(f"user:{user}:sessions")
    yield
    for user in ("test_user", "race_user"):
        await r.delete(f"user:{user}:sessions")
    await rl._redis.aclose()
    rl._redis = None


@pytest.mark.asyncio
async def test_acquire_up_to_limit():
    """Should allow exactly MAX_CONCURRENT_SESSIONS, then reject."""
    results = []
    for _ in range(MAX_CONCURRENT_SESSIONS):
        results.append(await acquire_session_slot("test_user", _sid()))
    assert all(results), "All slots within limit should be acquired"

    # Next one should be rejected
    assert await acquire_session_slot("test_user", _sid()) is False


@pytest.mark.asyncio
async def test_release_frees_slot():
    """After releasing a slot, a new acquire should succeed."""
    sid1 = _sid()
    sid2 = _sid()
    await acquire_session_slot("test_user", sid1)
    await acquire_session_slot("test_user", sid2)

    # At limit — next should fail
    assert await acquire_session_slot("test_user", _sid()) is False

    # Release one
    await release_session_slot("test_user", sid1)

    # Now should succeed
    assert await acquire_session_slot("test_user", _sid()) is True


@pytest.mark.asyncio
async def test_ttl_expiry_unblocks_user():
    """If TTL expires (simulating server crash), user can connect again."""
    r = await get_redis()
    key = "user:test_user:sessions"

    # Fill up slots
    for _ in range(MAX_CONCURRENT_SESSIONS):
        await acquire_session_slot("test_user", _sid())

    # Confirm blocked
    assert await acquire_session_slot("test_user", _sid()) is False

    # Simulate crash: set TTL to 1 second instead of waiting 5 minutes
    await r.expire(key, 1)
    await asyncio.sleep(1.1)

    # Key should have expired — user is unblocked
    assert await acquire_session_slot("test_user", _sid()) is True


@pytest.mark.asyncio
async def test_refresh_ttl_extends_expiry():
    """Heartbeat refresh should keep the key alive."""
    r = await get_redis()
    key = "user:test_user:sessions"

    await acquire_session_slot("test_user", _sid())

    # Set a short TTL
    await r.expire(key, 2)

    # Refresh should reset it to the full SESSION_TTL_SECONDS
    await refresh_session_ttl("test_user")

    ttl = await r.ttl(key)
    assert ttl > 2, f"TTL should have been refreshed, got {ttl}"


@pytest.mark.asyncio
async def test_concurrent_acquires_respect_limit():
    """Fire many concurrent acquires — total granted must never exceed the limit."""
    num_concurrent = 20

    results = await asyncio.gather(
        *[acquire_session_slot("race_user", _sid()) for _ in range(num_concurrent)]
    )

    granted = sum(1 for r in results if r is True)
    assert granted == MAX_CONCURRENT_SESSIONS, (
        f"Expected exactly {MAX_CONCURRENT_SESSIONS} granted, got {granted}"
    )

    # Verify Redis state matches
    r = await get_redis()
    actual_count = await r.scard("user:race_user:sessions")
    assert actual_count == MAX_CONCURRENT_SESSIONS
