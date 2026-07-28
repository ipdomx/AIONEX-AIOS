from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class PendingMobileAction:
    action_id: str
    user_id: str
    owner_id: str
    action: str
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0
    completed: bool = False


class AndroidOfflineQueue:
    def __init__(self) -> None:
        self._actions: dict[str, PendingMobileAction] = {}

    def enqueue(self, action: PendingMobileAction) -> PendingMobileAction:
        if action.action_id in self._actions:
            raise ValueError(f"duplicate mobile action: {action.action_id}")
        self._actions[action.action_id] = action
        return action

    def pending_for_user(self, user_id: str) -> list[PendingMobileAction]:
        return sorted(
            (
                action
                for action in self._actions.values()
                if action.user_id == user_id and not action.completed
            ),
            key=lambda action: action.created_at,
        )

    def record_attempt(self, action_id: str) -> PendingMobileAction:
        action = self._actions[action_id]
        if action.completed:
            raise RuntimeError("completed action cannot be retried")
        action.attempts += 1
        return action

    def complete(self, action_id: str) -> PendingMobileAction:
        action = self._actions[action_id]
        action.completed = True
        return action
