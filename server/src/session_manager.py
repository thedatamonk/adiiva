"""
Maps session IDs to session metadata.
"""

from dataclasses import dataclass, field
from typing import Optional

import time

from loguru import logger


@dataclass
class SessionInfo:
    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, SessionInfo] = {}

    def create_session(self, session_id: str, user_id: str) -> SessionInfo:
        session = SessionInfo(session_id=session_id, user_id=user_id)
        self._sessions[session_id] = session
        logger.info(f"Session created: {session_id} for user {user_id}")
        return session

    def remove_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            logger.info(f"Session removed: {session_id}")

    def active_count(self) -> int:
        return len(self._sessions)
