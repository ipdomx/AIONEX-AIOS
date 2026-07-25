from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryScope(str, Enum):
    GLOBAL = "global"
    TENANT = "tenant"
    USER = "user"
    PROJECT = "project"
    WORKER = "worker"
    SESSION = "session"


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Provenance:
    source: str
    source_type: str = "internal"
    collected_at: str = field(default_factory=utc_now)
    author: str | None = None
    uri: str | None = None
    checksum: str | None = None


@dataclass
class KnowledgeItem:
    item_id: str
    namespace: str
    subject: str
    content: Any
    confidence: float
    provenance: tuple[Provenance, ...]
    tags: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    supersedes: str | None = None
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provenance"] = [asdict(item) for item in self.provenance]
        return data


@dataclass
class LearningEvent:
    event_id: str
    action: str
    context_fingerprint: str
    outcome: Outcome
    evidence: tuple[str, ...]
    strategy: str | None = None
    project: str | None = None
    error_fingerprint: str | None = None
    lesson: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["outcome"] = self.outcome.value
        return data


@dataclass(frozen=True)
class ResearchClaim:
    claim: str
    source: str
    source_quality: float
    corroboration: int = 1
    recency: float = 1.0
    direct_evidence: bool = True


@dataclass(frozen=True)
class VerificationResult:
    claim: str
    confidence: float
    accepted: bool
    conflicts: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class DecisionOption:
    option_id: str
    title: str
    evidence_strength: float
    reliability: float
    security: float
    maintainability: float
    reversibility: float
    long_term_value: float
    cost_efficiency: float
    risk: float


@dataclass(frozen=True)
class WisdomDecision:
    selected_option: str | None
    score: float
    abstained: bool
    rationale: str
    ranking: tuple[tuple[str, float], ...]
    conditions: tuple[str, ...] = ()
