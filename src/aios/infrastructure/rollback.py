from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class RollbackStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class RollbackRequest:
    release_id: str
    current_version: str
    target_version: str
    reason: str
    requested_by: str
    status: RollbackStatus = RollbackStatus.REQUESTED
    approved_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class RollbackManager:
    def __init__(self) -> None:
        self._requests: dict[str, RollbackRequest] = {}

    def request(self, request: RollbackRequest) -> RollbackRequest:
        if request.current_version == request.target_version:
            raise ValueError("rollback target must differ from current version")
        if request.release_id in self._requests:
            raise ValueError("rollback already requested for this release")
        self._requests[request.release_id] = request
        return request

    def approve(self, release_id: str, owner_id: str) -> RollbackRequest:
        request = self.get(release_id)
        request.status = RollbackStatus.APPROVED
        request.approved_by = owner_id
        return request

    def execute(self, release_id: str, executor: Callable[[RollbackRequest], bool]) -> RollbackRequest:
        request = self.get(release_id)
        if request.status is not RollbackStatus.APPROVED:
            raise PermissionError("owner approval required before rollback")
        request.status = RollbackStatus.RUNNING
        try:
            request.status = RollbackStatus.SUCCEEDED if executor(request) else RollbackStatus.FAILED
        except Exception:
            request.status = RollbackStatus.FAILED
            raise
        return request

    def get(self, release_id: str) -> RollbackRequest:
        try:
            return self._requests[release_id]
        except KeyError as exc:
            raise KeyError(f"unknown rollback request: {release_id}") from exc
