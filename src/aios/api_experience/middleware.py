from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str
    principal_id: str
    organization_id: str | None = None
    project_id: str | None = None
    capabilities: frozenset[str] = frozenset()
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CorrelationMiddleware:
    def build_context(
        self,
        principal_id: str,
        correlation_id: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
        capabilities: set[str] | frozenset[str] | None = None,
    ) -> RequestContext:
        if not principal_id.strip():
            raise ValueError("principal_id is required")
        return RequestContext(
            correlation_id=correlation_id or str(uuid4()),
            principal_id=principal_id,
            organization_id=organization_id,
            project_id=project_id,
            capabilities=frozenset(capabilities or set()),
        )
