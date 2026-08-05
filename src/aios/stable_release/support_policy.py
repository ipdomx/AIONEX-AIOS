from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class SupportTier(str, Enum):
    STANDARD = "standard"
    EXTENDED = "extended"
    LONG_TERM = "long_term"


@dataclass(slots=True)
class StableSupportPolicy:
    version: str
    owner_id: str
    tier: SupportTier
    released_at: datetime
    support_ends_at: datetime
    security_updates: bool = True
    maintenance_updates: bool = True
    notes: list[str] = field(default_factory=list)


class StableSupportRegistry:
    DURATIONS = {
        SupportTier.STANDARD: timedelta(days=180),
        SupportTier.EXTENDED: timedelta(days=365),
        SupportTier.LONG_TERM: timedelta(days=1095),
    }

    def __init__(self) -> None:
        self._policies: dict[str, StableSupportPolicy] = {}

    def create(self, version: str, owner_id: str, tier: SupportTier) -> StableSupportPolicy:
        if version in self._policies:
            raise ValueError(f"support policy already exists: {version}")
        released_at = datetime.now(timezone.utc)
        policy = StableSupportPolicy(
            version=version,
            owner_id=owner_id,
            tier=tier,
            released_at=released_at,
            support_ends_at=released_at + self.DURATIONS[tier],
        )
        self._policies[version] = policy
        return policy

    def get(self, version: str, owner_id: str) -> StableSupportPolicy:
        policy = self._policies[version]
        if policy.owner_id != owner_id:
            raise PermissionError("support policy is not owned by this owner")
        return policy

    def is_supported(self, version: str, owner_id: str, at: datetime | None = None) -> bool:
        policy = self.get(version, owner_id)
        current = at or datetime.now(timezone.utc)
        return current <= policy.support_ends_at
