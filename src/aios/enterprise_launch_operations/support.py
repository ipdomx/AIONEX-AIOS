from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SupportPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SupportIncident:
    incident_id: str
    title: str
    description: str
    priority: SupportPriority = SupportPriority.NORMAL
    organization_id: str | None = None
    project_id: str | None = None
    resolved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class SupportQueue:
    def __init__(self) -> None:
        self._incidents: dict[str, SupportIncident] = {}

    def open(self, incident: SupportIncident) -> SupportIncident:
        if not incident.incident_id.strip() or not incident.title.strip():
            raise ValueError("incident_id and title are required")
        if incident.incident_id in self._incidents:
            raise ValueError(f"duplicate incident_id: {incident.incident_id}")
        self._incidents[incident.incident_id] = incident
        return incident

    def get(self, incident_id: str) -> SupportIncident:
        try:
            return self._incidents[incident_id]
        except KeyError as exc:
            raise LookupError(f"incident not found: {incident_id}") from exc

    def resolve(self, incident_id: str) -> SupportIncident:
        incident = self.get(incident_id)
        incident.resolved = True
        incident.resolved_at = datetime.now(timezone.utc)
        return incident

    def unresolved(self) -> list[SupportIncident]:
        priority_rank = {
            SupportPriority.CRITICAL: 0,
            SupportPriority.HIGH: 1,
            SupportPriority.NORMAL: 2,
            SupportPriority.LOW: 3,
        }
        return sorted(
            [incident for incident in self._incidents.values() if not incident.resolved],
            key=lambda incident: (priority_rank[incident.priority], incident.created_at),
        )
