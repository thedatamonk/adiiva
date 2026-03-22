"""Tests for MetricsStore — in-memory session metrics with SSE fan-out."""

import pytest
from src.metrics_store import MetricsStore
from src.observers import TurnLatency


@pytest.fixture
def store():
    return MetricsStore()


def _make_turn(turn_number: int, wall_clock: float = 1.0, **kwargs) -> TurnLatency:
    return TurnLatency(turn_number=turn_number, total_wall_clock=wall_clock, **kwargs)


# ── start_session ────────────────────────────────────────────────────

class TestStartSession:
    def test_creates_session(self, store: MetricsStore):
        store.start_session("s1", "u1")
        assert "s1" in store._sessions
        s = store._sessions["s1"]
        assert s.session_id == "s1"
        assert s.user_id == "u1"
        assert s.status == "active"
        assert isinstance(s.started_at, str)
        assert s.ended_at is None
        assert s.turns == []


# ── add_turn ─────────────────────────────────────────────────────────

class TestAddTurn:
    def test_appends_turn(self, store: MetricsStore):
        store.start_session("s1", "u1")
        turn = _make_turn(1, wall_clock=0.5)
        store.add_turn("s1", turn)
        assert len(store._sessions["s1"].turns) == 1
        assert store._sessions["s1"].turns[0].total_wall_clock == 0.5

    def test_add_multiple_turns(self, store: MetricsStore):
        store.start_session("s1", "u1")
        store.add_turn("s1", _make_turn(1, 0.3))
        store.add_turn("s1", _make_turn(2, 0.7))
        assert len(store._sessions["s1"].turns) == 2

    def test_add_turn_unknown_session_raises(self, store: MetricsStore):
        with pytest.raises(KeyError):
            store.add_turn("nonexistent", _make_turn(1))


# ── end_session ──────────────────────────────────────────────────────

class TestEndSession:
    def test_marks_completed(self, store: MetricsStore):
        store.start_session("s1", "u1")
        store.end_session("s1")
        s = store._sessions["s1"]
        assert s.status == "completed"
        assert s.ended_at is not None

    def test_idempotent(self, store: MetricsStore):
        store.start_session("s1", "u1")
        store.end_session("s1")
        ended_at_first = store._sessions["s1"].ended_at
        store.end_session("s1")
        # ended_at should not change on second call
        assert store._sessions["s1"].ended_at == ended_at_first
        assert store._sessions["s1"].status == "completed"


# ── snapshot ─────────────────────────────────────────────────────────

class TestSnapshot:
    def test_empty_store(self, store: MetricsStore):
        snap = store.snapshot()
        assert snap["active_sessions"] == []
        assert snap["completed_sessions"] == []
        assert snap["latency_histogram"]["count"] == 0

    def test_with_turns(self, store: MetricsStore):
        store.start_session("s1", "u1")
        store.add_turn("s1", _make_turn(1, wall_clock=1.0, llm_prompt_tokens=10, llm_completion_tokens=5, tts_characters=100))
        store.add_turn("s1", _make_turn(2, wall_clock=2.0, llm_prompt_tokens=20, llm_completion_tokens=10, tts_characters=200))
        store.end_session("s1")

        snap = store.snapshot()
        assert len(snap["completed_sessions"]) == 1
        sess = snap["completed_sessions"][0]
        assert sess["session_id"] == "s1"
        assert sess["turn_count"] == 2
        assert sess["llm_prompt_tokens"] == 30
        assert sess["llm_completion_tokens"] == 15
        assert sess["tts_characters"] == 300

        hist = snap["latency_histogram"]
        assert hist["count"] == 2
        assert hist["min"] == 1.0
        assert hist["max"] == 2.0
        assert hist["mean"] == 1.5

    def test_histogram_percentiles_100_turns(self, store: MetricsStore):
        store.start_session("s1", "u1")
        for i in range(1, 101):
            store.add_turn("s1", _make_turn(i, wall_clock=float(i)))

        snap = store.snapshot()
        hist = snap["latency_histogram"]
        assert hist["count"] == 100
        assert hist["min"] == 1.0
        assert hist["max"] == 100.0

        sorted_vals = list(range(1, 101))
        n = 100
        assert hist["p50"] == round(float(sorted_vals[n // 2]), 4)
        assert hist["p95"] == round(float(sorted_vals[int(n * 0.95)]), 4)
        assert hist["p99"] == round(float(sorted_vals[int(n * 0.99)]), 4)

    def test_active_and_completed_separation(self, store: MetricsStore):
        store.start_session("s1", "u1")
        store.start_session("s2", "u2")
        store.end_session("s1")

        snap = store.snapshot()
        active_ids = [s["session_id"] for s in snap["active_sessions"]]
        completed_ids = [s["session_id"] for s in snap["completed_sessions"]]
        assert "s2" in active_ids
        assert "s1" in completed_ids


# ── subscribe / unsubscribe / fan-out ────────────────────────────────

class TestFanOut:
    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        store = MetricsStore()
        queue = store.subscribe()

        store.start_session("s1", "u1")
        event = queue.get_nowait()
        assert event["type"] == "session_started"
        assert event["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_turn_completed_event(self):
        store = MetricsStore()
        queue = store.subscribe()

        store.start_session("s1", "u1")
        _ = queue.get_nowait()  # consume session_started

        turn = _make_turn(1, wall_clock=0.5, llm_ttfb=0.1)
        store.add_turn("s1", turn)
        event = queue.get_nowait()
        assert event["type"] == "turn_completed"
        assert event["session_id"] == "s1"
        assert event["turn_number"] == 1
        assert event["total_wall_clock"] == 0.5
        assert event["llm_ttfb"] == 0.1

    @pytest.mark.asyncio
    async def test_session_ended_event(self):
        store = MetricsStore()
        queue = store.subscribe()

        store.start_session("s1", "u1")
        _ = queue.get_nowait()

        store.end_session("s1")
        event = queue.get_nowait()
        assert event["type"] == "session_ended"
        assert event["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_up(self):
        store = MetricsStore()
        queue = store.subscribe()
        assert len(store._subscribers) == 1

        store.unsubscribe(queue)
        assert len(store._subscribers) == 0

        # After unsubscribe, events should not appear in queue
        store.start_session("s1", "u1")
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        store = MetricsStore()
        q1 = store.subscribe()
        q2 = store.subscribe()

        store.start_session("s1", "u1")
        assert not q1.empty()
        assert not q2.empty()
