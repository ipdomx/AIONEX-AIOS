from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class BiometricGrant:
    device_id: str
    owner_id: str
    granted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return self.expires_at is None or current < self.expires_at


class AndroidBiometricSecurity:
    def __init__(self, grant_ttl_minutes: int = 15) -> None:
        if grant_ttl_minutes <= 0:
            raise ValueError("grant ttl must be positive")
        self._ttl = timedelta(minutes=grant_ttl_minutes)
        self._grants: dict[str, BiometricGrant] = {}

    def grant(self, device_id: str, owner_id: str) -> BiometricGrant:
        now = datetime.now(timezone.utc)
        grant = BiometricGrant(
            device_id=device_id,
            owner_id=owner_id,
            granted_at=now,
            expires_at=now + self._ttl,
        )
        self._grants[device_id] = grant
        return grant

    def require(self, device_id: str, owner_id: str) -> BiometricGrant:
        grant = self._grants.get(device_id)
        if grant is None or grant.owner_id != owner_id or not grant.active():
            raise PermissionError("active biometric grant required")
        return grant

    def revoke(self, device_id: str, owner_id: str) -> None:
        grant = self._grants.get(device_id)
        if grant is None:
            return
        if grant.owner_id != owner_id:
            raise PermissionError("device is not owned by this owner")
        self._grants.pop(device_id, None)
