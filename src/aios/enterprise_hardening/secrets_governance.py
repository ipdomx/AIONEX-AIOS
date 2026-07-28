from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class SecretRecord:
    secret_id: str
    owner_id: str
    provider: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rotated_at: datetime | None = None
    rotation_days: int = 90
    revoked: bool = False

    def rotation_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        baseline = self.rotated_at or self.created_at
        return now >= baseline + timedelta(days=self.rotation_days)


class SecretsGovernanceService:
    def __init__(self) -> None:
        self._records: dict[str, SecretRecord] = {}

    def register(self, record: SecretRecord) -> SecretRecord:
        if record.secret_id in self._records:
            raise ValueError(f"duplicate secret record: {record.secret_id}")
        self._records[record.secret_id] = record
        return record

    def rotate(self, secret_id: str, owner_id: str) -> SecretRecord:
        record = self._require_owner(secret_id, owner_id)
        if record.revoked:
            raise RuntimeError("revoked secrets cannot be rotated")
        record.rotated_at = datetime.now(timezone.utc)
        return record

    def revoke(self, secret_id: str, owner_id: str) -> SecretRecord:
        record = self._require_owner(secret_id, owner_id)
        record.revoked = True
        return record

    def due_for_rotation(self, owner_id: str) -> list[SecretRecord]:
        return [
            record
            for record in self._records.values()
            if record.owner_id == owner_id and not record.revoked and record.rotation_due()
        ]

    def _require_owner(self, secret_id: str, owner_id: str) -> SecretRecord:
        record = self._records[secret_id]
        if record.owner_id != owner_id:
            raise PermissionError("secret record is not owned by this owner")
        return record
