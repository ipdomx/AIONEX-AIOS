from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OwnerApproval:
    case_id: str
    owner_id: str
    approved: bool
    note: str
    timestamp: str


class OwnerOffice:
    def __init__(self, owner_id: str = "owner") -> None:
        self.owner_id = owner_id
        self._approvals: dict[str, OwnerApproval] = {}

    def decide(self, case_id: str, actor_id: str, approved: bool, note: str = "") -> OwnerApproval:
        if actor_id != self.owner_id:
            raise PermissionError("Only the owner may issue an owner approval.")
        record = OwnerApproval(
            case_id=case_id,
            owner_id=actor_id,
            approved=approved,
            note=note,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._approvals[case_id] = record
        return record

    def get(self, case_id: str) -> OwnerApproval | None:
        return self._approvals.get(case_id)
