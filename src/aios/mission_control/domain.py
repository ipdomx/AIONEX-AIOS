from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CommandPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class CommandStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OwnerCommand:
    command_id: str
    owner_id: str
    action: str
    target_type: str
    target_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: CommandPriority = CommandPriority.NORMAL
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class CommandRecord:
    command: OwnerCommand
    status: CommandStatus = CommandStatus.PENDING
    approved_by: str | None = None
    rejection_reason: str | None = None
    result: dict[str, Any] | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class OwnerScope:
    owner_id: str
    organization_ids: frozenset[str]
    project_ids: frozenset[str]
    can_view_all_incidents: bool = True
    can_override_approvals: bool = False


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    project_id: str
    organization_id: str
    status: str
    progress_percent: float
    active_tasks: int
    failed_tasks: int
    blocked_tasks: int
    cost_minor: int
    currency: str
    risk_score: float
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IncidentSnapshot:
    incident_id: str
    severity: str
    status: str
    source: str
    summary: str
    project_id: str | None
    opened_at: datetime
    acknowledged_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    requested_by: str
    subject_type: str
    subject_id: str
    action: str
    reason: str
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MissionControlSnapshot:
    generated_at: datetime
    projects: tuple[ProjectSnapshot, ...]
    incidents: tuple[IncidentSnapshot, ...]
    pending_approvals: tuple[ApprovalRequest, ...]
    active_workers: int
    unhealthy_workers: int
    queued_tasks: int
    running_tasks: int
    completed_tasks_24h: int
    failed_tasks_24h: int
