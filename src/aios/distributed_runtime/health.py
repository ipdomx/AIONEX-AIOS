from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HealthReport:
    worker_id: str
    state: HealthState
    heartbeat_at: datetime | None
    active_tasks: int
    capacity: int
    reason: str


class HealthManager:
    """Maintains worker health snapshots and derives cluster readiness."""

    def __init__(self, *, stale_after: timedelta = timedelta(seconds=45)) -> None:
        self._stale_after = stale_after
        self._lock = RLock()
        self._reports: dict[str, HealthReport] = {}

    def record(
        self,
        *,
        worker_id: str,
        heartbeat_at: datetime | None,
        active_tasks: int,
        capacity: int,
        now: datetime | None = None,
    ) -> HealthReport:
        now = now or _utcnow()
        if heartbeat_at is None:
            state, reason = HealthState.UNKNOWN, "heartbeat_missing"
        elif now - heartbeat_at > self._stale_after:
            state, reason = HealthState.UNHEALTHY, "heartbeat_stale"
        elif capacity <= 0:
            state, reason = HealthState.UNHEALTHY, "capacity_invalid"
        elif active_tasks >= capacity:
            state, reason = HealthState.DEGRADED, "worker_saturated"
        else:
            state, reason = HealthState.HEALTHY, "ready"
        report = HealthReport(worker_id, state, heartbeat_at, active_tasks, capacity, reason)
        with self._lock:
            self._reports[worker_id] = report
        return report

    def get(self, worker_id: str) -> HealthReport | None:
        with self._lock:
            return self._reports.get(worker_id)

    def cluster_ready(self) -> bool:
        with self._lock:
            return any(r.state in {HealthState.HEALTHY, HealthState.DEGRADED} for r in self._reports.values())
