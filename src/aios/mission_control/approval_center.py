from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(slots=True)
class ApprovalRequest:
    approval_id: str
    owner_id: str
    action: str
    requested_by: str
    reason: str
    state: ApprovalState = ApprovalState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None
    decision_note: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class OwnerApprovalCenter:
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def submit(self, request: ApprovalRequest) -> ApprovalRequest:
        if request.approval_id in self._requests:
            raise ValueError(f"duplicate approval request: {request.approval_id}")
        self._requests[request.approval_id] = request
        return request

    def approve(self, approval_id: str, owner_id: str, note: str | None = None) -> ApprovalRequest:
        return self._decide(approval_id, owner_id, ApprovalState.APPROVED, note)

    def reject(self, approval_id: str, owner_id: str, note: str | None = None) -> ApprovalRequest:
        return self._decide(approval_id, owner_id, ApprovalState.REJECTED, note)

    def expire(self, approval_id: str) -> ApprovalRequest:
        request = self._requests[approval_id]
        if request.state is ApprovalState.PENDING:
            request.state = ApprovalState.EXPIRED
            request.decided_at = datetime.now(timezone.utc)
        return request

    def pending_for_owner(self, owner_id: str) -> list[ApprovalRequest]:
        return sorted(
            (
                request
                for request in self._requests.values()
                if request.owner_id == owner_id and request.state is ApprovalState.PENDING
            ),
            key=lambda request: request.created_at,
        )

    def _decide(
        self,
        approval_id: str,
        owner_id: str,
        state: ApprovalState,
        note: str | None,
    ) -> ApprovalRequest:
        request = self._requests[approval_id]
        if request.owner_id != owner_id:
            raise PermissionError("approval request is not owned by this owner")
        if request.state is not ApprovalState.PENDING:
            raise RuntimeError(f"approval request already decided: {request.state.value}")
        request.state = state
        request.decided_at = datetime.now(timezone.utc)
        request.decision_note = note
        return request
