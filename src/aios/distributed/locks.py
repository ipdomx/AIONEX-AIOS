from __future__ import annotations
import asyncio, time, uuid
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class LockLease:
    key: str
    owner: str
    token: str
    acquired_at: float
    expires_at: float

class DistributedLockManager:
    def __init__(self):
        self.leases: Dict[str, LockLease] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, key: str, owner: str, ttl_seconds: float = 30.0) -> Optional[LockLease]:
        now = time.time()
        async with self.lock:
            current = self.leases.get(key)
            if current and current.expires_at > now and current.owner != owner:
                return None
            lease = LockLease(key, owner, uuid.uuid4().hex, now, now + ttl_seconds)
            self.leases[key] = lease
            return lease

    async def renew(self, key: str, token: str, ttl_seconds: float = 30.0) -> LockLease:
        async with self.lock:
            lease = self.leases[key]
            if lease.token != token or lease.expires_at <= time.time():
                raise PermissionError("invalid or expired lease")
            lease.expires_at = time.time() + ttl_seconds
            return lease

    async def release(self, key: str, token: str) -> bool:
        async with self.lock:
            lease = self.leases.get(key)
            if lease is None or lease.token != token:
                return False
            del self.leases[key]
            return True

    async def cleanup_expired(self) -> int:
        now = time.time()
        async with self.lock:
            expired = [key for key, lease in self.leases.items() if lease.expires_at <= now]
            for key in expired:
                del self.leases[key]
            return len(expired)

    async def is_owner(self, key: str, token: str) -> bool:
        async with self.lock:
            lease = self.leases.get(key)
            return bool(lease and lease.token == token and lease.expires_at > time.time())
