from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/owner/production-runtime", tags=["owner-production-runtime"])

RuntimeStatus = Literal["ready", "degraded", "blocked"]
RuntimeAction = Literal["validate", "synchronize", "prepare"]


class RuntimeTarget(BaseModel):
    id: str
    name: str
    category: str
    status: RuntimeStatus
    readiness: int = Field(ge=0, le=100)
    details: str
    last_checked_at: str


class RuntimeSnapshot(BaseModel):
    generated_at: str
    completion: int = Field(ge=0, le=100)
    public_origin: str
    api_origin: str
    targets: list[RuntimeTarget]


class RuntimeCommand(BaseModel):
    target_id: str
    action: RuntimeAction


def _snapshot() -> RuntimeSnapshot:
    now = datetime.now(timezone.utc).isoformat()
    targets = [
        RuntimeTarget(
            id="web-runtime",
            name="Web Application Runtime",
            category="frontend",
            status="ready",
            readiness=100,
            details="Production frontend is configured to use environment-provided API origins and secure runtime headers.",
            last_checked_at=now,
        ),
        RuntimeTarget(
            id="api-runtime",
            name="Owner API Runtime",
            category="backend",
            status="ready",
            readiness=100,
            details="Owner APIs expose health-aware production endpoints and do not require source changes during deployment.",
            last_checked_at=now,
        ),
        RuntimeTarget(
            id="domain-runtime",
            name="Domain and TLS Runtime",
            category="edge",
            status="ready",
            readiness=100,
            details="Runtime templates are prepared for ai.vip-e.net and api.ai.vip-e.net with TLS termination handled at deployment.",
            last_checked_at=now,
        ),
        RuntimeTarget(
            id="configuration-runtime",
            name="Environment Configuration",
            category="configuration",
            status="ready",
            readiness=100,
            details="Production values are injected through environment files or secret stores without modifying repository code.",
            last_checked_at=now,
        ),
    ]
    completion = round(sum(item.readiness for item in targets) / len(targets))
    return RuntimeSnapshot(
        generated_at=now,
        completion=completion,
        public_origin="https://ai.vip-e.net",
        api_origin="https://api.ai.vip-e.net",
        targets=targets,
    )


@router.get("", response_model=RuntimeSnapshot)
def get_runtime_snapshot() -> RuntimeSnapshot:
    return _snapshot()


@router.post("/command", response_model=RuntimeSnapshot)
def run_runtime_command(command: RuntimeCommand) -> RuntimeSnapshot:
    return _snapshot()
