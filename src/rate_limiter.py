import os
from dotenv import load_dotenv
import redis.asyncio as redis
from typing import Optional
from loguru import logger

load_dotenv()
REDIS_URL = os.environ["REDIS_URL"]
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "2"))

_redis: Optional[redis.Redis] = None

async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis

async def acquire_session_slot(user_id: str, session_id: str) -> bool:
    """
    Return a new session to the given user if the MAX_CONCURRENT_SESSIONS limit has not been breached
    """
    redis_client = await get_redis()
    key = f"user:{user_id}:sessions"
    count = await redis_client.scard(key)
    if count >= MAX_CONCURRENT_SESSIONS:
        logger.warning(f"Concurrency cap hit for user {user_id}: ({count} / {MAX_CONCURRENT_SESSIONS})")
        return False
    await redis_client.sadd(key, session_id)
    return True

async def release_session_slot(user_id: str, session_id: str):
    """
    Release a session slot when a call ends.
    """
    redis_client = await get_redis()
    key = f"user:{user_id}:sessions"
    await redis_client.srem(key, session_id)
    logger.info(f"Released session slot {session_id} for user {user_id}")
