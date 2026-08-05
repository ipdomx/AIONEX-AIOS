from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SyncState(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"


@dataclass(slots=True)
class SyncRecord:
    record_id: str
    owner_id: str
    resource_type: str
    resource_id: str
    version: int
    payload: dict[str, object]
    state: SyncState = SyncState.PENDING
    attempts: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AndroidSyncEngine:
    def __init__(self) -> None:
        self._records: dict[str, SyncRecord] = {}

    def enqueue(self, record: SyncRecord) -> SyncRecord:
        existing = self._records.get(record.record_id)
        if existing is not None and existing.version >= record.version:
            return existing
        self._records[record.record_id] = record
        return record

    def next_batch(self, owner_id: str, limit: int = 50) -> list[SyncRecord]:
        if limit <= 0:
            return []
        candidates = [
            record
            for record in self._records.values()
            if record.owner_id == owner_id and record.state in {SyncState.PENDING, SyncState.FAILED}
        ]
        candidates.sort(key=lambda record: (record.updated_at, record.record_id))
        batch = candidates[:limit]
        for record in batch:
            record.state = SyncState.SYNCING
            record.attempts += 1
            record.updated_at = datetime.now(timezone.utc)
        return batch

    def mark_synced(self, record_id: str, owner_id: str) -> SyncRecord:
        record = self._require_owner(record_id, owner_id)
        record.state = SyncState.SYNCED
        record.updated_at = datetime.now(timezone.utc)
        return record

    def mark_failed(self, record_id: str, owner_id: str) -> SyncRecord:
        record = self._require_owner(record_id, owner_id)
        record.state = SyncState.FAILED
        record.updated_at = datetime.now(timezone.utc)
        return record

    def _require_owner(self, record_id: str, owner_id: str) -> SyncRecord:
        record = self._records[record_id]
        if record.owner_id != owner_id:
            raise PermissionError("sync record is not owned by this owner")
        return record
