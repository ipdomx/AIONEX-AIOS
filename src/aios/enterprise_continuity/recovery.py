from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RecoveryStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RecoveryAction:
    action_id: str
    plan_id: str
    service_id: str
    description: str
    owner_id: str
    sequence: int
    status: RecoveryStatus = RecoveryStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    evidence: dict[str, str] = field(default_factory=dict)

    def transition(self, status: RecoveryStatus) -> None:
        allowed = {
            RecoveryStatus.PENDING: {RecoveryStatus.RUNNING, RecoveryStatus.CANCELLED},
            RecoveryStatus.RUNNING: {RecoveryStatus.COMPLETED, RecoveryStatus.FAILED, RecoveryStatus.CANCELLED},
            RecoveryStatus.COMPLETED: set(),
            RecoveryStatus.FAILED: {RecoveryStatus.RUNNING, RecoveryStatus.CANCELLED},
            RecoveryStatus.CANCELLED: set(),
        }
        if status not in allowed[self.status]:
            raise ValueError(f"invalid recovery transition: {self.status.value} -> {status.value}")
        now = datetime.now(timezone.utc)
        self.status = status
        if status is RecoveryStatus.RUNNING:
            self.started_at = now
        if status in {RecoveryStatus.COMPLETED, RecoveryStatus.FAILED, RecoveryStatus.CANCELLED}:
            self.completed_at = now


class RecoveryCoordinator:
    def __init__(self) -> None:
        self._actions: dict[str, RecoveryAction] = {}

    def add(self, action: RecoveryAction) -> RecoveryAction:
        if not action.action_id.strip() or not action.plan_id.strip() or not action.service_id.strip():
            raise ValueError("action_id, plan_id and service_id are required")
        if action.sequence < 1:
            raise ValueError("sequence must be positive")
        if action.action_id in self._actions:
            raise ValueError(f"duplicate recovery action: {action.action_id}")
        self._actions[action.action_id] = action
        return action

    def start(self, action_id: str) -> RecoveryAction:
        action = self.get(action_id)
        prerequisites = [item for item in self.actions_for_plan(action.plan_id) if item.sequence < action.sequence]
        if any(item.status is not RecoveryStatus.COMPLETED for item in prerequisites):
            raise RuntimeError("recovery prerequisites are incomplete")
        action.transition(RecoveryStatus.RUNNING)
        return action

    def complete(self, action_id: str, evidence: dict[str, str] | None = None) -> RecoveryAction:
        action = self.get(action_id)
        action.evidence.update(evidence or {})
        action.transition(RecoveryStatus.COMPLETED)
        return action

    def fail(self, action_id: str, evidence: dict[str, str] | None = None) -> RecoveryAction:
        action = self.get(action_id)
        action.evidence.update(evidence or {})
        action.transition(RecoveryStatus.FAILED)
        return action

    def get(self, action_id: str) -> RecoveryAction:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise LookupError(f"recovery action not found: {action_id}") from exc

    def actions_for_plan(self, plan_id: str) -> list[RecoveryAction]:
        return sorted(
            [item for item in self._actions.values() if item.plan_id == plan_id],
            key=lambda item: item.sequence,
        )

    def progress(self, plan_id: str) -> float:
        actions = self.actions_for_plan(plan_id)
        if not actions:
            return 0.0
        completed = sum(1 for action in actions if action.status is RecoveryStatus.COMPLETED)
        return completed / len(actions)
