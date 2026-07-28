from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PluginPermissionPolicy:
    allowed_permissions: set[str] = field(default_factory=set)
    forbidden_permissions: set[str] = field(default_factory=set)
    owner_approval_required: set[str] = field(default_factory=set)


class PluginPermissionEvaluator:
    def __init__(self, policy: PluginPermissionPolicy) -> None:
        self._policy = policy

    def validate(self, requested: set[str], *, owner_approved: bool = False) -> None:
        forbidden = requested & self._policy.forbidden_permissions
        if forbidden:
            raise PermissionError(f"forbidden plugin permissions: {sorted(forbidden)}")

        unknown = requested - self._policy.allowed_permissions
        if unknown:
            raise PermissionError(f"unsupported plugin permissions: {sorted(unknown)}")

        gated = requested & self._policy.owner_approval_required
        if gated and not owner_approved:
            raise PermissionError(f"owner approval required for: {sorted(gated)}")
