"""
Server-wide metrics: latency histogram and completed session history.
Also contains LatencyTracker which hooks into Pipecat's observer system.
"""
import time
from dataclasses import dataclass, field

from loguru import logger
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    UserBotLatencyObserver,
)


@dataclass
class LatencyRecord:
    session_id: str
    e2e_seconds: float
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    def __init__(self):
        self._latencies: list[LatencyRecord] = []
        self._completed_sessions: list[dict] = []

    def record_latency(self, session_id: str, e2e_seconds: float):
        self._latencies.append(LatencyRecord(session_id=session_id, e2e_seconds=e2e_seconds))

    def record_completed_session(self, session_summary: dict):
        self._completed_sessions.append(session_summary)

    def snapshot(self) -> dict:
        latencies = [r.e2e_seconds for r in self._latencies]
        if latencies:
            latencies_sorted = sorted(latencies)
            n = len(latencies_sorted)
            histogram = {
                "count": n,
                "min": round(latencies_sorted[0], 4),
                "max": round(latencies_sorted[-1], 4),
                "mean": round(sum(latencies_sorted) / n, 4),
                "p50": round(latencies_sorted[n // 2], 4),
                "p95": round(latencies_sorted[int(n * 0.95)], 4),
                "p99": round(latencies_sorted[int(n * 0.99)], 4),
            }
        else:
            histogram = {"count": 0}

        return {
            "latency_histogram": histogram,
            "completed_sessions": self._completed_sessions[-50:],
        }


class LatencyTracker:
    """Per-session wrapper around Pipecat's UserBotLatencyObserver.

    Records TTFB into the global MetricsCollector and logs per-turn breakdowns.
    """

    def __init__(self, session_id: str, metrics: MetricsCollector):
        self.session_id = session_id
        self._metrics = metrics
        self._observer = UserBotLatencyObserver()

        @self._observer.event_handler("on_latency_breakdown")
        async def on_latency_breakdown(observer, breakdown):
            await self._on_latency_breakdown(observer, breakdown)

    @property
    def observer(self) -> UserBotLatencyObserver:
        return self._observer

    async def _on_latency_breakdown(self, observer, breakdown: LatencyBreakdown):
        adjusted_latency = sum(ttfb.duration_secs for ttfb in breakdown.ttfb)
        if breakdown.text_aggregation:
            adjusted_latency += breakdown.text_aggregation.duration_secs
        if breakdown.function_calls:
            adjusted_latency += sum(fc.duration_secs for fc in breakdown.function_calls)
        self._metrics.record_latency(self.session_id, adjusted_latency)

        parts = [f"[{self.session_id}] Turn's latency breakdown"]

        if breakdown.user_turn_secs is not None:
            parts.append(f"user_turn={breakdown.user_turn_secs * 1000:.0f}ms")

        for ttfb in breakdown.ttfb:
            parts.append(f"{ttfb.processor}={ttfb.duration_secs * 1000:.0f}ms")

        if breakdown.text_aggregation:
            parts.append(
                f"text_agg={breakdown.text_aggregation.duration_secs * 1000:.0f}ms"
            )

        if breakdown.function_calls:
            for fc in breakdown.function_calls:
                parts.append(f"{fc.function_name}={fc.duration_secs * 1000:.0f}ms")

        logger.info(" | ".join(parts))
