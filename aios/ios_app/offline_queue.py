from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class OfflineActionState(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class OfflineAction:
    action_id: str
    owner_id: str
    action_type: str
    payload: dict[str, object]
    state: OfflineActionState = OfflineActionState.PENDING
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSOfflineQueue:
    def __init__(self) -> None:
        self._actions: dict[str, OfflineAction] = {}

    def enqueue(self, action: OfflineAction) -> OfflineAction:
        if action.action_id in self._actions:
            raise ValueError("duplicate offline action")
        self._actions[action.action_id] = action
        return action

    def pending_for_owner(self, owner_id: str) -> list[OfflineAction]:
        return [
            action
            for action in self._actions.values()
            if action.owner_id == owner_id and action.state in {OfflineActionState.PENDING, OfflineActionState.FAILED}
        ]

    def start(self, action_id: str, owner_id: str) -> OfflineAction:
        action = self._require_owner(action_id, owner_id)
        action.state = OfflineActionState.SYNCING
        action.attempts += 1
        return action

    def complete(self, action_id: str, owner_id: str) -> OfflineAction:
        action = self._require_owner(action_id, owner_id)
        action.state = OfflineActionState.COMPLETED
        return action

    def fail(self, action_id: str, owner_id: str) -> OfflineAction:
        action = self._require_owner(action_id, owner_id)
        action.state = OfflineActionState.FAILED
        return action

    def _require_owner(self, action_id: str, owner_id: str) -> OfflineAction:
        action = self._actions[action_id]
        if action.owner_id != owner_id:
            raise PermissionError("offline action belongs to another owner")
        return action
