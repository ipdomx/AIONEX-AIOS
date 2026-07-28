from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256


@dataclass(slots=True)
class PromotionAuditEntry:
    entry_id: str
    owner_id: str
    proposal_id: str
    action: str
    actor_id: str
    previous_hash: str
    entry_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PromotionAuditLog:
    def __init__(self) -> None:
        self._entries: list[PromotionAuditEntry] = []

    def append(self, *, entry_id: str, owner_id: str, proposal_id: str, action: str, actor_id: str) -> PromotionAuditEntry:
        previous_hash = self._entries[-1].entry_hash if self._entries else "GENESIS"
        payload = "|".join([entry_id, owner_id, proposal_id, action, actor_id, previous_hash])
        entry_hash = sha256(payload.encode("utf-8")).hexdigest()
        entry = PromotionAuditEntry(
            entry_id=entry_id,
            owner_id=owner_id,
            proposal_id=proposal_id,
            action=action,
            actor_id=actor_id,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous_hash = "GENESIS"
        for entry in self._entries:
            payload = "|".join(
                [entry.entry_id, entry.owner_id, entry.proposal_id, entry.action, entry.actor_id, previous_hash]
            )
            if entry.previous_hash != previous_hash:
                return False
            if sha256(payload.encode("utf-8")).hexdigest() != entry.entry_hash:
                return False
            previous_hash = entry.entry_hash
        return True

    def list_for_owner(self, owner_id: str) -> list[PromotionAuditEntry]:
        return [entry for entry in self._entries if entry.owner_id == owner_id]
