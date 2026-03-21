"""
Main fastAPI app that triggers execution
of the Pipecat PipelineTask
"""

import sys

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from uuid import uuid4

from .auth import create_token, verify_token
from .cost_estimator import estimate_cost
from .metrics import MetricsCollector
from .pipeline import create_pipeline
from .rate_limiter import acquire_session_slot, release_session_slot
from .session_manager import SessionManager

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
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    serialize=True,  # JSON structured logs to file
)

app = FastAPI(title="ADIIVA Voice AI Gateway")
session_mgr = SessionManager()
metrics = MetricsCollector()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/token")
async def issue_token(user_id: str):
    token = create_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@app.websocket("/ws/talk")
async def websocket_talk(websocket: WebSocket, token: str = Query(None)):

    # Authentication using JWT
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()

    session_id = str(uuid4())

    # Check # of concurrent sessions for this user
    allowed = await acquire_session_slot(user_id, session_id)
    if not allowed:
        await websocket.close(code=4001, reason="Concurrency limit exceeded")
        return

    session = session_mgr.create_session(session_id, user_id)
    try:
        logger.info(f"[{session_id}] Pipeline starting for user {user_id}")
        await create_pipeline(websocket, session_id, session.usage)
    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket disconnected")
    except Exception as e:
        logger.error(f"[{session_id}] Pipeline error: {e}")
    finally:
        await release_session_slot(user_id, session_id)
        summary = await session_mgr.remove_session(session_id)
        if summary:
            summary_with_cost = estimate_cost(summary)
            metrics.record_completed_session(summary_with_cost)
            logger.info(
                f"[{session_id}] Session ended for user {user_id} | "
                f"Usage: {summary_with_cost}"
            )


@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": session_mgr.active_count()}


@app.get("/metrics")
async def get_metrics():
    active_sessions = []
    for sid, session in session_mgr._sessions.items():
        active_sessions.append(estimate_cost(session.usage.summary()))

    return {
        **metrics.snapshot(),
        "active_sessions": active_sessions,
        "active_session_count": session_mgr.active_count(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
