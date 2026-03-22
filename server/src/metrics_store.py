"""In-memory store for session metrics with SSE fan-out."""

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from src.observers import TurnLatency


@dataclass
class SessionMetrics:
    session_id: str
    user_id: str
    status: str = "active"  # "active" | "completed"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    turns: list[TurnLatency] = field(default_factory=list)


class MetricsStore:
    def __init__(self):
        self._sessions: dict[str, SessionMetrics] = {}
        self._subscribers: list[asyncio.Queue] = []

    # ── mutations ────────────────────────────────────────────────────

    def start_session(self, session_id: str, user_id: str) -> None:
        session = SessionMetrics(
            session_id=session_id,
            user_id=user_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._sessions[session_id] = session
        self._fan_out({
            "type": "session_started",
            "session_id": session_id,
            "user_id": user_id,
            "started_at": session.started_at,
        })

    def add_turn(self, session_id: str, turn: TurnLatency) -> None:
        session = self._sessions[session_id]  # raises KeyError if missing
        session.turns.append(turn)
        self._fan_out({
            "type": "turn_completed",
            "session_id": session_id,
            **asdict(turn),
        })

    def end_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.status == "completed":
            return
        session.status = "completed"
        session.ended_at = datetime.now(timezone.utc).isoformat()
        self._fan_out({
            "type": "session_ended",
            "session_id": session_id,
            "ended_at": session.ended_at,
        })

    # ── queries ──────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        active = []
        completed = []

        for s in self._sessions.values():
            summary = self._session_summary(s)
            if s.status == "active":
                active.append(summary)
            else:
                completed.append(summary)

        # Latency histogram from all turns across all sessions
        all_wall_clocks = [
            t.total_wall_clock
            for s in self._sessions.values()
            for t in s.turns
            if t.total_wall_clock is not None
        ]

        if all_wall_clocks:
            sorted_wc = sorted(all_wall_clocks)
            n = len(sorted_wc)
            histogram = {
                "count": n,
                "min": round(sorted_wc[0], 4),
                "max": round(sorted_wc[-1], 4),
                "mean": round(mean(sorted_wc), 4),
                "p50": round(sorted_wc[n // 2], 4),
                "p95": round(sorted_wc[int(n * 0.95)], 4),
                "p99": round(sorted_wc[int(n * 0.99)], 4),
            }
        else:
            histogram = {"count": 0}

        return {
            "active_sessions": active,
            "completed_sessions": completed,
            "latency_histogram": histogram,
        }

    # ── SSE fan-out ──────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def _fan_out(self, event: dict) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _session_summary(s: SessionMetrics) -> dict:
        turns_list = [asdict(t) for t in s.turns]
        return {
            "session_id": s.session_id,
            "user_id": s.user_id,
            "status": s.status,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "turn_count": len(s.turns),
            "llm_prompt_tokens": sum(t.llm_prompt_tokens for t in s.turns if t.llm_prompt_tokens is not None),
            "llm_completion_tokens": sum(t.llm_completion_tokens for t in s.turns if t.llm_completion_tokens is not None),
            "tts_characters": sum(t.tts_characters for t in s.turns if t.tts_characters is not None),
            "turns": turns_list,
        }
