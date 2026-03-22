"""
Voice AI Gateway — handles auth, rate limiting, and worker spawning.
Does NOT run pipelines directly.
"""

import asyncio
import json
import os
import subprocess
import sys

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from loguru import logger
from typing import Optional
from uuid import uuid4

import redis.asyncio as redis

from .auth import create_token, verify_token
from .user_store import authenticate_user
from .rate_limiter import acquire_session_slot

load_dotenv(override=True)

logger.remove()
logger.add(
    sys.stderr,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
    level="INFO",
    serialize=False,
)
logger.add(
    "logs/gateway.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} | {message}",
    level="INFO",
    rotation="10 MB",
    retention="7 days",
    serialize=False,
)

app = FastAPI(title="ADIIVA Voice AI Gateway")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
WORKER_BASE_PORT = int(os.getenv("WORKER_BASE_PORT", "9000"))
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "localhost")
WORKER_READY_TIMEOUT = 5  # seconds to wait for worker to register in Redis

_redis: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


_next_port = WORKER_BASE_PORT


async def get_next_port() -> int:
    """Return the next port using an in-memory counter. Simple and race-free
    within a single gateway process."""
    global _next_port
    port = _next_port
    _next_port += 1
    return port


async def wait_for_worker_ready(session_id: str, timeout: float = WORKER_READY_TIMEOUT) -> bool:
    """Poll Redis until the worker registers or timeout."""
    redis_client = await get_redis()
    key = f"worker:{session_id}"
    elapsed = 0.0
    interval = 0.1
    while elapsed < timeout:
        if await redis_client.exists(key):
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


@app.post("/token")
async def issue_token(user_id: str, password: str):
    if not authenticate_user(user_id, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@app.post("/connect")
async def connect(authorization: Optional[str] = Header(None)):
    # Auth
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    session_id = str(uuid4())

    # Rate limit
    allowed = await acquire_session_slot(user_id, session_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Concurrency limit exceeded")

    # Pick a port
    port = await get_next_port()

    # Spawn worker
    process = subprocess.Popen(
        [
            sys.executable, "-m", "src.worker",
            "--port", str(port),
            "--session-id", session_id,
            "--user-id", user_id,
        ],
        env={**os.environ},
    )

    logger.info(f"[{session_id}] Spawned worker PID={process.pid} on port {port} for user {user_id}")

    # Wait for worker to register
    ready = await wait_for_worker_ready(session_id)
    if not ready:
        logger.error(f"[{session_id}] Worker failed to register in time, killing PID={process.pid}")
        process.kill()
        from .rate_limiter import release_session_slot
        await release_session_slot(user_id, session_id)
        raise HTTPException(status_code=503, detail="Worker failed to start")

    worker_url = f"ws://{GATEWAY_HOST}:{port}"
    logger.info(f"[{session_id}] Worker ready at {worker_url}")

    return {"worker_url": worker_url, "session_id": session_id}


@app.get("/health")
async def health():
    redis_client = await get_redis()
    count = 0
    async for _ in redis_client.scan_iter("worker:*"):
        count += 1
    return {"status": "ok", "active_sessions": count}


@app.get("/metrics")
async def get_metrics():
    redis_client = await get_redis()

    # Collect completed session metrics from Redis
    completed = []
    async for key in redis_client.scan_iter("metrics:*"):
        raw = await redis_client.get(key)
        if raw:
            completed.append(json.loads(raw))

    # Count active workers
    active_count = 0
    async for _ in redis_client.scan_iter("worker:*"):
        active_count += 1

    return {
        "completed_sessions": completed[-50:],
        "active_session_count": active_count,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
