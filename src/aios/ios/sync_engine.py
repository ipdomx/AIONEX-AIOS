from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SyncState(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(slots=True)
class SyncRecord:
    record_id: str
    owner_id: str
    entity_type: str
    entity_id: str
    local_version: int
    remote_version: int
    payload: dict[str, object] = field(default_factory=dict)
    state: SyncState = SyncState.PENDING
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IOSSyncEngine:
    def __init__(self) -> None:
        self._records: dict[str, SyncRecord] = {}

    def queue(self, record: SyncRecord) -> SyncRecord:
        if record.record_id in self._records:
            raise ValueError(f"duplicate sync record: {record.record_id}")
        self._records[record.record_id] = record
        return record

    def reconcile(self, record_id: str, owner_id: str, *, remote_version: int) -> SyncRecord:
        record = self._require_owner(record_id, owner_id)
        record.remote_version = remote_version
        if remote_version > record.local_version:
            record.state = SyncState.CONFLICT
        else:
            record.state = SyncState.SYNCED
        record.updated_at = datetime.now(timezone.utc)
        return record

    def resolve_conflict(self, record_id: str, owner_id: str, *, merged_payload: dict[str, object]) -> SyncRecord:
        record = self._require_owner(record_id, owner_id)
        if record.state is not SyncState.CONFLICT:
            raise RuntimeError("sync record has no conflict")
        record.payload = dict(merged_payload)
        record.local_version = max(record.local_version, record.remote_version) + 1
        record.state = SyncState.SYNCED
        record.updated_at = datetime.now(timezone.utc)
        return record

    def _require_owner(self, record_id: str, owner_id: str) -> SyncRecord:
        record = self._records[record_id]
        if record.owner_id != owner_id:
            raise PermissionError("sync record is not owned by this owner")
        return record
