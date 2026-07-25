from __future__ import annotations
import asyncio, time, uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Optional


@dataclass
class MetricPoint:
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    def __init__(self, max_points_per_metric: int = 1000):
        self.metrics: Dict[str, Deque[MetricPoint]] = defaultdict(lambda: deque(maxlen=max_points_per_metric))
        self.counters: Dict[str, float] = defaultdict(float)
        self.lock = asyncio.Lock()

    async def record(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        async with self.lock:
            self.metrics[name].append(MetricPoint(name, float(value), labels=labels or {}))

    async def increment(self, name: str, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> float:
        async with self.lock:
            self.counters[name] += amount
            value = self.counters[name]
            self.metrics[name].append(MetricPoint(name, value, labels=labels or {}))
            return value

    async def summary(self) -> dict:
        async with self.lock:
            result = {}
            for name, points in self.metrics.items():
                values = [p.value for p in points]
                if values:
                    result[name] = {"count": len(values), "latest": values[-1], "minimum": min(values),
                                    "maximum": max(values), "average": sum(values) / len(values)}
            return result


class SpanStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class TraceSpan:
    span_id: str
    trace_id: str
    operation: str
    service: str
    started_at: float
    status: SpanStatus = SpanStatus.RUNNING
    finished_at: Optional[float] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


class ObservabilityManager:
    def __init__(self, metrics: Optional[MetricsCollector] = None):
        self.metrics = metrics or MetricsCollector()
        self.spans: Dict[str, TraceSpan] = {}
        self.lock = asyncio.Lock()

    async def start_span(self, operation: str, service: str, trace_id: Optional[str] = None,
                         attributes: Optional[Dict[str, Any]] = None) -> TraceSpan:
        span = TraceSpan(uuid.uuid4().hex, trace_id or uuid.uuid4().hex, operation, service, time.time(),
                         attributes=attributes or {})
        async with self.lock:
            self.spans[span.span_id] = span
        await self.metrics.increment("spans_started_total", labels={"service": service})
        return span

    async def finish_span(self, span_id: str, status: SpanStatus = SpanStatus.SUCCESS,
                          error: Optional[str] = None) -> TraceSpan:
        async with self.lock:
            span = self.spans[span_id]
            if span.finished_at is None:
                span.finished_at = time.time()
                span.duration_ms = (span.finished_at - span.started_at) * 1000
                span.status, span.error = status, error
        await self.metrics.record("span_duration_ms", span.duration_ms or 0, {"service": span.service, "status": span.status.value})
        return span
