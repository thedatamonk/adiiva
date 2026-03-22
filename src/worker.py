"""
Standalone worker process. Runs one Pipecat pipeline for one client session.

Usage:
    python -m src.worker --port 9001 --session-id abc123 --user-id alice
"""

import argparse
import asyncio
import json
import os
import signal
import sys

from dotenv import load_dotenv
from loguru import logger
import redis.asyncio as redis

from .pipeline import create_pipeline
from .usage_tracker import UsageTracker
from .metrics import MetricsCollector
from .rate_limiter import release_session_slot

load_dotenv(override=True)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
WORKER_TTL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10


async def register_worker(redis_client: redis.Redis, session_id: str, port: int, user_id: str):
    """Register this worker in Redis so the gateway can confirm it's ready."""
    key = f"worker:{session_id}"
    data = json.dumps({"port": port, "user_id": user_id, "status": "ready"})
    await redis_client.set(key, data, ex=WORKER_TTL_SECONDS)
    logger.info(f"[{session_id}] Worker registered on port {port}")


async def deregister_worker(redis_client: redis.Redis, session_id: str):
    """Remove this worker from Redis."""
    key = f"worker:{session_id}"
    await redis_client.delete(key)
    logger.info(f"[{session_id}] Worker deregistered")


async def heartbeat(redis_client: redis.Redis, session_id: str):
    """Periodically refresh Redis TTL so the worker key doesn't expire."""
    key = f"worker:{session_id}"
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await redis_client.expire(key, WORKER_TTL_SECONDS)
    except asyncio.CancelledError:
        pass


async def push_metrics_to_redis(redis_client: redis.Redis, session_id: str, usage: UsageTracker):
    """Push session usage metrics to Redis before exiting."""
    key = f"metrics:{session_id}"
    data = json.dumps(usage.summary())
    await redis_client.set(key, data, ex=86400)  # 24h TTL
    logger.info(f"[{session_id}] Metrics pushed to Redis")


async def run_worker(port: int, session_id: str, user_id: str):
    """Main worker loop: register, run pipeline, cleanup."""
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    usage = UsageTracker(session_id=session_id)
    metrics = MetricsCollector()

    logger.remove()
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | worker | {message}",
        level="INFO",
    )

    await register_worker(redis_client, session_id, port, user_id)
    heartbeat_task = asyncio.create_task(heartbeat(redis_client, session_id))

    try:
        logger.info(f"[{session_id}] Starting pipeline on port {port} for user {user_id}")
        await create_pipeline("0.0.0.0", port, session_id, usage, metrics)
    except Exception as e:
        logger.error(f"[{session_id}] Pipeline error: {e}")
    finally:
        heartbeat_task.cancel()
        await release_session_slot(user_id, session_id)
        await push_metrics_to_redis(redis_client, session_id, usage)
        await deregister_worker(redis_client, session_id)
        await redis_client.aclose()
        logger.info(f"[{session_id}] Worker exiting")


def main():
    parser = argparse.ArgumentParser(description="Pipecat pipeline worker")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--session-id", type=str, required=True)
    parser.add_argument("--user-id", type=str, required=True)
    args = parser.parse_args()

    asyncio.run(run_worker(args.port, args.session_id, args.user_id))


if __name__ == "__main__":
    main()
