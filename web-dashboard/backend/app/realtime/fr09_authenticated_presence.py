"""Optional, server-observed FR09 authenticated WebSocket presence telemetry.

Disabled by default. Only a connection that has passed the existing
AuthorizedRealtimeSocket and has been admitted to the event hub may be counted.
All Redis members are scoped, keyed digests or random socket IDs, never
credentials, subject IDs, tenant IDs, request bodies or prompts. This records
presence evidence; it does NOT authorize release or assert 5,000 users exist.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.db.redis import get_redis
from app.realtime.authorized_socket import StreamPrincipal

SOURCE = "server-authenticated-session-tracker-v1"
LIVE_SECONDS = 20
KEY_EXPIRE_SECONDS = 3600
_RUN_ID = re.compile(r"fr09-[a-z0-9][a-z0-9-]{10,60}[a-z0-9]\Z", re.ASCII)

# Atomic heartbeat registration, with 1h fail-closed expiry after abnormal
# shutdown. All events carry server-side random connection IDs and MACed users.
_HEARTBEAT = """
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 1
"""

_DELETE = """
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""

# A standalone collector reads exactly one atomic Redis snapshot; stale
# connections are removed before any count. A temporary Redis outage must
# fail, never synthesize the desired count.
_SNAPSHOT = """
local cutoff = tonumber(ARGV[1]) - tonumber(ARGV[2])
local stale = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', cutoff)
for _, sid in ipairs(stale) do
  redis.call('HDEL', KEYS[1], sid)
end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', cutoff)
local connections = redis.call('ZRANGE', KEYS[2], 0, -1)
local distinct = {}
local users = 0
for _, sid in ipairs(connections) do
  local identity = redis.call('HGET', KEYS[1], sid)
  if not identity then
    return redis.error_reply('missing authenticated socket identity')
  end
  if not distinct[identity] then
    distinct[identity] = true
    users = users + 1
  end
end
return {#connections, users}
"""


def read_private_key(path: str) -> bytes:
    """Reject symlinks, broad permissions, other owners and short secrets."""
    file = Path(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(file, flags)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
            or not 32 <= metadata.st_size <= 4096
        ):
            raise ValueError("FR09 key file must be owner-private 0600")
        key = os.read(fd, 4097)
        if len(key) != metadata.st_size or not 32 <= len(key) <= 4096:
            raise ValueError("FR09 key length invalid")
        return key
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True)
class PresenceConfig:
    run_id: str
    identity_key: bytes

    def __post_init__(self) -> None:
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("FR09 run identifier invalid")
        if type(self.identity_key) is not bytes or len(self.identity_key) < 32:
            raise ValueError("FR09 private identity key invalid")

    @property
    def keys(self) -> tuple[str, str]:
        return (
            f"aionex:fr09:presence:{self.run_id}:identities",
            f"aionex:fr09:presence:{self.run_id}:connections",
        )


@lru_cache(maxsize=1)
def optional_presence_config() -> PresenceConfig | None:
    flag = os.getenv("AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED", "false").strip().lower()
    if flag == "false":
        return None
    if flag != "true":
        raise ValueError("FR09 presence toggle must be true or false")
    run_id = os.getenv("AIOS_FR09_AUTHENTICATED_PRESENCE_RUN_ID", "").strip()
    key_file = os.getenv("AIOS_FR09_AUTHENTICATED_PRESENCE_KEY_FILE", "").strip()
    if not key_file:
        raise ValueError("FR09 operator-owned identity key required")
    return PresenceConfig(run_id, read_private_key(key_file))


def identity_digest(config: PresenceConfig, principal: StreamPrincipal) -> str:
    if (
        not principal.organization_id
        or not principal.user_id
        or type(principal.auth_version) is not int
        or principal.auth_version < 0
    ):
        raise ValueError("verified socket principal required")
    data = json.dumps(
        [principal.organization_id, principal.user_id, principal.auth_version],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hmac.new(config.identity_key, data, hashlib.sha256).hexdigest()


class ServerPresenceRecorder:
    """Lifecycle adapter called *only* from the authenticated socket route."""

    def __init__(self, config: PresenceConfig, redis: Any) -> None:
        self.config = config
        self.redis = redis

    @classmethod
    async def from_enabled_config(cls) -> ServerPresenceRecorder | None:
        config = optional_presence_config()
        if config is None:
            return None
        return cls(config, await get_redis())

    async def register(self, verified: StreamPrincipal) -> tuple[str, str]:
        user_digest = identity_digest(self.config, verified)
        socket_id = secrets.token_hex(24)
        await self._heartbeat(socket_id, user_digest)
        return socket_id, user_digest

    async def revalidate(
        self, socket_id: str, user_digest: str, verified: StreamPrincipal
    ) -> None:
        if not hmac.compare_digest(
            user_digest, identity_digest(self.config, verified)
        ):
            raise ValueError("socket principal changed during FR09 measurement")
        await self._heartbeat(socket_id, user_digest)

    async def _heartbeat(self, socket_id: str, user_digest: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{48}", socket_id):
            raise ValueError("server socket identity invalid")
        await self.redis.eval(
            _HEARTBEAT,
            2,
            *self.config.keys,
            socket_id,
            user_digest,
            str(time.time()),
            str(KEY_EXPIRE_SECONDS),
        )

    async def disconnect(self, socket_id: str) -> None:
        await self.redis.eval(_DELETE, 2, *self.config.keys, socket_id)

    async def sample(self) -> dict[str, Any]:
        observed_at = time.time()
        output = await self.redis.eval(
            _SNAPSHOT, 2, *self.config.keys, str(observed_at), str(LIVE_SECONDS)
        )
        if (
            not isinstance(output, (list, tuple))
            or len(output) != 2
            or any(type(v) is not int or v < 0 for v in output)
            or output[1] > output[0]
        ):
            raise ValueError("server session count invalid")
        return {
            "at_epoch": observed_at,
            "authenticated_sessions": output[0],
            "distinct_authenticated_users": output[1],
        }
