import os
from dotenv import load_dotenv
import redis.asyncio as redis
from typing import Optional
from loguru import logger

load_dotenv()
REDIS_URL = os.environ["REDIS_URL"]
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "2"))
SESSION_TTL_SECONDS = 300  # 5 minutes — refreshed by heartbeat

_redis: Optional[redis.Redis] = None

# Lua script: atomically check count and add session if under limit.
# Returns 1 if acquired, 0 if limit reached.
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local session_id = ARGV[1]
local max_sessions = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

if redis.call('SCARD', key) >= max_sessions then
    return 0
end
redis.call('SADD', key, session_id)
redis.call('EXPIRE', key, ttl)
return 1
"""


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def acquire_session_slot(user_id: str, session_id: str) -> bool:
    """
    Atomically check the concurrency cap and add the session if under limit.
    Sets a TTL on the key so stale sessions expire if the server crashes.
    """
    redis_client = await get_redis()
    key = f"user:{user_id}:sessions"
    result = await redis_client.eval(
        _ACQUIRE_SCRIPT, 1, key, session_id, MAX_CONCURRENT_SESSIONS, SESSION_TTL_SECONDS
    )
    if result == 0:
        logger.warning(f"Concurrency cap hit for user {user_id} ({MAX_CONCURRENT_SESSIONS} max)")
        return False
    logger.info(f"Acquired session slot {session_id} for user {user_id}")
    return True


async def refresh_session_ttl(user_id: str):
    """
    Refresh the TTL on a user's session set. Call this periodically
    from a heartbeat so the key doesn't expire while sessions are alive.
    """
    redis_client = await get_redis()
    key = f"user:{user_id}:sessions"
    await redis_client.expire(key, SESSION_TTL_SECONDS)


async def release_session_slot(user_id: str, session_id: str):
    """
    Release a session slot when a call ends.
    """
    redis_client = await get_redis()
    key = f"user:{user_id}:sessions"
    await redis_client.srem(key, session_id)
    logger.info(f"Released session slot {session_id} for user {user_id}")
