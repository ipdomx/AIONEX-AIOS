from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True, frozen=True)
class OwnerDashboardSnapshot:
    owner_id: str
    active_projects: int
    pending_approvals: int
    open_incidents: int
    active_workers: int
    queued_tasks: int
    monthly_cost: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OwnerDashboardApi:
    def __init__(self) -> None:
        self._snapshots: dict[str, OwnerDashboardSnapshot] = {}

    def publish(self, snapshot: OwnerDashboardSnapshot) -> OwnerDashboardSnapshot:
        if snapshot.active_projects < 0 or snapshot.pending_approvals < 0:
            raise ValueError("dashboard counters must be non-negative")
        if snapshot.open_incidents < 0 or snapshot.active_workers < 0 or snapshot.queued_tasks < 0:
            raise ValueError("dashboard counters must be non-negative")
        if snapshot.monthly_cost < 0:
            raise ValueError("monthly cost must be non-negative")
        self._snapshots[snapshot.owner_id] = snapshot
        return snapshot

    def get(self, owner_id: str) -> OwnerDashboardSnapshot:
        try:
            return self._snapshots[owner_id]
        except KeyError as exc:
            raise KeyError(f"dashboard snapshot not found for owner: {owner_id}") from exc
