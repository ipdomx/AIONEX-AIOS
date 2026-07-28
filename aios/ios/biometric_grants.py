from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class BiometricGrant:
    grant_id: str
    owner_id: str
    device_id: str
    scope: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


class IOSBiometricGrantService:
    def __init__(self) -> None:
        self._grants: dict[str, BiometricGrant] = {}

    def issue(self, *, grant_id: str, owner_id: str, device_id: str, scope: str, ttl_minutes: int = 5) -> BiometricGrant:
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        if grant_id in self._grants:
            raise ValueError(f"duplicate biometric grant: {grant_id}")
        grant = BiometricGrant(
            grant_id=grant_id,
            owner_id=owner_id,
            device_id=device_id,
            scope=scope,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )
        self._grants[grant_id] = grant
        return grant

    def authorize(self, grant_id: str, owner_id: str, device_id: str, scope: str) -> bool:
        grant = self._grants[grant_id]
        if grant.owner_id != owner_id or grant.device_id != device_id:
            raise PermissionError("biometric grant is not owned by this owner and device")
        return grant.scope == scope and grant.active

    def revoke(self, grant_id: str, owner_id: str) -> BiometricGrant:
        grant = self._grants[grant_id]
        if grant.owner_id != owner_id:
            raise PermissionError("biometric grant is not owned by this owner")
        grant.revoked_at = datetime.now(timezone.utc)
        return grant
