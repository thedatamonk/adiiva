import pytest
from src.metrics import LatencyTracker, MetricsCollector


def test_latency_tracker_creates_observer():
    metrics = MetricsCollector()
    tracker = LatencyTracker("test-session", metrics)
    assert tracker.observer is not None


@pytest.mark.asyncio
async def test_latency_tracker_records_latency():
    """Simulate on_latency_measured being called."""
    metrics = MetricsCollector()
    tracker = LatencyTracker("test-session", metrics)
    await tracker._on_latency_measured(tracker.observer, 1.5)
    snapshot = metrics.snapshot()
    assert snapshot["latency_histogram"]["count"] == 1
    assert snapshot["latency_histogram"]["mean"] == 1.5
