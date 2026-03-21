import time
from dataclasses import dataclass, field


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

    def record_completed_session(self, session_summary_with_cost: dict):
        self._completed_sessions.append(session_summary_with_cost)

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
