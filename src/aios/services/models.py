from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class ServiceState(str, Enum):
    AVAILABLE='available'
    EXPERIMENTAL='experimental'
    ENABLED='enabled'
    DISABLED='disabled'
    BLOCKED='blocked'
    DEPRECATED='deprecated'

@dataclass(frozen=True)
class ServiceDefinition:
    service_id: str
    name: str
    category: str
    capabilities: tuple[str, ...]
    requires_secret: bool = True
    default_state: ServiceState = ServiceState.DISABLED
    version: str = '1'
    metadata: dict = field(default_factory=dict)

@dataclass(frozen=True)
class ServiceEvaluation:
    service_id: str
    value_score: float
    security_score: float
    compatibility_score: float
    approved_by_council: bool
    owner_approved: bool

    @property
    def eligible(self) -> bool:
        return self.approved_by_council and self.owner_approved and min(self.value_score,self.security_score,self.compatibility_score) >= 70
