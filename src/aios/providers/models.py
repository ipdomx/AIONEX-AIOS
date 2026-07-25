from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class DataSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    provider: str
    model: str
    tasks: frozenset[str]
    languages: frozenset[str] = frozenset()
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    local: bool = False
    max_context_tokens: int = 0
    quality_score: float = 0.5
    latency_score: float = 0.5
    privacy_score: float = 0.5
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: str
    prompt: str
    system_prompt: str = ""
    language: str = "en"
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    max_cost: float | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    require_local: bool = False
    require_tools: bool = False
    require_vision: bool = False
    require_audio: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    provider: str
    model: str
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    provider: str
    model: str
    score: float
    estimated_cost: float
    reasons: tuple[str, ...]
