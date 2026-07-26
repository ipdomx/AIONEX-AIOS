from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SyncConflict(str, Enum):
    NONE = "none"
    CLIENT_NEWER = "client_newer"
    SERVER_NEWER = "server_newer"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class SyncResult:
    entity_id: str
    version: int
    conflict: SyncConflict
    payload: dict[str, object]
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MobileSyncEngine:
    def __init__(self) -> None:
        self._state: dict[str, tuple[int, dict[str, object]]] = {}

    def push(self, entity_id: str, version: int, payload: dict[str, object]) -> SyncResult:
        if not entity_id.strip():
            raise ValueError("entity_id is required")
        if version < 1:
            raise ValueError("version must be positive")
        current = self._state.get(entity_id)
        if current is None or version > current[0]:
            self._state[entity_id] = (version, dict(payload))
            return SyncResult(entity_id, version, SyncConflict.NONE, dict(payload))
        if version == current[0] and payload == current[1]:
            return SyncResult(entity_id, version, SyncConflict.NONE, dict(current[1]))
        return SyncResult(entity_id, current[0], SyncConflict.SERVER_NEWER, dict(current[1]))

    def pull(self, entity_id: str, client_version: int = 0) -> SyncResult:
        try:
            version, payload = self._state[entity_id]
        except KeyError as exc:
            raise LookupError(f"entity not found: {entity_id}") from exc
        conflict = SyncConflict.NONE if client_version < version else SyncConflict.CLIENT_NEWER if client_version > version else SyncConflict.NONE
        return SyncResult(entity_id, version, conflict, dict(payload))

    def snapshot(self) -> dict[str, int]:
        return {entity_id: version for entity_id, (version, _) in self._state.items()}
