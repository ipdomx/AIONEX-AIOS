from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe


@dataclass(slots=True)
class ApiKeyRecord:
    key_id: str
    owner_id: str
    name: str
    digest: str
    scopes: set[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class ApiKeyService:
    def __init__(self) -> None:
        self._keys: dict[str, ApiKeyRecord] = {}

    def issue(self, *, key_id: str, owner_id: str, name: str, scopes: set[str]) -> tuple[ApiKeyRecord, str]:
        if key_id in self._keys:
            raise ValueError(f"duplicate api key: {key_id}")
        secret = token_urlsafe(32)
        record = ApiKeyRecord(
            key_id=key_id,
            owner_id=owner_id,
            name=name,
            digest=self._digest(secret),
            scopes=set(scopes),
        )
        self._keys[key_id] = record
        return record, secret

    def authenticate(self, key_id: str, secret: str) -> ApiKeyRecord:
        record = self._keys[key_id]
        if not record.active:
            raise PermissionError("api key is revoked")
        if record.digest != self._digest(secret):
            raise PermissionError("invalid api key secret")
        return record

    def revoke(self, key_id: str, owner_id: str) -> ApiKeyRecord:
        record = self._keys[key_id]
        if record.owner_id != owner_id:
            raise PermissionError("api key is not owned by this owner")
        if record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
        return record

    @staticmethod
    def _digest(secret: str) -> str:
        return sha256(secret.encode("utf-8")).hexdigest()
