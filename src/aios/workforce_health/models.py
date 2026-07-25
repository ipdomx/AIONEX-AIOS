from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class WorkerObservation:
    worker_id: str
    project_id: str | None
    quality: float
    reliability: float
    collaboration: float
    policy_compliance: float
    learning: float
    incidents: tuple[str, ...] = ()
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class WorkerHealthReport:
    worker_id: str
    operational_health: float
    performance: float
    collaboration: float
    trust: float
    learning: float
    recommendation: str
    restrictions: tuple[str, ...] = ()
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
