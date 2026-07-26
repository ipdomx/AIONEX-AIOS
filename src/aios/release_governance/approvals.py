from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class ApprovalRecord:
    release_id: str
    reviewer_id: str
    role: str
    decision: ApprovalDecision
    reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ReleaseApprovalBoard:
    def __init__(self, required_roles: set[str] | None = None) -> None:
        self.required_roles = set(required_roles or {"chief_engineer", "security", "owner"})
        self._records: dict[str, dict[str, ApprovalRecord]] = {}

    def submit(self, record: ApprovalRecord) -> ApprovalRecord:
        if not record.release_id.strip() or not record.reviewer_id.strip() or not record.role.strip():
            raise ValueError("release_id, reviewer_id, and role are required")
        self._records.setdefault(record.release_id, {})[record.role] = record
        return record

    def records_for(self, release_id: str) -> list[ApprovalRecord]:
        return list(self._records.get(release_id, {}).values())

    def is_approved(self, release_id: str) -> bool:
        records = self._records.get(release_id, {})
        for role in self.required_roles:
            record = records.get(role)
            if record is None or record.decision is not ApprovalDecision.APPROVE:
                return False
        return not any(record.decision is ApprovalDecision.REJECT for record in records.values())

    def rejected(self, release_id: str) -> bool:
        return any(record.decision is ApprovalDecision.REJECT for record in self.records_for(release_id))
