from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ProjectControlState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    COMPLETED = "completed"


@dataclass(slots=True)
class ProjectControl:
    project_id: str
    owner_id: str
    state: ProjectControlState = ProjectControlState.ACTIVE
    budget_limit: float | None = None
    service_flags: dict[str, bool] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class OwnerProjectControlService:
    def __init__(self) -> None:
        self._projects: dict[str, ProjectControl] = {}

    def register(self, control: ProjectControl) -> ProjectControl:
        if control.project_id in self._projects:
            raise ValueError(f"project already registered: {control.project_id}")
        self._projects[control.project_id] = control
        return control

    def set_state(
        self,
        project_id: str,
        owner_id: str,
        state: ProjectControlState,
    ) -> ProjectControl:
        control = self._require_owner(project_id, owner_id)
        if control.state is ProjectControlState.COMPLETED and state is not ProjectControlState.COMPLETED:
            raise RuntimeError("completed projects cannot be reopened")
        control.state = state
        control.updated_at = datetime.now(timezone.utc)
        return control

    def set_budget_limit(self, project_id: str, owner_id: str, limit: float | None) -> ProjectControl:
        if limit is not None and limit < 0:
            raise ValueError("budget limit must be non-negative")
        control = self._require_owner(project_id, owner_id)
        control.budget_limit = limit
        control.updated_at = datetime.now(timezone.utc)
        return control

    def set_service_enabled(
        self,
        project_id: str,
        owner_id: str,
        service: str,
        enabled: bool,
    ) -> ProjectControl:
        control = self._require_owner(project_id, owner_id)
        control.service_flags[service] = enabled
        control.updated_at = datetime.now(timezone.utc)
        return control

    def _require_owner(self, project_id: str, owner_id: str) -> ProjectControl:
        control = self._projects[project_id]
        if control.owner_id != owner_id:
            raise PermissionError("project is not owned by this owner")
        return control
