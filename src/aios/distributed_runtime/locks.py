from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class LockLease:
    name: str
    owner_id: str
    token: str
    expires_at: datetime


class DistributedLockManager:
    """Process-local lock contract suitable for swapping with Redis or etcd."""

    def __init__(self) -> None:
        self._guard = RLock()
        self._leases: dict[str, LockLease] = {}

    def acquire(self, *, name: str, owner_id: str, ttl: timedelta) -> LockLease | None:
        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        now = _utcnow()
        with self._guard:
            current = self._leases.get(name)
            if current and current.expires_at > now and current.owner_id != owner_id:
                return None
            lease = LockLease(name, owner_id, str(uuid4()), now + ttl)
            self._leases[name] = lease
            return lease

    def renew(self, *, token: str, ttl: timedelta) -> LockLease:
        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        with self._guard:
            for name, lease in self._leases.items():
                if lease.token == token:
                    renewed = LockLease(name, lease.owner_id, token, _utcnow() + ttl)
                    self._leases[name] = renewed
                    return renewed
        raise KeyError("lock lease not found")

    def release(self, *, token: str) -> bool:
        with self._guard:
            for name, lease in tuple(self._leases.items()):
                if lease.token == token:
                    del self._leases[name]
                    return True
        return False
