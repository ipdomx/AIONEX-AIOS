from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..models import ModelResponse, RouteDecision


class OptimizationMode(str, Enum):
    BALANCED = "balanced"
    COST = "cost"
    SPEED = "speed"
    QUALITY = "quality"
    PRIVACY = "privacy"


class ExecutionMode(str, Enum):
    SINGLE = "single"
    PARALLEL = "parallel"
    CONSENSUS = "consensus"
    VOTE = "vote"


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    optimization: OptimizationMode = OptimizationMode.BALANCED
    execution: ExecutionMode = ExecutionMode.SINGLE
    max_models: int = 1
    timeout_seconds: float = 60.0
    retry_attempts: int = 1
    allow_failover: bool = True
    offline_only: bool = False
    privacy_mode: bool = False
    provider_priority: tuple[str, ...] = ()
    excluded_providers: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CandidateResult:
    decision: RouteDecision
    response: ModelResponse | None
    error: str | None = None

    @property
    def successful(self) -> bool:
        return self.response is not None and self.error is None


@dataclass(frozen=True, slots=True)
class RoutedResult:
    selected: ModelResponse
    candidates: tuple[CandidateResult, ...]
    strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)
