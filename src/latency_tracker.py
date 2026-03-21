"""Per-turn latency logging using Pipecat's UserBotLatencyObserver."""

from loguru import logger
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    UserBotLatencyObserver,
)

from .metrics import MetricsCollector


class LatencyTracker:
    def __init__(self, session_id: str, metrics: MetricsCollector):
        self.session_id = session_id
        self._metrics = metrics
        self._observer = UserBotLatencyObserver()

        @self._observer.event_handler("on_latency_measured")
        async def on_latency_measured(observer, ttfb_seconds):
            await self._on_latency_measured(observer, ttfb_seconds)

        @self._observer.event_handler("on_latency_breakdown")
        async def on_latency_breakdown(observer, breakdown):
            await self._on_latency_breakdown(observer, breakdown)

    @property
    def observer(self) -> UserBotLatencyObserver:
        return self._observer

    async def _on_latency_measured(self, observer, ttfb_seconds: float):
        self._metrics.record_latency(self.session_id, ttfb_seconds)
        logger.info(
            f"[{self.session_id}] E2E TTFB: {ttfb_seconds * 1000:.0f}ms"
        )

    async def _on_latency_breakdown(self, observer, breakdown: LatencyBreakdown):
        parts = [f"[{self.session_id}] Turn latency"]

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
