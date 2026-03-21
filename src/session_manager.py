"""
Maps sessions to PipelineTask instances
"""

from dataclasses import dataclass, field
from typing import Optional

from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

from .usage_tracker import UsageTracker
import time

from loguru import logger

@dataclass
class SessionInfo:
    session_id: str
    user_id: str
    task: Optional[PipelineTask] = None
    runner: Optional[PipelineRunner] = None
    usage: Optional[UsageTracker] = None
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if self.usage is None:
            self.usage = UsageTracker(session_id=self.session_id)
    
class SessionManager:
    def __init__(self):
        # We are storing all the user sessions in a in-memory hashmap
        self._sessions: dict[str, SessionInfo] = {}

    def create_session(self, session_id: str, user_id: str) -> SessionInfo:
        session = SessionInfo(session_id=session_id, user_id=user_id)
        self._sessions[session_id] = session
        logger.info(f"Session created: {session_id} for user {user_id}")
        return session

    async def remove_session(self, session_id: str) -> Optional[dict]:
        session = self._sessions.pop(session_id, None)
        if not session:
            return None
        summary = session.usage.summary()
        logger.info(f"Session removed: {session_id} | Usage: {summary}")
        return summary
    
    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> list[str]:
        return [
            sid for sid, s in self._sessions.items() if s.user_id == user_id
        ]
    
    def active_count(self) -> int:
        return len(self._sessions)

    def active_count_for_user(self, user_id: str) -> int:
        return len(self.get_user_sessions(user_id))
