from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class IOSProjectSummary:
    project_id: str
    owner_id: str
    name: str
    state: str
    progress: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSProjectAccessService:
    def __init__(self) -> None:
        self._projects: dict[str, IOSProjectSummary] = {}

    def upsert(self, project: IOSProjectSummary) -> IOSProjectSummary:
        existing = self._projects.get(project.project_id)
        if existing and existing.owner_id != project.owner_id:
            raise PermissionError("project belongs to another owner")
        if not 0.0 <= project.progress <= 100.0:
            raise ValueError("progress must be between 0 and 100")
        project.updated_at = datetime.now(timezone.utc)
        self._projects[project.project_id] = project
        return project

    def get(self, project_id: str, owner_id: str) -> IOSProjectSummary:
        project = self._projects[project_id]
        if project.owner_id != owner_id:
            raise PermissionError("project belongs to another owner")
        return project

    def list_for_owner(self, owner_id: str) -> list[IOSProjectSummary]:
        return sorted(
            (project for project in self._projects.values() if project.owner_id == owner_id),
            key=lambda project: project.updated_at,
            reverse=True,
        )
