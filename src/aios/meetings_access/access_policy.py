from __future__ import annotations

from dataclasses import dataclass, field

from .models import SessionRole


@dataclass(slots=True)
class AccessPolicy:
    owner_id: str
    free_minutes_by_role: dict[SessionRole, int] = field(default_factory=dict)
    paid_access_enabled: bool = True
    role_enabled: dict[SessionRole, bool] = field(default_factory=dict)


class AccessPolicyService:
    def __init__(self) -> None:
        self._policies: dict[str, AccessPolicy] = {}
        self._free_usage: dict[tuple[str, SessionRole], int] = {}

    def set_policy(self, policy: AccessPolicy) -> AccessPolicy:
        for minutes in policy.free_minutes_by_role.values():
            if minutes < 0:
                raise ValueError("free minute limits must be non-negative")
        self._policies[policy.owner_id] = policy
        return policy

    def can_request(self, *, owner_id: str, user_id: str, role: SessionRole, paid: bool) -> bool:
        policy = self._policies[owner_id]
        if not policy.role_enabled.get(role, True):
            return False
        if paid:
            return policy.paid_access_enabled
        limit = policy.free_minutes_by_role.get(role, 0)
        used = self._free_usage.get((user_id, role), 0)
        return used < limit

    def reserve_free_minutes(
        self,
        *,
        owner_id: str,
        user_id: str,
        role: SessionRole,
        minutes: int,
    ) -> int:
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        policy = self._policies[owner_id]
        limit = policy.free_minutes_by_role.get(role, 0)
        key = (user_id, role)
        used = self._free_usage.get(key, 0)
        if used + minutes > limit:
            raise PermissionError("free session limit exceeded")
        self._free_usage[key] = used + minutes
        return self._free_usage[key]
