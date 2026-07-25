from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models import ModelRequest
from ..routing.models import RoutingPolicy


@dataclass(frozen=True, slots=True)
class AIWorkItem:
    task_id: str
    request: ModelRequest
    policy: RoutingPolicy = field(default_factory=RoutingPolicy)
    project: str | None = None
    budget_scope: str = "global"
    priority: int = 100
    actor: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AIWorkResult:
    task_id: str
    provider: str
    model: str
    text: str
    confidence: float
    strategy: str
    candidates: int
    cost: float
    latency_ms: float
    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
