from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class RateLimitPolicy:
    policy_id: str
    limit: int
    window_seconds: int

    def validate(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if self.limit <= 0 or self.window_seconds <= 0:
            raise ValueError("rate limit values must be positive")


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[datetime]] = {}

    def allow(self, principal_id: str, policy: RateLimitPolicy, now: datetime | None = None) -> bool:
        policy.validate()
        current = now or datetime.now(timezone.utc)
        key = (principal_id, policy.policy_id)
        cutoff = current - timedelta(seconds=policy.window_seconds)
        events = [event for event in self._events.get(key, []) if event > cutoff]
        if len(events) >= policy.limit:
            self._events[key] = events
            return False
        events.append(current)
        self._events[key] = events
        return True

    def remaining(self, principal_id: str, policy: RateLimitPolicy, now: datetime | None = None) -> int:
        policy.validate()
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(seconds=policy.window_seconds)
        events = [event for event in self._events.get((principal_id, policy.policy_id), []) if event > cutoff]
        return max(0, policy.limit - len(events))
